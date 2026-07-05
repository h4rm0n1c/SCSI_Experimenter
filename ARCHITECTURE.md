# Pico ↔ AM33C93A SCSI Board — Software Architecture

Target: Raspberry Pi Pico W (RP2040) or Pico 2 W (RP2350) as the host
processor for the h4rm0n1c AM33C93A/WD33C93A experimenter board, SCSI-1
narrow initiator mode.

Sources: `repo/scsi/scsi.kicad_sch` + `scsi.kicad_pcb` (netlist verified
pad-by-pad), `repo/h4rm0n1c.kicad_sym`, AMD Am33C93A datasheet (Nov 1991,
pub #11853), WD33C93A datasheet + app notes (Nov 1990, incl. errata
E018/E022/E024/E049), WD33C93B datasheet, ANSI X3.131-1986,
`docs/PICO_GPIO_CHEATSHEET.md`, RP2040/RP2350 datasheets.

---

## 0. What the board actually is (netlist findings)

Extracted from `scsi.kicad_pcb` (authoritative — the schematic has no net
labels, everything is point-to-point wiring):

* **U1** — AM33C93A, PLCC-44. Pinout in the KiCad symbol matches the AMD
  datasheet connection diagram exactly.
* **J1** — 50-pin SCSI-1 connector. All odd pins + 20–24/28–30/34 GND,
  pin 25 open, pin 26 TERMPWR. SD0–SD7/SDP and the nine control lines go
  straight from U1's SCSI-side pins to J1 (open-drain 48 mA drivers on
  chip, no external transceivers — single-ended SCSI, as expected).
* **J4 "CPU"** — 26-pin (2×13) host header. **This is the Pico's world.**
  Full pinout below.
* **J3 "ENABLE_TERMINATION"** — connects the commons of RN1/RN3 (330 Ω)
  to GND and RN2/RN4 (220 Ω) to +5 V: classic SCSI-1 passive 220/330
  termination on all 18 signals, jumper-enabled.
* **J2 "VAMPIRE_OR_HBA"** — TERMPWR direction select through two SS33
  Schottkys: *HBA* position sources J1-26 TERMPWR from the board's +5 V
  (D1); *VAMPIRE* position back-feeds the board's +5 V rail *from* bus
  TERMPWR (D2).
* **ALE (U1 pin 27) is hard-wired to GND.** This is deliberate: per the
  WD33C93A datasheet §6.2.2, grounding ALE selects **indirect
  addressing** — there is no address bus, only A0. Every register access
  is a two-cycle operation (see §3).
* **SCSI RST (J1 pin 40) does not touch U1 at all** — the 33C93 family
  has **no RST pin**. The board routes RST straight to **J4 pin 7** so
  the host processor asserts and monitors bus reset itself.
* **DP (U1 pin 11 → J4 pin 3)** — host-bus data parity. On the PLCC part
  parity is *always generated* on DP during reads; *checking* of host
  parity is optional (Own ID bit EHP). Safe to leave unused.
* Test pins **1 (SI), 22 (SCLK), 36 (HALT)** are unconnected — correct
  per the AMD datasheet note ("test purposes only").

### J4 host header pinout (verified against PCB netlist)

| J4 pin | Signal | U1 pin | Dir (Pico view) | J4 pin | Signal | U1 pin | Dir |
|---|---|---|---|---|---|---|---|
| 1 | DRQ̅ | 9 | in | 2 | DACK̅ | 10 | out |
| 3 | DP | 11 | bidir (opt) | 4 | INTRQ | 12 | in (active **high**) |
| 5 | MR̅ | 40 | out | 6 | D1 | 14 | bidir |
| 7 | **SCSI RST̅** (J1-40) | — | open-drain bidir | 8 | D0 | 13 | bidir |
| 9 | CLK | 8 | out (8–16/20 MHz) | 10 | D3 | 16 | bidir |
| 11 | GND | | | 12 | D2 | 15 | bidir |
| 13 | GND | | | 14 | D6 | 19 | bidir |
| 15 | GND | | | 16 | D4 | 17 | bidir |
| 17 | GND | | | 18 | A0 | 21 | out |
| 19 | GND | | | 20 | D5 | 18 | bidir |
| 21 | +5V | | in/out (J2 mode!) | 22 | D7 | 20 | bidir |
| 23 | +5V | | | 24 | WE̅ | 25 | out |
| 25 | CS̅ | 24 | out | 26 | RE̅ | 26 | out |

16 logic signals + power. Fits a Pico with 10 GPIOs to spare.

> **Power note:** in HBA mode the Pico side must supply +5 V into J4-21/23
> (wire from Pico VBUS/VSYS). In VAMPIRE mode the SCSI bus supplies it —
> and could back-power the Pico via VSYS through a Schottky if you wire
> it that way. Pick one; don't fight USB power.
>
> **TERMPWR budget (HBA mode):** SCSI-1 §4.4.3 requires TERMPWR =
> **4.0–5.25 V** at up to 800 mA source capability. Path from USB:
> VBUS (4.75 V worst-case) → J4 → D1 SS33 (~0.35 V) ≈ **4.4 V** — in
> spec, but with little headroom, and both far-end terminators can draw
> ~160 mA static (18 lines × 5 V/550 Ω per end). A USB port + thin
> cable will sag. **Prefer an external 5 V supply into J4-21/23 for any
> setup with real termination load**; USB-only power is fine for a
> single short-cable bench target.

---

## 1. Hardware interface — GPIO allocation

### 5 V tolerance (the fork in the road)

* **RP2040 (Pico W): NOT 5 V tolerant.** Abs max = IOVDD + 0.5 V ≈ 3.8 V.
  Every signal the 33C93A can drive (D0–D7, DP, INTRQ, DRQ̅, SCSI RST̅)
  **must** be level-shifted 5 V → 3.3 V.
* **RP2350 (Pico 2 W): all GPIOs 5 V tolerant while powered**
  (VPIN_FT −0.5…5.5 V, RP2350 datasheet Table 1433). 5 V inputs connect
  **directly**.
* **3.3 V → 5 V direction needs no shifter on either board.** The AMD
  datasheet states "All inputs and outputs are TTL compatible", and the
  WD33C93A DC characteristics table confirms **V_IH = 2.0 V min for all
  inputs, with no CMOS-level exception for CLK**. RP2040 V_OH ≥ 2.62 V
  → ≥ 0.62 V worst-case margin. Use 8 mA drive + fast slew on CLK and
  the strobes. (The cheat sheet was over-conservative here; it has been
  corrected to match the datasheet DC spec.)

**RP2350/Pico 2 W: zero glue chips — wire J4 straight to the Pico 2.**

**RP2040/Pico W glue (required):**
* D0–D7: one **74LVC8T245** dual-supply transceiver (A-port 3.3 V,
  B-port 5 V). Wire **DIR = RE̅** (RE̅ low ⇒ B→A, chip drives Pico;
  RE̅ high ⇒ A→B). Add weak pull-ups on the A port so it doesn't float
  between read strobes while the Pico's pins are Hi-Z. OE̅ → GND (or CS̅).
* INTRQ, DRQ̅, RST̅ inputs: spare 74LVC245 / 74LVC2G34, or 10k/15k
  dividers (these edges are slow enough).
* Outputs (A0, CS̅, WE̅, RE̅, DACK̅, MR̅, CLK): direct, TTL-compatible.

### GPIO map (both boards — chosen for PIO side-set contiguity)

| GPIO | Signal | Direction | Why here |
|---|---|---|---|
| GP0–GP7 | D0–D7 | bidir | PIO `IN`/`OUT` pin base 0, contiguous |
| GP8 | A0 | out | 9th bit of the PIO `OUT` group (written with data) |
| GP9 | CS̅ | out | side-set group A base (register SM: CS̅/WE̅/RE̅) |
| GP10 | WE̅ | out | shared by both side-set groups |
| GP11 | RE̅ | out | |
| GP12 | DACK̅ | out | side-set group B base+2 (burst SM: WE̅/RE̅/DACK̅) |
| GP13 | CLK → 33C93 | out | PWM slice 6B — clock gen without PIO cost |
| GP14 | MR̅ | out | plain SIO GPIO (1 µs pulse, no timing pressure) |
| GP15 | INTRQ | in | GPIO IRQ, rising edge (active high) |
| GP16 | DRQ̅ | in | burst SM `WAIT`/`JMP PIN` |
| GP17 | DP | in (ignore) | leave EHP=0; parity is generated by chip anyway |
| GP18 | SCSI RST̅ | pseudo-open-drain | out-low ↔ input; GPIO IRQ falling = bus reset |
| GP19 | spare | — | LVC8T245 DIR override / logic-analyzer trigger |
| GP20, GP21 | UART1 TX/RX debug | — | GP21 doubles as `clk_gpout0` (alt CLK source) |
| GP22, GP26–28 | spare | — | GP26–28 = ADC (e.g. TERMPWR/divider monitor) |

Constraints honored: GP23–25 + GP29 reserved by CYW43439 on both W
boards; both side-set groups are contiguous (GP9–11 and GP10–12); data +
A0 form one contiguous 9-bit `OUT` group.

Init state: CS̅=WE̅=RE̅=DACK̅=MR̅=1, A0=0, RST̅ released (input).
**Errata E024:** DACK̅ must be held inactive whenever you use polled I/O
— the init state above satisfies it.

**DRQ̅ needs an external pull-up (~1 kΩ, hardware requirement).** The
WD pin description says DRQ̅ "can be an open drain output — a pullup
resistor is required when operating in DMA or Burst mode", and every
DMA timing table footnotes "external load on DRQ & DACK is assumed to
be 1 KΩ". The Pico's internal 50–80 kΩ pull is ~50× too weak: DRQ̅'s
rising (deasserting) edge would take ~1 µs, during which SM1 would
clock extra strobes into a chip that isn't ready. Fit ~1 kΩ from J4-1
to +5 V on the board side (RP2350 input tolerates it directly; on
RP2040 it sits on the 5 V side of the shifter). Firmware side: enable
`gpio_pull_up(16)` anyway (harmless belt-and-braces) and mask/ignore
DRQ̅ and INTRQ until `sbic_init()` completes — the reset-default
internal pull-*down* would otherwise read as DRQ̅ asserted while the
chip is still coming up.

**GP18 (SCSI RST̅) is *pseudo*-open-drain** — neither RP chip has true
open-drain pads. Assert = switch to output-low; release = switch back
to input and let the bus terminators restore the line (220/330
termination at both ends ≈ 3 V Thevenin, ~66 Ω — rise is fast, but a
long loaded cable adds RC). Rules: hold asserted ≥ 25 µs (SCSI-1 Reset
Hold Time, §4.7.12); after releasing, **wait ≥ 5 µs and read the pin
back high before any re-assertion or bus activity** so a still-rising
line is never glitched; never configure GP18 output-high even
momentarily (on RP2040 that fights a 5 V bus with a 3.3 V driver).

---

## 2. PIO state machine design

### Why PIO at all

The indirect-read timing table has a trap: **RE̅ pulse width is min
180 ns *and max 10 µs*** (WD33C93A §9.1.4). A CPU bit-banging RE̅ that
takes an interrupt mid-strobe violates the max and can corrupt the
access. PIO gives hard-bounded strobes regardless of CPU load, plus
FIFOs that DMA can feed. All host-side timing then derives from the PIO
clock divider, not from code path length.

Both SMs below live in **one PIO block** (they share pin mappings and
must be in the same block; only one runs at a time). Total = 22 of the
32 instruction slots.

### Side-set encoding budget (this constrains everything)

PIO instructions carry a single **5-bit delay/side-set field**, split by
the `.side_set` directive:

| Directive | side data | enable bit | delay bits | max `[n]` |
|---|---|---|---|---|
| `.side_set 3 opt` | 3 | 1 | 1 | `[1]` |
| **`.side_set 3`** (used here) | 3 | 0 | 2 | **`[3]`** |

We need 3 side-set pins per SM and delays up to 3, so side-set is
**non-optional** — which requires a `side` annotation on *every*
instruction (all listings below comply). Longer intervals than 4 cycles
are built by letting a strobe span **multiple instructions**: side-set
values persist until some later instruction changes them, so pulse
widths are not limited by the delay field.

### SM clock derivation

Inputs to the choice:

1. sys_clk = **120 MHz** (fixed by §6: integer-divides to the chip's
   15 MHz CLK, valid on both RP2040 and RP2350).
2. The SM divider must be a small exact integer (no fractional jitter
   in strobe widths).
3. PIO **input synchronizers are 2 sys_clk stages** (§3.5.6.3 RP2040):
   an `in pins` at SM cycle N reads the pin state from ~2/120 MHz =
   **16.7 ns earlier**. Every read-sample margin must absorb this.
4. All datasheet minimums should land on cycle counts reachable with
   `[3]` delays plus at most one extra `nop`, with real margin.

Take **divider = 5.0 → f_SM = 24 MHz, T = 41.67 ns** and check every
constraint (indirect mode, WD33C93A §9.1.3/9.1.4):

| Constraint | Spec | Cycles req'd | Achieved (below) | Margin |
|---|---|---|---|---|
| tCLWL/tCLRL (CS̅↓→strobe↓) | ≥ 0 | 0 | 0 (one side-set co-asserts) | — |
| tWE (WE̅ low) | ≥ 120 ns | ⌈120/41.67⌉ = 3 | 4 cyc = 166.7 ns | +46.7 ns |
| tDVWH (data setup→WE̅↑) | ≥ 70 ns | 2 | 5 cyc = 208.3 ns | +138 ns |
| tWHDI/tWHAI/tWHCH (holds) | ≥ 0 | 0 | pins held past strobe | — |
| tRE (RE̅ low) | ≥ 180 ns, ≤ 10 µs | 5 | 7 cyc = 291.7 ns | +111.7 ns / −9.7 µs |
| sample after RE̅↓ | ≥ tRLDV(180) + tsync(16.7) = 196.7 ns | 5 | cycle 6 = 250 ns → data age 233.3 ns | +36.6 ns |
| tWHWL/tRHRL (recovery) | ≥ 100 ns | 3 | 8 cyc = 333 ns | +233 ns |

(A ÷4 = 30 MHz SM also closes with one more nop per strobe; ÷5 is chosen
for margin. Anything ≥ ~30 MHz makes the cycle-6 sample land before
196.7 ns unless you add instructions — that, not the pulse width, is the
binding constraint on SM speed.)

### SM0 — register/PIO-mode bus cycle engine

One program does both directions. Each transaction is **one TX-FIFO
word**: `bit9 = R/W̅ (1 = read)`, `bit8 = A0`, `bits7:0 = data`
(don't-care for reads). Reads return one byte in the RX FIFO.

Required shift config (the program depends on it):
`sm_config_set_out_shift(right, autopull=OFF, —)` — OSR shifts right so
`out pins,9` peels bits 8:0 (A0+data) and `out x,1` then gets bit 9;
autopull must be off or the pull threshold would split the 10-bit word.
`sm_config_set_in_shift(left, autopush=ON, threshold=8)` — ISR shifts
left so the byte lands in bits [7:0] for byte-wide DMA/CPU reads.

```pioasm
.program sbic_bus
.side_set 3                ; {bit2=RE, bit1=WE, bit0=CS} base GP9, idle 0b111
; OUT pins: base GP0, count 9 (D0-7 + A0). IN pins: base GP0.

entry:
    pull block          side 0b111
    out pins, 9         side 0b111      ; latch data + A0 onto pin registers
    out x, 1            side 0b111      ; x = R/W flag
    jmp !x, wr          side 0b111
rd: mov osr, null       side 0b111
    out pindirs, 8      side 0b111      ; release D0-7 (A0 stays output)
    nop                 side 0b010 [3]  ; CS+RE fall at t=0; cycles 0-3
    nop                 side 0b010 [1]  ; cycles 4-5
    in  pins, 8         side 0b010      ; cycle 6: sample t=250ns, age 233ns >= 180 OK
    jmp entry           side 0b111 [1]  ; cycle 7: RE rises -> low 291.7ns in [180ns,10us]
wr: mov osr, ~null      side 0b111
    out pindirs, 8      side 0b111      ; D0-7 driven; data appears >= 1 cyc pre-strobe
    nop                 side 0b100 [3]  ; CS+WE low 4 cyc = 166.7ns >= tWE 120
    jmp entry           side 0b111 [1]  ; WE rises; data stays driven (hold >= 0)
```

Cycle accounting (convention: side-set asserts on an instruction's
*first* cycle; an instruction with delay d occupies 1+d cycles; a strobe
asserted by instruction i and released by instruction j is low for the
sum of the cycles of i..j−1):

* **Read:** RE̅ low = 4+2+1 = 7 cyc = 291.7 ns. Sample at cycle 6 =
  250 ns; minus 16.7 ns synchronizer age = 233.3 ns ≥ tRLDV 180 ✓.
* **Write:** WE̅ low = 4 cyc = 166.7 ns ≥ 120 ✓. Data valid from
  `out pindirs` (1 cyc before strobe) to WE̅↑ = 1+4 = 5 cyc = 208 ns ≥
  tDVWH 70 ✓ (worst case — if the previous transaction was also a write,
  the pins were driven far earlier). A0 valid 3 cyc = 125 ns before the
  strobe (tAVWL ≥ 0 ✓).
* **Recovery (both paths):** strobe↑ at `jmp`, next strobe↓ after
  `jmp[1]`(2) + entry(4) + mov/out(2) = 8 cyc = 333 ns ≥ 100 ✓.
* Totals: write transaction 12 cyc = 500 ns, read 13 cyc = 542 ns → one
  indirect register access (address cycle + data cycle) ≈ 1.0–1.05 µs.

14 instructions.

> **FIFO-stall hazard (the 10 µs RE̅ max):** with autopush, `in pins`
> *stalls with RE̅ held low* if the RX FIFO is full. Four un-drained
> reads is the FIFO depth — the register layer must consume each read's
> result before queueing a fifth (it is synchronous, so it does). Never
> fire-and-forget a batch of >4 read words at SM0.

*RP2040 note:* the LVC8T245 with DIR=RE̅ flips direction when RE̅
falls — prop delay ~5 ns, absorbed by the 250 ns sample point.

### SM1 — burst-DMA data-phase engine (DRQ̅/DACK̅)

Control register DMA mode = **Burst** (`DM = 001`): DRQ̅ stays asserted
while the chip's 12-byte FIFO can move data; the host answers with
DACK̅ + RE̅/WE̅ strobes, **CS̅ high**. Burst timing — **visually
verified against both datasheets' timing pages** (A app notes
§9.1.11/9.1.12 pp. 60–61; B datasheet §6.1.11/6.1.12 pp. 56–57):

* **A**: read strobe ≥ 80 ns, recovery ≥ 80 ns, data valid ≤ 50 ns from
  RE̅↓; write strobe ≥ 50 ns, setup ≥ 25 ns.
* **B** (fitted on the demo board) is faster and uses a *pipelined*
  read model: strobes ≥ 30 ns, recovery ≥ 30 ns, write setup ≥ 18 ns;
  read data for the **first** byte is valid ≤ 50 ns after DACK̅↓, and
  for each later byte ≤ 80 ns after the **previous RE̅↑** — RE̅ just
  advances the FIFO.

The SM below is sized to the A (the stricter chip) and satisfies the
B's pipelined model as a side effect: its previous-RE̅↑ → next-RE̅↓ gap
is ≥ 3 cyc = 125 ns ≥ 80, so byte N's data is stable before its strobe
even falls.

Constraint check at 24 MHz (A numbers = worst case):

| Constraint | Spec | Achieved |
|---|---|---|
| RE̅ low (read) | ≥ 80 ns | 4 cyc = 166.7 ns |
| sample after RE̅↓ | ≥ 50 + 16.7 = 66.7 ns | cycle 3 = 125 ns → age 108 ns |
| WE̅ low (write) | ≥ 50 ns | 2 cyc = 83.3 ns |
| data setup to WE̅↑ | ≥ 25 ns | 3 cyc = 125 ns |
| recovery | ≥ 80 ns | ≥ 3 cyc = 125 ns |

```pioasm
.program sbic_burst_in          ; SCSI DATA IN -> memory
.side_set 3                     ; {bit2=DACK, bit1=RE, bit0=WE} base GP10, idle 0b111
    wait 0 gpio 16      side 0b111     ; DRQ- asserted (2-stage sync, ~17ns late: harmless)
    nop                 side 0b001 [2] ; DACK+RE fall t=0; cycles 0-2
    in  pins, 8         side 0b001     ; cycle 3: sample t=125ns, age 108ns >= 70 OK
    jmp 0               side 0b111 [1] ; strobes rise: RE low 166.7ns >= 80 OK
```

```pioasm
.program sbic_burst_out         ; memory -> SCSI DATA OUT
.side_set 3
    wait 0 gpio 16      side 0b111
    out pins, 8         side 0b111     ; autopull(right,8); data 1 cyc pre-strobe
    nop                 side 0b010 [1] ; DACK+WE low 2 cyc = 83.3ns >= 50 OK
    jmp 0               side 0b111 [1] ; release; recovery >= 3 cyc = 125ns >= 80 OK
```

4 instructions each (8 slots total). Per byte: read ≥ 7 cyc = 292 ns,
write ≥ 6 cyc = 250 ns → ~3.4 MB/s engine ceiling; the chip's DRQ̅
handshake latency will dominate in practice. DMA byte-size accesses to
the TX FIFO are bus-replicated across the 32-bit word, and OSR
shift-right consumes bits [7:0] — so `DMA_SIZE_8` feeds `out pins,8`
correctly; on the read side ISR shift-left + autopush 8 puts the byte at
[7:0] where a `DMA_SIZE_8` read of the RX FIFO expects it. Keep the DMA
channel running for the whole transfer: pausing it can leave `in`
stalled with RE̅ low.

A **DMA channel** services each SM: RX FIFO → buffer (DREQ_PIOx_RXn) for
data in, buffer → TX FIFO (DREQ_PIOx_TXn) for data out, byte transfers,
IRQ_QUIET, count = transfer length. CPU involvement per data phase:
program Transfer Count, issue the chip command, start DMA, sleep until
INTRQ.

### SM0/SM1 handoff discipline

SM0 and SM1 overlap on WE̅/RE̅. A SM parked on a stalled `pull`
re-asserts its side-set (idle `0b111`) every stall cycle; if both SMs
ran at once, same-cycle writes to a shared pin resolve highest-SM-wins —
don't rely on it. Before starting a burst: drain SM0, then
`pio_sm_set_enabled(pio, sm_reg, false)` (CS̅ must be inactive during
DMA anyway per the datasheet), flip D0–7 pindirs for the transfer
direction (`pio_sm_set_consecutive_pindirs`), enable SM1 + DMA.
Reverse on completion.

### Explicit per-SM PINCTRL/shift configuration (not optional)

Each SM has its **own** OUT/IN/side-set pin mapping. SM1's `out pins,8`
/ `in pins,8` only hit D0–D7 if its OUT/IN base is explicitly set to
GP0 — it does *not* inherit anything from SM0, and an unset base
defaults to 0 only by accident of the reset value. Pin both down in
code:

```c
// SM0 — register engine
pio_sm_config c0 = sbic_bus_program_get_default_config(off_bus);
sm_config_set_out_pins    (&c0, 0, 9);        // D0-7 + A0
sm_config_set_in_pins     (&c0, 0);           // D0-7
sm_config_set_sideset_pins(&c0, 9);           // {CS,WE,RE} = GP9,10,11
sm_config_set_out_shift   (&c0, true,  false, 32); // shift RIGHT, autopull OFF
sm_config_set_in_shift    (&c0, false, true,  8);  // shift LEFT,  autopush 8
sm_config_set_clkdiv_int_frac(&c0, 5, 0);     // 120 MHz / 5 = 24 MHz

// SM1 — burst engine (either direction's program)
pio_sm_config c1 = sbic_burst_in_program_get_default_config(off_burst);
sm_config_set_out_pins    (&c1, 0, 8);        // D0-7 (burst_out)
sm_config_set_in_pins     (&c1, 0);           // D0-7 (burst_in)
sm_config_set_sideset_pins(&c1, 10);          // {WE,RE,DACK} = GP10,11,12
sm_config_set_out_shift   (&c1, true,  true,  8);  // autopull 8 (burst_out)
sm_config_set_in_shift    (&c1, false, true,  8);  // autopush 8 (burst_in)
sm_config_set_clkdiv_int_frac(&c1, 5, 0);
```

(The `wait 0 gpio 16` in the burst programs uses an *absolute* GPIO
index, so DRQ̅ needs no mapping — but GP0–12 must all be handed to the
PIO block with `pio_gpio_init()` and the side-set pins driven high
before either SM starts.)

### Optional SM2 — CLK generation

Two instructions (`set pins,1 [N] / set pins,0 [N]`) give any even
division of sysclk. **Don't spend an SM on this** — PWM does it free
(§6). Listed only as a fallback.

### Block/SM budget

| | RP2040 (Pico W) | RP2350 (Pico 2 W) |
|---|---|---|
| CYW43 WiFi driver | 1 SM + 1 DMA ch (default PIO1) | same |
| SCSI SM0+SM1 | PIO0 (2 of 4 SMs, ~26/32 slots) | PIO2 all to SCSI, PIO0/1 free |
| Headroom | 2 SMs in PIO0, 3 in PIO1 | 10 SMs elsewhere |

---

## 3. Register access layer

### Indirect addressing (ALE grounded — how this board works)

* Write the target register number with **A0 = 0** (loads Address reg).
* Access the register with **A0 = 1** (RE̅ or WE̅).
* The Address register **auto-increments** after each A0=1 access —
  *except* at Aux Status, **Data (19h)**, and Command (18h). So
  multi-byte register loads are 1 + N cycles, and the Data register can
  be streamed with repeated A0=1 accesses without re-addressing.
* **Auxiliary Status** is read directly with **A0 = 0** (single cycle,
  any time except during DMA).

### Register map (summary — full bit-level reference in Appendix F)

| Addr | R/W | Register |
|---|---|---|
| 00h | R/W | Own ID / CDB Size (SCSI ID 2:0, EAF, EHP, RAF[B], FS1:0 clock divisor) |
| 01h | R/W | Control (DM2:0 DMA mode, HHP, EDI, IDI, HA, HSP) |
| 02h | R/W | Timeout Period (select/reselect; value = Tper_ms × f_CLK_MHz / 80) |
| 03h–0Eh | R/W | CDB bytes 1–12 (a.k.a. Translate-Address geometry regs) |
| 0Fh | R/W | Target LUN (returns SCSI status byte after SAT command) |
| 10h | R/W | Command Phase (resume pointer for combination commands — Appendix H) |
| 11h | R/W | Synchronous Transfer (offset/period; 0 = async; FSS[B]) |
| 12h–14h | R/W | Transfer Count MSB/mid/LSB (24-bit) |
| 15h | R/W | Destination ID (+ TG1:0[B], DF[B], DPD, SCC) |
| 16h | R/W | Source ID (SIV/SI2:0, DSP, ES, ER) |
| 17h | R | SCSI Status (interrupt cause — reading clears INTRQ; Appendix G) |
| 18h | R/W | Command (bit7 = SBT single-byte transfer; opcodes in Appendix B) |
| 19h | R/W | Data (port into the 12-byte FIFO) |
| 1Ah | R/W | Queue Tag **[WD33C93B only]** |
| — (A0=0 read) | R | Auxiliary Status: INT LCI BSY CIP — FFE[B] PE DBR |

`[B]` = WD33C93B only (the demo board's fitted chip); absent/reserved-0
on WD33C93A/AM33C93A. See the Appendix F legend.

### C API (pico-sdk style)

```c
// ---- sbic_bus.c : PIO transport -------------------------------------
#define SBIC_XW(a0, d)   (((uint32_t)(a0) << 8) | (uint8_t)(d))        // write
#define SBIC_XR(a0)      ((1u << 9) | ((uint32_t)(a0) << 8))           // read

void     sbic_bus_init(PIO pio, uint sm_reg, uint sm_burst);
void     sbic_hw_reset(void);                 // MR- low >= 1 us, wait reset intr

// ---- register layer (indirect addressing under the hood) ------------
uint8_t  sbic_aux_status(void);               // 1 cycle: read A0=0
void     sbic_set_addr(uint8_t reg);          // 1 cycle: write A0=0
uint8_t  sbic_read_reg(uint8_t reg);          // set_addr + read A0=1
void     sbic_write_reg(uint8_t reg, uint8_t v);
void     sbic_write_regs(uint8_t first, const uint8_t *v, size_t n); // auto-inc
void     sbic_read_regs(uint8_t first, uint8_t *v, size_t n);        // auto-inc
static inline void sbic_command(uint8_t cmd)  { sbic_write_reg(SBIC_REG_CMD, cmd); }
static inline uint8_t sbic_scsi_status(void)  { return sbic_read_reg(SBIC_REG_SCSI_STATUS); }

// polled data-phase (DM=000): poll DBR in aux status per byte
int      sbic_pio_data_in (uint8_t *dst, size_t n, uint32_t timeout_us);
int      sbic_pio_data_out(const uint8_t *src, size_t n, uint32_t timeout_us);

// burst data-phase (DM=001): SM1 + DMA channel, returns immediately;
// completion signalled by INTRQ (chip) after transfer count exhausts
void     sbic_dma_data_in (uint8_t *dst, size_t n);
void     sbic_dma_data_out(const uint8_t *src, size_t n);
void     sbic_dma_abort(void);                // drain FIFO per datasheet 6.2.21

// 24-bit transfer count helper
void     sbic_set_xfer_count(uint32_t n);     // regs 12h..14h
uint32_t sbic_get_xfer_count(void);
```

Implementation notes:
* `sbic_write_reg` = push `SBIC_XW(0, reg)`, `SBIC_XW(1, v)` to SM0 TX.
* `sbic_read_reg` = push `SBIC_XW(0, reg)`, `SBIC_XR(1)`, pop RX.
* Because SM0's FIFO serializes transactions, the layer is naturally
  safe from strobe-timing races; guard it with a mutex if both cores use it.
* **7 µs rule:** the chip ignores a command written < 7 µs after the last
  SCSI Status read (sets LCI in aux status). Enforce with
  `busy_wait_us(7)` in `sbic_command()` after any status read, and check
  LCI afterwards.
* Never write Command while CIP or INT set; never issue a Level II
  command while BSY set (aux status gates all of this).

---

## 4. SCSI bus phase engine

### Division of labor

The 33C93A contains a microcontroller + SCSI sequencer. **It owns the
electrical phases**: arbitration (assert BSY/ID after bus-free
detection), selection with timeout, all REQ̅/ACK̅ byte handshakes, ATN
assertion, and — with the combination commands — entire command
executions. The Pico never touches BSY/SEL/REQ/ACK; they aren't even on
J4. Firmware works at the level of *"chip, do X" → INTRQ → read SCSI
Status → decide*.

### Two operating strategies

**A. High-level (recommended I/O path): Select-with-ATN-and-Transfer (08h)**

Setup: Own ID (done at init), Destination ID (15h), Target LUN (0Fh),
Sync Transfer = 0 (async), Transfer Count (12–14h), CDB into 03h–0Eh
via one auto-increment burst, Command Phase (10h) = 00, Control DM=001,
start the burst DMA engine, then `sbic_command(0x08)`.

The chip then executes ARBITRATION → SELECTION (with ATN) → MESSAGE OUT
(IDENTIFY built from Dest ID/LUN) → COMMAND (CDB from registers) → DATA
(via DRQ̅/DACK̅/DMA) → STATUS (latched into reg 0Fh) → MESSAGE IN
(Command Complete) and raises **one** interrupt (16h = success). Errors
/ disconnects suspend into the Command Phase register and are resumable
(IDI/EDI control bits govern disconnect interrupts). One IRQ per SCSI
command; this is the whole point of the part.

SAT-mode bug workarounds (E018 bug list, full text in the app notes):
* **P1** — a spurious DATA IN phase interrupt can follow the IDENTIFY
  message. Recovery: resume SAT with Command Phase register = 41h.
* **P2** — never issue **Assert-ATN (02h) during SAT's IDENTIFY or
  COMMAND phases**; the chip goes unpredictable. Queue the ATN request
  until the command phase completes (or run strategy B for that target).
* **P3 / E046** — on a target disconnect during DATA OUT, FIFO bytes
  are silently lost unless **IDI is set**, and the chip's internal
  transfer count can diverge from the host-side DMA count. Always set
  IDI when disconnects are enabled, and on any disconnect interrupt
  re-read Transfer Count (12h–14h) from the chip instead of trusting
  the DMA channel's remaining count.

**B. Low-level (bring-up, debug, unusual targets): phased engine**

Firmware state machine driven entirely by INTRQ:

```
IDLE ──select cmd (06h/07h)──► SELECTING
SELECTING ──intr── success codes ► CONNECTED   (timeout code ► IDLE)
CONNECTED: on every "REQ asserted" interrupt, SCSI Status low bits
           carry MCI (MSG,C/D,I/O) = the phase the TARGET now requests:
   000 DATA OUT   → set count, Transfer Info (20h), feed data
   001 DATA IN    → set count, Transfer Info, drain data
   010 COMMAND    → Transfer Info, send CDB bytes
   011 STATUS     → Transfer Info+SBT (80h|20h), read 1 byte
   110 MESSAGE OUT→ Transfer Info, send (e.g. IDENTIFY 80h)
   111 MESSAGE IN → Transfer Info+SBT, read byte, then Negate ACK (03h)
DISCONNECT interrupt ► IDLE (bus free)
```

Key rules encoded in the engine:
* The **target** dictates phases; the initiator only follows MCI. A
  "phase mismatch"-style interrupt (paused/aborted group, 2xh) simply
  means the target moved on — reload and issue the next Transfer Info.
* MESSAGE IN requires the explicit **Negate ACK (03h)** command after
  the byte is read (chip holds ACK so the initiator can inspect the
  message first). Related errata **E039**: ACK̅ may deassert before
  REQ̅ — treat REQ̅/ACK̅ ordering leniently when debugging message
  phases with a logic analyzer; it is a chip quirk, not a target fault.
* The MCI encoding above (000 = DATA OUT … 111 = MESSAGE IN, bit set =
  signal asserted) is taken from the datasheet §6.2.20 table. Errata
  **E067** ("logic orientation of SCSI phase bits") exists precisely
  because implementers got this inverted — its full text is not in the
  combined PDF, so **verify the orientation against a real target's
  COMMAND phase (MCI = 010) during bring-up** before trusting the
  decode table.
* **Assert ATN (02h)** before MESSAGE OUT if you need to send one
  mid-connection.
* SCSI Status code groups: `0x` reset, `1x` success, `2x`
  paused/aborted, `4x` terminated-with-error, `8x` bus service
  (reselection, unexpected phase). Low nibble = qualifier/MCI.

### Reset & init flow

```
1. Pulse MR- low >= 1 us; wait INTRQ; read SCSI Status (expect 00/01).
2. Write Own ID (00h) = FS bits | EAF | initiator SCSI ID (7).
3. sbic_command(RESET 00h); wait INTRQ (00h = plain, 01h = EAF acknowledged).
4. Write Control (01h): DM=000, no halts; Timeout Period (02h)
   (e.g. 250 ms @ 15 MHz -> 47); Sync Transfer (11h) = 0 (async);
   Source ID (16h): reselection disabled.
```

### SCSI RST̅ (GPIO18, firmware-owned)

* Assert: output-low ≥ 25 µs (SCSI-1 minimum), release to input.
  Afterwards re-run chip init (targets drop everything; the 33C93 does
  not see RST and must be told).
* Monitor: falling-edge GPIO IRQ → abort DMA, flush, mark bus dead,
  re-init. This is mandatory — the chip will never tell you.

---

## 5. Interrupt vs polling vs PIO — transfer-path analysis

| Mechanism | Latency | CPU cost | Timing risk | Use for |
|---|---|---|---|---|
| Poll aux status (DBR) per byte | ~1 µs/byte (2 reg cycles) | 100 % of a core | none (PIO strobes) | bring-up, tiny transfers, non-data phases |
| INTRQ GPIO IRQ | ~1–2 µs to handler | ~0 | must respect 7 µs cmd rule | **all command/phase events** |
| DRQ̅ polled by CPU | worse than DBR | high | E022 DRQ glitch errata (rev C/D) | never |
| **Burst DMA: DRQ̅-paced PIO SM + DMA ch** | 0 (hardware) | **0** | strobes hardware-bounded | **all DATA IN/OUT** |
| Single-byte DMA mode (DM=100) | 1 IRQ/byte equiv | high | — | never (burst supersedes) |

Recommended architecture:

* **Control plane = interrupt-driven.** INTRQ (GP15, rising) wakes a
  handler that reads SCSI Status once and feeds an event queue consumed
  by the phase engine (or completes the SAT command). Never issue chip
  commands from the ISR itself — the 7 µs rule and register-layer FIFO
  make a deferred worker (second core or main loop) cleaner. The Pico's
  free second core is a natural home for the whole SCSI stack, leaving
  core 0 for USB/WiFi/application.
* **Data plane = PIO SM1 + DMA in Burst mode.** Zero CPU per byte;
  completion = chip INTRQ (transfer count reached) + DMA count check.
  The 12-byte on-chip FIFO absorbs REQ/ACK vs host jitter.
* **Why not DACK-less polled data with DMA feeding SM0?** Possible
  (Data reg doesn't auto-increment away), but each byte must be gated on
  DBR, which DMA can't test — you'd throttle blind. Burst mode exists
  precisely for this; use it.
* **Errata to honor:** see the full matrix in **Appendix D**. The ones
  that shape this section: E024 (park DRQ̅/DACK̅ inactive in polled
  mode), E022 (ignore brief DRQ̅ deassertions — the `wait 0 gpio` +
  per-byte re-check pattern already handles it), E040 (after SAT, check
  PE bit even on success), E018-P3 (set IDI before SAT when disconnects
  + Data Out are possible, or FIFO bytes vanish silently).

Throughput reality check: SCSI-1 async tops out ≈ 1.5–2 MB/s on real
targets; the burst engine sustains ~2.5 MB/s+, chip ceiling 5 MB/s
(sync). The Pico is never the bottleneck.

---

## 6. Clock generation (33C93A CLK, pin 8 ← GP13)

Requirements: square wave, WD33C93A 8–16 MHz, WD33C93B/AMD-20 to
20 MHz, AMD-16 to 16 MHz. **Avoid 11 MHz** (divisor gap breaks bus-clear
timing). The Own ID FS field must match:

| f_CLK | FS1:0 | divisor | max transfer rate |
|---|---|---|---|
| 8–10 MHz | 00 | ÷2 | 4–5 MB/s |
| 12–15 MHz | 01 | ÷3 | 4–5 MB/s |
| 16 MHz (20 on -20/B parts) | 10 | ÷4 | 4–5 MB/s |

**Primary: PWM.** GP13 = PWM slice 6B. For an exact 50 % square wave use
integer division of sysclk:

* **Recommended: sys_clk = 120 MHz** (`set_sys_clock_khz(120000, true)`,
  fine on RP2040 and RP2350): PWM TOP=7, CC=4 → **15 MHz**, FS=01.
  Also makes the SM0/SM1 divider exact (÷5 → 24 MHz, 41.67 ns/cycle —
  the clock all of §2's delay counts are derived from; change either
  number and §2's constraint table must be re-run).
  120 MHz is USB-compatible on both chips — the SDK keeps PLL_USB at
  48 MHz independently of the sys PLL, and BOOTSEL mode runs on boot
  defaults regardless — but **"USB still enumerates at 120 MHz" belongs
  on the bring-up checklist**, verified once per board revision.
* 125 MHz default sysclk alternatives: ÷10 → 12.5 MHz (FS=01), ÷8 →
  15.625 MHz (out of the 12–15 band — don't).
* For a -20/B part chasing sync transfers: sys 160 MHz ÷ 8 = 20 MHz, FS=10.

Set 8 mA drive + `GPIO_SLEW_RATE_FAST` on GP13; keep the trace short.
On RP2040 builds the HCT/LVC output buffer squares it up anyway.

**Alternatives:**
* `clk_gpout0` on **GP21**: hardware clock output with its own divider,
  glitch-free, zero peripheral cost — but pin-fixed (GP21) and
  fractional division adds jitter, so use integer only.
* PIO 2-instruction toggler: works, wastes an SM.
* Canned oscillator on the board: only if you want the Pico removable;
  the board has no footprint for one, so PWM it is.
* Timeout register ties to this: `TPR = ceil(Tper_ms × f_MHz / 80)`
  → 250 ms @ 15 MHz = 47 (0x2F).

---

## 7. RP2040 (Pico W) vs RP2350 (Pico 2 W)

| Aspect | Pico W (RP2040) | Pico 2 W (RP2350) | Firmware impact |
|---|---|---|---|
| 5 V tolerance | None — shift all chip-driven lines | All GPIOs FT (powered) | **BOM: 2–3 ICs vs 0.** Same firmware; shifters are transparent. |
| PIO | 2 blocks / 8 SMs, CYW43 takes one | 3 blocks / 12 SMs | RP2350: park SCSI on PIO2, never contend with WiFi. Same programs (32-slot memory identical). |
| Sysclk default | 125 MHz | 150 MHz | Use `set_sys_clock_khz(120000)` on both → identical PWM/PIO divider math. (150 MHz ÷ 10 = 15 MHz also works if you stay stock on Pico 2.) |
| CPU | 2× M0+ | 2× M33 (or Hazard3) | Faster IRQ entry & phase engine; irrelevant to data plane (DMA does it). |
| SRAM | 264 KB | 520 KB | Bigger disk-block caches / more in-flight buffers. |
| Unpowered failsafe | — | FT pins only 3.3 V-safe unpowered | Power sequencing: don't leave the 5 V board driving a dead Pico 2 for long; shared power rail (J4 +5 V → VSYS via Schottky) sidesteps it. |
| Security/OTP | — | OTP, signed boot | Irrelevant here. |

**Recommendation: build on Pico 2 W.** Direct wiring (16 jumper wires),
a whole PIO block to itself, and headroom for a WiFi SCSI-over-TCP
bridge later. Keep the RP2040 build as a compile-time board variant —
nothing in the firmware architecture changes, only `#define`s for
shifter DIR handling (GP19) and clock setup.

---

## Appendix A — firmware module layout

```
src/
  sbic_bus.pio        SM0 register engine + SM1 burst in/out
  sbic_bus.c/.h       PIO/DMA transport, GPIO init, MR/RST control
  sbic_regs.h         register addresses, bit masks, command opcodes
  sbic.c/.h           chip driver: init/reset, command issue, IRQ handler,
                      aux/SCSI status decode, 7us guard, errata workarounds
  scsi_phase.c/.h     strategy B phase engine (Transfer Info per phase)
  scsi_sat.c/.h       strategy A: Select-w/ATN-and-Transfer wrapper
  scsi_initiator.c/.h public API: scsi_execute(cdb, dir, buf, len, &status)
  scsi_cmds.c/.h      INQUIRY / TEST UNIT READY / READ CAPACITY /
                      READ(6/10) / WRITE(6/10) / REQUEST SENSE builders
  main.c              core1: SCSI stack; core0: CLI/USB-MSC/WiFi bridge
```

## Appendix B — complete command reference

Command register (18h): bit 7 = **SBT** (single-byte transfer: disables
the Transfer Count for info-transfer commands, exactly one byte moves;
also lets Wait-for-Select-and-Receive accept a LUNTAR Identify),
bits 6:0 = opcode.

Rules: **Level I** commands (except Reset/Abort) complete without an
interrupt and may be issued while a Level II command runs. **Level II**
commands always end in an interrupt; issuing one while another Level II
runs (BSY set) is undefined; issuing any command with CIP or INT set is
ignored (LCI) or invalid. A Level II command issued in the wrong
chip state gives an "invalid command" interrupt (40h); a Level I command
in the wrong state is silently ignored. States: **D** disconnected,
**T** connected-as-target, **I** connected-as-initiator.

### Level I

| Op | Command | Valid | What it does |
|---|---|---|---|
| 00 | Reset | D,T,I | Soft reset: applies Own ID (ID, divisor, EAF/EHP/RAF), clears 01h–16h, ends with interrupt 00h (01h if EAF) |
| 01 | Abort | D,T | D: halt selection/reselection attempt (before arbitration won → 22h; after, de-assert IDs, target may still answer within 200 µs). T: halt Send/Receive — for Sends stop servicing DRQ immediately, for Receives KEEP servicing until the interrupt; count left in 12h–14h |
| 02 | Assert ATN | I | Announce pending message-out. Auto-negated before last Transfer Info byte / after SAT Identify / at bus free. **Never during SAT IDENTIFY/COMMAND phases (E018-P2)** |
| 03 | Negate ACK | I | Release ACK̅ held after Message-In pause, parity halt, advanced reselection, save-data-pointer, queue-tag mismatch[B], status parity error. Assert ATN *first* if replying MESSAGE REJECT / MESSAGE PARITY ERROR / INITIATOR DETECTED ERROR |
| 04 | Disconnect | T,I | Immediate release of all bus signals → D. Target: normal end-of-op disconnect. Initiator: bail-out (e.g. after timeout). Transfer Count NOT trustworthy afterwards |
| 0F | Set IDI | D,T,I | Set the Control IDI bit while a Level II command is running (register file is otherwise locked) — enables overlapped-I/O disconnect interrupts mid-command |

### Level II — simple

| Op | Command | Valid | What it does |
|---|---|---|---|
| 05 | Reselect | D | Arbitrate + reselect initiator in Destination ID (I/O̅ asserted) → connected-as-**target**. Timeout per 02h |
| 06 | Select-with-ATN | D | Arbitrate + select target in Destination ID, ATN̅ asserted before SEL̅ release → I. Timeout 42h / abort 22h; selection/reselection *of us* during arbitration → 8xh |
| 07 | Select-without-ATN | D | Same, no ATN̅ |
| 10–13 | Receive Command / Data / Message-Out / Unspecified-Info-Out | T | Target-role in-phases (I/O̅=0). Phase lines set from opcode: MSG,C/D = 10:(0,1) 11:(0,0) 12:(1,1) 13:(1,0). Receive **Data** (11h) honors Sync Transfer + Control DM bits; others polled/async |
| 14–17 | Send Status / Data / Message-In / Unspecified-Info-In | T | Target-role out-phases (I/O̅=1). MSG,C/D = 14:(0,1) 15:(0,0) 16:(1,1) 17:(1,0). Send **Data** (15h) honors Sync Transfer + DM bits |
| 18 | Translate Address | D,T | LBA→CHS using 03h–0Eh geometry aliases; overflow → 45h. Spare-sector compensation via Head/Cylinder Number preload |
| 20 | Transfer Info | I | One information phase in the direction/type the target requests (MCI from last 8x/1x interrupt). Preload Transfer Count (or SBT); for Data phases set DM bits + Sync Transfer first. Non-message-in → 18h+MCI on next REQ̅; Message-In → pauses 20h with ACK̅ held |

### Level II — combination

| Op | Command | Valid | What it does |
|---|---|---|---|
| 08 | Select-with-ATN-and-Transfer | D,I(resume) | Full initiator SCSI op: arbitrate, select+ATN, IDENTIFY (built from LUN reg ⊕ 80h/C0h per ER; +tag msg[B] per TG bits), CDB from 03h–0Eh (6/10/12 by group; CDB-Size for unknown groups in advanced mode), Data phase per Transfer Count/DM/Sync, Status → LUN reg, Command-Complete → 16h interrupt (EDI delays to disconnect). Resume by rewriting Command Phase + reissuing (Appendix H) |
| 09 | Select-without-ATN-and-Transfer | D,I(resume) | Same without ATN/IDENTIFY (expects COMMAND right after selection) |
| 0A | Reselect-and-Receive-Data | D,T(resume) | Target-role: reselect initiator, send IDENTIFY (+tag[B]), Receive Data-Out, then interrupt — or chain per EDI/SCC to 0Dh (SCC=0) / 0Eh (SCC=1) |
| 0B | Reselect-and-Send-Data | D,T(resume) | Same with Data-In to the initiator |
| 0C | Wait-for-Select-and-Receive | D,T(resume) | Idle until selected; auto-receive IDENTIFY (→ LUN reg; tag[B] → 15h/1Ah) and CDB (→ 03h–0Eh; group from byte 1, unknown group pauses 87h/phase 31h in advanced mode). EDI=1: auto-chain to Send-Disconnect-Message on read-class opcodes |
| 0D | Send-Status-and-Command-Complete | T | Sends status = CDB11, then Command-Complete (00h) or Linked-C-C (0Ah/0Bh per CDB12 bits 0–1); links chain to 0Ch's command fetch unless DF set |
| 0E | Send-Disconnect-Message | T | Sends Disconnect (04h) — preceded by Save-Data-Pointer (02h) if IDI=1 — then releases BSY̅ → D |

Removed vs the original WD33C93: Transfer Pad and initiator-mode Abort
(do not use on A/B). Tag-message behavior throughout (TG bits, Queue
Tag register, phase values 21/22/70/71) is **[B] only**.

## Appendix C — host-bus timing minima used by the PIO programs

All values below were **visually verified against the PDF timing pages**
(A app notes pp. 52–53, 60–62; B datasheet pp. 47–49, 56–57) because the
text-layer extraction of these tables was unreliable.

Indirect write (identical A and B): tWE ≥ 120 ns, data setup ≥ 70 ns,
hold 0, recovery ≥ 100 ns (B adds tWHCH min −5 ns — CS̅ may rise just
before WE̅; we co-deassert, unaffected).
Indirect read: tRE ≥ 180 ns **and ≤ 10 µs**; data valid ≤ 180 ns (A) /
≤ 162 ns (B) from RE̅↓; data held 5–40 ns after RE̅↑; recovery ≥ 100 ns.
Burst DMA (A, governing worst case): write strobe ≥ 50 ns, setup ≥ 25 ns,
read strobe ≥ 80 ns, read data valid ≤ 50 ns from RE̅↓, recovery ≥ 80 ns,
DACK̅↔strobe skew ≥ 0. (B: strobes ≥ 30 ns and a pipelined read model —
see §2.) MR̅ ≥ 1 µs. INTRQ: rises ≥ 0 before RE̅↓ of the status read,
falls ≤ 100 ns after RE̅↑, stays low ≥ 100 ns before re-asserting.
CLK (E018 revision; B §6.1.1 identical): period 50–125 ns →
**8–20 MHz**, high/low ≥ 20 ns.

## Appendix D — errata matrix (WD app notes index #071-A + included texts)

The combined PDF contains the **index** of all app notes but full text
for only some. "In PDF" = full write-up available in
`docs/WD33C93A-appnotes.pdf` / `docs-extracted/WD33C93A-appnotes.txt`.

| # | Subject | Impact on this design | Handling |
|---|---|---|---|
| E018 (in PDF) | WD33C93A bug list P1–P7 + 20 MHz clock spec | P1 spurious DATA IN after IDENTIFY (SAT); P2 Assert-ATN during SAT IDENTIFY/COMMAND = undefined behavior; P3 FIFO loss on DATA OUT disconnect; P5 false bus-free on ≥200 ns BSY/SEL glitches | §4 strategy-A workarounds; keep termination clean (P5); P4/P6/P7 are target-mode/WD-bus only — N/A |
| E022 | DRQ̅ may glitch-deassert (rev C/D) | burst engine pacing | per-byte `wait 0 gpio` re-check absorbs it |
| E024 | DRQ̅/DACK̅ must be false in polled I/O | init/idle state | DACK̅ idles high (§1) |
| E039 | ACK̅ may deassert before REQ̅ | initiator handshake appearance on the wire | tolerance note in §4; no firmware action — chip-internal handshake |
| E040 | Parity error masked by other interrupts in SAT | error detection | check PE (aux status) after every SAT completion, even 16h success |
| E043 | Aux Status register usage notes | DBR polling edge cases | **full text not in PDF — obtain before relying on DBR corner cases**; polled path is bring-up-only here, burst DMA path unaffected |
| E044 | How to abort Wait-for-Select-and-Transfer | abort paths | initiator-only design never issues WFS; if reselection is later enabled, obtain this note first |
| E046 | Unexpected disconnect ⇒ internal vs external transfer counts diverge | SAT + DMA byte accounting | on any disconnect interrupt, re-read Transfer Count 12h–14h from chip; never trust DMA remaining-count (§4) |
| E049 | ALE maximum timing | none | **N/A — ALE is grounded on this board** (indirect addressing) |
| E066 | Command/interrupt matrix | firmware correctness reference | obtain; use as the truth table for the §4 event handler |
| E067 | SCSI Status phase-bit orientation | MCI decode in strategy B | verify decode against a live COMMAND phase at bring-up (§4) |
| E025, E031, E033, E042, E045, E047, E048, E050, E062, E065, E070, E071 | conversion guides, noise paper, transfer-mode descriptions, reserved-bit rule | background | E070: always write reserved register bits as 0 (already required by datasheet note) |

## Appendix E — bring-up checklist

1. USB enumerates with `set_sys_clock_khz(120000, true)` (PLL_USB stays
   at 48 MHz; BOOTSEL uses boot defaults — but verify once per board).
2. CLK at U1 pin 8: 15 MHz, ≥ 20 ns high and low (scope).
3. `tools/check_pio_timing.py` passes after any PIO/clock edit.
4. MR̅ reset → INTRQ fires, SCSI Status reads 00h/01h.
5. Register file walk: write/read-back CDB regs 03h–0Eh via
   auto-increment, confirm Address register behavior (Data/Command/Aux
   excluded from auto-increment).
6. DRQ̅ external ~1 kΩ pull-up fitted; DRQ̅ reads high (deasserted)
   after init, before any transfer command.
7. MCI orientation check against a real target: SELECT then confirm the
   first bus-service interrupt decodes as COMMAND phase (MCI = 010) —
   validates the E067 concern.
8. TERMPWR ≥ 4.0 V at J1-26 under full termination load (both
   terminator packs jumpered).
9. Variant probe: soft-reset with EAF=1 — SCSI Status 01h confirms
   A/B-class silicon; with RAF=1[B], CDB1 returns the microcode
   revision (B only).

---

# Complete Programming Reference (WD33C93 / 93A / 93B)

Everything firmware-facing, consolidated from the WD33C93B datasheet
(§3.1.1–3.1.23, §4), the WD33C93A app notes, and the E062 family-
difference notes — so nobody has to cross-reference four PDFs.

**Variant legend** — the PLCC-44 socket takes any of the three:
* *(no flag)* — WD33C93, 93A, AM33C93A, 93B all implement it.
* **[A+]** — added on WD33C93A/AM33C93A; absent on plain WD33C93.
* **[B]** — WD33C93B only (**the chip fitted on the demo board**);
  reserved/zero on A. Firmware that must run on both chips: write
  [B] bits as 0 and don't read [B] registers on an A.

## Appendix F — register reference (bit-level)

Access convention (this board, ALE grounded → indirect addressing):
write register number with A0=0, access with A0=1; auto-increment
except at Data (19h) and Command (18h); Aux Status = read with A0=0.

### Aux Status (read A0=0; direct-mode address 1Fh) — read-only

| Bit | Name | Meaning |
|---|---|---|
| 0 | DBR | Data register ready: set when FIFO can give (in) / take (out) a byte in polled I/O; cleared by the Data access |
| 1 | PE | Parity error seen on a received byte (SCSI always checked; host side only if EHP). Set regardless of HSP/HHP. Cleared by next command |
| 2 | FFE **[B]** | FIFO full/empty: with DBR set, host may write 11 / read 12 bytes without re-polling DBR (two exceptions: first fill after Transfer Info/Send allows 12; never write the *last* message-out byte until the chip re-requests it) |
| 3 | 0 | reserved |
| 4 | CIP | Command being interpreted — Command register unavailable |
| 5 | BSY | Level II command executing — only Command (if CIP=0), Data, Aux Status accessible |
| 6 | LCI | Last command ignored (issued too close to a pending interrupt — the 7 µs rule) |
| 7 | INT | Mirrors INTRQ pin; read SCSI Status to clear |

### 00h — Own ID / CDB Size (R/W)

Sampled **only by the Reset command** (mode 1). In advanced mode
(mode 2) bits 3:0 = CDB length for unknown command groups.

| Bit | Name | Meaning |
|---|---|---|
| 2:0 | ID2:0 | Own SCSI bus ID for arbitration/selection |
| 3 | EAF | Enable advanced features (§4.3.1 [B numbering]: unexpected-reselection Identify fetch, unknown-CDB-group handling, DPD direction check). Reset interrupt becomes 01h |
| 4 | EHP | Enable host-bus parity *checking* (generation on DP is always on) |
| 5 | RAF **[B]** | Really-advanced features: microcode rev → CDB1 at reset, immediate halts, protocol-error interrupt 25h, unexpected-bus-free 41h/85h. **Incompatible with A firmware expectations** |
| 7:6 | FS1:0 | Input-clock divisor: 00=÷2 (8–10 MHz), 01=÷3 (12–15 MHz), 10=÷4 (16 MHz A / 16–20 MHz B & AMD-20), 11=undefined. Never use 10–12 MHz |

### 01h — Control (R/W)

| Bit | Name | Meaning |
|---|---|---|
| 0 | HSP | Halt on SCSI parity error (Receive/Transfer Info). Initiator: ACK̅ left asserted to freeze the target. Sync transfers check on 4096-byte boundaries (every byte if RAF[B] immediate halt) |
| 1 | HA | Target mode: halt Send/Receive when initiator asserts ATN̅ (checked at start / 4096-byte boundaries / end; continuous with RAF[B]) |
| 2 | IDI | Intermediate disconnect interrupt (initiator, SAT): proper target disconnect → 85h + suspend, resumable. Target combo commands: execution-option select. **Required set when disconnects enabled + Data-Out expected (E018-P3)** |
| 3 | EDI | Ending disconnect interrupt: delay SAT's 16h until the target disconnects (replaces 85h); target side: enables command chaining (0A/0B→0D/0E, 0C auto-disconnect on reads) |
| 4 | HHP | Halt on host parity error (Send/Transfer out). ACK̅ *not* held. Needs EHP=1 |
| 7:5 | DM2:0 | 000 polled I/O · 001 Burst (demand DMA — **this design's data plane**) · 010 WD-bus/DBA (bus-master into external RAM; RE̅/WE̅/DACK̅ reverse direction — unused here) · 100 single-byte DMA |

### 02h — Timeout Period (R/W)

`value = ceil(Tper_ms × Ficlk_MHz / 80)` (undivided CLK); 0 disables.
Governs Select/Reselect BSY̅-response wait. 15 MHz, 250 ms → 47.

### 03h–0Eh — CDB 1–12 / Translate-Address aliases (R/W)

One register file, three uses:

| Addr | As CDB | As Translate Address | Other |
|---|---|---|---|
| 03h | CDB1 | Total Sectors (per track) | microcode rev after reset [B, RAF] |
| 04h | CDB2 | Total Heads | |
| 05h/06h | CDB3/4 | Total Cylinders MSB/LSB | |
| 07h–0Ah | CDB5–8 | Logical Address MSB…LSB (32-bit in) | |
| 0Bh | CDB9 | Sector Number (result) | |
| 0Ch | CDB10 | Head Number (result; preload spares/cylinder for compensation, else 0) | |
| 0Dh | CDB11 | Cylinder MSB (result) | status byte to send, for 0Dh command |
| 0Eh | CDB12 | Cylinder LSB (result) | link-control bits for 0Dh (bit0 linked, bit1 flag) |

### 0Fh — Target LUN (R/W)

| Bit | Name | Meaning |
|---|---|---|
| 2:0 | TL2:0 | LUN for IDENTIFY generation/check (SAT, RAT) |
| 6 | DOK | Disconnect-OK: WFSR: initiator allowed disconnects. SAT: with ER=1, respond to reselection but send IDENTIFY without disconnect privilege |
| 7 | TLV | Identify-valid flag (WFSR result; keep 0 when issuing SAT) |

Also receives: target's status byte (SAT), reselecting LUN/target-routine
number (advanced-mode unexpected reselection).

### 10h — Command Phase (R/W) — see Appendix H

Progress/resume pointer for combination commands. Read after abnormal
termination to locate the failure; write before reissuing to resume.

### 11h — Synchronous Transfer (R/W)

| Bit | Name | Meaning |
|---|---|---|
| 3:0 | OF3:0 | REQ/ACK offset 0–12. **0 = asynchronous** (this design's default). Values 13–15 undefined |
| 6:4 | TP2:0 | Min transfer period in internal-clock cycles: 000=8, 001=2, 010=3, 011=4, 100=5, 101=6, 110=7 (sync pulse widths in parentheses in datasheet table). Non-data phases always use 6 |
| 7 | FSS **[B]** | Fast SCSI: with ÷4 (16–20 MHz clock), doubles the internal transfer clock → up to 10 MB/s sync. No effect on async |

Internal cycle = divisor / (2 × Ficlk); with FSS[B] at ≥16 MHz:
2 / ((FSS+1) × Ficlk).

### 12h–14h — Transfer Count (R/W, 24-bit MSB first)

Preloaded before Send/Receive/Transfer Info (0 or SBT ⇒ single byte,
counter disabled). After success: 0. After halt/abort/phase change:
**bytes NOT transferred over SCSI, including bytes stranded in the
FIFO** — hence it can legitimately differ from the Pico DMA channel's
count (E046: always trust these registers, not the DMA remainder).

### 15h — Destination ID (R/W)

| Bit | Name | Meaning |
|---|---|---|
| 2:0 | DI2:0 | Bus ID to select/reselect |
| 4:3 | TG1:0 **[B]** | Tag message for SAT/WFSR/RAT: 00 none, 01 Simple (20h), 10 Head-of-queue (21h), 11 Ordered (22h) |
| 5 | DF **[B]** | Disable: DPD direction check + auto 0Dh→0Ch link on linked-command-complete |
| 6 | DPD [A+] | Expected SAT data-phase direction (0=out, 1=in); mismatch → unexpected-phase interrupt (advanced mode; disabled by DF[B]) |
| 7 | SCC [A+] | RAT chain select when EDI=1: 0 → Send-Status-and-Command-Complete, 1 → Send-Disconnect-Message |

### 16h — Source ID (R/W)

| Bit | Name | Meaning |
|---|---|---|
| 2:0 | SI2:0 | Bus ID of the device that (re)selected us (valid iff SIV) |
| 3 | SIV | Set when the (re)selector asserted its own ID bit |
| 5 | DSP | Disable parity check during selection/reselection response |
| 6 | ES | Enable response to **selection** (target-mode master switch) |
| 7 | ER | Enable response to **reselection** (initiator disconnect/reconnect support; also sets IDENTIFY bit 6) |

### 17h — SCSI Status (read-only) — see Appendix G

Cause of the last INTRQ; frozen until read; reading clears INTRQ.
Then wait ≥ 7 µs before writing Command (LCI rule).

### 18h — Command (R/W) — see Appendix B

### 19h — Data (R/W)

Port into the 12-byte FIFO, all phases and both DMA/processor paths.
Polled rules: only touch when DBR=1 (exception: advanced-mode
reselection Identify must be read out regardless); FFE[B] batch rules
in the Aux Status row above; during a Data phase only touch it if
DM=000 or you've quiesced the DMA interface (DACK̅ inactive). If a
command halts (abort etc.), **keep servicing the FIFO until the
interrupt arrives** or the chip stays wedged.

### 1Ah — Queue Tag (R/W) **[B only]**

Second byte of tag messages: sent by SAT/RAT after the tag code;
receives the incoming tag from WFSR/SAT-reselection. SAT compares the
reselection tag with the previous contents — mismatch → interrupt 26h
with ACK̅ held.

### Reset behavior

| Condition | Hard reset (MR̅) | Soft reset (cmd 00h) |
|---|---|---|
| Aux Status | cleared; INT set when done | DBR cleared; INT set when done |
| Own ID (00h) | **cleared** | interpreted (ID, divisor, EAF/EHP/RAF applied) |
| 01h–15h | **preserved** | cleared (01h–16h) |
| Source ID ES/ER/DSP | cleared (bits 0–3 preserved) | cleared (whole 16h) |
| SCSI Status | 00h | 00h (01h if EAF set) |
| FIFO/counters/offsets/state | cleared | cleared; SCSI signals released |
| Divisor | ÷2 | per FS1:0 |

WD's suggested SCSI-RST handling fits GP18 exactly: OR the incoming
bus-reset into MR̅ (or, as here, take the GPIO IRQ and pulse MR̅ in
firmware), then rebuild state from the preserved 01h–15h registers.

## Appendix G — SCSI Status (17h) interrupt code reference

Code = `GGGGQQQQ`: high nibble = group, low nibble = qualifier. Where
the qualifier is shown as `1MCI`, bit 3 is 1 and bits 2:0 are the
**MCI** phase code of the *requested* phase (verify orientation at
bring-up — E067):

| MCI | Phase | MCI | Phase |
|---|---|---|---|
| 000 | DATA OUT | 100 | unspec. info out |
| 001 | DATA IN | 101 | unspec. info in |
| 010 | COMMAND | 110 | MESSAGE OUT |
| 011 | STATUS | 111 | MESSAGE IN |

States: D disconnected, T target, I initiator. "→" = recommended
firmware action.

### 0xh — reset complete

| Code | State | Meaning → action |
|---|---|---|
| 00 | D,T,I | Hard reset or soft reset (EAF=0) done → program Own ID, issue Reset cmd (first time) or re-init |
| 01 | D,T,I | Soft reset done with EAF=1 → proceed to Control/Timeout/Source ID setup |

### 1xh — successful completion

| Code | State | Meaning → action |
|---|---|---|
| 10 | D | Reselect (05h) won → now T; proceed with IDENTIFY out |
| 11 | D | Select (06/07h) won → now I; await 8MCI phase request |
| 13 | T | Receive/Send/RAT/WFSR/0Dh/0Eh done, ATN̅ negated → next target phase (for WFSR: parse CDB in 03h–0Eh) |
| 14 | T | As 13 but **ATN̅ asserted** (and 0Eh not in this list — a completed disconnect can't see ATN) → issue Receive Message Out (12h) first |
| 15 | D,T | Translate Address done → read CHS results |
| 16 | I | SAT complete → read status from LUN reg (0Fh); check PE (E040) |
| 18+MCI | I | Transfer Info (non-msg-in) done; target now requests MCI → run the phase engine on MCI |

### 2xh — paused / aborted

| Code | State | Meaning → action |
|---|---|---|
| 20 | I | Transfer Info (Message In) paused, **ACK̅ held** → inspect byte; ATN+message-out to object, then Negate ACK (03h) |
| 21 | I | Save-Data-Pointer received during SAT → save host data pointer, resume SAT (phase 41h) |
| 22 | D | Select/Reselect/WFSR aborted (Abort cmd or selection abort) → idle |
| 23 | T | Receive/Send aborted, or WFSR got bad IDENTIFY (ATN̅ off) → Transfer Count = residue |
| 24 | T | As 23 but ATN̅ asserted → service message out |
| 25 | T | Transfer corrupted by REQ/ACK noise (protocol error) **[B, RAF]** → treat data as suspect, retry |
| 26 | I | Reselected by process with mismatched queue tag **[B]**, ACK̅ held; new tag now in 1Ah → context-switch or reject |
| 27 | I | Advanced-mode SAT: reselected by wrong target/LUN; ID in 16h, LUN in 0Fh, ACK̅ held → save state of current op, service the interloper (multi-threaded I/O) or reject |

### 4xh — terminated with error

| Code | State | Meaning → action |
|---|---|---|
| 40 | D,T,I | Invalid command for current state → firmware bug; log |
| 41 | T,I | Unexpected disconnect (bus went free) → now D; fail the op (with RAF[B] may also be a SEL glitch, E062) |
| 42 | D | Select/Reselect timeout (per 02h) → no such device |
| 43 | T,I | Parity error terminated a command (ATN̅ off); direction ⇒ SCSI vs host side → error recovery, count in 12h–14h |
| 44 | T | As 43 with ATN̅ asserted → service message out |
| 45 | D,T | Translate Address overflow (LBA beyond disk) → reject |
| 46 | I | Non-advanced SAT: reselected by wrong-ID target; still connected → sort it out manually (Transfer Info) or Disconnect |
| 47 | I | Status byte had parity error during SAT, ACK̅ held → ATN + INITIATOR DETECTED ERROR, or accept via Negate ACK |
| 4MCI (bit3=1) | I | **Unexpected phase** MCI requested (count ≠ 0 mid-Transfer-Info, or SAT protocol deviation) → the normal "target changed phase early" path: reload phase engine from MCI (check PE first on sync transfers) |

### 8xh — service required

| Code | State | Meaning → action |
|---|---|---|
| 80 | D | Reselected (normal mode) → now I; read 16h for reselector, resume that op |
| 81 | D | Reselected (advanced mode); IDENTIFY **in Data register**, ACK̅ held → read 19h, match to a suspended op, Negate ACK |
| 82 | D | Selected, no ATN̅ → now T; expect COMMAND out (Receive Command 10h) |
| 83 | D | Selected with ATN̅ → now T; Receive Message Out (12h) first |
| 84 | T | ATN̅ asserted mid-operation → Receive Message Out |
| 85 | T,I | Target disconnected (T: after our 0Eh; I: IDI-enabled SAT suspension, Command Phase = 43h) → park op, bus is free |
| 87 | T | WFSR paused: unknown CDB group (advanced); opcode in CDB1, phase = 31h → write total CDB length into 00h bits 3:0, reissue 0Ch to resume. Only Resume-WFSR/Abort/Disconnect/Reset accepted while paused |
| 8MCI (bit3=1) | I | REQ̅ asserted while initiator-idle: target requests phase MCI → issue Transfer Info (the phase engine's main event) |

## Appendix H — Command Phase register (10h) values

The heart of combination-command recovery: on any abnormal SAT/RAT/WFSR
termination, read 10h to see how far it got; to resume, write a valid
resume value (right column ✓) and reissue the same command opcode.

### Select-and-Transfer (08/09h)

| Value | Got this far | Resume? |
|---|---|---|
| 00 | nothing — still disconnected | reissue from scratch |
| 10 | target selected | ✓ |
| 20 | IDENTIFY sent | ✓ (implied Negate ACK) |
| 21/22 **[B]** | tag code / queue tag sent | ✓ 22 (implied Negate ACK) |
| 30 | COMMAND phase begun, 0 bytes | ✓ |
| 3x | x CDB bytes transferred | — |
| 41 | Save-Data-Pointer received | ✓ (implied Negate ACK; also the E018-P1 workaround resume point) |
| 42 | Disconnect message received, bus not yet free | ✓ (complete the disconnect) |
| 43 | target disconnected (bus free) | — (wait for reselection or abort) |
| 44 | reselected by matching target | ✓ (expects IDENTIFY in) |
| 45 | IDENTIFY (+tag[B]) verified after reselection | ✓ (more data; implied Negate ACK) |
| 46 | Data phase complete (count = 0) | ✓ (expects Status; **no** implied Negate ACK) |
| 47 | Status phase begun | — |
| 50 | status byte in 0Fh | ✓ (complete Command-Complete msg) |
| 60 | Command-Complete received | ✓ |
| 70/71 **[B]** | IDENTIFY matched, tag expected / Simple-Queue-Tag received | ✓ 70 (implied Negate ACK) |

### Reselect-and-Transfer (0A/0Bh)

00 idle · 10 initiator reselected (resume ✓ → IDENTIFY out) ·
20 IDENTIFY sent (resume ✓ → data phase; count 0 ⇒ skip to chain) ·
46 data transfer complete.

### Wait-for-Select-and-Receive (0Ch)

00 idle · 10 selected (resume ✓: message-out if ATN else command) ·
20 got Identify byte → 0Fh (resume ✓: validate) · 21 got tag code
(resume ✓)[B] · 22 got queue tag[B] · 30 ready for COMMAND phase
(resume ✓) · 31 1 CDB byte in — unknown-group pause point (resume ✓
after loading CDB size, see 87h) · 3x x CDB bytes in.
Paused interrupts at phase 20/21 = invalid message byte; Identify
parity error leaves phase = 10 so a plain reissue retries cleanly.

### Send-Status-and-Command-Complete (0Dh)

00 nothing (ATN̅ was up) · 50 status sent (resume ✓) · 60
Command-Complete sent · 61 Linked-Command-Complete sent.

### Send-Disconnect-Message (0Eh)

00 nothing (ATN̅ was up) · 41 Save-Data-Pointer sent (IDI=1) ·
42 Disconnect message sent · 43 bus free — disconnected.

## Appendix I — target mode: init and phase engine

Nothing in §1/§2 changes: same GPIO map, same PIO engines (Send/Receive
Data honor the Control DM bits, so the SM1 burst engine and DMA channel
drive target-mode data phases exactly as initiator ones).

### Configuration

```
1. MR̅ pulse → interrupt 00h.
2. Own ID (00h) = our ID | EAF (| RAF only if B-specific firmware).
3. Command 00h (Reset) → interrupt 00h/01h.
4. Source ID (16h): ES=1 (respond to selection). ER only matters for
   initiator-role reconnects; DSP as needed.
5. Control (01h): DM=001 (burst) for data phases; HA=1 recommended so
   an initiator's ATN̅ interrupts long transfers; EDI/IDI per chaining
   strategy below.
6. Timeout (02h) still applies — to OUR Reselect attempts.
```

A selection by an initiator then arrives as interrupt **82h** (no ATN)
or **83h** (ATN) — or is absorbed automatically by a pending
Wait-for-Select-and-Receive.

### Two strategies, mirroring §4

**A. Combination (recommended): park in Wait-for-Select-and-Receive.**
Issue 0Ch when idle. The chip auto-handles selection, IDENTIFY (→ 0Fh,
tag → 1Ah[B]), and the whole COMMAND phase (CDB → 03h–0Eh, length from
the group code). One interrupt (13h/14h) delivers a parsed SCSI command.
Then:

* immediate service: Send Data (15h) / Receive Data (11h) with Transfer
  Count + burst DMA, then **0Dh** (status in CDB11, link bits in CDB12)
  → bus free, reissue 0Ch;
* disconnecting service (EDI=1): read-class CDBs auto-chain to **0Eh**
  (disconnect) before you even see them finish; do the medium work,
  then **0Ah/0Bh** to reselect and move data, with EDI/SCC chaining
  straight into 0Dh or 0Eh — a full disconnected READ costs ~3
  interrupts total;
* unknown CDB group (advanced): 87h pause → write length to 00h bits
  3:0 → reissue 0Ch.

**B. Manual (bring-up/debug): phase-at-a-time.** ES=1, wait for 82h/83h,
then drive the bus yourself — the key inversion vs initiator mode is
that **the target chooses the phases**: 12h Receive Message Out (if
83h) → 10h Receive Command → 11h/15h data → 14h Send Status → 16h Send
Message In (Command-Complete 00h) → 04h Disconnect. The opcode's low
bits set MSG/C/D directly (Appendix B); REQ̅/ACK̅ handshakes are still
entirely the chip's problem.

### Target-side rules that differ from §4

* **ATN̅ is the initiator's interrupt to us**: 84h (or HA-halted
  transfer, codes 14/24/44) means "stop and run Receive Message Out".
* Aborting a **Send**: stop feeding DRQ/DBR immediately after writing
  Abort. Aborting a **Receive**: keep draining until the interrupt
  (Appendix B, Abort row) — get this backwards and the FIFO wedges.
* Reselection (0A/0B/05h) arbitrates like selection and honors the
  same Timeout register; loss/timeout leaves phase = 00.
* IDENTIFY generation is automatic from 0Fh + ER/DOK; don't hand-build
  message bytes unless in strategy B (then it's just Send Message In).
* WFSR rejects LUNTAR Identifies unless the command is issued with SBT
  set (target-routine support).
