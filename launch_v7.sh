#!/usr/bin/env bash
# Launch the v7 pass over the 858 directories that still need work.
#
# Run this from a FILE, not inline over ssh: `pkill -f
# "beets_bulk_analyze_v6"` matches any command line containing that
# string, including the shell that is running the pkill. Inline, it
# kills itself before the ledger reset and the launch ever happen.
set -u
CV=/var/lib/docker/volumes/beets-swarm_config/_data
W=/var/tmp/beets-bulk

PAT='beets_bulk_analyze_v6'
pkill -f "$PAT" 2>/dev/null
sleep 4

echo "=== reset the ledgers ==="
# the glob must be expanded BY ROOT - ladmin cannot list the volume
sudo sh -c "rm -f $CV/bulk-analysis.done.v6.shard* $CV/bulk-analysis.failed.v6.shard*"
echo "   done ledger:   $(sudo sh -c "cat $CV/bulk-analysis.done.v6.shard* 2>/dev/null | wc -l")"
echo "   failed ledger: $(sudo sh -c "cat $CV/bulk-analysis.failed.v6.shard* 2>/dev/null | wc -l")"

echo "=== the work list ==="
sudo sh -c "cp /tmp/v7work.list $W/untagged.list"
echo "   $(sudo sh -c "wc -l < $W/untagged.list") directories"

echo "=== launch 3 shards ==="
for S in 0 1 2; do
  sudo setsid nohup /var/tmp/beets_bulk_analyze_v6.sh "$S" 3 >/dev/null 2>&1 &
done
sleep 180
echo "   runners: $(pgrep -fc "$PAT")"
echo "   done:    $(sudo sh -c "cat $CV/bulk-analysis.done.v6.shard* 2>/dev/null | sort -u | wc -l")"
echo "   failed:  $(sudo sh -c "cat $CV/bulk-analysis.failed.v6.shard* 2>/dev/null | wc -l")"
echo "=== the log ==="
sudo grep "VERIFIED\|PARTIAL\|DAMAGED" "$CV/bulk-analysis.log" 2>/dev/null | tail -5 | cut -c1-102
