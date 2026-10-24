#!/usr/bin/env python
"""Read a transcript and say what the room actually did.

Written for the first overnight run, and deliberately opinionated about what matters: a conversation can
look healthy in a log and be a loop of acknowledgements, or look sparse and be three people talking past
each other. So it reports the things that separate those cases --

  * rate and gaps, against the target and against Discord's floor
  * **how much of the conversation is content**: a room where most lines are three words or fewer is a
    room that is technically alive and saying nothing
  * **repetition**, including immediate repeats, which is the shape a loop takes in a transcript
  * **the job mix**, read from the ladder's own trail, which says which rung produced each line
  * **dead ends**: lines nobody picked up

Reads the live transcript (``data/chatter.jsonl``) and the simulator's output, which are the same shape.

    tools/analyse_chatter.py data/chatter.jsonl
    tools/analyse_chatter.py /tmp/week.jsonl --top 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

#: A line this short or shorter carries no content -- "yeah", "ah, oh", "hi".
THIN_WORDS = 3
#: A gap longer than this reads as the room having stopped rather than paused.
DEAD_GAP_MINUTES = 10
#: How long a line may go unpicked-up before it is a dead end.
UNANSWERED_MINUTES = 15


def words(text: str) -> int:
    return len([part for part in text.split() if part.strip("?!.,")])


def load(path: Path) -> tuple[dict, list[dict], list[dict]]:
    """Read a transcript, header and lines. A missing header is fine; a missing file is not."""
    if not path.exists():
        raise SystemExit(f"no transcript at {path}")
    header: dict = {}
    lines: list[dict] = []
    marks: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("kind") == "header":
            header = entry
        elif entry.get("kind") == "start":
            entry["_at"] = datetime.fromisoformat(entry["at"])
            marks.append(entry)
        elif entry.get("text"):
            entry["_at"] = datetime.fromisoformat(entry["at"])
            lines.append(entry)
    if not lines:
        raise SystemExit(f"{path} has no conversation in it yet")
    return header, lines, marks


def percent(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def meaning_pairs(friends: list[dict]) -> list[tuple[str, str, datetime]]:
    """(job, topic, when) for every line whose trail says what kind of thing it was about what.

    The trails are the only place this exists: `job=offer_hook` and `about=topic:trains|` together are the
    *meaning* of a turn, as opposed to its words. Two turns that differ in every word and share a pair are the
    same beat said twice -- which is what a reader notices long before they notice repeated phrasing.
    """
    pairs: list[tuple[str, str, datetime]] = []
    for line in friends:
        trail = line.get("trail") or ""
        if "job=" not in trail:
            continue
        job = trail.split("job=")[1].split(" >")[0].strip()
        topic = ""
        if "about=topic:" in trail:
            topic = trail.split("about=topic:")[1].split("|")[0].strip()
        pairs.append((job, topic, line["_at"]))
    return pairs


def report_meaning(pairs: list[tuple[str, str, datetime]], *, window_hours: float = 6.0) -> None:
    """How often the room says the same *kind* of thing about the same *thing*."""
    if not pairs:
        return
    print("\nrepetition of meaning (job x topic, from the trails)")
    seen: dict[tuple[str, str], datetime] = {}
    first_time = 0
    intervals: list[float] = []
    for job, topic, at in pairs:
        key = (job, topic)
        previous = seen.get(key)
        if previous is None or (at - previous).total_seconds() / 3600 > window_hours:
            first_time += 1
        else:
            intervals.append((at - previous).total_seconds() / 60.0)
        seen[key] = at

    distinct = len({(job, topic) for job, topic, _ in pairs})
    print(f"  {distinct} distinct pairs over {len(pairs)} turns ({percent(distinct, len(pairs)):.0f}%)")
    print(
        f"  first-time in {window_hours:g}h: {first_time} of {len(pairs)} "
        f"({percent(first_time, len(pairs)):.0f}%)"
    )
    if intervals:
        ordered = sorted(intervals)
        print(
            f"  repeat interval: median {statistics.median(intervals):.1f} min, "
            f"shortest {min(intervals):.1f}, longest {max(intervals):.1f}"
        )
        print("  (a median below the length of a session means the room is playing reruns)")
    else:
        print("  nothing was repeated inside the window")


def report(path: Path, *, top: int) -> int:
    header, lines, marks = load(path)
    humans = [line for line in lines if line["speaker"] == "human"]
    friends = [line for line in lines if line["speaker"] != "human"]
    span = (lines[-1]["_at"] - lines[0]["_at"]).total_seconds() / 3600
    gaps = [
        (later["_at"] - earlier["_at"]).total_seconds() / 60
        for earlier, later in zip(lines, lines[1:])
    ]
    lengths = [words(line["text"]) for line in friends]

    print(f"transcript: {path}")
    if header:
        cadence = header.get("cadence", {})
        print(
            f"  from {header.get('at', '?')} at commit {header.get('commit') or 'unknown'}; "
            f"cadence mean {cadence.get('mean_seconds', '?')}s, "
            f"sleep {'on' if header.get('sleep_enabled') else 'off'}"
        )
    print(
        f"  {len(lines)} lines over {span:.1f}h "
        f"({len(lines) / span if span else 0:.1f}/hour), {len(humans)} from the human"
    )

    if marks:
        print("  restarts during the run: " + ", ".join(mark["at"][11:16] for mark in marks))

    print("\nspeakers")
    for speaker, count in Counter(line["speaker"] for line in lines).most_common():
        print(f"  {speaker:10} {count:5d}  {percent(count, len(lines)):5.1f}%")

    print("\ngaps between lines")
    if gaps:
        ordered = sorted(gaps)
        print(
            f"  mean {statistics.mean(gaps):.1f} min, median {statistics.median(gaps):.1f}, "
            f"p90 {ordered[int(len(ordered) * 0.9)]:.1f}, longest {max(gaps):.1f}"
        )
        dead = sum(1 for gap in gaps if gap > DEAD_GAP_MINUTES)
        print(f"  over {DEAD_GAP_MINUTES} min: {dead} ({percent(dead, len(gaps)):.0f}%)")

    print("\ncontent (friends only)")
    print(
        f"  words: median {statistics.median(lengths):.0f}, mean {statistics.mean(lengths):.1f}, "
        f"max {max(lengths)}"
    )
    thin = sum(1 for size in lengths if size <= THIN_WORDS)
    print(
        f"  {THIN_WORDS} words or fewer: {thin} ({percent(thin, len(friends)):.0f}%) "
        f"-- these carry no information"
    )

    print("\nrepetition")
    texts = [line["text"] for line in friends]
    print(f"  distinct: {len(set(texts))} of {len(texts)} ({percent(len(set(texts)), len(texts)):.0f}%)")
    immediate = sum(1 for earlier, later in zip(texts, texts[1:]) if earlier == later)
    print(f"  immediately repeated: {immediate} ({percent(immediate, len(texts)):.0f}%)")
    for text, count in Counter(texts).most_common(top):
        if count > 1:
            print(f"    x{count:<3} {text[:70]}")

    trails = [line.get("trail", "") for line in friends if line.get("trail")]
    if trails:
        print("\njob mix (from the ladder's own trail)")
        jobs = Counter(trail.split("job=")[1].split(" >")[0] for trail in trails if "job=" in trail)
        for job, count in jobs.most_common():
            print(f"  {job:14} {count:5d}  {percent(count, len(trails)):5.1f}%")

    turns: dict[str, list[dict]] = {}
    for line in friends:
        key = line.get("turn") or f"{line['speaker']}@{line['at']}"
        turns.setdefault(key, []).append(line)
    if turns:
        print("\npackaging (how a turn arrived)")
        counts = Counter(len(group) for group in turns.values())
        for size in sorted(counts):
            print(f"  {size} message(s): {counts[size]:5d}  {percent(counts[size], len(turns)):5.1f}%")
        split = sum(count for size, count in counts.items() if size > 1)
        print(f"  split into more than one: {split} of {len(turns)} ({percent(split, len(turns)):.1f}%)")
        if len(counts) == 1:
            print("  every turn arrived the same way -- the packaging is not varying")

    report_meaning(meaning_pairs(friends))

    print(f"\ndead ends (nothing said within {UNANSWERED_MINUTES} min)")
    ends = 0
    for line, later in zip(lines, lines[1:]):
        if (later["_at"] - line["_at"]).total_seconds() / 60 > UNANSWERED_MINUTES:
            ends += 1
            if ends <= 5:
                print(f"    {line['_at']:%H:%M} {line['speaker']}: {line['text'][:60]}")
    print(f"  {ends} of {len(lines)} ({percent(ends, len(lines)):.0f}%)")

    print("\nby hour")
    hours = Counter(line["_at"].hour for line in lines)
    for hour in range(24):
        count = hours.get(hour, 0)
        print(f"  {hour:02d}  {'#' * min(count, 40):40} {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analyse_chatter.py", description="Read a conversation transcript and measure it."
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path("data/chatter.jsonl"))
    parser.add_argument("--top", type=int, default=5, help="how many repeated lines to show")
    args = parser.parse_args(argv)
    return report(args.path, top=args.top)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
