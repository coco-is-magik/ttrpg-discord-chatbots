"""``ttrpg-chatbots-persona``: read the report, or check one friend's material.

A report is for a person deciding whether to edit content; the exit code is for a script. Both matter:
the suite asserts the report passes, and this is how you read the numbers behind that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ttrpg_chatbots.bots.persona import PersonaError
from ttrpg_chatbots.bots.persona_harness import measure


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-persona",
        description="Check a friend's material against the brief, and report the numbers.",
    )
    parser.add_argument("friend", nargs="?", default="friend-a", help="bot id (default: friend-a)")
    parser.add_argument(
        "--data", type=Path, default=Path("examples/friends_world"), help="world directory"
    )
    parser.add_argument(
        "--roster", type=Path, default=Path("examples/bots.example.json"), help="bot roster"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--quiet", action="store_true", help="only the verdict and the failures"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = measure(args.friend, data=args.data, roster=args.roster)
    except (PersonaError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "friend": report.friend,
                    "ok": report.ok,
                    "stats": report.stats,
                    "findings": [
                        {
                            "check": finding.check,
                            "question": finding.question,
                            "ok": finding.ok,
                            "evidence": list(finding.evidence),
                        }
                        for finding in report.findings
                    ],
                },
                indent=2,
            )
        )
        return 0 if report.ok else 1

    if args.quiet:
        print("PASS" if report.ok else "FAIL")
        for finding in report.failures:
            print(finding.describe())
        return 0 if report.ok else 1

    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
