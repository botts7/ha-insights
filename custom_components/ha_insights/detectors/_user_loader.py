"""User-supplied detector loader with opt-in gate + AST sandbox.

Scans `<config>/ha_insights_detectors/` for *.py files and imports each
in isolation. The module's `@register_detector` decorator handles real
registration; we just provide the import path.

Threat model + mitigations
==========================

User detectors are arbitrary Python that runs with full HA process
privileges. A community-shared detector could read `secrets.yaml`,
exfiltrate over urllib, or fire arbitrary services via `hass.services`.

We mitigate via two gates:

  1. **Opt-in flag.** `CONF_ALLOW_USER_DETECTORS` defaults to False, so
     the loader is a no-op until the user explicitly toggles it on in
     OptionsFlow. Users who don't actively want community detectors
     never run any user code.

  2. **AST forbidden-imports scan.** Even when opt-in, every module is
     parsed and rejected if it imports network / filesystem / subprocess
     / reflection modules. The allowlist is conservative; modules using
     only the standard typing/dataclass/enum/re/math/datetime surface
     plus the HA Insights detector API will pass.

The AST check is best-effort, not a hard sandbox. A determined attacker
could bypass it via `getattr(__builtins__, 'i' + 'mport')` or similar
string-construction tricks. Real isolation requires subprocess
sandboxing, which is out of scope for v1.0. The combination of opt-in
+ allowlist matches the threat model: protect the user from accidental
risk, signal the security model clearly, and document the limitation.

Design notes
============
- Underscore prefix on the filename so the auto-loader in
  `detectors/__init__.py` doesn't try to load THIS file as a detector.
- Per-module try/except so one broken file can't take the rest of the
  integration with it.
- We don't add the user dir to sys.path; we use `spec_from_file_location`
  so the user's module names live in their own namespace and can't
  shadow our built-in detector modules.
- No hot reload. Users restart HA / reload the integration to pick up
  changes. Live reload during a scan would risk torn state in the
  rolling buffer.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


# Modules an honest detector should never need. Network egress, filesystem
# writes, subprocess, code execution, low-level reflection all live here.
# A handful of "looks innocent but enables exfil" entries (json plus
# urllib.request, base64 encoding for binary smuggling) are deliberately
# left out — base64 + json alone aren't dangerous; only their combination
# with one of these modules enables data exfil.
_FORBIDDEN_TOP_LEVEL_MODULES: frozenset[str] = frozenset({
    # Network egress
    "socket",
    "ssl",
    "urllib",
    "urllib3",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "ftplib",
    "smtplib",
    "telnetlib",
    "imaplib",
    "poplib",
    "asyncore",
    # Filesystem writes / shell access
    "os",  # broad — even read access to env is undesirable for detectors
    "shutil",
    "tempfile",
    "subprocess",
    "pty",
    "fcntl",
    "termios",
    "pwd",
    "grp",
    "spwd",
    # Code execution / reflection escape hatches
    "ctypes",
    "cffi",
    "pickle",  # arbitrary code execution on load
    "marshal",
    "shelve",  # uses pickle
    "code",
    "codeop",
    "compile_all",
})


# Names that signal an attempted sandbox escape. AST attribute access
# scanned for these.
_FORBIDDEN_NAMES: frozenset[str] = frozenset({
    "__import__",
    "__builtins__",
    "__loader__",
    "__spec__",
    "eval",
    "exec",
    "compile",
})


def discover_user_detector_files(directory: Path) -> list[Path]:
    """Return *.py files in `directory` (non-recursive), excluding dunders.

    Returns empty list if the directory doesn't exist — that's the common
    case and a no-op is the right behavior. Sorting keeps the load order
    predictable (and so error messages are reproducible).
    """
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file()
        and p.suffix == ".py"
        and not p.name.startswith("_")
    )


def _scan_for_forbidden(source: str, path: Path) -> list[str]:
    """Return a list of human-readable violation messages, empty if clean.

    Walks the AST looking for:
      - import / from-import of any module whose top-level name is in
        _FORBIDDEN_TOP_LEVEL_MODULES
      - use of any name in _FORBIDDEN_NAMES (eval, exec, compile,
        __import__, __builtins__, etc.)

    Falls back to "could not parse" if the module isn't syntactically
    valid — that's a parse-time failure the importer would also reject,
    so we surface a clear rejection rather than letting exec_module die.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"could not parse {path.name}: {exc}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in _FORBIDDEN_TOP_LEVEL_MODULES:
                    violations.append(
                        f"forbidden import {alias.name!r} at line {node.lineno}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".", 1)[0]
                if top in _FORBIDDEN_TOP_LEVEL_MODULES:
                    violations.append(
                        f"forbidden from-import {node.module!r} "
                        f"at line {node.lineno}"
                    )
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                violations.append(
                    f"forbidden name {node.id!r} at line {node.lineno}"
                )
        elif isinstance(node, ast.Attribute):
            # Catch __builtins__.eval, getattr-style escapes are out of
            # scope for AST-only analysis but the obvious attribute
            # patterns are caught here.
            if node.attr in _FORBIDDEN_NAMES:
                violations.append(
                    f"forbidden attribute {node.attr!r} at line {node.lineno}"
                )
    return violations


def load_user_detectors(directory: Path, *, allow: bool = True) -> int:
    """Import every *.py in `directory`. Returns count successfully loaded.

    `allow=False` short-circuits to 0 — used when the user hasn't opted
    in to user-supplied detectors via OptionsFlow. The opt-in gate is
    the primary defense; the AST scan is the second layer.

    Each module is AST-scanned BEFORE import; any forbidden import or
    name is logged + the module is skipped without ever running its
    code. Modules that pass the scan are imported with their
    @register_detector decorators side-effecting into the global
    DETECTORS registry.

    Failures (parse error, import error, anything) are logged but never
    raised — one busted user detector mustn't take the integration
    down.
    """
    if not allow:
        # Quietly do nothing — the call site decides whether to log.
        return 0

    files = discover_user_detector_files(directory)
    if not files:
        return 0

    loaded = 0
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            _LOGGER.warning(
                "HA Insights: could not read user detector %s: %s", path, exc
            )
            continue

        violations = _scan_for_forbidden(source, path)
        if violations:
            _LOGGER.warning(
                "HA Insights: skipping user detector %s — sandbox check "
                "rejected %d violation(s):\n  %s",
                path.name,
                len(violations),
                "\n  ".join(violations),
            )
            continue

        # Module name must be unique enough to avoid colliding with
        # built-in detector names in sys.modules. Prefix with our own
        # namespace marker so a user's `schedule.py` doesn't shadow
        # our built-in ScheduleDetector module.
        mod_name = f"ha_insights_user.{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            _LOGGER.warning(
                "HA Insights: could not build import spec for %s", path
            )
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            _LOGGER.exception(
                "HA Insights: failed to load user detector %s", path
            )
            continue
        loaded += 1
        _LOGGER.info("HA Insights: loaded user detector %s", path.name)
    return loaded


__all__ = [
    "discover_user_detector_files",
    "load_user_detectors",
]
