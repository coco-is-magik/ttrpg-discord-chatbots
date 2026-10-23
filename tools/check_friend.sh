#!/usr/bin/env bash
# Everything about one friend that can be checked without Discord.
#
# The manual half of the procedure is docs/TESTING.md: what to say in the channel, what to expect, and
# which file to blame when it is wrong. This half exists so a content edit or a rebuild can be checked
# in about a minute, before anybody types anything.
#
#   tools/check_friend.sh friend-b
set -uo pipefail

FRIEND="${1:-friend-a}"
cd "$(dirname "$0")/.." || exit 2

PY=".venv/bin/python"
FAILED=0

step() { printf '\n=== %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
fail() { printf '    FAIL: %s\n' "$1"; FAILED=1; }

step "one process"
if pgrep -f 'ttrpg-chatbots-bot' > /dev/null; then
    COUNT=$(pgrep -fc 'ttrpg-chatbots-bot')
    if [ "$COUNT" -gt 1 ]; then
        fail "$COUNT bot processes are running -- two of them means double replies"
    else
        note "running (1 process)"
    fi
else
    note "not running (fine for the offline checks, not for the Discord ones)"
fi

step "the suite"
# No -q: the project already passes it in addopts, and a second one eats the summary line.
if $PY -m pytest > /tmp/check_friend_pytest.log 2>&1; then
    note "$(grep -oE '[0-9]+ passed.*' /tmp/check_friend_pytest.log | tail -1)"
else
    fail "$(grep -oE '[0-9]+ (failed|passed).*' /tmp/check_friend_pytest.log | tail -1)"
fi

step "his material ($FRIEND)"
if $PY -m ttrpg_chatbots.bots.persona_cli "$FRIEND" --quiet > /tmp/check_friend_persona.log 2>&1; then
    note "$(head -1 /tmp/check_friend_persona.log)"
    $PY -m ttrpg_chatbots.bots.persona_cli "$FRIEND" | tail -1 | sed 's/^/    /'
else
    fail "the material does not match the brief:"
    sed 's/^/      /' /tmp/check_friend_persona.log
fi

step "his voice, and every other pinned voice"
if .venv/bin/ttrpg-chatbots-tts --verify-voice > /tmp/check_friend_voice.log 2>&1; then
    sed 's/^/    /' /tmp/check_friend_voice.log
else
    fail "a pinned voice does not match its lock:"
    sed 's/^/      /' /tmp/check_friend_voice.log
    note "restore it with: .venv/bin/ttrpg-chatbots-tts --fetch-voice"
fi

step "what he says to ten ordinary lines"
$PY - "$FRIEND" <<'PY'
import json, sys
from pathlib import Path

from ttrpg_chatbots.bots.identity import bots_from_records
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.style import apply_style

friend = sys.argv[1]
roster = bots_from_records(json.loads(Path("data/bots.json").read_text()), source="data/bots.json")
spec = next(bot for bot in roster if bot.id == friend)
style = spec.persona.style if spec.persona else None

world = load_world(Path("examples/friends_world"))
lines = [
    "hey",
    "what are you up to",
    "why?",
    "thanks",
    "i am nervous about tomorrow",
    "rough day at work",
    "good night",
    "what is the plot of dune?",
]
# his own subjects, so the probe covers what only he knows
for item in world.knowledge:
    if item.owned_by(friend) and any(tag.startswith("topic:") for tag in item.tags):
        lines.append(item.text)
        break

ladder = Ladder(friend=friend, style=style)
for text in lines:
    out = ladder.line(text=text, memory=FriendMemory.load(friend), speaker="tav")
    said = out.text if hasattr(out, "text") else f"(silence: {out.reason})"
    print(f"    {text:34} -> {said}")
PY
if [ $? -ne 0 ]; then
    fail "the probe itself crashed -- the traceback is above"
fi

step "verdict"
if [ "$FAILED" -eq 0 ]; then
    printf '    OK -- now do the Discord half in docs/TESTING.md\n'
else
    printf '    SOMETHING IS WRONG -- see the FAIL lines above\n'
fi
exit "$FAILED"
