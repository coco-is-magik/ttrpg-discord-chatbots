"""Command line front end for the LLM backends.

The one useful thing here beyond ``curl`` is the fallback: ``--ask`` wires the model to
the classifier and prints which one actually answered. With no model running and no key
set, that means a warning on stderr and an in-character answer anyway.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ttrpg_chatbots.config import DEFAULT_ENV_FILE
from ttrpg_chatbots.llm import backends, config as llm_config, fallback, wire
from ttrpg_chatbots.llm.http import UrllibTransport
from ttrpg_chatbots.llm.prompt import MAX_CONTEXT_FACTS, persona_from
from ttrpg_chatbots.llm.responder import LlmResponder
from ttrpg_chatbots.llm.types import LlmError, Persona
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.responder import ClassifierResponder
from ttrpg_chatbots.reply.types import Character, ReplyError
from ttrpg_chatbots.respond import Answer

DEFAULT_DATA = Path("examples/demo_world")

LOGGER = logging.getLogger("ttrpg_chatbots.llm.cli")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-llm",
        description="Ask a language model in character, falling back to the classifier.",
    )
    parser.add_argument("--ask", metavar="TEXT", help="the question or line to answer")
    parser.add_argument("--show-config", action="store_true", help="print the resolved config")
    parser.add_argument("--character", help="character id or name (default: the first one)")
    parser.add_argument("--speaker", help="who is being answered; fills {speaker}")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="dataset directory")
    parser.add_argument("--backend", help="local, openai, clinepass or off")
    parser.add_argument("--model", help="model id or ClinePass slug")
    parser.add_argument("--base-url", help="override the API base URL")
    parser.add_argument("--wire", choices=wire.WIRES, help="chat or responses")
    parser.add_argument("--timeout", type=float, default=None, help="request timeout in seconds")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument(
        "--ground",
        action="store_true",
        help="give the model the facts the classifier matched for this question",
    )
    parser.add_argument(
        "--no-fallback", action="store_true", help="fail instead of answering with the classifier"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def _config(args: argparse.Namespace) -> llm_config.LlmConfig:
    """Overrides are folded into the environment mapping, so validation stays in one place."""
    env = dict(os.environ)
    overrides = {
        llm_config.ENV_BACKEND: args.backend,
        llm_config.ENV_MODEL: args.model,
        llm_config.ENV_BASE_URL: args.base_url,
        llm_config.ENV_WIRE: args.wire,
        llm_config.ENV_TIMEOUT: None if args.timeout is None else str(args.timeout),
        llm_config.ENV_MAX_TOKENS: None if args.max_tokens is None else str(args.max_tokens),
        llm_config.ENV_TEMPERATURE: None if args.temperature is None else str(args.temperature),
    }
    for name, value in overrides.items():
        if value is not None:
            env[name] = value
    return llm_config.load_llm_config(env)


def _persona(character: Character) -> Persona:
    """Map a dataset character onto the plain strings the prompt builder needs."""
    return persona_from(character)


def _grounding(replier: Replier, character: Character):
    """Facts for the prompt: the best-matching knowledge this character may know.

    Reusing the classifier's ranking means the model is grounded in exactly the facts
    the tagging system allows, rather than in whatever it remembers about the world.
    """

    def facts(query: str) -> tuple[str, ...]:
        classification = replier.classify(query)
        items = {item.id: item for item in replier.world.knowledge}
        chosen: list[str] = []
        for match in classification.matches:
            item = items.get(match.ref)
            if item is None or not (item.tags & character.known_tags):
                continue
            chosen.append(item.text)
            if len(chosen) >= MAX_CONTEXT_FACTS:
                break
        return tuple(chosen)

    return facts


def _report_config(config: llm_config.LlmConfig, *, as_json: bool) -> int:
    payload = config.describe()
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0
    for name, value in payload.items():
        print(f"{name}: {value}")
    return 0


def _report_answer(
    answer: Answer, character: Character, config: llm_config.LlmConfig, *, as_json: bool
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "text": answer.text,
                    "source": answer.source,
                    "character": character.name,
                    "degraded": answer.degraded,
                    "fallback_reason": answer.fallback_reason,
                    "detail": dict(answer.detail),
                    "config": config.describe(),
                },
                indent=2,
            )
        )
        return 0
    print(f"{character.name}:")
    print(answer.text)
    print(f"source: {answer.source}")
    if answer.degraded:
        print(f"NOTE answered by the fallback: {answer.fallback_reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-llm`` console script."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if DEFAULT_ENV_FILE.exists():
        # Same rule as the Discord token: a real environment variable always wins.
        load_dotenv(DEFAULT_ENV_FILE, override=False)

    try:
        config = _config(args)
    except LlmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.show_config:
        return _report_config(config, as_json=args.json)
    if not args.ask:
        print("error: give --ask or --show-config", file=sys.stderr)
        return 2
    if not config.enabled:
        print(
            "error: the LLM is switched off; unset TTRPG_LLM_BACKEND or set it to "
            "local, openai or clinepass",
            file=sys.stderr,
        )
        return 2
    LOGGER.debug("resolved config: %s", config.describe())

    try:
        world = load_world(args.data)
        character = world.character(args.character or world.characters[0].id)
        replier = Replier(world)
        primary = LlmResponder(
            lambda: backends.build_backend(config, transport=UrllibTransport()),
            _persona(character),
            name=f"llm:{config.backend}",
            context_for=_grounding(replier, character) if args.ground else None,
        )
        answerer = (
            primary
            if args.no_fallback
            else fallback.FallbackResponder(
                primary,
                ClassifierResponder(replier, character.id, speaker=args.speaker),
            )
        )
        answer = answerer.answer(args.ask)
    except (LlmError, ReplyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return _report_answer(answer, character, config, as_json=args.json)

