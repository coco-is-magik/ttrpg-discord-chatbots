#!/usr/bin/env bash
# Keep the bot up, so a run that is supposed to produce a dataset produces one.
#
# Two crashes in one week stopped the room mid-run, and an overnight run that dies at 2am is six hours of
# missing data that nobody notices until morning. This checks the process table (not the pid file, which a
# crash leaves stale) and restarts if nothing is running.
#
# Install it once, every ten minutes:
#
#     (crontab -l 2>/dev/null; echo "*/10 * * * * $PWD/tools/watch_bot.sh >> $PWD/data/logs/watchdog.log 2>&1") | crontab -
#
# Or run it by hand whenever you want to be sure.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE" || exit 1

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

running=$(pgrep -fc 'ttrpg-chatbots-bot' 2>/dev/null || echo 0)
if [ "$running" -ge 1 ]; then
    echo "$(stamp) up ($running process(es))"
    exit 0
fi

echo "$(stamp) DOWN -- restarting"
./start-bot.sh -d
sleep 20
after=$(pgrep -fc 'ttrpg-chatbots-bot' 2>/dev/null || echo 0)
if [ "$after" -ge 1 ]; then
    echo "$(stamp) restarted ($after process(es)); the transcript records the gap as a restart marker"
else
    echo "$(stamp) RESTART FAILED -- check data/logs/bot.log"
    exit 1
fi
