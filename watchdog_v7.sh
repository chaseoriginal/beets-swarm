#!/usr/bin/env bash
# Watchdog for the v7 analysis pass.
#
# The pass is long (hundreds of albums, and Chroma fingerprinting has
# to decode every file in full, so an MP3 album takes minutes). It has
# to survive:
#   - the Beets container being recreated by the swarm, which kills
#     the runner and loses the per-album databases in /tmp
#   - an SSH disconnect
#
# So it runs from a host crontab, checks that the runner is alive and
# that it is making progress, and relaunches it if it is not. The
# work list and the ledgers are on the HOST, so a relaunch picks up
# exactly where the previous attempt stopped - the runner skips the
# directories already in the done ledger.
#
# Runs every 30 minutes.
set -u
CV=/var/lib/docker/volumes/beets-swarm_config/_data
W=/var/tmp/beets-bulk
PAT='beets_bulk_analyze_v6'
LOG=/var/tmp/beets-bulk/watchdog-v7.log

say() { echo "$(date -Is) $*" >> "$LOG"; }

# how many directories are left?
total=$(sudo sh -c "wc -l < $W/untagged.list" 2>/dev/null | tr -d ' ')
done_n=$(sudo sh -c "cat $CV/bulk-analysis.done.v6.shard* 2>/dev/null | sort -u | wc -l")
failed=$(sudo sh -c "cat $CV/bulk-analysis.failed.v6.shard* 2>/dev/null | wc -l")
say "total=$total done=$done_n failed=$failed"

# if everything is done, stop the watchdog
if [ "${done_n:-0}" -ge "${total:-1}" ]; then
  say "the work list is complete - removing the watchdog"
  crontab -l 2>/dev/null | grep -v 'watchdog_v7.sh' | crontab -
  exit 0
fi

# is the runner alive?
alive=$(pgrep -fc "$PAT")
if [ "${alive:-0}" -lt 1 ]; then
  say "the runner is not running - relaunching"
  for S in 0 1 2; do
    sudo setsid nohup /var/tmp/beets_bulk_analyze_v6.sh "$S" 3 \
      >/dev/null 2>&1 &
  done
  sleep 5
  say "relaunched: $(pgrep -fc "$PAT") processes"
  exit 0
fi

# is it making progress? the log's last VERIFIED line must be recent
last=$(sudo sh -c "grep VERIFIED $CV/bulk-analysis.log 2>/dev/null | tail -1" | cut -d' ' -f1)
if [ -n "$last" ]; then
  age=$(( $(date +%s) - $(date -d "$last" +%s) ))
  say "last VERIFIED $last (${age}s ago)"
  if [ "$age" -gt 3600 ]; then
    say "no progress for over an hour - restarting the runner"
    pkill -f "$PAT"
    sleep 5
    for S in 0 1 2; do
      sudo setsid nohup /var/tmp/beets_bulk_analyze_v6.sh "$S" 3 \
        >/dev/null 2>&1 &
    done
  fi
else
  say "no VERIFIED line in the log yet"
fi
