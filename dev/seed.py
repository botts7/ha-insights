#!/usr/bin/env python3
"""Synthetic state-history seeder for HA Insights dev harness.

Generates backdated state-change events into HA's recorder to simulate
N days of usage. Used for testing detectors (e.g., ScheduleDetector
needs >=7 days of routine data per the charter).

Stub for G1 — implementation lands at critical-path step 9
(ScheduleDetector MVP) when it's first needed.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed HA with synthetic state history"
    )
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--pattern", type=str, default="weekday-routine")
    parser.add_argument("--entity", type=str)
    parser.add_argument("--action", type=str)
    parser.add_argument("--time", type=str)
    args = parser.parse_args()

    print(
        f"seed.py stub — would generate {args.days}d of "
        f"'{args.pattern}' for entity '{args.entity}' "
        f"action '{args.action}' time '{args.time}'"
    )
    print("Implementation lands at critical-path step 9.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
