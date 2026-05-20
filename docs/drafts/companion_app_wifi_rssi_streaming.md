# HA Companion App: Wi-Fi RSSI streaming for "find my device" UX

**Status:** Draft. Sibling to the existing BLE-active-scan feature
request. Reference architecture lives in HA Insights v1.18–v1.21.x
and the find-my-ha PWA v0.7.x.

## Problem

Home Assistant has scattered identification primitives (`light.flash`,
companion "Ring my phone") but **no unified "find any entity"
walking warmer/colder UX**. The find-my-ha PWA + HA Insights
custom integration prove the architecture works end-to-end for two
device classes:

- **BLE-trackable devices** (Hue, AirTag, BTHome, BLE locks):
  PWA reads BLE advertisements via Web Bluetooth, streams RSSI
  samples to HA, smoothed + bucketed warmer/colder UI works.
- **Wi-Fi-trackable devices on UniFi / Omada / Mikrotik / similar
  controller installs**: HA Insights subscribes to the controller's
  per-client signal sensor, streams as the user walks.

**Gap**: installs without a controller integration (Asuswrt stock,
DD-WRT, FritzBox-but-no-RSSI, plain DHCP-based trackers, ~60-70%
of HA users by various counts) have **no walking-find for Wi-Fi
devices**. Phones, tablets, IoT-on-Wi-Fi all become unfindable.

## What we need from the Companion app

A foreground-streaming WiFi RSSI sensor with two modes:

### Passive mode (default — already mostly exists)
The Android Companion app has an "auto sensor" called
**WiFi Signal Strength**. Today it updates at the standard sensor
interval (~minutes). Useful for room-of-house inference but too
slow for walking find.

**Ask**: nothing more than the existing sensor — keep as-is for
the steady-state case.

### Active mode (the missing primitive)
While a "find" session is active in HA Insights / find-my-ha:
- Companion subscribes to a server-side event saying "find session
  for entity `device_tracker.alice_phone` started"
- Companion responds by polling Wi-Fi signal at **1-2 Hz** for the
  duration of the session
- Each sample is reported through the existing
  `home_insights/wifi_find_self` WS contract (already defined +
  shipped in HA Insights v1.21.0)
- Companion stops polling when the session ends or app backgrounds

**Why active mode is needed**: walking warmer/colder needs at
least 1 Hz updates to feel responsive. UniFi controller cadence
(10-30 s) is already painful; the default Companion sensor
cadence (~minutes) is unusable.

## Existing architecture (reference implementation)

```
Find-my-ha PWA               HA Insights                    HA Companion
                                                            (the proposed addition)
  ┌──────────────┐           ┌──────────────────────┐      ┌─────────────────┐
  │  pick phone  │           │                      │      │                 │
  │  pick target │           │  ws_wifi_find_self   │      │  WiFi sensor    │
  └──────┬───────┘           │  ─────────────────   │      │  reads RSSI     │
         │                   │                      │      │  at 1-2 Hz      │
         │  subscribe        │  collects sister     │      │  during a       │
         ├──────────────────►│  entity attrs        │◄─────│  find session   │
         │                   │  via _collect_       │      │                 │
         │                   │  device_state_attrs  │      └─────────────────┘
         │  RSSI events      │                      │
         │◄──────────────────┤  ema-smoothed        │
         │                   │  forwarded to PWA    │
         │  warmer/colder    │                      │
         │  rendering        └──────────────────────┘
```

The Companion app drops into the boxed slot above. No HA Insights
changes needed — the WS handler already accepts state-changes from
any entity on the device.

## Concrete asks (in priority order)

1. **Expose existing "WiFi Signal Strength" auto sensor at higher
   cadence during a foreground HA session** — minimum 1 Hz, ideally
   2-4 Hz. Today: ~minute cadence.
2. **Subscribe to a "find session active" event from HA** so the
   Companion can switch into the higher-cadence mode only during a
   walk and revert to default otherwise (battery cost). Event name
   suggestion: `home_insights/find_session` with `{entity_id,
   started: bool}` payload.
3. **Expose BSSID (which AP the phone is associated with) as a sensor**
   so the v1.18 area-inference detector has the data it needs. Today
   Android exposes `WifiInfo.getBSSID()` privately; should be a sensor.

## Why this serves HA core, not just one custom integration

The proposed primitive is "Wi-Fi RSSI streamed from the device at
session cadence." Many use cases land downstream:

- **Find my device** — the obvious one.
- **Hyper-local presence detection** — "phone signal strength to
  the kitchen AP > -50 dBm" → user is in the kitchen, no PIR sensor
  needed.
- **Roaming health diagnostic** — "phone keeps re-associating with
  the wrong AP" → home-network owner can see the data.
- **Path planning for robot vacuums** — RSSI gradient across a
  floor is a cheap signal for "where in the house is the dock."

## What I'm bringing to the conversation

- **Working architecture**: the HA Insights side of the contract
  is shipped + documented. Reference implementation in
  https://github.com/botts7/ha-insights/blob/main/custom_components/ha_insights/ws_api/wifi_find_self.py
- **Working UX**: find-my-ha PWA at
  https://botts7.github.io/find-my-ha/ wires everything end-to-end.
  Source: https://github.com/botts7/find-my-ha
- **A community-released PWA proving the demand** — happy to point
  at metrics when there's enough user data.

## Sibling proposal

This is the Wi-Fi sibling of the BLE active-scan ask. Both share
the same architectural pattern (find session event → device-side
scanner pumps RSSI at higher cadence → HA Insights smooths +
renders). File together as a single Companion-app issue covering
both? Or as separate-but-cross-linked? Open to maintainer
preference.

## Not asking for

- iOS support. (Apple's WebKit / Wi-Fi privacy model makes this
  much harder. Android-first is fine.)
- Background scanning. (Battery and Android-9+ scan limits
  preclude this. Foreground session only.)
- HA core changes. (The handler + smoothing already exists in
  HA Insights. Companion just needs to push samples.)
