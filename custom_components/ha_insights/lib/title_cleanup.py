"""Title-string cleanup helpers — shared between detector emission and WS read.

Pure-string transforms. No HA imports. Tested via
`tests/test_lib_title_cleanup.py`.
"""
from __future__ import annotations

import re

# Trailing call-to-action patterns detectors emit. Stripped on insights
# the conflict scanner already matched to an existing automation —
# keeping the question reads as contradictory when the 🔁 pill already
# says "you've automated this". End-anchored so it can't chew up
# earlier text accidentally.
_ALREADY_AUTOMATED_CTA_RE = re.compile(
    r"\s*(?:Automate\s+(?:this|it)\??|Build\s+automation\??)\s*$",
    re.IGNORECASE,
)

# Cohort dedup appends "(+N similar entities: <merge_label>)" to the
# representative insight's title. When the CTA is followed by this
# suffix, the end-anchored CTA regex no-ops because the title no longer
# ends in the CTA. We detect the suffix, strip the CTA from the prefix
# portion (anchored to end-of-prefix), and rejoin.
_COHORT_SUFFIX_RE = re.compile(
    r"\s*\(\+\d+\s+similar\s+(?:entities|members)[^)]*\)\s*$",
    re.IGNORECASE,
)


def strip_already_automated_cta(title: str) -> str:
    """Drop the trailing CTA from titles whose conflict-scanner status
    indicates the pattern is already automated.

    Handles both:
      - "Build automation? at ~17:27"
        → "at ~17:27"
      - "Build automation? at ~17:27 (+5 similar entities: light.*)"
        → "at ~17:27 (+5 similar entities: light.*)"

    Idempotent and side-effect-free.
    """
    if not title:
        return title

    suffix_match = _COHORT_SUFFIX_RE.search(title)
    if suffix_match:
        prefix = title[: suffix_match.start()]
        suffix = title[suffix_match.start():].lstrip()
        cleaned_prefix = _ALREADY_AUTOMATED_CTA_RE.sub("", prefix).rstrip()
        if not cleaned_prefix:
            return suffix
        return f"{cleaned_prefix} {suffix}"

    return _ALREADY_AUTOMATED_CTA_RE.sub("", title).rstrip()


__all__ = ["strip_already_automated_cta"]
