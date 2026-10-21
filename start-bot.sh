#!/usr/bin/env bash
#
# Start the TTRPG chatbot Discord bot.
#
#   ./start-bot.sh              run in the foreground (Ctrl-C stops it)
#   ./start-bot.sh --background run detached, logging to data/logs/bot.log
#   ./start-bot.sh --check      validate config and voice support, do not connect
#   ./start-bot.sh --status     is it running?
#   ./start-bot.sh --stop       stop the detached bot
#   ./start-bot.sh --logs       follow the log
#
# Credentials come from .env (or DISCORD_TOKEN / DISCORD_TOKEN_FILE). This script never
# prints the token, and refuses to start if .env could be committed to git.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"
BOT="$VENV/bin/ttrpg-chatbots-bot"
LOG_DIR="$ROOT/data/logs"
LOG="$LOG_DIR/bot.log"
PIDFILE="$ROOT/data/bot.pid"

# Files this script creates are private: the log can contain channel names and user
# handles, and the pid file is nobody's business.
umask 077

die() {
    printf 'start-bot: %s\n' "$1" >&2
    exit 1
}

usage() {
    # Print the comment block at the top of this file, stopping at the first real line.
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
}

# The virtualenv was once copied from another checkout, which silently sent installs and
# interpreter lookups to the wrong directory. Refuse to run in that state.
require_sane_venv() {
    [ -x "$PYTHON" ] || die "no virtualenv at $VENV; run: python3 -m venv .venv"
    [ -x "$BOT" ] || die "the bot is not installed; run: .venv/bin/python -m pip install -e ."

    if ! "$PYTHON" - "$ROOT" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
problems = []
if pathlib.Path(sys.prefix).resolve() != (root / ".venv"):
    problems.append(f"interpreter prefix is {sys.prefix}, expected {root / '.venv'}")
import ttrpg_chatbots

package = pathlib.Path(ttrpg_chatbots.__file__).resolve()
if not package.is_relative_to(root / "src"):
    problems.append(f"imported {package}, expected a file under {root / 'src'}")
if problems:
    print("\n".join(problems), file=sys.stderr)
    raise SystemExit(1)
PY
    then
        die "the environment does not match $ROOT (recreate: rm -rf .venv && python3 -m venv .venv)"
    fi

    if [ -n "${VIRTUAL_ENV:-}" ]; then
        if [ "$(readlink -f "$VIRTUAL_ENV")" != "$(readlink -f "$VENV")" ]; then
            printf 'start-bot: warning: VIRTUAL_ENV is %s, not this project\n' \
                "$VIRTUAL_ENV" >&2
            printf 'start-bot: using %s anyway (the script never relies on activation)\n' \
                "$VENV" >&2
        fi
    fi
}

# A secret in the repository is a leak forever; refuse to be the tool that did it.
require_secret_hygiene() {
    if [ -f "$ROOT/.env" ]; then
        command -v git >/dev/null 2>&1 || return 0
        if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
            return 0
        fi
        if git -C "$ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
            die ".env is tracked by git; run: git rm --cached .env  (and rotate the token)"
        fi
        if ! git -C "$ROOT" check-ignore -q .env; then
            die ".env is not git-ignored; fix .gitignore before putting a token in it"
        fi
    fi
}

running_pid() {
    [ -f "$PIDFILE" ] || return 1
    local pid
    pid=$(cat "$PIDFILE" 2>/dev/null || true)
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    printf '%s\n' "$pid"
}

# Every process running this bot, not just the one the pid file knows about.
#
# The pid file was not enough: a foreground run left behind by a closed terminal kept a full set
# of gateway connections alive, and two processes sharing one token fight over the session and
# both answer the same message. The user sees double replies; the log, written by both, looks
# almost normal. So the script asks the process table instead of trusting one file.
all_pids() {
    {
        running_pid || true
        pgrep -f -- "$BOT" 2>/dev/null || true
    } | sort -u | while read -r pid; do
        [ -n "$pid" ] || continue
        kill -0 "$pid" 2>/dev/null && printf '%s\n' "$pid"
    done
}

require_single_process() {
    local pids
    pids=$(all_pids || true)
    [ -n "$pids" ] || return 0
    printf 'start-bot: already running (pid%s %s); stop it first: ./start-bot.sh --stop\n' \
        "$(printf '%s' "$pids" | wc -l | grep -qx 1 || printf 's')" \
        "$(printf '%s' "$pids" | tr '\n' ' ')" >&2
    exit 1
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --check)
        require_sane_venv
        require_secret_hygiene
        exec "$BOT" --check
        ;;
    --status)
        pids=$(all_pids || true)
        if [ -z "$pids" ]; then
            printf 'not running\n'
            exit 1
        fi
        count=$(printf '%s\n' "$pids" | wc -l)
        printf 'running (%s process%s: pid %s), logging to %s\n' \
            "$count" "$([ "$count" -eq 1 ] && printf '' || printf 'es')" \
            "$(printf '%s' "$pids" | tr '\n' ' ')" "$LOG"
        if [ "$count" -gt 1 ]; then
            printf 'WARNING: several processes are using the same tokens. That is what produces double replies; run ./start-bot.sh --stop\n' >&2
        fi
        exit 0
        ;;
    --stop)
        pids=$(all_pids || true)
        if [ -z "$pids" ]; then
            rm -f "$PIDFILE"
            printf 'not running\n'
            exit 0
        fi
        for pid in $pids; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        for _ in $(seq 1 20); do
            still=$(all_pids || true)
            [ -n "$still" ] || break
            sleep 0.25
        done
        for pid in $(all_pids || true); do
            kill -KILL "$pid" 2>/dev/null || true
        done
        rm -f "$PIDFILE"
        printf 'stopped (pid %s)\n' "$(printf '%s' "$pids" | tr '\n' ' ')"
        exit 0
        ;;
    --logs)
        [ -f "$LOG" ] || die "no log yet at $LOG"
        exec tail -n 50 -f "$LOG"
        ;;
    -d|--background)
        require_sane_venv
        require_secret_hygiene
        require_single_process
        mkdir -p "$LOG_DIR"
        printf '\n=== %s starting ===\n' "$(date -Iseconds)" >> "$LOG"
        nohup "$BOT" >> "$LOG" 2>&1 &
        pid=$!
        printf '%s\n' "$pid" > "$PIDFILE"
        sleep 2
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PIDFILE"
            printf 'start-bot: the bot exited immediately; last lines of %s:\n' "$LOG" >&2
            tail -n 20 "$LOG" >&2
            exit 1
        fi
        printf 'started (pid %s)\nlog:  %s\nstop: %s\n' \
            "$pid" "$LOG" "./start-bot.sh --stop"
        exit 0
        ;;
    "")
        require_sane_venv
        require_secret_hygiene
        exec "$BOT"
        ;;
    *)
        die "unknown argument: $1 (try --help)"
        ;;
esac
