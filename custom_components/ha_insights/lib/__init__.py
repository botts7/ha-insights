"""HA-Insights pure-logic helpers.

Modules in this package have ZERO `homeassistant` imports. Pure
functions, easily testable from a standard Python environment.
The integration's ws_api / detectors are responsible for the HA
glue (registry walks, store I/O); they call into these helpers
for the actual data shaping.
"""
