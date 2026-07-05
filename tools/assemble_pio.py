#!/usr/bin/env python3
"""Stage-2 PIO verification: really assemble the ARCHITECTURE.md programs.

check_pio_timing.py (stage 1) validates encoding-field budgets and
simulates strobe timing, but it parses the source text itself — it can't
catch a syntax error, a mis-assembled instruction, or a wrong side-set
declaration. This tool closes that gap by running the real `pioasm` on
the exact code blocks in ARCHITECTURE.md and inspecting its output:

  1. Extracts every ```pioasm block (same regex as check_pio_timing.py).
  2. Minimal defensive cleaning only: strips `;` comments from directive
     lines that some pioasm versions reject them on (currently a no-op —
     pioasm 2.2.0 accepts the blocks verbatim). The doc itself is never
     modified.
  3. Compiles each .program standalone; on failure reports pioasm's
     error (which includes line/column) and exits non-zero.
  4. Parses the generated C header: instruction array, wrap target/top,
     and the sm_config_set_sideset(...) call.
  5. Asserts side-set config == (3, false, false): 3 bits, mandatory
     (non-opt), maps to pins (not pindirs).
  6. Reports the 32-slot instruction budget across all programs.
  7. Verifies the `mov osr, ~null` idiom assembles to the correct
     encoding: bits 15:13=101 (MOV), dest 7:5=111 (OSR), op 4:3=01
     (invert), src 2:0=011 (NULL) -> 0xA0EB with a zeroed delay/side
     field. Checked both in-program (masking the side/delay field) and
     via a standalone compile.

Run from the repo root:
    python3 tools/assemble_pio.py
Exit 0 = everything compiled and matched; non-zero otherwise.
"""

import os
import re
import subprocess
import sys
import tempfile

DOC = "ARCHITECTURE.md"

PIOASM_CANDIDATES = [
    "/home/harri/pico/EBD_IPKVM/build/pioasm-install/pioasm/pioasm",
    "pioasm",  # PATH
]
PIOASM_SDK_SRC = "/home/harri/pico/pico-sdk/tools/pioasm"

EXPECT_SIDESET = ("3", "false", "false")   # bits, optional, pindirs
PIO_SLOTS = 32

# mov osr, ~null with delay/side-set field zeroed:
#   15:13 opcode MOV=101 | 12:8 delay/side | 7:5 dest OSR=111
#   | 4:3 op invert=01 | 2:0 src NULL=011
MOV_OSR_INV_NULL = 0xA0EB
FIELD_MASK = 0xE0FF                        # everything except bits 12:8


def find_pioasm():
    for cand in PIOASM_CANDIDATES:
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True)
            return cand
        except (OSError, subprocess.CalledProcessError):
            continue
    # Fall back: build from SDK source
    if os.path.isdir(PIOASM_SDK_SRC):
        build = tempfile.mkdtemp(prefix="pioasm-build-")
        print(f"pioasm not found; building from {PIOASM_SDK_SRC} ...")
        subprocess.run(["cmake", PIOASM_SDK_SRC], cwd=build, check=True,
                       capture_output=True)
        subprocess.run(["make", "-j4"], cwd=build, check=True,
                       capture_output=True)
        exe = os.path.join(build, "pioasm")
        subprocess.run([exe, "--version"], capture_output=True, check=True)
        return exe
    sys.exit("FATAL: no pioasm binary found and SDK source unavailable")


def extract_programs(doc_text):
    """-> list of (name, source). Same block regex as check_pio_timing.py."""
    programs = []
    for block in re.findall(r"```pioasm\n(.*?)```", doc_text, re.S):
        name = re.search(r"\.program (\S+)", block).group(1)
        cleaned = []
        for line in block.splitlines():
            # Defensive: some pioasm versions reject ; comments on
            # directive lines. Strip them there only; leave instruction
            # comments alone (pioasm handles those, and stripping more
            # would hide doc problems this tool exists to find).
            if line.lstrip().startswith(".program"):
                line = line.split(";")[0].rstrip()
            cleaned.append(line)
        programs.append((name, "\n".join(cleaned) + "\n"))
    return programs


def compile_program(pioasm, name, source, workdir):
    src = os.path.join(workdir, f"{name}.pio")
    hdr = os.path.join(workdir, f"{name}.pio.h")
    with open(src, "w") as f:
        f.write(source)
    r = subprocess.run([pioasm, "-o", "c-sdk", src, hdr],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()
    return open(hdr).read(), None


def parse_header(name, header):
    instrs = [int(h, 16) for h in re.findall(
        r"0x([0-9a-fA-F]{4}), //", header)]
    wrap_target = int(re.search(
        rf"#define {name}_wrap_target (\d+)", header).group(1))
    wrap = int(re.search(rf"#define {name}_wrap (\d+)", header).group(1))
    ss = re.search(
        r"sm_config_set_sideset\(&c, (\d+), (\w+), (\w+)\)", header)
    sideset = ss.groups() if ss else None
    length = int(re.search(r"\.length = (\d+),", header).group(1))
    ver_m = re.search(rf"#define {name}_pio_version (\d+)", header)
    pio_version = int(ver_m.group(1)) if ver_m else 0
    return instrs, length, wrap_target, wrap, sideset, pio_version


def check_mov_osr_inv_null(pioasm, workdir):
    """Standalone compile of the idiom, then decode the fields."""
    hdr, err = compile_program(
        pioasm, "movtest", ".program movtest\n    mov osr, ~null\n", workdir)
    if err:
        return f"standalone compile failed: {err}"
    instr = parse_header("movtest", hdr)[0][0]
    checks = [
        ("opcode MOV (101)",   (instr >> 13) & 0x7, 0b101),
        ("dest OSR (111)",     (instr >> 5) & 0x7,  0b111),
        ("op invert (01)",     (instr >> 3) & 0x3,  0b01),
        ("src NULL (011)",     instr & 0x7,         0b011),
    ]
    bad = [f"{what}: got {got:#b}, want {want:#b}"
           for what, got, want in checks if got != want]
    if bad:
        return "; ".join(bad)
    if instr != MOV_OSR_INV_NULL:
        return f"encoded {instr:#06x}, expected {MOV_OSR_INV_NULL:#06x}"
    return None


def main():
    doc_text = open(DOC).read()
    pioasm = find_pioasm()
    programs = extract_programs(doc_text)
    if not programs:
        sys.exit(f"FATAL: no pioasm blocks found in {DOC}")

    failures = 0
    total = 0
    lengths = {}
    pio_versions = {}
    width = max(len(n) for n, _ in programs) + 1

    with tempfile.TemporaryDirectory(prefix="assemble-pio-") as workdir:
        for name, source in programs:
            header, err = compile_program(pioasm, name, source, workdir)
            if err:
                print(f"{name + ':':<{width}} COMPILE FAILED\n  {err}")
                failures += 1
                continue

            instrs, length, wrap_target, wrap, sideset, pio_ver = \
                parse_header(name, header)
            total += length
            lengths[name] = length
            pio_versions[name] = pio_ver
            problems = []
            if pio_ver != 0:
                problems.append(
                    f"pio_version {pio_ver}: uses RP2350-only features, "
                    "breaks the ARCHITECTURE.md both-boards guarantee")
            if len(instrs) != length:
                problems.append(
                    f"array has {len(instrs)} words but .length={length}")
            if sideset is None:
                problems.append("no sm_config_set_sideset() emitted")
            elif sideset != EXPECT_SIDESET:
                problems.append(
                    f"sideset{tuple(sideset)} != expected "
                    f"({', '.join(EXPECT_SIDESET)})")
            # every mov osr, ~null in the program must carry the right
            # base encoding under its side/delay field
            for i, w in enumerate(instrs):
                dis = re.search(rf"0x{w:04x}, // {i:2}: (.*)$", header, re.M)
                if dis and "mov" in dis.group(1) and "~null" in dis.group(1):
                    if (w & FIELD_MASK) != MOV_OSR_INV_NULL:
                        problems.append(
                            f"instr {i} mov osr,~null encodes {w:#06x}, "
                            f"base {(w & FIELD_MASK):#06x} != "
                            f"{MOV_OSR_INV_NULL:#06x}")

            verdict = "PASS" if not problems else "FAIL"
            failures += len(problems)
            print(f"{name + ':':<{width}} {length:2} instr  "
                  f"wrap({wrap_target},{wrap})  "
                  f"sideset({','.join(sideset) if sideset else '?'})  "
                  f"{verdict}")
            for p in problems:
                print(f"  !! {p}")

        movtest_err = check_mov_osr_inv_null(pioasm, workdir)
        if movtest_err:
            print(f"mov osr, ~null decode: FAIL — {movtest_err}")
            failures += 1
        else:
            print(f"mov osr, ~null decode: {MOV_OSR_INV_NULL:#06x} "
                  "(MOV|OSR|invert|NULL) PASS")

    # Cross-assert against stage 1: both tools extract with the same
    # regex; per-program instruction counts must agree or the extraction
    # has diverged between them.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_pio_timing
        stage1 = {n: len(instrs) for n, (instrs, _errs)
                  in check_pio_timing.parse_programs(doc_text).items()}
        if stage1 != lengths:
            print(f"CROSS-CHECK vs check_pio_timing: FAIL — "
                  f"stage1 {stage1} != pioasm {lengths}")
            failures += 1
        else:
            print(f"CROSS-CHECK vs check_pio_timing: counts agree "
                  f"({sum(stage1.values())} instr) PASS")
    except ImportError as e:
        print(f"CROSS-CHECK vs check_pio_timing: SKIPPED ({e})")

    vers = set(pio_versions.values())
    if vers == {0}:
        print("PIO_VERSION: 0 (RP2040/RP2350 compatible)")
    elif vers:
        print(f"PIO_VERSION: {sorted(vers)} — non-zero versions are "
              "flagged FAIL above")

    over = total > PIO_SLOTS
    print(f"TOTAL: {total}/{PIO_SLOTS} slots ({100 * total // PIO_SLOTS}%)"
          + ("  FAIL: over budget" if over else ""))
    if over:
        failures += 1
    print("ALL COMPILED OK" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
