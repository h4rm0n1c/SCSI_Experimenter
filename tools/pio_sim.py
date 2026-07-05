#!/usr/bin/env python3
"""Stage-3 PIO verification: behavioral simulation against a mock 33C93A.

check_pio_timing.py (stage 1) proves the strobe *timing* meets the
datasheet; assemble_pio.py (stage 2) proves the source *assembles*.
Neither proves the programs implement the *protocol*: that the bits SM0
puts on D0–7/A0 while WE̅ is low actually drive the indirect-addressing
state machine of the chip (WD33C93A app notes §6.2.2 / B datasheet
§3.1.2), that INTRQ rises and falls when the datasheet says (§9.1.13),
or that SM1's DACK̅+strobe bursts move bytes in order (§9.1.11/9.1.12;
B §6.1.11/6.1.12). This tool closes that gap:

  1. Assembles the ```pioasm blocks in ARCHITECTURE.md to real 16-bit
     PIO machine words with a built-in encoder, and cross-checks the
     sbic_bus result word-for-word against the pioasm-2.2.0 output
     captured in session/6e23006d-*/ (golden reference embedded below).
  2. Executes those *words* — decode included, so a mis-encoded field
     is an execution failure, not a parse difference — in a
     cycle-accurate PIO SM model: OSR/ISR shifts, autopush/autopull,
     FIFO stalls, side-set-on-first-cycle, delay cycles, pindirs, and
     the 2-sys_clk input-synchronizer age on `in pins` / `wait gpio`.
  3. Wires the pins (per the ARCHITECTURE.md §1 GPIO map) to a mock
     WD33C93A register file that enforces the datasheet at every edge:
     strobe min/max widths, recovery, data setup/valid windows, bus
     contention, DACK̅-vs-CS̅ exclusion (errata E024), the indirect
     Address-register protocol with its auto-increment exceptions
     (Aux Status / Data 19h / Command 18h), INTRQ set/clear semantics,
     the 7 µs LCI rule, and DRQ̅ burst handshaking.

Timing constants (SM divider, sys_clk, datasheet minima) intentionally
mirror check_pio_timing.py so the two stages cannot silently diverge.

Tests (run all; exit 0 = pass):
  golden-encoding    assembler output == pioasm 2.2.0 words from session
  init-sequence      SM0 full init: MR̅ pulse → wait INTRQ → read SCSI
                     Status (INTRQ must clear) → write Own ID → read back
  aux-status         A0=0 read returns Aux Status, Address reg untouched
  auto-increment     CDB regs 03h–06h written 1+N cycles, read back;
                     Data (19h) does NOT auto-increment
  lci-7us-rule       command <7 µs after status read ignored + LCI;
                     ≥7 µs accepted (soft reset → interrupt 00h)
  burst-in           SM1 DRQ̅/DACK̅ read burst: order, timing, CS̅ high
  burst-out          SM1 write burst: order, setup, strobe width
  fifo-stall-hazard  >4 un-drained SM0 reads → `in` stalls with RE̅ low
                     → mock must flag the tRE ≤ 10 µs violation

Run from the repo root:
    python3 tools/pio_sim.py [-v]
"""

import argparse
import re
import sys

DOC = "ARCHITECTURE.md"

# --- clocking (same numbers as check_pio_timing.py) --------------------
F_SYS = 120e6
SM_DIV = 5
T = 1e9 / (F_SYS / SM_DIV)      # ns per SM cycle (41.67)
SYNC = 2 * (1e9 / F_SYS)        # input-synchronizer age, ns (16.7)

# --- GPIO map (ARCHITECTURE.md section 1) -------------------------------
D0 = 0                          # GP0-7  D0-D7
A0 = 8                          # GP8
CS = 9                          # GP9   CS-   (active low)
WE = 10                         # GP10  WE-
RE = 11                         # GP11  RE-
DACK = 12                       # GP12  DACK-
MR = 14                         # GP14  MR-
INTRQ = 15                      # GP15  INTRQ (active HIGH)
DRQ = 16                        # GP16  DRQ-  (active low, 1k pull-up)

# --- datasheet limits, ns (A app notes 9.1.3/9.1.4/9.1.11/9.1.12/9.1.13;
#     Appendix C of ARCHITECTURE.md) -------------------------------------
IND_TWE_MIN = 120.0         # WE- pulse width
IND_TDVWH_MIN = 70.0        # data valid to WE- high
IND_TRE_MIN = 180.0         # RE- pulse width
IND_TRE_MAX = 10_000.0      # RE- pulse width max (the FIFO-stall trap)
IND_TRLDV = 180.0           # RE- low to data valid (chip drive delay)
IND_RECOVERY = 100.0        # tWHWL / tRHRL
BST_TRD_MIN = 80.0          # burst RE- width (A)
BST_TRLDV = 50.0            # burst RE- low to data valid (A)
BST_TWR_MIN = 50.0          # burst WE- width (A)
BST_TDVWH_MIN = 25.0        # burst data setup (A)
BST_RECOVERY = 80.0         # burst strobe recovery (A)
BST_PIPE_GAP = 80.0         # B pipelined read: prev RE-hi -> next RE-lo
MR_MIN = 1_000.0            # MR- pulse width
LCI_WINDOW = 7_000.0        # 7 us command lockout after status read
RESET_DONE_NS = 5_000.0     # mock: MR-/soft-reset completion latency

# Golden sbic_bus words: pioasm 2.2.0 output captured in
# session/6e23006d-864c-4742-9457-511b329ae541.jsonl (sbic_bus.pio.h).
GOLDEN_SBIC_BUS = [
    0x9CA0, 0x7C09, 0x7C21, 0x1C2A, 0xBCE3, 0x7C88, 0xAB42,
    0xA942, 0x4808, 0x1D00, 0xBCEB, 0x7C88, 0xB342, 0x1D00,
]

# Register file constants
REG_OWN_ID = 0x00
REG_CONTROL = 0x01
REG_CDB1 = 0x03
REG_SCSI_STATUS = 0x17
REG_COMMAND = 0x18
REG_DATA = 0x19

CMD_RESET = 0x00
CMD_TRANSFER_INFO = 0x20

# TX-word encoding (ARCHITECTURE.md section 3 C API)
def XW(a0, d):
    return ((a0 & 1) << 8) | (d & 0xFF)

def XR(a0):
    return (1 << 9) | ((a0 & 1) << 8)


# ========================================================================
# pioasm subset assembler (validated against GOLDEN_SBIC_BUS)
# ========================================================================

_JMP_COND = {"": 0, "!x": 1, "x--": 2, "!y": 3, "y--": 4,
             "x!=y": 5, "pin": 6, "!osre": 7}
_OUT_DEST = {"pins": 0, "x": 1, "y": 2, "null": 3, "pindirs": 4,
             "pc": 5, "isr": 6, "exec": 7}
_IN_SRC = {"pins": 0, "x": 1, "y": 2, "null": 3, "isr": 6, "osr": 7}
_MOV_DEST = {"pins": 0, "x": 1, "y": 2, "exec": 4, "pc": 5,
             "isr": 6, "osr": 7}
_MOV_SRC = {"pins": 0, "x": 1, "y": 2, "null": 3, "status": 5,
            "isr": 6, "osr": 7}
_WAIT_SRC = {"gpio": 0, "pin": 1, "irq": 2}

_LINE_RE = re.compile(
    r"^(?:(\w+):\s*)?(\S.*?)?\s*(?:side\s+(0b[01]+|\d+))?\s*(?:\[(\d+)\])?$")


def assemble(source, side_bits=3):
    """Assemble the pioasm subset used by ARCHITECTURE.md -> word list."""
    labels, body = {}, []
    for raw in source.splitlines():
        line = raw.split(";")[0].strip()
        if not line or line.startswith("."):
            continue
        m = _LINE_RE.match(line)
        label, instr, side, delay = m.groups()
        if label:
            labels[label] = len(body)
        if instr:
            if side is None:
                raise ValueError(f"missing side annotation: {line!r}")
            body.append((instr.strip(), int(side, 0), int(delay or 0)))

    delay_bits = 5 - side_bits
    if any(d >= (1 << delay_bits) for _, _, d in body):
        raise ValueError("delay exceeds field budget")

    words = []
    for instr, side, delay in body:
        parts = instr.replace(",", " ").split()
        op, args = parts[0], parts[1:]
        if op == "nop":
            word = 0xA000 | (_MOV_DEST["y"] << 5) | _MOV_SRC["y"]
        elif op == "pull":
            word = 0x8000 | (1 << 7) | (("block" in args) << 5)
        elif op == "push":
            word = 0x8000 | (("block" in args) << 5)
        elif op == "jmp":
            cond = args[0] if len(args) == 2 else ""
            target = args[-1]
            addr = labels[target] if target in labels else int(target, 0)
            word = 0x0000 | (_JMP_COND[cond] << 5) | addr
        elif op == "out":
            count = int(args[1], 0)
            word = 0x6000 | (_OUT_DEST[args[0]] << 5) | (count & 0x1F)
        elif op == "in":
            count = int(args[1], 0)
            word = 0x4000 | (_IN_SRC[args[0]] << 5) | (count & 0x1F)
        elif op == "mov":
            src = args[1]
            invert = src.startswith("~")
            word = (0xA000 | (_MOV_DEST[args[0]] << 5)
                    | (0b01 << 3 if invert else 0)
                    | _MOV_SRC[src.lstrip("~!")])
        elif op == "wait":
            pol, src, idx = int(args[0], 0), args[1], int(args[2], 0)
            word = 0x2000 | (pol << 7) | (_WAIT_SRC[src] << 5) | idx
        else:
            raise ValueError(f"unsupported instruction: {instr!r}")
        word |= (side << (8 + delay_bits)) | (delay << 8)
        words.append(word)
    return words


def extract_programs(doc_text):
    """-> {name: (source, words)} from the ```pioasm blocks."""
    programs = {}
    for block in re.findall(r"```pioasm\n(.*?)```", doc_text, re.S):
        name = re.search(r"\.program (\S+)", block).group(1)
        programs[name] = (block, assemble(block))
    return programs


# ========================================================================
# Pin bus with timestamped history (for synchronizer-delayed sampling)
# ========================================================================

class Bus:
    """Resolves SM outputs, firmware GPIOs and chip drivers per pin.

    Precedence per pin: at most one driver may be active (contention is
    a logged violation).  Undriven pins float to their pull value.
    """

    def __init__(self):
        self.pull = {DRQ: 1}                # 1k external pull-up on DRQ-
        self.sm_out = {}                    # pin -> level (output register)
        self.sm_dir = {}                    # pin -> bool driven by SM
        self.fw_out = {}                    # pin -> level or absent
        self.chip_out = {}                  # pin -> level or absent
        self.history = {}                   # pin -> [(t, level)]
        self.violations = []
        self.listeners = []                 # f(t, pin, old, new)
        self._levels = {}

    def violation(self, t, msg):
        self.violations.append((t, msg))

    def level(self, pin):
        drivers = []
        if self.sm_dir.get(pin):
            drivers.append(self.sm_out.get(pin, 0))
        if pin in self.fw_out:
            drivers.append(self.fw_out[pin])
        if pin in self.chip_out:
            drivers.append(self.chip_out[pin])
        if not drivers:
            return self.pull.get(pin, 1)    # float high (terminated bus)
        return drivers[0]

    def contention(self, pin):
        n = (bool(self.sm_dir.get(pin)) + (pin in self.fw_out)
             + (pin in self.chip_out))
        return n > 1

    def commit(self, t):
        """Recompute all pins; record transitions and notify listeners.

        Two-phase: all same-cycle level changes land in _levels/history
        first, THEN listeners fire -- so a listener judging pin X (e.g.
        "was DACK- low when RE- fell?") sees every co-asserted side-set
        bit of the same instruction, regardless of GPIO numbering.
        """
        pins = (set(self.sm_out) | set(self.sm_dir) | set(self.fw_out)
                | set(self.chip_out) | set(self.pull) | set(self._levels))
        changed = []
        for pin in sorted(pins):
            if self.contention(pin):
                self.violation(t, f"bus contention on GP{pin}")
            new = self.level(pin)
            old = self._levels.get(pin, self.pull.get(pin, 1))
            if new != old or pin not in self._levels:
                self._levels[pin] = new
                self.history.setdefault(pin, []).append((t, new))
                changed.append((pin, old, new))
        for pin, old, new in changed:
            for f in self.listeners:
                f(t, pin, old, new)

    def sampled(self, pin, t):
        """Pin level as seen through the 2-flop synchronizer at time t."""
        hist = self.history.get(pin, [])
        val = self.pull.get(pin, 1)
        for ht, hv in hist:
            if ht <= t:
                val = hv
            else:
                break
        return val

    def now(self, pin):
        return self._levels.get(pin, self.pull.get(pin, 1))

    def data_byte_now(self):
        return sum(self.now(D0 + i) << i for i in range(8))

    def data_byte_sampled(self, t):
        return sum(self.sampled(D0 + i, t) << i for i in range(8))


# ========================================================================
# PIO state machine: executes 16-bit words, cycle-accurate
# ========================================================================

class StateMachine:
    def __init__(self, bus, words, *, name, sideset_base, out_base,
                 out_count, in_base, side_bits=3,
                 out_shift_right=True, autopull=False, pull_thresh=32,
                 in_shift_right=False, autopush=False, push_thresh=8):
        self.bus = bus
        self.name = name
        self.words = words
        self.sideset_base = sideset_base
        self.side_bits = side_bits
        self.delay_bits = 5 - side_bits
        self.out_base, self.out_count = out_base, out_count
        self.in_base = in_base
        self.out_shift_right = out_shift_right
        self.autopull, self.pull_thresh = autopull, pull_thresh
        self.in_shift_right = in_shift_right
        self.autopush, self.push_thresh = autopush, push_thresh
        self.pc = 0
        self.x = self.y = 0
        self.osr, self.osr_count = 0, 32        # 32 = empty (all shifted)
        self.isr, self.isr_count = 0, 0
        self.tx, self.rx = [], []               # FIFOs, depth 4
        self.delay_left = 0
        self.enabled = True

    # -- pin helpers -----------------------------------------------------
    def _apply_sideset(self, side):
        for i in range(self.side_bits):
            pin = self.sideset_base + i
            self.bus.sm_out[pin] = (side >> i) & 1
            self.bus.sm_dir[pin] = True

    def set_pins(self, base, count, value, dirs=False):
        for i in range(count):
            pin = base + i
            if dirs:
                self.bus.sm_dir[pin] = bool((value >> i) & 1)
            else:
                self.bus.sm_out[pin] = (value >> i) & 1

    # -- OSR/ISR ----------------------------------------------------------
    def _out_shift(self, n):
        if self.out_shift_right:
            val = self.osr & ((1 << n) - 1)
            self.osr >>= n
        else:
            val = (self.osr >> (32 - n)) & ((1 << n) - 1)
            self.osr = (self.osr << n) & 0xFFFFFFFF
        self.osr_count += n
        return val

    def step(self, t):
        """Execute one SM cycle beginning at time t (ns)."""
        if not self.enabled:
            return
        if self.delay_left:                     # burning delay cycles
            self.delay_left -= 1
            return

        word = self.words[self.pc]
        side = (word >> (8 + self.delay_bits)) & ((1 << self.side_bits) - 1)
        delay = (word >> 8) & ((1 << self.delay_bits) - 1)
        opc = word >> 13
        rest = word & 0xFF

        # side-set takes effect on the first cycle, stall or not
        self._apply_sideset(side)
        self.bus.commit(t)

        stalled = False
        advance = True

        if opc == 0b000:                        # JMP
            cond, addr = (rest >> 5) & 7, word & 0x1F
            take = {0: True, 1: self.x == 0, 3: self.y == 0}.get(cond)
            if cond == 2:
                take, self.x = self.x != 0, (self.x - 1) & 0xFFFFFFFF
            if cond == 4:
                take, self.y = self.y != 0, (self.y - 1) & 0xFFFFFFFF
            if cond == 5:
                take = self.x != self.y
            if cond == 6:
                take = self.bus.sampled(0, t - SYNC) == 1  # unused here
            self.pc = addr if take else self.pc + 1
            advance = False
        elif opc == 0b001:                      # WAIT
            pol, src, idx = (rest >> 7) & 1, (rest >> 5) & 3, word & 0x1F
            assert src == 0, "only WAIT ... GPIO modeled"
            if self.bus.sampled(idx, t - SYNC) != pol:
                stalled = True
        elif opc == 0b010:                      # IN
            src, n = (rest >> 5) & 7, (word & 0x1F) or 32
            assert src == 0, "only IN PINS modeled"
            # autopush full-RX stall happens *before* the shift commits
            if self.autopush and self.isr_count + n >= self.push_thresh \
                    and len(self.rx) >= 4:
                stalled = True
            else:
                val = 0
                for i in range(n):
                    val |= self.bus.sampled(self.in_base + i, t - SYNC) << i
                if self.in_shift_right:
                    self.isr = (self.isr >> n) | (val << (32 - n))
                else:
                    self.isr = ((self.isr << n) | val) & 0xFFFFFFFF
                self.isr_count += n
                if self.autopush and self.isr_count >= self.push_thresh:
                    self.rx.append(self.isr & ((1 << self.push_thresh) - 1)
                                   if not self.in_shift_right else self.isr)
                    self.isr, self.isr_count = 0, 0
        elif opc == 0b011:                      # OUT
            dest, n = (rest >> 5) & 7, (word & 0x1F) or 32
            if self.autopull and self.osr_count >= self.pull_thresh:
                if self.tx:
                    self.osr, self.osr_count = self.tx.pop(0), 0
                else:
                    stalled = True
            if not stalled:
                val = self._out_shift(n)
                if dest == 0:
                    self.set_pins(self.out_base, n, val)
                elif dest == 1:
                    self.x = val
                elif dest == 2:
                    self.y = val
                elif dest == 4:
                    self.set_pins(self.out_base, n, val, dirs=True)
                else:
                    raise NotImplementedError(f"OUT dest {dest}")
        elif opc == 0b100:                      # PUSH/PULL
            if (rest >> 7) & 1:                 # PULL
                if self.tx:
                    self.osr, self.osr_count = self.tx.pop(0), 0
                else:
                    stalled = True              # block assumed
            else:                               # PUSH
                if len(self.rx) < 4:
                    self.rx.append(self.isr)
                    self.isr, self.isr_count = 0, 0
                else:
                    stalled = True
        elif opc == 0b101:                      # MOV
            dest, op_, src = (rest >> 5) & 7, (rest >> 3) & 3, word & 7
            srcval = {1: self.x, 2: self.y, 3: 0,
                      6: self.isr, 7: self.osr}.get(src)
            if srcval is None:
                raise NotImplementedError(f"MOV src {src}")
            if op_ == 1:
                srcval = (~srcval) & 0xFFFFFFFF
            if dest == 1:
                self.x = srcval
            elif dest == 2:
                self.y = srcval
            elif dest == 6:
                self.isr, self.isr_count = srcval, 0
            elif dest == 7:
                self.osr, self.osr_count = srcval, 0
            else:
                raise NotImplementedError(f"MOV dest {dest}")
        else:
            raise NotImplementedError(f"opcode {opc:#05b}")

        self.bus.commit(t)
        if stalled:
            return                              # retry same instr next cycle
        if advance:
            self.pc = (self.pc + 1) % len(self.words)
        elif self.pc >= len(self.words):        # jmp past end wraps
            self.pc = 0
        self.delay_left = delay


# ========================================================================
# Mock WD33C93A: register file + datasheet enforcement at the pins
# ========================================================================

class MockWD33C93A:
    """Indirect-addressing (ALE grounded) register-file model.

    Watches CS-/WE-/RE-/DACK-/A0/D0-7/MR- edges via bus listeners and
    enforces every host-bus constraint from Appendix C at the moment it
    can be judged (strobe edges).  Read data is driven onto D0-7 only
    after the datasheet valid delay -- a PIO program that samples too
    early reads a garbage pattern AND logs a violation, so functional
    results double as timing proof.
    """

    def __init__(self, bus):
        self.bus = bus
        bus.listeners.append(self.on_pin_change)
        bus.chip_out[INTRQ] = 0         # driven inactive from power-on
        self.regs = [0] * 0x20
        self.addr_reg = 0
        # aux status bits
        self.int_ = False
        self.lci = False
        self.dbr = False
        # timing bookkeeping
        self.fall = {}                  # pin -> (t, context) of active strobe
        self.last_rise = None           # (t, 'ind'|'bst') last strobe rise
        self.last_re_rise_bst = None
        self.mr_fall = None
        self.data_stable_since = -1e18  # last D0-7 change (host side)
        self.last_status_read = -1e18
        # read-drive model
        self.driving = False
        self.drive_valid_at = None
        self.drive_value = 0
        self._pending_read = (0, 0)
        # scheduled chip events [(t, fn)]
        self.events = []
        # burst engine
        self.burst_dir = None           # 'in' | 'out' | None
        self.scsi_in = []               # bytes the "target" will send us
        self.scsi_out = []              # bytes captured from burst writes
        self.xfer_remaining = 0
        # log of decoded register accesses
        self.log = []

    # -- helpers -----------------------------------------------------------
    def viol(self, t, msg):
        self.bus.violation(t, f"chip: {msg}")

    def schedule(self, t, fn):
        self.events.append((t, fn))
        self.events.sort(key=lambda e: e[0])

    def run_events(self, t):
        while self.events and self.events[0][0] <= t:
            et, fn = self.events.pop(0)
            fn()
            self.bus.commit(et)         # chip drives must hit the bus NOW
        # keep DRQ- pin in sync with burst state
        if self.burst_dir:
            want = 0 if self._drq_ready() else 1
            if self.bus.chip_out.get(DRQ) != want:
                self.bus.chip_out[DRQ] = want
                self.bus.commit(t)

    def _drq_ready(self):
        if self.burst_dir == "in":
            return bool(self.scsi_in)
        if self.burst_dir == "out":
            return self.xfer_remaining > 0
        return False

    def aux_status(self):
        return ((self.int_ << 7) | (self.lci << 6) | (self.dbr << 0))

    def set_int(self, code):
        self.regs[REG_SCSI_STATUS] = code
        self.int_ = True
        self.bus.chip_out[INTRQ] = 1

    # -- data-bus drive model ----------------------------------------------
    def begin_drive(self, t, value, valid_delay):
        self.driving = True
        self.drive_valid_at = t + valid_delay
        self.drive_value = value
        for i in range(8):
            self.bus.chip_out[D0 + i] = 0      # pre-valid garbage
        self.schedule(self.drive_valid_at, self._make_valid)

    def _make_valid(self):
        if self.driving:
            for i in range(8):
                self.bus.chip_out[D0 + i] = (self.drive_value >> i) & 1

    def end_drive(self, t):
        # hold 5 ns min after strobe rise, then release
        def release():
            self.driving = False
            for i in range(8):
                self.bus.chip_out.pop(D0 + i, None)
        self.schedule(t + 5.0, release)

    # -- pin-edge protocol -------------------------------------------------
    def on_pin_change(self, t, pin, old, new):
        if D0 <= pin < D0 + 8 and not self.driving:
            self.data_stable_since = t
        if pin == MR:
            if new == 0:
                self.mr_fall = t
            elif self.mr_fall is not None:
                if t - self.mr_fall < MR_MIN:
                    self.viol(t, f"MR- pulse {t - self.mr_fall:.0f} ns "
                                 f"< {MR_MIN:.0f} min")
                self.schedule(t + RESET_DONE_NS, self._hard_reset_done)
                self.mr_fall = None
        elif pin in (WE, RE):
            cs, dack = self.bus.now(CS), self.bus.now(DACK)
            if new == 0:
                if cs == 0 and dack == 0:
                    self.viol(t, "CS- and DACK- both low (E024)")
                ctx = "ind" if cs == 0 else ("bst" if dack == 0 else None)
                if ctx is None:
                    self.viol(t, f"strobe GP{pin} fell with neither "
                                 "CS- nor DACK- low")
                    ctx = "ind"
                self._strobe_fall(t, pin, ctx)
            elif pin in self.fall:
                self._strobe_rise(t, pin)

    def _strobe_fall(self, t, pin, ctx):
        self.fall[pin] = (t, ctx)
        if self.last_rise is not None:
            lt, lctx = self.last_rise
            need = IND_RECOVERY if ctx == "ind" else BST_RECOVERY
            if t - lt < need:
                self.viol(t, f"recovery {t - lt:.1f} ns < {need:.0f} "
                             f"({ctx})")
        if pin == RE:
            if ctx == "ind":
                a0 = self.bus.now(A0)
                val = (self.aux_status() if a0 == 0
                       else self.regs[self.addr_reg])
                self._pending_read = (a0, self.addr_reg)
                self.begin_drive(t, val, IND_TRLDV)
            else:                               # burst read
                if self.burst_dir != "in":
                    self.viol(t, "burst RE- with no data-in transfer")
                    self.begin_drive(t, 0xEE, BST_TRLDV)
                elif not self.scsi_in:
                    self.viol(t, "burst RE- with FIFO empty (DRQ- high)")
                    self.begin_drive(t, 0xEE, BST_TRLDV)
                else:
                    self.begin_drive(t, self.scsi_in[0], BST_TRLDV)
                if self.last_re_rise_bst is not None \
                        and t - self.last_re_rise_bst < BST_PIPE_GAP:
                    self.viol(t, f"B pipelined-read gap "
                                 f"{t - self.last_re_rise_bst:.1f} ns "
                                 f"< {BST_PIPE_GAP:.0f}")

    def _strobe_rise(self, t, pin):
        t0, ctx = self.fall.pop(pin)
        width = t - t0
        self.last_rise = (t, ctx)
        if pin == WE:
            lo = IND_TWE_MIN if ctx == "ind" else BST_TWR_MIN
            if width < lo:
                self.viol(t, f"WE- width {width:.1f} ns < {lo:.0f} ({ctx})")
            setup = IND_TDVWH_MIN if ctx == "ind" else BST_TDVWH_MIN
            if not all(self.bus.sm_dir.get(D0 + i) for i in range(8)):
                self.viol(t, "WE- rose with D0-7 not host-driven")
            elif t - self.data_stable_since < setup:
                self.viol(t, f"data setup {t - self.data_stable_since:.1f} "
                             f"ns < {setup:.0f} ({ctx})")
            byte = self.bus.data_byte_now()
            if ctx == "ind":
                self._reg_write(t, self.bus.now(A0), byte)
            else:
                self._burst_write(t, byte)
        else:                                   # RE
            lo = IND_TRE_MIN if ctx == "ind" else BST_TRD_MIN
            if width < lo:
                self.viol(t, f"RE- width {width:.1f} ns < {lo:.0f} ({ctx})")
            if ctx == "ind" and width > IND_TRE_MAX:
                self.viol(t, f"RE- width {width:.1f} ns > "
                             f"{IND_TRE_MAX:.0f} max")
            if ctx == "ind":
                self._reg_read_done(t)
            else:
                self.last_re_rise_bst = t
                if self.burst_dir == "in" and self.scsi_in:
                    self.scsi_in.pop(0)
                    if not self.scsi_in:
                        self.bus.chip_out[DRQ] = 1
                        self.set_int(0x18)      # transfer complete
            self.end_drive(t)

    def check_hanging_strobes(self, t):
        """Call at end of run: an RE- still low past tRE max is a bug."""
        for pin, (t0, ctx) in self.fall.items():
            if pin == RE and ctx == "ind" and t - t0 > IND_TRE_MAX:
                self.viol(t, f"RE- still low after {t - t0:.0f} ns "
                             f"> {IND_TRE_MAX:.0f} max (FIFO stall?)")

    # -- register semantics --------------------------------------------------
    def _reg_write(self, t, a0, byte):
        if a0 == 0:
            self.addr_reg = byte & 0x1F
            self.log.append(("setaddr", byte & 0x1F))
            return
        reg = self.addr_reg
        self.log.append(("write", reg, byte))
        if reg == REG_COMMAND:
            self._command(t, byte)
        else:
            self.regs[reg] = byte
            if reg != REG_DATA:
                self.addr_reg = (self.addr_reg + 1) & 0x1F

    def _reg_read_done(self, t):
        a0, reg = self._pending_read
        if a0 == 0:
            self.log.append(("aux", self.aux_status()))
            return
        self.log.append(("read", reg, self.drive_value))
        if reg == REG_SCSI_STATUS:
            # INTRQ falls <= 100 ns after RE- rise (9.1.13); model at edge
            self.int_ = False
            self.bus.chip_out[INTRQ] = 0
            self.last_status_read = t
        if reg not in (REG_COMMAND, REG_DATA):
            self.addr_reg = (self.addr_reg + 1) & 0x1F

    def _command(self, t, byte):
        if t - self.last_status_read < LCI_WINDOW:
            self.lci = True
            self.log.append(("cmd-ignored-lci", byte))
            return
        self.lci = False
        self.regs[REG_COMMAND] = byte
        op = byte & 0x7F
        self.log.append(("cmd", op))
        if op == CMD_RESET:
            eaf = (self.regs[REG_OWN_ID] >> 3) & 1
            for r in range(0x01, 0x17):
                self.regs[r] = 0
            self.schedule(t + RESET_DONE_NS,
                          lambda: self.set_int(0x01 if eaf else 0x00))
        elif op == CMD_TRANSFER_INFO:
            dm = (self.regs[REG_CONTROL] >> 5) & 7
            if dm != 0b001:
                self.viol(t, f"Transfer Info with DM={dm:03b}, "
                             "burst test expects 001")
            count = ((self.regs[0x12] << 16) | (self.regs[0x13] << 8)
                     | self.regs[0x14])
            self.xfer_remaining = count
            if self.burst_dir == "in":
                self.scsi_in = self.scsi_in[:count]

    def _burst_write(self, t, byte):
        if self.burst_dir != "out":
            self.viol(t, "burst WE- with no data-out transfer")
            return
        if self.xfer_remaining <= 0:
            self.viol(t, "burst WE- past transfer count (DRQ- high)")
            return
        self.scsi_out.append(byte)
        self.xfer_remaining -= 1
        if self.xfer_remaining == 0:
            self.bus.chip_out[DRQ] = 1
            self.set_int(0x18)

    def _hard_reset_done(self):
        self.regs[REG_OWN_ID] = 0
        self.regs[REG_SCSI_STATUS] = 0
        self.dbr = self.lci = False
        self.set_int(0x00)


# ========================================================================
# Simulation harness ("firmware" = the test code)
# ========================================================================

class Sim:
    def __init__(self, words_by_name):
        self.bus = Bus()
        self.chip = MockWD33C93A(self.bus)
        self.t = 0.0
        self.words = words_by_name
        self.sm = None
        # firmware init state (ARCHITECTURE.md section 1): strobes idle
        # high, A0 low, MR- high; handed to the SM before it starts.
        for pin in (CS, WE, RE, DACK):
            self.bus.fw_out[pin] = 1
        self.bus.fw_out[MR] = 1
        self.bus.commit(self.t)

    def start_sm0(self):
        # firmware releases the SM-owned pins to the PIO block
        for pin in (CS, WE, RE):
            self.bus.fw_out.pop(pin, None)
        sm = StateMachine(
            self.bus, self.words["sbic_bus"], name="sm0",
            sideset_base=CS, out_base=D0, out_count=9, in_base=D0,
            out_shift_right=True, autopull=False,
            in_shift_right=False, autopush=True, push_thresh=8)
        sm.set_pins(D0, 9, 0)
        sm.set_pins(D0, 9, 0x1FF, dirs=True)    # D0-7 + A0 outputs
        sm._apply_sideset(0b111)
        self.bus.commit(self.t)
        self.sm = sm
        return sm

    def start_sm1(self, program, data_in):
        for pin in (WE, RE, DACK):
            self.bus.fw_out.pop(pin, None)
        self.bus.fw_out[CS] = 1                 # CS- inactive during DMA
        sm = StateMachine(
            self.bus, self.words[program], name="sm1",
            sideset_base=WE, out_base=D0, out_count=8, in_base=D0,
            out_shift_right=True, autopull=True, pull_thresh=8,
            in_shift_right=False, autopush=True, push_thresh=8)
        dirs = 0x00 if data_in else 0xFF
        sm.set_pins(D0, 8, 0)
        sm.set_pins(D0, 8, dirs, dirs=True)
        sm._apply_sideset(0b111)
        self.bus.commit(self.t)
        self.sm = sm
        return sm

    def stop_sm(self):
        """SM0/SM1 handoff: drain + disable, firmware re-parks the pins."""
        if self.sm:
            self.sm.enabled = False
            for i in range(self.sm.side_bits):
                self.bus.sm_dir.pop(self.sm.sideset_base + i, None)
            for i in range(9):
                self.bus.sm_dir.pop(D0 + i, None)
        for pin in (CS, WE, RE, DACK):
            self.bus.fw_out[pin] = 1
        self.bus.commit(self.t)
        self.sm = None

    def run(self, ns=None, cycles=None, until=None):
        n = cycles if cycles is not None else int((ns or 0) / T) + 1
        for _ in range(n):
            self.chip.run_events(self.t)
            if self.sm:
                self.sm.step(self.t)
            self.t += T
            if until and until():
                self.chip.run_events(self.t)
                return True
        self.chip.run_events(self.t)
        return until() if until else True

    # -- firmware-level register ops over SM0 ------------------------------
    def sm0_read(self, reg=None, a0_direct=False, max_us=50):
        """Queue an indirect (or A0=0 direct) read; return the byte."""
        if a0_direct:
            self.sm.tx.append(XR(0))
        else:
            self.sm.tx.append(XW(0, reg))
            self.sm.tx.append(XR(1))
        got = self.run(ns=max_us * 1000, until=lambda: len(self.sm.rx) > 0)
        if not got:
            raise TimeoutError("SM0 read produced no RX word")
        return self.sm.rx.pop(0)

    def sm0_write(self, reg, *values):
        self.sm.tx.append(XW(0, reg))
        for v in values:
            self.sm.tx.append(XW(1, v))
        ok = self.run(ns=50_000, until=lambda: not self.sm.tx)
        self.run(ns=2_000)                      # let the last strobe finish
        if not ok:
            raise TimeoutError("SM0 write did not drain")

    def pulse_mr(self, low_ns=1_500):
        self.bus.fw_out[MR] = 0
        self.bus.commit(self.t)
        self.run(ns=low_ns)
        self.bus.fw_out[MR] = 1
        self.bus.commit(self.t)


# ========================================================================
# Tests
# ========================================================================

VERBOSE = False


def report(sim, name, ok, detail=""):
    v = sim.bus.violations if sim else []
    for vt, msg in v:
        print(f"    violation @ {vt / 1000:.2f} us: {msg}")
    status = "PASS" if ok and not v else "FAIL"
    print(f"  {name:<22} {status}   {detail}")
    return status == "PASS"


def test_golden_encoding(programs):
    words = programs["sbic_bus"][1]
    ok = words == GOLDEN_SBIC_BUS
    if not ok:
        for i, (a, b) in enumerate(zip(words, GOLDEN_SBIC_BUS)):
            if a != b:
                print(f"    word {i}: assembled {a:#06x} != golden {b:#06x}")
    print(f"  {'golden-encoding':<22} {'PASS' if ok else 'FAIL'}   "
          f"{len(words)} words == session pioasm 2.2.0 output")
    return ok


def test_init_sequence(programs):
    """THE required proof: SM0 completes a full init sequence.

    MR- pulse -> wait INTRQ -> read SCSI Status (clears INTRQ) ->
    write Own ID -> read it back. Every strobe timing-checked by the
    mock; the read-back value proves the indirect protocol end-to-end.
    """
    sim = Sim({n: w for n, (_, w) in programs.items()})
    chip = sim.chip
    sim.start_sm0()

    # 1. hardware reset
    sim.pulse_mr(low_ns=1_500)
    ok = sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    checks = [("INTRQ rose after MR- reset", ok)]

    # 2. read SCSI Status -> must be 00h (hard reset), INTRQ must fall
    status = sim.sm0_read(REG_SCSI_STATUS)
    checks.append(("SCSI Status == 00h", status == 0x00))
    sim.run(ns=500)
    checks.append(("INTRQ cleared by status read", sim.bus.now(INTRQ) == 0))
    checks.append(("aux INT bit cleared", not chip.int_))

    # 3. LCI rule: wait 7 us before any command; here we only write
    #    registers, but keep the gap to mirror real firmware.
    sim.run(ns=LCI_WINDOW)

    # 4. write Own ID: ID=7, FS=01 (divide-by-3 for the 15 MHz CLK)
    own_id = 0x47
    sim.sm0_write(REG_OWN_ID, own_id)
    checks.append(("Own ID landed in register file",
                   chip.regs[REG_OWN_ID] == own_id))
    checks.append(("address auto-incremented past 00h",
                   chip.addr_reg == 0x01))

    # 5. read it back through the same indirect path
    back = sim.sm0_read(REG_OWN_ID)
    checks.append(("Own ID read-back == written", back == own_id))

    chip.check_hanging_strobes(sim.t)
    if VERBOSE:
        for what, okc in checks:
            print(f"    {'ok ' if okc else 'BAD'} {what}")
        for entry in chip.log:
            print(f"    log: {entry}")
    bad = [w for w, okc in checks if not okc]
    return report(sim, "init-sequence", not bad,
                  f"MR->INTRQ->status->OwnID={own_id:#04x}->readback"
                  + (f"  FAILED: {bad}" if bad else ""))


def test_aux_status(programs):
    sim = Sim({n: w for n, (_, w) in programs.items()})
    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    aux = sim.sm0_read(a0_direct=True)          # single-cycle A0=0 read
    ok1 = aux & 0x80                            # INT set, pre status-read
    addr_before = sim.chip.addr_reg
    sim.sm0_read(a0_direct=True)
    ok2 = sim.chip.addr_reg == addr_before      # no auto-increment
    return report(sim, "aux-status", bool(ok1) and ok2,
                  f"aux={aux:#04x} (INT set), Address reg untouched")


def test_auto_increment(programs):
    sim = Sim({n: w for n, (_, w) in programs.items()})
    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    sim.sm0_read(REG_SCSI_STATUS)
    sim.run(ns=LCI_WINDOW)
    # one set-addr + four data writes lands in CDB1..CDB4 (03h-06h)
    vals = [0x12, 0x34, 0x56, 0x78]
    sim.sm0_write(REG_CDB1, *vals)
    ok = [sim.chip.regs[REG_CDB1 + i] == v for i, v in enumerate(vals)]
    back = [sim.sm0_read(REG_CDB1 + i) for i in range(4)]
    ok.append(back == vals)
    # Data register (19h) must NOT auto-increment
    sim.sm0_write(REG_DATA, 0xAA)
    ok.append(sim.chip.addr_reg == REG_DATA)
    return report(sim, "auto-increment", all(ok),
                  f"CDB1-4 <- {vals} via 1+4 cycles, 19h sticky")


def test_lci_7us_rule(programs):
    sim = Sim({n: w for n, (_, w) in programs.items()})
    chip = sim.chip
    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    sim.sm0_read(REG_SCSI_STATUS)
    # command immediately after status read (well inside 7 us) -> LCI
    sim.sm0_write(REG_COMMAND, CMD_RESET)
    aux = sim.sm0_read(a0_direct=True)
    early_ignored = ("cmd-ignored-lci", CMD_RESET) in chip.log
    lci_seen = bool(aux & 0x40)
    # now respect the rule
    sim.run(ns=LCI_WINDOW)
    sim.sm0_write(REG_OWN_ID, 0x47)             # sampled by soft reset
    sim.sm0_write(REG_COMMAND, CMD_RESET)
    got_int = sim.run(ns=30_000, until=lambda: sim.bus.now(INTRQ) == 1)
    status = sim.sm0_read(REG_SCSI_STATUS)
    ok = early_ignored and lci_seen and got_int and status == 0x00
    return report(sim, "lci-7us-rule", ok,
                  f"early cmd ignored (LCI={lci_seen}), late cmd -> "
                  f"int {status:#04x}")


def test_burst_in(programs):
    sim = Sim({n: w for n, (_, w) in programs.items()})
    chip = sim.chip
    data = [0xC0, 0x01, 0xD0, 0x0D, 0x5C, 0x51, 0xAA, 0x55,
            0xDE, 0xAD, 0xBE, 0xEF]
    chip.burst_dir = "in"
    chip.scsi_in = list(data)

    # program the transfer through SM0 like real firmware would
    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    sim.sm0_read(REG_SCSI_STATUS)
    sim.run(ns=LCI_WINDOW)
    sim.sm0_write(REG_CONTROL, 0b001 << 5)      # DM = burst
    sim.sm0_write(0x12, 0, 0, len(data))        # transfer count 24-bit
    sim.sm0_write(REG_COMMAND, CMD_TRANSFER_INFO)
    sim.stop_sm()                               # handoff discipline

    sm1 = sim.start_sm1("sbic_burst_in", data_in=True)
    rxed = []
    def dma_drain():                            # models the DMA channel
        while sm1.rx:
            rxed.append(sm1.rx.pop(0))
        return len(rxed) == len(data)
    sim.run(ns=50_000, until=dma_drain)
    sim.stop_sm()
    got_int = sim.run(ns=5_000,
                      until=lambda: sim.bus.now(INTRQ) == 1)
    ok = rxed == data and got_int and sim.bus.now(DRQ) == 1
    if VERBOSE or not ok:
        print(f"    sent {data}\n    got  {rxed}")
    return report(sim, "burst-in", ok,
                  f"{len(rxed)}/{len(data)} bytes in order, DRQ- "
                  "deasserted, completion INTRQ")


def test_burst_out(programs):
    sim = Sim({n: w for n, (_, w) in programs.items()})
    chip = sim.chip
    data = [0x0F, 0x1E, 0x2D, 0x3C, 0x4B, 0x5A, 0x69, 0x78]
    chip.burst_dir = "out"

    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    sim.sm0_read(REG_SCSI_STATUS)
    sim.run(ns=LCI_WINDOW)
    sim.sm0_write(REG_CONTROL, 0b001 << 5)
    sim.sm0_write(0x12, 0, 0, len(data))
    sim.sm0_write(REG_COMMAND, CMD_TRANSFER_INFO)
    sim.stop_sm()

    sm1 = sim.start_sm1("sbic_burst_out", data_in=False)
    sm1.tx.extend(data)                         # models the DMA channel
    sim.run(ns=50_000, until=lambda: len(chip.scsi_out) == len(data))
    sim.stop_sm()
    got_int = sim.run(ns=5_000,
                      until=lambda: sim.bus.now(INTRQ) == 1)
    ok = chip.scsi_out == data and got_int
    if VERBOSE or not ok:
        print(f"    sent {data}\n    got  {chip.scsi_out}")
    return report(sim, "burst-out", ok,
                  f"{len(chip.scsi_out)}/{len(data)} bytes in order, "
                  "completion INTRQ")


def test_fifo_stall_hazard(programs):
    """ARCHITECTURE.md section 2 documents that >4 fire-and-forget reads
    stall `in pins` with RE- low past the 10 us tRE max. Prove the
    hazard is real AND that the mock catches it: queue 5 un-drained
    reads and require the violation to be flagged."""
    sim = Sim({n: w for n, (_, w) in programs.items()})
    sim.start_sm0()
    sim.pulse_mr()
    sim.run(ns=20_000, until=lambda: sim.bus.now(INTRQ) == 1)
    for _ in range(5):                          # 5th read must stall
        sim.sm0_read(REG_SCSI_STATUS, max_us=5)
        sim.sm.rx.insert(0, 0)                  # sabotage: never drained
    # rx now holds 4+ words; queue one more read and let it wedge
    sim.sm.tx.append(XW(0, REG_SCSI_STATUS))
    sim.sm.tx.append(XR(1))
    sim.run(ns=15_000)
    sim.chip.check_hanging_strobes(sim.t)
    hits = [m for _, m in sim.bus.violations if "10000" in m]
    ok = bool(hits) and sim.bus.now(RE) == 0    # genuinely wedged low
    print(f"  {'fifo-stall-hazard':<22} {'PASS' if ok else 'FAIL'}   "
          f"RE- wedged low, mock flagged: {hits[0] if hits else 'NOTHING'}")
    return ok


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    doc_text = open(DOC).read()
    programs = extract_programs(doc_text)
    need = {"sbic_bus", "sbic_burst_in", "sbic_burst_out"}
    missing = need - set(programs)
    if missing:
        sys.exit(f"FATAL: programs missing from {DOC}: {missing}")

    print(f"pio_sim: {len(programs)} programs assembled from {DOC} "
          f"(SM clock {1e3 / T:.0f} MHz, T={T:.2f} ns, sync={SYNC:.1f} ns)")

    results = [
        test_golden_encoding(programs),
        test_init_sequence(programs),
        test_aux_status(programs),
        test_auto_increment(programs),
        test_lci_7us_rule(programs),
        test_burst_in(programs),
        test_burst_out(programs),
        test_fifo_stall_hazard(programs),
    ]
    failed = results.count(False)
    print("ALL TESTS PASSED" if not failed else f"{failed} TEST(S) FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
