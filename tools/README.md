# Tools

Work products from the ARCHITECTURE.md design session (2026-07-05).
These regenerate/verify the evidence the architecture document is
built on. Run everything from the repo root.

## check_pio_timing.py — PIO program validator & timing simulator

```
python3 tools/check_pio_timing.py
```

Parses the `pioasm` code blocks **directly out of ARCHITECTURE.md** and:

1. **Encoding check** — enforces the `.side_set 3` (non-optional) field
   budget: side annotation on every instruction, side values ≤ 3 bits,
   delays ≤ `[3]`. This catches the class of bug found in review (the
   original draft used `.side_set 3 opt`, which only leaves 1 delay bit,
   with `[4]`/`[2]` delays that would not assemble).
2. **Cycle-accurate timing simulation** — replays each program at the
   24 MHz SM clock (120 MHz sys ÷ 5), measures every strobe's low width,
   inter-strobe recovery, and `in pins` sample age (including the
   2-sys_clk input-synchronizer latency, −16.7 ns), and asserts them
   against the WD33C93A app-notes limits (§9.1.3/9.1.4 indirect register
   access, §9.1.11/9.1.12 burst DMA).

Exit code 0 = all pass. **Re-run this after any edit to the PIO
listings, the SM divider, or the sys_clk choice in ARCHITECTURE.md** —
the spec table in the script is the single place the datasheet numbers
live.

## assemble_pio.py — stage-2: real pioasm compilation

```
python3 tools/assemble_pio.py
```

Runs **after** `check_pio_timing.py` as the second stage of a two-stage
validation. Stage 1 checks field budgets and simulates timing but only
*parses* the source; stage 2 feeds the exact same code blocks to the
real `pioasm` (prebuilt at
`/home/harri/pico/EBD_IPKVM/build/pioasm-install/pioasm/pioasm`, falls
back to `$PATH`, then to building from
`/home/harri/pico/pico-sdk/tools/pioasm`) and verifies its output:

- each `.program` compiles standalone (syntax, jump targets, delay
  limits — pioasm itself rejects the `.side_set 3 opt` + `[2+]` class
  of bug found in review, so this stage catches it mechanically);
- generated `sm_config_set_sideset(&c, 3, false, false)` matches the
  required 3-bit / mandatory / pins config for every program;
- instruction-array length, wrap(target,top), and the 32-slot budget;
- the `mov osr, ~null` idiom decodes to 0xA0EB
  (MOV | dest OSR | invert | src NULL), checked standalone and per
  occurrence in-program under the side/delay field mask;
- **cross-check against stage 1**: per-program instruction counts from
  `check_pio_timing.py`'s parser must match pioasm's — catches any
  extraction/regex divergence between the two tools;
- **pio_version must be 0** (RP2040/RP2350 compatible); a non-zero
  version means an RP2350-only instruction crept in and breaks the
  ARCHITECTURE.md both-boards guarantee → FAIL.

Exit 0 = all compiled and matched. Never modifies ARCHITECTURE.md —
it validates whatever the doc actually says.

## pio_sim.py — stage-3: behavioral simulation vs a mock 33C93A

```
python3 tools/pio_sim.py [-v]
```

Stage 1 proves the strobe timing, stage 2 proves the source assembles —
neither proves the programs implement the **protocol**. Stage 3
executes the programs cycle-by-cycle against a mock WD33C93A register
file and checks what the chip would actually *do*:

- **Executes real machine words.** A built-in assembler turns the
  ARCHITECTURE.md `pioasm` blocks into 16-bit PIO instructions, then a
  cycle-accurate SM model (OSR/ISR shifts, autopush/autopull, FIFO
  stalls, side-set-on-first-cycle, delay cycles, pindirs, the 2-sys_clk
  input-synchronizer age) decodes and runs the *words* — so a
  mis-encoded field is an execution failure. The assembled `sbic_bus`
  is cross-checked word-for-word against the pioasm 2.2.0 output
  captured in `../session/6e23006d-*` (golden reference embedded).
- **Mock chip enforces the datasheet at every pin edge**: indirect
  Address-register protocol with its auto-increment exceptions
  (Aux Status / Data 19h / Command 18h — app notes §6.2.2, B datasheet
  §3.1.2), strobe min/max widths and recovery (§9.1.3/9.1.4), read
  data driven only after tRLDV — a program that samples early gets
  garbage *and* a logged violation — data setup on writes, bus
  contention, DACK̅-vs-CS̅ exclusion (E024), MR̅ ≥ 1 µs, INTRQ
  set/clear semantics (§9.1.13), the 7 µs LCI rule, and DRQ̅/DACK̅
  burst handshaking.
- **Chip-variant-aware burst timing** (`chip_variant="A"|"B"` on
  `Bus`/`Sim`/`MockWD33C93A`, default A = worst case). A enforces
  §9.1.11/9.1.12: every read byte independently valid ≤ 50 ns from
  RE̅↓, strobes ≥ 80/50 ns, setup ≥ 25 ns, recovery ≥ 80 ns. B
  enforces §6.1.11/6.1.12: strobes ≥ 30 ns, setup ≥ 18 ns, and the
  *pipelined* read model — the mock only makes the first byte valid
  ≤ 50 ns from DACK̅↓ (tDLDV) and each later byte ≤ 80 ns from the
  *previous* RE̅↑ (tRHDV), so an SM that strobes faster than the
  pipeline delivers reads garbage and fails functionally.

Tests (any datasheet violation fails the test that produced it):

| Test | Proves |
|---|---|
| `golden-encoding` | assembler == session pioasm 2.2.0 words |
| `init-sequence` | **SM0 full init: MR̅ pulse → wait INTRQ → read SCSI Status (INTRQ clears) → write Own ID → read it back** |
| `aux-status` | A0=0 read returns Aux Status, Address reg untouched |
| `auto-increment` | CDB 03h–06h in 1+N cycles; Data 19h doesn't advance |
| `lci-7us-rule` | command <7 µs after status read ignored + LCI; ≥7 µs accepted (soft reset → interrupt 00h) |
| `burst-in` / `burst-out` | SM1 DRQ̅/DACK̅ bursts (A variant) move every byte in order, CS̅ high, completion INTRQ, DRQ̅ deasserts |
| `golden-burst-pipeline` | B variant: 12 bytes arrive intact under the pipelined validity model, and every prev-RE̅↑ → next-RE̅↓ gap ≥ 80 ns (the §2 claim that B data is stable before its strobe even falls) |
| `variant-probe` | Appendix E item 9 works: soft reset with EAF+RAF → SCSI Status 01h on both variants; CDB1 = microcode revision on a B, 0 on an A |
| `fifo-stall-hazard` | the §2 warning is real: a 5th un-drained SM0 read wedges `in pins` with RE̅ low, and the mock flags the tRE ≤ 10 µs violation |

The mock's checks are mutation-tested: shortening a strobe delay or
moving the read sample earlier makes the corresponding test fail.
Timing constants deliberately mirror `check_pio_timing.py`. Exit 0 =
all tests pass. Like the other stages it never modifies
ARCHITECTURE.md — it validates whatever the doc actually says.

**Validation flow after any PIO-related edit:**
```
python3 tools/check_pio_timing.py   # encoding budget + timing sim
python3 tools/assemble_pio.py       # real compiler + config verification
python3 tools/pio_sim.py            # behavioral sim vs mock 33C93A
```

## extract_netlist.py — KiCad PCB netlist dump

```
python3 tools/extract_netlist.py [repo/scsi/scsi.kicad_pcb]
```

Dumps pad → net for every footprint. The schematic has no net labels,
so this is how the J4 "CPU" header pinout, the grounded-ALE discovery,
the direct-to-header SCSI RST routing, and the J2/J3 termination/TERMPWR
analysis in ARCHITECTURE.md §0 were derived. U1 pads are annotated with
AM33C93A pin names (from `repo/h4rm0n1c.kicad_sym`, verified against the
AMD datasheet PLCC-44 connection diagram).

# ../docs-extracted/

`pdftotext` extractions of the datasheets that have text layers, kept
because the searchable text is what all register/timing citations in
ARCHITECTURE.md came from.

**OCR reliability status (verified 2026-07-05):** prose and register
bit descriptions extract fine, but **multi-column timing tables come
out with jumbled columns — do not trust extracted timing numbers.**
Every timing value used by ARCHITECTURE.md / check_pio_timing.py was
re-verified by reading the PDF pages as images: A app notes pp. 52–53
(indirect R/W), 60–62 (burst DMA, INTRQ); B datasheet pp. 47–49 (CLK,
MR̅, indirect R/W), 56–57 (burst DMA). The complete SCSI Status
interrupt-code tables and MCI decode (Appendix G) were likewise
verified against B datasheet pp. 21–24 — every code value, state
column, and meaning matched (one wording nuance fixed at 14h). One extraction-induced error was
found and fixed (A burst-read tRLDV is 50 ns, not 70), plus one real
finding (B burst reads are pipelined from DACK̅↓/previous RE̅↑). If you
pull new timing numbers from these .txt files, verify the page visually
first:

- `WD33C93A-appnotes.txt` — register map, indirect-addressing rules, all
  host-bus timing tables, errata index (E018/E022/E024/E040/E049…).
- `WD33C93B.txt` — command opcode table, B-variant differences.
- `SCSI-1-spec.txt` (ANSI X3.131-1986) — **kept local-only, not
  committed**: it is the full text of a paid ANSI standard. Regenerate
  with `pdftotext SCSI-1-spec.pdf docs-extracted/SCSI-1-spec.txt` from a
  locally obtained copy of the standard.

Not present: `AM33C93A.pdf` and `WD33C93A.pdf` are page scans with no
text layer (extraction yields nothing) — consult those PDFs visually;
the AMD PLCC-44 connection diagram is on datasheet page 1-5.
