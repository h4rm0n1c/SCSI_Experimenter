#!/usr/bin/env python3
"""Dump the pad -> net mapping for every footprint in a KiCad PCB file.

The schematic (scsi.kicad_sch) has no net labels -- everything is wired
point-to-point -- so the PCB netlist is the authoritative source for how
the AM33C93A (U1), the SCSI connector (J1), and the CPU header (J4) are
connected. This script produced the J4 pinout table in ARCHITECTURE.md.

Usage:
    python3 tools/extract_netlist.py [path/to/board.kicad_pcb]

Cross-reference U1 pad numbers against the pin names in
repo/h4rm0n1c.kicad_sym (which matches the AMD Am33C93A PLCC-44
connection diagram) to turn pad numbers into signal names.
"""

import re
import sys

DEFAULT_PCB = "repo/scsi/scsi.kicad_pcb"

# AM33C93A PLCC-44 pin names, from repo/h4rm0n1c.kicad_sym, verified
# against the AMD datasheet connection diagram (pub #11853 p.1-5).
U1_PIN_NAMES = {
    1: "(SI test)", 2: "I/O-", 3: "MSG-", 4: "GND", 5: "C/D-", 6: "BSY-",
    7: "SEL-", 8: "CLK", 9: "DRQ-", 10: "DACK-", 11: "DP", 12: "INTRQ",
    13: "D0", 14: "D1", 15: "D2", 16: "D3", 17: "D4", 18: "D5", 19: "D6",
    20: "D7", 21: "A0", 22: "(SCLK test)", 23: "GND", 24: "CS-", 25: "WE-",
    26: "RE-", 27: "ALE", 28: "SDP-", 29: "SD0-", 30: "SD1-", 31: "GND",
    32: "SD2-", 33: "SD3-", 34: "SD4-", 35: "SD5-", 36: "(HALT test)",
    37: "SD6-", 38: "SD7-", 39: "GND", 40: "MR-", 41: "ATN-", 42: "ACK-",
    43: "REQ-", 44: "VCC",
}

PAD_RE = re.compile(
    r'\(pad "([^"]+)"[^()]*?(?:\((?!net)[^()]*\)[^()]*?)*\(net \d+ "([^"]+)"\)'
)


def main() -> None:
    pcb = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PCB
    text = open(pcb).read()

    for fp in re.split(r'\(footprint "', text)[1:]:
        ref_m = re.search(r'\(property "Reference" "([^"]+)"', fp)
        if not ref_m:
            continue
        ref = ref_m.group(1)
        val_m = re.search(r'\(property "Value" "([^"]+)"', fp)
        val = val_m.group(1) if val_m else "?"
        pads = sorted(
            set(PAD_RE.findall(fp)),
            key=lambda p: int(p[0]) if p[0].isdigit() else 999,
        )
        if not pads:
            continue
        print(f"== {ref} ({val}) ==")
        for pad, net in pads:
            name = ""
            if ref == "U1" and pad.isdigit():
                name = f"  [{U1_PIN_NAMES.get(int(pad), '?')}]"
            print(f"  pad {pad}: {net}{name}")


if __name__ == "__main__":
    main()
