# Walking find for Zigbee / Z-Wave — hardware paths

## TL;DR

Live walking find ("warmer/colder" UX) for Zigbee/Z-Wave devices
**cannot work on a stock phone** — phones don't have Zigbee or
Z-Wave radios. The architecture HA Insights uses for BLE
(phone scans advertisements) and Wi-Fi (phone reads its own AP
RSSI, or APs report client RSSI) does not translate.

What's left if a user wants the UX anyway: **carry a mobile
device that participates in the Zigbee/Z-Wave network and
streams per-neighbor link quality to HA over Wi-Fi.**

HA Insights itself will not ship hardware. This doc captures
the hardware recipes a community contributor could build today.

## Tier 1 — Pi Zero 2 W + Zigbee dongle (works today)

Off-the-shelf parts, ~1 hour assembly, well-trodden HA community
path.

| Part | Notes | ~Cost (USD) |
|---|---|---|
| Raspberry Pi Zero 2 W | Cheapest viable SBC with Wi-Fi | $15 |
| Sonoff Zigbee 3.0 USB Dongle Plus (`ZBDongle-P`, CC2652P) | OR ConBee III / SLZB-06 | $20 |
| microSD card (8 GB+) | Class 10 | $5 |
| PiSugar 2 / 3 LiPo HAT | Battery + charger + power button | $20 |
| USB-C cable for charging | | $3 |
| **Total** | | **~$60** |

**Firmware**: standard Z2M / ZHA configured as a Zigbee router.
The mesh sees it as just another router. As the carrier walks,
every target device's LQI **to this router** updates.

**Mode of operation**:
- The Pi joins your existing Z2M network (don't form a new one).
- Z2M exposes per-device `linkquality` to MQTT.
- HA Insights subscribes to LQI updates from this specific router
  and smooths them server-side (mirrors `wifi_find_self` EMA path).
- Card shows warmer/colder as the user walks with the Pi in hand.

**Battery life**: 2-4 hours on the PiSugar 2 — plenty for a find
session.

## Tier 2 — ESP32-C6 native (the cleaner future)

The ESP32-C6 has Wi-Fi 6 **and** 802.15.4 on-chip. No daughterboard.
Genuinely pocket-sized.

| Part | Notes | ~Cost (USD) |
|---|---|---|
| ESP32-C6 dev board | e.g. ESP32-C6-DevKitC-1 | $8-10 |
| 18650 cell + holder + LiPo charger module | TP4056 + boost is fine | $5-7 |
| Optional case | 3D-print or repurpose | $0-5 |
| **Total** | | **~$15-20** |

**Firmware**: ESPHome's `esp-zigbee` component (built on
Espressif's ESP-Zigbee SDK).

**Reality check (as of 2026-05)**: the ESPHome component ships
**end-device** patterns (ESP32 acting as a Zigbee sensor that joins
your network). Running it as a **router** with per-neighbor LQI
exposed over the existing ESPHome native_api → HA path is
possible with the underlying SDK but **not turnkey in ESPHome
today**. 6-12 months out before this is a copy-paste recipe.

When it's ready, this is the right hardware. Until then, Tier 1.

## Tier 3 — Z-Wave (Pi-only, no ESP path)

Z-Wave silicon is proprietary to Silicon Labs (ZG23 family).
**No open MCU implements Z-Wave** and no ESP equivalent will
ever exist.

| Part | Notes | ~Cost (USD) |
|---|---|---|
| Raspberry Pi Zero 2 W | | $15 |
| Aeotec Z-Stick 7 | Or Zooz ZST10 700 / Silicon Labs UZB-7 | $50 |
| microSD + LiPo HAT + cable | Same as Tier 1 | $30 |
| **Total** | | **~$95** |

Otherwise identical pattern to Tier 1 (Z-Wave JS as the host,
expose per-device RSSI to HA, subscribe from HA Insights).

## Why HA Insights won't ship hardware

Asking 95% of users to buy a Pi before they can use a feature
breaks the value prop. Live Zigbee/Z-Wave find is a low-frequency
need that the Identify primitive (shipped v1.10.12 / v1.12.23)
already covers ergonomically:

> Walk through the house, tap "Identify" on the unfamiliar entity,
> the device flashes/beeps. No signal data required.

For the 5% of users with multiple identically-named devices in
one area (where Identify is ambiguous), this DIY path exists. The
ones who want it badly enough will build it.

## What HA Insights could ship server-side

Independent of any DIY hardware:

**ZigbeeAreaInferenceDetector** — passive LQI→area mapping. ZHA
+ Z2M already expose per-device LQI to the coordinator and to
each router in the mesh. With multiple routers tagged to areas,
the detector can infer "this device lives near router X" from
which router has the highest LQI for it. No live walking; static
inference at scan time. Mirrors the `WifiFindDetector` (v1.18)
pattern.

Useful for the orphan-device area-assign workflow ("I have 47
unassigned Zigbee devices; where do they live?"), NOT for "I
dropped my Aqara button somewhere in the kitchen, find it."

Tracked as task #232.
