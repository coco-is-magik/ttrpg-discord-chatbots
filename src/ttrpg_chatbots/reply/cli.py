"""Command line front end for the reply engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ttrpg_chatbots.reply import compression
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.types import Classification, ReplyError, World

DEFAULT_DATA = Path("examples/demo_world")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-reply",
        description="Classify text by compression and answer in character. No LLM.",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="dataset directory")
    parser.add_argument("--character", help="character id or name (default: the first one)")
    parser.add_argument("--speaker", help="who is being answered; fills {speaker}")
    parser.add_argument("--compressor", default=compression.DEFAULT, choices=compression.names())
    parser.add_argument("--top-k", type=int, default=5, help="candidates folded into tag scores")
    parser.add_argument("--max-distance", type=float, default=None, help="refuse weaker matches")
    parser.add_argument("--ask", metavar="TEXT", help="answer a question in character")
    parser.add_argument("--classify", metavar="TEXT", help="show the tag ranking only")
    parser.add_argument(
        "--validate", action="store_true", help="check the dataset, print a summary"
    )
    parser.add_argument("--list-characters", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def _report_classification(classification: Classification, *, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "query": classification.query,
                    "compressor": classification.compressor,
                    "tags": [
                        {"tag": score.tag, "distance": round(score.distance, 4), "ref": score.ref}
                        for score in classification.tags
                    ],
                    "matches": [
                        {"ref": match.ref, "distance": round(match.distance, 4)}
                        for match in classification.matches
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"{'tag':<24}{'distance':>10}  best item")
    for score in classification.tags:
        print(f"{score.tag:<24}{score.distance:>10.4f}  {score.ref}")
    return 0


def _report_world(world: World, *, as_json: bool) -> int:
    coverage = []
    for character in world.characters:
        per_tag = {
            tag: sum(
                1
                for template in world.responses
                if tag in template.tags
                and template.character in {character.id, "*"}
            )
            for tag in sorted(character.known_tags)
        }
        coverage.append(
            {
                "character": character.id,
                "name": character.name,
                "known_tags": sorted(character.known_tags),
                "templates": per_tag,
                "tags_without_templates": sorted(
                    tag for tag, count in per_tag.items() if not count
                ),
            }
        )
    unknown_by_all = sorted(
        tag for tag in world.tags if not any(tag in who.known_tags for who in world.characters)
    )
    if as_json:
        print(
            json.dumps(
                {
                    "world": world.name,
                    "knowledge": len(world.knowledge),
                    "responses": len(world.responses),
                    "tags": sorted(world.tags),
                    "characters": coverage,
                    "tags_known_by_nobody": unknown_by_all,
                },
                indent=2,
            )
        )
        return 0

    print(f"world: {world.name}")
    print(f"knowledge: {len(world.knowledge)} items across {len(world.tags)} tags")
    print(f"responses: {len(world.responses)} templates")
    for row in coverage:
        print(f"  {row['character']:<12}{row['name']}")
        print(f"    knows: {', '.join(row['known_tags']) or 'nothing'}")
        if row["tags_without_templates"]:
            print(f"    WARNING no template for: {', '.join(row['tags_without_templates'])}")
    if unknown_by_all:
        print(f"WARNING knowledge tagged for nobody: {', '.join(unknown_by_all)}")
    return 0


def _report_reply(reply, world: World, *, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "text": reply.text,
                    "character": reply.character,
                    "character_name": world.character(reply.character).name,
                    "tag": reply.tag,
                    "knowledge_id": reply.knowledge_id,
                    "template_id": reply.template_id,
                    "distance": None if reply.distance is None else round(reply.distance, 4),
                    "known": reply.known,
                },
                indent=2,
            )
        )
        return 0

    origin = f"{reply.tag} via {reply.knowledge_id}" if reply.tag else "no knowledge"
    distance = "" if reply.distance is None else f", d={reply.distance:.3f}"
    state = "" if reply.known else " (deflected)"
    print(f"{world.character(reply.character).name} [{origin}{distance}{state}]:")
    print(reply.text)
    return 0


def _list_characters(world: World, *, as_json: bool) -> int:
    rows = [
        {"id": character.id, "name": character.name, "known_tags": sorted(character.known_tags)}
        for character in world.characters
    ]
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        print(f"{row['id']:<12}{row['name']:<28}{len(row['known_tags'])} tags")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-reply`` console script."""
    args = _parse_args(argv)

    try:
        world = load_world(args.data)
        replier = Replier(
            world,
            compressor=compression.get(args.compressor),
            top_k=args.top_k,
            max_distance=args.max_distance,
        )
    except (ReplyError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.validate:
        return _report_world(world, as_json=args.json)
    if args.list_characters:
        return _list_characters(world, as_json=args.json)
    if not args.ask and not args.classify:
        print(
            "error: give one of --ask, --classify, --validate or --list-characters",
            file=sys.stderr,
        )
        return 2

    try:
        if args.classify:
            return _report_classification(replier.classify(args.classify), as_json=args.json)
        character = args.character or world.characters[0].id
        reply = replier.reply(args.ask, character, speaker=args.speaker)
        return _report_reply(reply, world, as_json=args.json)
    except (ReplyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
