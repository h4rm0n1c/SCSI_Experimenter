# SCSI Experimenter

A 33C93A/WD33C93-based SCSI experimenter board for microcontroller projects, with a complete software architecture for running it from a Raspberry Pi Pico W or Pico 2 W.

## What it is

This repo contains:

- **KiCad hardware design** — a breakout board built around the AM33C93A/WD33C93A SCSI bus interface controller, with a 26-pin CPU header and 50-pin SCSI-1 connector, passive 220/330Ω termination, and TERMPWR direction switch (HBA/vampire modes).
- **Complete software architecture** — verified PIO firmware design for initiator and target modes, documented at `ARCHITECTURE.md` (1184 lines).
- **Verification tools** — cycle-accurate PIO timing simulation, real `pioasm` compilation checks, and KiCad netlist extraction.
- **Datasheets** — AM33C93A, WD33C93A/B, RP2040, RP2350, and SCSI-1 spec, plus extracted text layers.

## Repository structure

```
├── ARCHITECTURE.md          — Complete software architecture reference
├── scsi/                    — KiCad PCB design files
│   ├── scsi.kicad_sch       — Schematic (S-expression)
│   ├── scsi.kicad_pcb       — PCB layout
│   └── scsi.kicad_pro       — Project metadata
├── h4rm0n1c.kicad_sym       — AM33C93A/AM33C93A KiCad symbol
├── render.png               — Board render
├── docs/                    — Datasheets and references
│   ├── AM33C93A.pdf         — AMD datasheet (49 pages)
│   ├── WD33C93A.pdf         — WD variant datasheet
│   ├── WD33C93B.pdf         — Enhanced version datasheet
│   ├── WD33C93A-appnotes.pdf — Combined datasheet + app notes + errata
│   ├── SCSI-1-spec.pdf      — ANSI X3.131-1986
│   ├── RP2040-datasheet.pdf — RP2040 microcontroller
│   ├── RP2350-datasheet.pdf — RP2350 microcontroller
│   ├── PicoW-pinout-diagram.pdf
│   ├── Pico2W-pinout-diagram.pdf
│   └── PICO_GPIO_CHEATSHEET.md — Verified GPIO reference
├── docs-extracted/          — pdftotext of searchable datasheets
│   ├── WD33C93A-appnotes.txt
│   └── WD33C93B.txt
└── tools/                   — Verification tools
    ├── check_pio_timing.py  — Stage 1: timing simulator
    ├── assemble_pio.py      — Stage 2: pioasm compilation + cross-check
    ├── extract_netlist.py   — KiCad PCB netlist dumper
    └── README.md            — Tool documentation
```

## Quick start

### 1. Hardware

The board has a 26-pin CPU header (J4) that connects directly to a Pico 2 W GPIOs — no level shifters required (RP2350 GPIOs are 5V tolerant). For RP2040/Pico W builds, a 74LVC8T245 is needed on the data bus.

See `ARCHITECTURE.md` §0 (§0 for the J4 pinout and §1 for the GPIO map.

### 2. Validation

From the repo root, verify the PIO design:

```bash
python3 tools/check_pio_timing.py   # timing simulation against datasheet specs
python3 tools/assemble_pio.py       # real pioasm compilation
```

Both should exit 0.

### 3. Reading the architecture

Start with `ARCHITECTURE.md`:

- **§0–1** — Board discovery and GPIO allocation
- **§2** — PIO state machine design (register engine + burst DMA)
- **§3** — Register access layer and C API
- **§4** — SCSI bus phase engine (initiator)
- **§5** — Interrupt vs polling vs DMA analysis
- **§6** — Clock generation
- **§7** — RP2040 vs RP2350 comparison
- **Appendices F–I** — Complete register reference, interrupt codes, command reference, target mode

## Architecture highlights

- **PIO-based bus interface** — two state machines in one PIO block (22 of 32 instruction slots), driving all 33C93A register accesses with hardware-bounded strobes. No CPU bit-banging.
- **Burst DMA** — DRQ/DACK-paced PIO engine + DMA channel for data phases, zero CPU per byte, ~2.5 MB/s throughput.
- **SM clock 24 MHz** — derived from 120 MHz sysclk, chosen so all timing minima land on integer cycle counts with margin.
- **Indirect addressing** — ALE is grounded on this board, so every register access is a two-cycle operation.
- **Dual board support** — same firmware binary runs on Pico W and Pico 2 W (Pico 2 W recommended for zero-glue wiring).

## Variant support

The architecture covers the full WD33C93 family — original WD33C93, WD33C93A, WD33C93B, and AMD AM33C93A. All variant-specific features are flagged `[A+]` or `[B]` throughout the reference. The fitted chip on this board is the WD33C93B, which is used as the primary reference.

## Target mode

The 33C93A supports both initiator and target SCSI roles. The architecture covers target mode in Appendix I, including Wait-for-Select-and-Receive (0Ch) as the recommended parked state, reselection handling, and the full set of target commands. The PIO layer is identical regardless of mode.

## License

WTFPL — see the schematic title block.
