"""LLM cost estimator — bytes -> tokens -> USD per outbound call.

Audit-log rows carry `bytes_sent` and `bytes_received` already. This
module derives token counts and a cents-level USD estimate at read
time so we don't need a schema migration to surface costs.

The numbers are intentionally rough — we don't see the prompt server-side
once it's redacted, so we use the byte-stream length and the standard
"~4 chars per token" English heuristic. Cloud pricing comes from public
list prices as of 2026-05; local agents always report $0.

`source` on the returned dict tells the UI whether to label the figure
as "estimate" (known agent), "rough estimate" (unknown agent fell back
to the default rate), or "free / local" (no network egress).
"""
from __future__ import annotations

from dataclasses import dataclass

from .privacy_log import derive_agent_locality

# Conventional rule-of-thumb for English text. Anthropic / OpenAI /
# Google all hover around 3.5-4.5 chars/token. We use 4 as the median;
# the resulting estimate is within +/-15% for typical prompts.
_CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class _Price:
    """USD per million tokens for input + output."""

    in_per_mtok: float
    out_per_mtok: float


# Public list prices as of 2026-05. The keys are substring markers tested
# against the lowercased agent_id — first match wins. Missing model
# names fall back to the default "any-cloud" rate.
_PRICING: dict[str, _Price] = {
    # Anthropic
    "claude-opus-4": _Price(in_per_mtok=15.0, out_per_mtok=75.0),
    "claude-sonnet-4": _Price(in_per_mtok=3.0, out_per_mtok=15.0),
    "claude-haiku-4": _Price(in_per_mtok=1.0, out_per_mtok=5.0),
    "claude-3-5-sonnet": _Price(in_per_mtok=3.0, out_per_mtok=15.0),
    "claude-3-5-haiku": _Price(in_per_mtok=0.8, out_per_mtok=4.0),
    "anthropic": _Price(in_per_mtok=3.0, out_per_mtok=15.0),  # generic Sonnet-tier
    # OpenAI
    "gpt-4o-mini": _Price(in_per_mtok=0.15, out_per_mtok=0.6),
    "gpt-4o": _Price(in_per_mtok=2.5, out_per_mtok=10.0),
    "openai": _Price(in_per_mtok=2.5, out_per_mtok=10.0),  # generic 4o-tier
    # Google
    "gemini-2-5-pro": _Price(in_per_mtok=3.5, out_per_mtok=10.5),
    "gemini-2-5-flash": _Price(in_per_mtok=0.3, out_per_mtok=2.5),
    "gemini-1-5-pro": _Price(in_per_mtok=3.5, out_per_mtok=10.5),
    "gemini-1-5-flash": _Price(in_per_mtok=0.075, out_per_mtok=0.3),
    "gemini": _Price(in_per_mtok=1.0, out_per_mtok=4.0),  # generic
    "google": _Price(in_per_mtok=1.0, out_per_mtok=4.0),
}

# Fallback for cloud agents we couldn't pin to a known model. Picked to
# approximate a mid-tier Sonnet/4o cost so the user gets a plausible
# upper-bound figure rather than zero.
_DEFAULT_CLOUD_PRICE = _Price(in_per_mtok=3.0, out_per_mtok=15.0)


def _bytes_to_tokens(byte_count: int) -> int:
    if byte_count <= 0:
        return 0
    return max(1, round(byte_count / _CHARS_PER_TOKEN))


def _resolve_price(agent_id: str | None) -> tuple[_Price, str]:
    """Return (price, source). Longest matching substring wins.

    Sorted by key length descending so `claude-opus-4` beats `anthropic`
    when the agent_id mentions both. Source is "exact" when a model-
    family marker matched, "default" when only a vendor marker did,
    and "fallback" when nothing matched but the agent is cloud-classified.
    """
    if not agent_id:
        return _DEFAULT_CLOUD_PRICE, "fallback"
    lowered = agent_id.lower()
    # Vendor-only markers are explicitly listed so adding new model entries
    # to _PRICING never accidentally promotes them to "exact" by length.
    vendor_only = {"anthropic", "openai", "google", "gemini"}
    for marker in sorted(_PRICING.keys(), key=len, reverse=True):
        if marker in lowered:
            source = "default" if marker in vendor_only else "exact"
            return _PRICING[marker], source
    return _DEFAULT_CLOUD_PRICE, "fallback"


def estimate_cost(
    *,
    agent_id: str | None,
    bytes_sent: int,
    bytes_received: int,
    locality: str | None = None,
) -> dict[str, object]:
    """Estimate token counts + USD cost for a single outbound call.

    Returns a dict with:
        tokens_in, tokens_out, cost_usd, source

    Local agents always cost $0.00 and report source="local_free". The
    `locality` argument lets callers pass a pre-computed classification
    when they already have it; otherwise we re-derive from agent_id.
    """
    classified = locality or derive_agent_locality(agent_id)
    tokens_in = _bytes_to_tokens(int(bytes_sent or 0))
    tokens_out = _bytes_to_tokens(int(bytes_received or 0))

    if classified == "local":
        return {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": 0.0,
            "source": "local_free",
        }

    price, source = _resolve_price(agent_id)
    cost_usd = (
        tokens_in * price.in_per_mtok / 1_000_000
        + tokens_out * price.out_per_mtok / 1_000_000
    )
    # Round to four decimals — sub-cent precision is meaningful when a
    # single Refine call costs ~$0.0008.
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 4),
        "source": source,
    }


__all__ = ["estimate_cost"]
