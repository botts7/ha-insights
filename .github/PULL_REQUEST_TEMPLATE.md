<!-- Thanks for the PR! Quick checklist below — if everything is green this lands fast. -->

## What this changes

<!-- One paragraph. The "why" matters more than the "what" — the diff shows the what. -->

## How to verify

<!-- A reviewer should be able to follow these steps and see the change works. -->

- [ ] Step 1: …
- [ ] Step 2: …

## Conventions checklist

- [ ] **Surgical diff** — every changed line traces to the description above. No drive-by refactors / style churn in unrelated files.
- [ ] **Tests added or updated** — pure logic → `tests/test_lib_*.py`, integration-shape checks → `tests/_smoke_v1_4_x.py`. New detector? Add an end-to-end smoke case.
- [ ] **Tests pass locally**:
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --noconftest tests/test_lib_*.py`
  - `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python tests/_smoke_v1_4_x.py`
- [ ] **CHANGELOG bumped** under `## [Unreleased]` if the change is user-visible (new feature, fixed bug, changed behavior). Pure refactors with no observable behavior change can skip.
- [ ] **manifest.json version bumped** only if this PR is itself the release (otherwise leave for the maintainer).
- [ ] **No hardcoded credentials / IPs / tokens** — privacy contract is a hard rule.
- [ ] **CPU loops over user-scale data yield** (`await asyncio.sleep(0)`) so the HA event loop isn't starved.

## Related issue / discussion

Closes #…  (or "n/a — drive-by polish")

<!--
The full conventions live in CLAUDE.md at the repo root.
The pre-merge `/ultrareview` pass against `main` typically flags anything missed here.
-->
