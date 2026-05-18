# Device Identify Quirks Reference

Internal reference for the Find Device / 🔆 Identify feature. Documents per-vendor pairing/reset thresholds we must NOT trip, and per-integration native identify primitives we should PREFER over generic toggle patterns. Authoritative source for `lib/identify_capability.py` thresholds + the v1.10.12 vendor-aware identify roadmap.

Last updated: 2026-05-18 (v1.10.9 ship).

---

## Vendor pairing / factory-reset thresholds

If our identify pattern crosses any of these, the user's device factory-resets mid-search.

| Vendor                | Reset trigger                                      | Mitigation                                                               |
|-----------------------|----------------------------------------------------|--------------------------------------------------------------------------|
| **Tuya / Smart Life** | 3× on/off within 10 s (some models 6× off-on)      | Never 3+ power cycles. Use BRIGHTNESS_WIGGLE for dimmable bulbs.         |
| **Aqara / Xiaomi**    | 5× toggles in 5 s (hard-wired switches); 5× on/off (bulbs) | 2-toggle slow strobe stays under.                                |
| **Philips Hue**       | 5× off/on within ~10 s puts bulb in search mode    | Native flash via `light.turn_on flash: short` always supported.          |
| **IKEA Trådfri**      | 6× off/on within ~10 s (sometimes 4×)              | Identify cluster supported via Z2M/ZHA — use flash.                      |
| **Sengled**           | 10× off/on rapid                                   | Far above any pattern we'd produce. Still cap at 2 toggles.              |
| **LIFX (WiFi)**       | 5× off/on within 5 s (≤2 s each)                   | Native `lifx.effect_*` / flash service preferred.                        |
| **Shelly relays**     | 5× rapid power cycles within 30 s                  | Cap at 2 toggles; long cadence (12 s) keeps aggregate safe.              |
| **Sonoff / Tasmota**  | Usually hold-button only; not toggle-triggered     | Generally safe but cap toggles to avoid relay wear.                      |
| **Z-Wave devices**    | Requires button press / exclusion, NOT toggle      | Use Z-Wave Indicator CC (0x87) for native identify (v1.10.12).           |

### How v1.10.9 stays under all of them

| Method               | Pattern                                | Total cycles / 10 min loop (12 s switch / 6 s media / 5 s light cadence) |
|----------------------|----------------------------------------|---------------------------------------------------------------------------|
| FLASH_LIGHT          | 1× flash service call (no power off)   | n/a (no cycles)                                                           |
| BRIGHTNESS_WIGGLE    | 4× turn_on at varying brightness       | 0 power cycles                                                            |
| STROBE_LIGHT         | 2 toggles in 6 s (3 s apart)           | ~24 toggles over 10 min — below all but Sengled (10× short-window)        |
| SIREN_CHIRP          | 1× turn_on duration=1                  | n/a                                                                       |
| SWITCH_TOGGLE        | 2 toggles in 5 s (2.5 s apart)         | ~20 cycles over 10 min                                                    |

Per-session ceilings (panel-level): max 5 min total, max 30 fires per entity. So worst-case lifetime = 30 × 2 = 60 toggles per switch, spread over 5 min. Below the 100k mechanical-relay endurance figure even if the user runs Find Device daily.

---

## Critical-load deny-list (v1.10.9 `lib/critical_load_keywords.py`)

Categories where the keyword matcher refuses to fire identify at all (admin can't override; entity must be renamed):

- **Medical**: cpap, oxygen, ventilator, dialysis, insulin, incubator, nebulizer
- **HA host (self-destruct prevention)**: homeassistant, ha_host, hass, hassio, haos, supervisor, proxmox, unraid, truenas, raspberry_pi, rpi, intel_nuc
- **Power infra**: server, nas, router, modem, firewall, ups, pdu, rack, synology, qnap
- **Refrigeration**: fridge, freezer, refrigerator, wine_cooler, kegerator, ice_maker
- **Live animals / plants**: aquarium, reptile, terrarium, hatchery, brooder, chicken_coop, grow_light, hydroponic
- **Pumps / climate / safety**: sump_pump, septic, well_pump, boiler, hot_water, water_heater, pool_pump, irrigation
- **EV / high-current**: ev_charger, evse, wallbox, easee, zappi, chargepoint, tesla_charger, tesla_wall
- **Safety / security**: alarm_panel, smoke_detector, co_alarm, water_leak, ip_camera, cctv, dvr, nvr, doorbell, garage_door, gate_motor
- **Solar / battery / generators**: solar_inverter, inverter, generator, powerwall, battery_storage
- **User-labelled**: critical, do_not_toggle, dnt, keep_on, always_on, locked_on, production

Gate applies to `switch.*` and `siren.*` only. Lights / media players bypass because their identify methods don't interrupt power.

---

## Native vendor identify primitives (v1.10.12 backlog)

These should be PREFERRED over generic toggle/strobe when the integration is detected:

| Integration        | Service call                                                | Method                       |
|--------------------|-------------------------------------------------------------|------------------------------|
| ZHA / Zigbee2MQTT  | `zha.issue_zigbee_cluster_command` cluster=0x0003 cmd=0x40  | Effect=blink (Identify cluster) |
| ZHA (alt)          | `mqtt.publish` topic=`zigbee2mqtt/X/set` payload=`{"effect":"blink"}` | Z2M effect attribute    |
| Z-Wave JS          | `zwave_js.invoke_cc_api` cc=Indicator (0x87)                | Z-Wave Indicator CC          |
| LIFX               | `lifx.effect_pulse` mode=blink                              | Native LIFX flash            |
| Yeelight           | `yeelight.start_flow` count=2                               | Native Yeelight flow         |
| WLED               | `wled.preset` preset=identify (if user-configured)          | User-defined preset          |
| Tuya Local         | Brightness only — never strobe                              | BRIGHTNESS_WIGGLE only       |
| ESPHome            | `light.turn_on flash: short` (if firmware exposes)          | Generic flash                |
| Hue (native)       | `light.turn_on flash: short`                                | Bridge handles                |
| Sonos / Cast       | `tts.speak` "Found me" + volume snapshot                    | TTS identify (v1.10.10)      |

---

## Wired switch → smart bulb pair detection (v1.10.10 backlog)

If a smart bulb is downstream of a dumb switch, toggling the switch cuts power to the bulb. User can't tell which one they're locating.

Detection signal: when switch X fires `turn_off`, watch for `state_changed: light.Y { unavailable -> on/off }` within 0-3 s. If correlation present, switch X is wired to light Y.

UX:
- Flag the switch row in Find Device modal: "⚠️ Wired to light.Y — light will flicker too."
- Add an insight: "Smart bulb downstream of dumb switch. Consider replacing switch with a Pico / smart relay that doesn't cut load."

---

## Power-consumption-based critical detection (v1.10.13 backlog)

Keywords miss cryptic device IDs. Real load measurement is authoritative.

Rule: if the entity has a linked power sensor (`sensor.{X}_power` or device-graph energy entity) AND last-10-min mean > 50 W, treat as critical regardless of keyword match.

Catches:
- Refrigerators with name "outlet_4"
- Network gear (PoE switches, modems) labelled by SKU not function
- Aquarium pumps with cryptic Zigbee IDs

Threshold rationale: phone chargers, doorbells, smart-home gear cluster < 10 W idle. Anything > 50 W continuous is doing real work and shouldn't be casually cycled.

---

## Device-graph alternative identifier (v1.10.11 backlog)

For devices that expose BOTH a relay/main-switch AND a diagnostic LED entity, prefer the LED for identify.

Examples:
- Shelly Plus 1: `switch.shelly_plus_1` (relay) + `light.shelly_plus_1_led` (status LED) → use LED
- Tesla Wall Connector: charging relay + multiple status LEDs → use LEDs
- EV chargers (generally): main contactor + indicator light → use indicator
- Sonoff with built-in WiFi LED: relay + LED → use LED

Lookup strategy: WS handler resolves entity → device_id via entity registry → enumerates sibling entities → scores by:
1. `entity_category: diagnostic` (priority 1)
2. Domain `light` (priority 2 — brightness-wiggle is safe)
3. Name contains `led|status|indicator` (priority 3)
4. Original entity (fallback)

When alternative is used, card shows: "Identifying via `light.shelly_plus_1_led` (safer than cycling relay)."

---

## Refs

- Tuya pairing thresholds: https://developer.tuya.com/en/docs/iot/factory-reset
- Hue Identify cluster: Zigbee Cluster Library §3.5, cluster 0x0003
- Z-Wave Indicator CC: SDS13781 spec, command class 0x87
- LIFX HTTP API: https://api.developer.lifx.com/reference/breathe-effect
- Mechanical relay endurance: typical 100k cycles @ rated load, IEC 61810-2
