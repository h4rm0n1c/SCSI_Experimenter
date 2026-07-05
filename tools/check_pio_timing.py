#!/usr/bin/env python3
"""Validate the PIO programs embedded in ARCHITECTURE.md against the
WD33C93A/AM33C93A host-bus timing specs.

Two independent checks:

1. Encoding: with `.side_set 3` (non-optional) the 5-bit delay/side-set
   field gives 3 side bits + 2 delay bits, so every instruction must
   carry a `side 0b...` annotation, side values must fit in 3 bits, and
   delays must be <= [3]. (With `opt` there is only 1 delay bit -- the
   bug this tool was written to catch.)

2. Timing: cycle-accurate simulation of each program at the SM clock,
   measuring strobe low-widths and `in pins` sample ages (including the
   2-sys_clk input synchronizer latency), asserted against the datasheet
   limits from WD33C93A app notes 9.1.3/9.1.4 (indirect register access)
   and 9.1.11/9.1.12 (burst DMA).

Conventions (RP2040/RP2350 datasheet, PIO chapter):
  - side-set takes effect on the FIRST cycle of an instruction;
  - an instruction with delay d occupies 1+d SM cycles;
  - a strobe asserted by instruction i and released by instruction j is
    low for the total cycles of instructions i..j-1;
  - `in pins` reads the pin state ~2 sys_clk in the past (input
    synchronizers), so effective data age = sample time - 2/f_sys.

Exit status 0 = all checks pass. Run from the repo root:
    python3 tools/check_pio_timing.py
"""

import re
import sys

DOC = "ARCHITECTURE.md"

F_SYS = 120e6            # Hz, sys_clk (see ARCHITECTURE.md section 6)
SM_DIV = 5               # PIO clock divider
T = 1e9 / (F_SYS / SM_DIV)     # ns per SM cycle (41.67 ns @ 24 MHz)
SYNC = 2 * (1e9 / F_SYS)       # input synchronizer age, ns (16.7 ns)

MAX_SIDE_BITS = 3
MAX_DELAY = 3            # 2 delay bits with .side_set 3 non-opt
PIO_SLOTS = 32

# Datasheet limits, ns. Keyed by program name; side-set bit index is
# program-local (bit0 = side-set base pin).
#   sbic_bus:      side {bit2=RE, bit1=WE, bit0=CS}   base GP9
#   sbic_burst_*:  side {bit2=DACK, bit1=RE, bit0=WE} base GP10
SPECS = {
    "sbic_bus": {
        "pulse_min": {0: 120.0, 1: 120.0, 2: 180.0},  # CS follows longest strobe
        "pulse_max": {2: 10_000.0},                   # tRE max 10 us
        "sample_min_age": 180.0,                      # tRLDV
        "recovery_min": 100.0,                        # tWHWL / tRHRL
    },
    "sbic_burst_in": {
        "pulse_min": {1: 80.0, 2: 0.0},               # tRD (A); DACK >= 0
        "pulse_max": {},
        # tRLDV max 50 ns, visually verified from A app notes 9.1.12
        # (p.61). B (6.1.12 p.57) is pipelined: first byte <= 50 ns from
        # DACK-low, later bytes <= 80 ns from the PREVIOUS RE-high --
        # covered because this SM's RE-high -> next RE-low gap >= 125 ns.
        "sample_min_age": 50.0,
        "recovery_min": 80.0,                         # trhrl/twhwl (A; B is 30)
    },
    "sbic_burst_out": {
        "pulse_min": {0: 50.0, 2: 0.0},               # tWR; DACK >= 0
        "pulse_max": {},
        "sample_min_age": None,
        "recovery_min": 80.0,
    },
}

INSTR_RE = re.compile(
    r"^(?:\w+:\s*)?(\S.*?)\s+side\s+0b([01]+)(?:\s*\[(\d+)\])?$"
)
LABEL_ONLY_RE = re.compile(r"^\w+:$")


def parse_programs(doc_text):
    programs = {}
    for block in re.findall(r"```pioasm\n(.*?)```", doc_text, re.S):
        name = re.search(r"\.program (\S+)", block).group(1)
        instrs, errors = [], []
        for raw in block.splitlines():
            line = raw.split(";")[0].strip()
            if not line or line.startswith(".") or LABEL_ONLY_RE.match(line):
                continue
            m = INSTR_RE.match(line)
            if not m:
                errors.append(f"missing/invalid side annotation: {line!r}")
                continue
            instr, side, delay = m.group(1), int(m.group(2), 2), int(m.group(3) or 0)
            if side >= (1 << MAX_SIDE_BITS):
                errors.append(f"side value {side:#b} exceeds {MAX_SIDE_BITS} bits: {line!r}")
            if delay > MAX_DELAY:
                errors.append(
                    f"delay [{delay}] exceeds [{MAX_DELAY}] "
                    f"(.side_set {MAX_SIDE_BITS} leaves 2 delay bits): {line!r}"
                )
            instrs.append((instr, side, delay))
        programs[name] = (instrs, errors)
    return programs


def simulate(instrs):
    """One pass through the program; returns pulse widths, sample ages,
    per-strobe release times, and total pass length (all ns)."""
    t = 0.0
    fall = {}
    pulses = []    # (bit, width, release_time)
    samples = []   # (bit, age_at_in)
    for instr, side, delay in instrs:
        for bit in range(MAX_SIDE_BITS):
            low = ((side >> bit) & 1) == 0
            if low and bit not in fall:
                fall[bit] = t
            elif not low and bit in fall:
                pulses.append((bit, t - fall.pop(bit), t))
        if instr.startswith("in "):
            samples.extend((bit, t - f - SYNC) for bit, f in fall.items())
        t += (1 + delay) * T
    return pulses, samples, t


def main():
    doc_text = open(DOC).read()
    programs = parse_programs(doc_text)
    failures = 0
    total = 0

    for name, (instrs, errors) in programs.items():
        spec = SPECS.get(name, {})
        total += len(instrs)
        print(f"== {name}: {len(instrs)} instructions ==")
        for e in errors:
            print(f"  FAIL encoding: {e}")
            failures += 1

        pulses, samples, loop_ns = simulate(instrs)

        for bit, width, released in pulses:
            lo = spec.get("pulse_min", {}).get(bit)
            hi = spec.get("pulse_max", {}).get(bit)
            verdict = "ok"
            if lo is not None and width < lo:
                verdict, failures = f"FAIL < {lo} ns min", failures + 1
            if hi is not None and width > hi:
                verdict, failures = f"FAIL > {hi} ns max", failures + 1
            print(f"  strobe bit{bit}: low {width:7.1f} ns   {verdict}")

            if spec.get("recovery_min") is not None:
                # Worst-case recovery: released -> wrap to first assertion
                first_fall = min((ft for b, w, r in pulses for ft in [r - w]), default=None)
                recovery = (loop_ns - released) + (first_fall or 0.0)
                verdict = "ok" if recovery >= spec["recovery_min"] else \
                    f"FAIL < {spec['recovery_min']} ns min"
                if verdict != "ok":
                    failures += 1
                print(f"    wrap recovery: {recovery:7.1f} ns   {verdict}")

        for bit, age in samples:
            need = spec.get("sample_min_age")
            verdict = "ok" if need is None or age >= need else f"FAIL < {need} ns min"
            if verdict != "ok":
                failures += 1
            print(f"  IN sample: data age {age:7.1f} ns after bit{bit} fell "
                  f"(incl -{SYNC:.1f} ns sync)   {verdict}")

        print(f"  loop pass: {loop_ns:7.1f} ns ({loop_ns / T:.0f} cycles)")

    print(f"\nTOTAL {total}/{PIO_SLOTS} instruction slots"
          f"{'   FAIL: over budget' if total > PIO_SLOTS else ''}")
    if total > PIO_SLOTS:
        failures += 1

    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
