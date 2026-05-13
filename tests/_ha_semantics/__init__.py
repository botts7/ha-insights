"""HA-semantics fixtures.

Each module here synthesizes a state_changed event stream that mimics
what real HA produces for a specific scenario (bootstrap fan-out,
group toggle, scene activation, etc.). Detectors are then run against
the fixture to assert they don't false-positive on the scenario.

Sourced from direct reading of homeassistant/core at
`C:\\Users\\botts\\homeassistant-core` — see
`docs/HA_EVENT_SEMANTICS.md` for the ground-truth document each
fixture is derived from.
"""
