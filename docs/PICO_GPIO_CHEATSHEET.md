# Raspberry Pi Pico / Pico W / Pico 2 / Pico 2 W — GPIO Reference

## Quick Summary

| Board | Chip | Cores | PIO Blocks | PIO SM | SRAM | WiFi |
|-------|------|-------|-----------|--------|------|------|
| Pico | RP2040 | 2× M0+ | 2 | 8 (4 ea) | 264 KB | No |
| Pico W | RP2040 | 2× M0+ | 2 | 8 | 264 KB | CYW43439 |
| Pico 2 | RP2350 | 2× M33 or 2× RISC-V | 3 | 12 (4 ea) | 520 KB | No |
| Pico 2 W | RP2350 | 2× M33 or 2× RISC-V | 3 | 12 | 520 KB | CYW43439 |

## Physical Pinout (40-pin DIP-style)

Boards are identical between Pico/Pico W and Pico 2/Pico 2 W.

```
           TOP  (USB port at top edge)
USB     +------------------------------+
        |  1: GP0  (pin 1 square pad)  |  40: VBUS (5V in)
        |  2: GP1                     |  39: VSYS (3.3V reg in)
        |  3: GND                     |  38: GND
        |  4: GP2                     |  37: 3V3_EN
        |  5: GP3                     |  36: 3V3_OUT
        |  6: GP4 (SDA1)              |  35: ADC_VREF (Volt)
        |  7: GP5 (SCL1)              |  34: GP28 (ADC2)
        |  8: GND                     |  33: GND (AGND)
        |  9: GP6                     |  32: GP27 (ADC1)
        | 10: GP7                     |  31: GP26 (ADC0)
        | 11: GP8                     |  30: RUN
        | 12: GP9                     |  29: GP22
        | 13: GND                     |  28: GND
        | 14: GP10                    |  27: GP21
        | 15: GP11                    |  26: GP20
        | 16: GP12                    |  25: GP19
        | 17: GP13                    |  24: GP18
        | 18: GND                     |  23: GND
        | 19: GP14                    |  22: GP17
        | 20: GP15                    |  21: GP16
        +------------------------------+
```

### Power Pins

| Pin | Name | Voltage | Notes |
|-----|------|---------|-------|
| 40 | VBUS | 5V | USB input, powers board when USB plugged |
| 39 | VSYS | 1.8–5.5V | Main system input to voltage regulator |
| 37 | 3V3_EN | — | Pull high to enable 3.3V reg; pull low to reset |
| 36 | 3V3_OUT | 3.3V | Regulated 3.3V output, up to 300 mA |
| 35 | ADC_VREF | 3.3V | ADC voltage reference |
| 30 | RUN | — | Reset pin, active low |
| 3,8,13,18,23,28,33,38 | GND | 0V | Ground |

### Wireless (W variants only)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| GPIO23 | CYW_SPI_CS | Output | SPI CS to wireless chip |
| GPIO24 | CYW_SPI_MISO | Input | SPI MISO from wireless chip |
| GPIO25 | CYW_SPI_CLK | Output | SPI clock to wireless chip |
| GPIO29 | CYW_SPI_MOSI | Output | SPI MOSI to wireless chip |
| — | CYW_DATA_OUT | — | OOB out-of-band data |
| — | CYW_DATA_IN | — | OOB in-band data |
| — | CYW_WAKE | Output | Wake the wireless chip |

**On W variants**, GPIO23, GPIO24, GPIO25, GPIO29 are **not available** for general use — they are connected to the CYW43439 WiFi/Bluetooth chip via SPI (CS, MISO, CLK, MOSI respectively).

On W variants, GP0 is NOT one of the WiFi-connected pins, but note that the CYW43439 on Pico W communicates via SPI on GP23–GP25 + GP29. These cannot be used for other purposes while WiFi is active.

### Pico 2 / RP2350 additional notes

- RP2350 has 48 GPIOs (0–47), but **only GPIO0–28 are physically broken out** on the Pico 2 board (same 40-pin layout).
- GPIO29 is used by the ADC for VSYS measurement (pin 39) — available as ADC3 on all boards.
- RP2350 has **3 PIO blocks** with 4 state machines each = 12 total (RP2040 has 2 blocks = 8 total).

## GPIO Function Table

All 26 usable GPIOs (GP0–GP28, except GP23–G25, GP29) on all Pico boards.

GPIO defaults after reset: **high-impedance input** (SIO function F5 selected). The functions below are **alternative functions available via the GPIO function select register** (F1 = GPIO_CTRL_FUNCSEL).

### F1 Alt Function (first alternative peripheral assignment)

| GPIO | Alt F1 func | Also available on other function codes |
|------|-------------|--------------------------------------|
| 0 | **SPI0 RX** | UART0 TX (F2), I2C0 SDA (F3), PWM0 A (F4) |
| 1 | **SPI0 CSn** | UART0 RX (F2), I2C0 SCL (F3), PWM0 B (F4) |
| 2 | **SPI0 SCK** | UART0 CTS (F2), I2C1 SDA (F3), PWM1 A (F4) |
| 3 | **SPI0 TX** | UART0 RTS (F2), I2C1 SCL (F3), PWM1 B (F4) |
| 4 | **SPI0 RX** | UART1 TX (F2), I2C0 SDA (F3), PWM2 A (F4) |
| 5 | **SPI0 CSn** | UART1 RX (F2), I2C0 SCL (F3), PWM2 B (F4) |
| 6 | **SPI0 SCK** | UART1 CTS (F2), I2C1 SDA (F3), PWM3 A (F4) |
| 7 | **SPI0 TX** | UART1 RTS (F2), I2C1 SCL (F3), PWM3 B (F4) |
| 8 | **SPI1 RX** | UART1 TX (F2), I2C0 SDA (F3), PWM4 A (F4) |
| 9 | **SPI1 CSn** | UART1 RX (F2), I2C0 SCL (F3), PWM4 B (F4) |
| 10 | **SPI1 SCK** | UART1 CTS (F2), I2C1 SDA (F3), PWM5 A (F4) |
| 11 | **SPI1 TX** | UART1 RTS (F2), I2C1 SCL (F3), PWM5 B (F4) |
| 12 | **SPI1 RX** | UART0 TX (F2), I2C0 SDA (F3), PWM6 A (F4) |
| 13 | **SPI1 CSn** | UART0 RX (F2), I2C0 SCL (F3), PWM6 B (F4) |
| 14 | **SPI1 SCK** | UART0 CTS (F2), I2C1 SDA (F3), PWM7 A (F4) |
| 15 | **SPI1 TX** | UART0 RTS (F2), I2C1 SCL (F3), PWM7 B (F4) |
| 16 | **SPI0 RX** | UART0 TX (F2), I2C0 SDA (F3), PWM0 A (F4) |
| 17 | **SPI0 CSn** | UART0 RX (F2), I2C0 SCL (F3), PWM0 B (F4) |
| 18 | **SPI0 SCK** | UART0 CTS (F2), I2C1 SDA (F3), PWM1 A (F4) |
| 19 | **SPI0 TX** | UART0 RTS (F2), I2C1 SCL (F3), PWM1 B (F4) |
| 20 | **SPI0 RX** | UART1 TX (F2), I2C0 SDA (F3), PWM2 A (F4) |
| 21 | **SPI0 CSn** | UART1 RX (F2), I2C0 SCL (F3), PWM2 B (F4) |
| 22 | **SPI0 SCK** | UART1 CTS (F2), I2C1 SDA (F3), PWM3 A (F4) |
| 23 | **SPI0 TX** | UART1 RTS (F2), I2C1 SCL (F3), PWM3 B (F4) |
| 24 | **SPI1 RX** | UART1 TX (F2), I2C0 SDA (F3), PWM4 A (F4) |
| 25 | **SPI1 CSn** | UART1 RX (F2), I2C0 SCL (F3), PWM4 B (F4) |
| 26 | **SPI1 SCK** | UART1 CTS (F2), I2C1 SDA (F3), PWM5 A (F4), **ADC0** |
| 27 | **SPI1 TX** | UART1 RTS (F2), I2C1 SCL (F3), PWM5 B (F4), **ADC1** |
| 28 | **SPI1 RX** | UART0 TX (F2), I2C0 SDA (F3), PWM6 A (F4), **ADC2** |
| 29 | **SPI1 CSn** | UART0 RX (F2), I2C0 SCL (F3), PWM6 B (F4), **ADC3** |

### I2C Mapping

| I2C Block | SDA Pins (GPIO) | SCL Pins (GPIO) |
|-----------|----------------|----------------|
| I2C0 | 0, 4, 8, 12, 16, 20 | 1, 5, 9, 13, 17, 21 |
| I2C1 | 2, 6, 10, 14, 18, 26 | 3, 7, 11, 15, 19, 27 |

### SPI Mapping

NOTE: SPI on Pico uses **only the F1 function code**. Each GPIO has a single F1 assignment — either SPI0 or SPI1 (never both). The table below shows the complete F1 assignments for both SPI blocks.

| SPI Block | TX (MOSI) Pins (GPIO) | RX (MISO) Pins (GPIO) | SCK Pins (GPIO) | CSn Pins (GPIO) |
|-----------|----------------------|----------------------|-----------------|-----------------|
| SPI0 (F1) | 3, 7, 19, 23 | 0, 4, 16, 20 | 2, 6, 18, 22 | 1, 5, 17, 21 |
| SPI1 (F1) | 11, 15, 27 | 8, 12, 24, 28 | 10, 14, 26 | 9, 13, 25, 29 |

### UART Mapping

| UART Block | TX Pins (GPIO) | RX Pins (GPIO) | CTS (GPIO) | RTS (GPIO) |
|------------|---------------|---------------|-----------|-----------|
| UART0 | 0, 12, 16, 28 | 1, 13, 17, 29 | 2, 14, 18 | 3, 15, 19 |
| UART1 | 4, 8, 20, 24 | 5, 9, 21, 25 | 6, 10, 22 | 7, 11, 23 |

### PWM

Every GPIO pin can be used for PWM output. RP2040 has 8 PWM slices × 2 channels = 16 channels total.
RP2350 has 12 PWM slices × 2 channels = 24 channels.

PWM slices wrap around the GPIOs: GPIO0/GPIO1 share slice 0, GPIO2/GPIO3 share slice 1, etc.

### ADC

| Channel | GPIO | Notes |
|---------|------|-------|
| ADC0 | GP26 | Available on all boards |
| ADC1 | GP27 | Available on all boards |
| ADC2 | GP28 | Available on all boards |
| ADC3 | GP29 | VSYS measurement (internal divider), NOT general purpose analog |
| ADC4 | — | Internal temperature sensor |

ADC input voltage: 0 to 3.3V (or ADC_VREF on pin 35).
Resolution: 12-bit (0–4095).
Sample rate: 500 kSps maximum.
Effective Number of Bits (ENOB): 8.7 bits minimum (per datasheet characterization).
Temperature sensor: channel 4 (ADC4), Vbe ~0.706V at 27°C, slope -1.721 mV/°C.

## PIO (Programmable I/O) — RP2040

### PIO Block Layout

| PIO Block | GPIO Mapping |
|-----------|-------------|
| PIO0 | All GPIOs, but only 4 state machines. Each SM can be configured independently. Base pin, sideset, jmp pin configurable per SM. |
| PIO1 | Same. |

### Constraints

- Each PIO block has **4 state machines** (SM0–SM3)
- Each PIO block has **32-slot shared instruction memory** (all 4 SMs in a block share this). Both RP2040 and RP2350 have 32 slots per block.
- SM can handle up to 32 GPIOs each (RP2040 has 30 physical GPIOs, RP2350 has 48 but only 0–28 are broken out on Pico boards)
- Each SM has a **4×32-bit FIFO in each direction (TX/RX)**, reconfigurable as 8×32 in a single direction via SHIFTCTRL_FJOIN
- Fractional clock divider: 16 integer + 8 fractional bits

### IO Mapping for PIO

```
PIO0_SM0_BASE  = user chosen     PIO0_SM0_JMP_PIN = user chosen
PIO0_SM0_SIDESET = 0-5 bits      PIO0_SM0_EXECCTRL = user chosen
```

All 30 physical GPIOs (GP0–GP29) can be used by any PIO SM on any PIO block. The `OUT` and `SET` instructions can address a contiguous range. `JMP` can test one pin.

### PIO Timing

- SM clock = system clock (usually 125 MHz or up to 270 MHz overclocked)
- Actual usable bit rate depends on instruction count in the PIO loop
- For asynchronous reads (like 33C93 bus): typically 8–15 MHz achievable with a tight loop
- For software-driven protocol: each instruction takes 1 cycle, so a read cycle of `pull(), set(), set(), in_(), push()` is ~5 cycles at 125MHz = 25 MHz theoretical, but realistically 10–15 MHz with GPIO delays

## PIO (Programmable I/O) — RP2350

### Differences from RP2040

| Feature | RP2040 | RP2350 |
|---------|--------|--------|
| PIO blocks | 2 | 3 (PIO0, PIO1, PIO2) |
| State machines | 8 total (4 per block) | 12 total (4 per block) |
| Instruction memory | 32 per block | 32 per block (same as RP2040) |
| FIFO depth | 4×32 TX + 4×32 RX | 4×32 TX + 4×32 RX (same, both joinable to 8×32 one direction) |
| HSTX pairing | No | PIO2 can pair with HSTX peripheral for high-speed serial |
| Boot-time PIO | No | PIO can run from boot ROM for custom flash interfaces |

## Voltage Levels & Logic

| Parameter | Value (RP2040 @ IOVDD=3.3V) | Value (RP2350 @ IOVDD=3.3V) |
|-----------|------------------------------|------------------------------|
| GPIO logic level | 3.3V (NOT 5V tolerant) | 3.3V (5V tolerant when powered) |
| Input high threshold VIH | ≥ 2.0V (min) | ≥ 2.0V (min) |
| Input low threshold VIL | ≤ 0.8V (max) | ≤ 0.8V (max) |
| Output high VOH | ≥ 2.62V (min) | — (see RP2350 datasheet) |
| Output low VOL | ≤ 0.5V (max) | — (see RP2350 datasheet) |
| Input hysteresis (Schmitt) | 0.2V (typ) | — |
| Drive strength | 2, 4, 8, 12 mA (configurable per pin) | Same |
| Pull-up | 50–80 kΩ (software on/off) | Same |
| Pull-down | 50–80 kΩ (software on/off) | Same |

**5V tolerance: critical difference between boards**
- **RP2040 (Pico / Pico W)**: GPIOs are **NOT 5V tolerant**. Absolute maximum voltage at any IO pin is IOVDD + 0.5V (= 3.8V at 3.3V IOVDD). The "(FT)" label on GPIOs refers to ESD protection level (4kV HBM vs 2kV standard), **not** 5V input tolerance.
- **RP2350 (Pico 2 / Pico 2 W)**: **ALL GPIOs are 5V tolerant** (FT type). Absolute max for FT pins when IOVDD=3.3V is **VPIN_FT = -0.5V to 5.5V** (RP2350 datasheet Table 1433). Condition: IOVDD must be **present/powered** for voltages above 3.63V. When unpowered (IOVDD=0V), failsafe max is 3.63V (prevents back-powering the chip).

Direct quote from RP2350 datasheet: *"GPIOs are 5 V-tolerant (powered) and 3.3 V-failsafe (unpowered)"*
Direct quote from RP2350 absolute maximum ratings: *"Voltage at IO (FT) ... IOVDD=3.3V: -0.5 to 5.5V"*

The AM33C93A operates at 5V. **For RP2350/Pico 2 W, inputs accept 5V directly.** For RP2040/Pico W, level shifting is required for ALL connections.

## Level Shifting Required for AM33C93A Interface

The AM33C93A is a 5V device, **but its inputs are TTL-compatible, not
5V-CMOS**: the AMD datasheet states "All inputs and outputs are TTL
compatible" and the WD33C93A DC characteristics table specifies
**V_IH = 2.0 V min for all inputs (including CLK)**. A 3.3V Pico output
(V_OH ≥ 2.62 V on RP2040) therefore drives every 33C93A input directly
with ≥ 0.6 V of margin — **the 3.3V→5V direction never needs a
shifter, on either board.** Use 8 mA drive strength + fast slew on CLK
and the strobes.

| Direction | RP2040 Pico / Pico W | RP2350 Pico 2 / Pico 2 W |
|-----------|---------------------|-------------------------|
| Pico → AM33C93A input (CS, WE, RE, A0, D0–D7, MR, CLK, DACK) | **Not required** — TTL-compatible inputs, V_IH 2.0V | **Not required** — same |
| AM33C93A → Pico input (D0–D7, DP, INTRQ, DRQ) | **Required** — 5V→3.3V (74LVC245 / 74LVC8T245) | **Not required** — RP2350 FT GPIOs accept 5V directly (up to 5.5V, powered) |
| Bidirectional data bus (D0–D7) | One dual-supply transceiver (74LVC8T245, DIR from RE̅) covers the read direction | **Direct connection** |

**Recommendation for RP2040 (Pico W):** one 74LVC8T245 on D0–D7 (5V→3.3V
protection when the chip drives) + 5V→3.3V handling on INTRQ/DRQ/RST
(spare LVC gates or dividers). No 3.3V→5V parts.
**Recommendation for RP2350 (Pico 2 W):** **zero glue chips** — wire the
header straight to the Pico 2.

## Minimum Host Interface for AM33C93A

The 33C93A needs at minimum these Pico GPIOs to operate in programmed I/O mode:

### Essential (directly wired)

| Signal | Pico GPIO | Direction | Notes |
|--------|-----------|-----------|-------|
| D0–D7 | 8 GPIOs (bidirectional) | Bidir | Needs level-shifted data bus |
| A0 | 1 GPIO | Pico→33C93 | Register select (0=control, 1=data) |
| CS | 1 GPIO | Pico→33C93 | Chip select (active low) |
| RE | 1 GPIO | Pico→33C93 | Read enable (active low) |
| WE | 1 GPIO | Pico→33C93 | Write enable (active low) |
| ALE | — | — | Address latch enable. For a separate-A0 (indirect addressing) design, **tie to GND** (WD33C93A datasheet §6.2.2) — the h4rm0n1c board grounds it on-PCB, so no GPIO needed |
| INTRQ | 1 GPIO | 33C93→Pico | Interrupt request (active high) |
| ~CLK | 1 GPIO or dedicated | Pico→33C93 | Clock input (8–20 MHz per E018 revised spec, can use PWM/PIO to generate) |
| MR | 1 GPIO | Pico→33C93 | Master reset (active low) |

**Total: ~15–17 Pico GPIOs minimum** for programmed I/O, plus 2–4 for handshake monitoring (BSY, REQ, ACK from the SCSI bus side if needed for debug).

### Optional DMA support

| Signal | Pico GPIO | Notes |
|--------|-----------|-------|
| DRQ | 1 GPIO | 33C93→Pico | DMA request (can use IRQ instead) |
| DACK | 1 GPIO | Pico→33C93 | DMA acknowledge (only if using DMA mode) |

In programmed I/O mode (polled DBR), DRQ/DACK must be held **inactive** (errata E024). For Burst-mode DMA transfers, note that DRQ can be an **open-drain output** — the WD timing tables assume a **1 kΩ external pull-up**; the Pico's internal 50–80 kΩ pull is too weak (≈1 µs rise) and will cause burst overruns.

## AM33C93A Clock Generation

The 33C93A needs a clock on pin 8. Options:
- **PWM generator**: RP2040 PWM can produce clock signals on any GPIO. With sysclk=125 MHz, max PWM frequency = 125 MHz / 2 = 62.5 MHz (TOP=1). For 16-20 MHz, use TOP ≈ 3-4 (125 MHz / (3+1) = 31.25 MHz, 125 MHz / (4+1) = 25 MHz) or use fractional divider via PIO for more precision.
- **PIO clock output**: A PIO SM can produce a clock output with `set()` + `set()` toggling.
- **External oscillator**: Dedicated crystal/can for precise SCSI timing.

The 33C93A datasheet specifies CLK as a square wave input. Ranges:
- Am33C93A: 8–20 MHz (Fast SCSI mode requires 16–20 MHz)
- WD33C93: 8–16 MHz
- WD33C93A: max 20 MHz
- WD33C93B: 8–20 MHz
A common choice is 16–20 MHz. The PIO clock divider should be set assuming the SCSI transfer period registers (TPx) will be configured accordingly.

Note: The 33C93A can also run an **internal clock divider** for the SCSI REQ/ACK handshake, making the CLK frequency less critical for logic correctness — it sets the transfer period through register bits TP0–TP5.

## RP2350 (Pico 2) Differences for This Project

| Feature | Pico W (RP2040) | Pico 2 W (RP2350) |
|---------|----------------|-------------------|
| GPIOs usable | 26 (0–28 minus wireless) | 26 (same 40-pin layout) |
| 5V tolerant inputs | **No** (abs max IOVDD+0.5V = 3.8V) | **Yes** (5V tolerant when powered) |
| PIO blocks | 2 | 3 |
| PIO SMs per block | 4 | 4 |
| PIO instructions/block | 32 | 32 (same as RP2040) |
| FIFO depth | 4×32 TX + 4×32 RX (joinable) | Same |
| Core | M0+ (single-cycle multiply, no hardware divide) | M33 (DSP, FPU, SIMD) or Hazard3 RISC-V |
| SRAM | 264 KB | 520 KB |
| OTP | No | 8 KB OTP for key storage |
| Hardware crypto | No | SHA-256 accelerator, TRNG |
| USB | USB 1.1 | USB 1.1 |
| Security | None | Boot signing, bus filtering, fault injection mitigation, OTP key storage |
| GPIO 5V tolerance | No | Yes |
| WiFi | CYW43439 | CYW43439 (same module) |

## References

- RP2040 Datasheet: Section 1.4 (Pinout), Section 3 (PIO), Section 4 (Peripherals)
- RP2350 Datasheet: Section 1.4 (Pinout), Section 3 (PIO-2), Section 4 (Peripherals)
- Pico W Pinout Diagram: `PicoW-pinout-diagram.pdf`
- Pico 2 W Pinout Diagram: `Pico2W-pinout-diagram.pdf`
