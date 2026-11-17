#!/usr/bin/env bash
# Launch the v6 runner shards.
#
# WHY THIS IS A FILE AND NOT AN INLINE COMMAND:
#   `pkill -f "beets_bulk_analyze_v6"` matches ANY process whose
#   command line contains that string - including the shell that is
#   running the pkill. An inline
#       ssh host 'pkill -f "beets_bulk_analyze_v6"; ... launch ...'
#   therefore kills itself before the launch ever happens, and the
#   runner silently never starts. Run it from a file and the pattern
#   is not in the launcher's command line.
set -u
CV=/var/lib/docker/volumes/beets-swarm_config/_data
NSHARD=${1:-4}

PAT='beets_bulk_analyze_v6'
pkill -f "$PAT" 2>/dev/null
sleep 3

sudo rm -f $CV/bulk-analysis.failed.v6.shard*

for S in $(seq 0 $((NSHARD-1))); do
  sudo setsid nohup /var/tmp/beets_bulk_analyze_v6.sh "$S" "$NSHARD" \
    >/dev/null 2>&1 &
done
sleep 90

echo "runners: $(pgrep -fc "$PAT")"
echo "done:    $(sudo sh -c "cat $CV/bulk-analysis.done.v6.shard0 $CV/bulk-analysis.done.v6.shard1 $CV/bulk-analysis.done.v6.shard2 $CV/bulk-analysis.done.v6.shard3 2>/dev/null | sort -u | wc -l")"
echo "failed:  $(sudo sh -c "cat $CV/bulk-analysis.failed.v6.shard* 2>/dev/null | wc -l")"
echo "=== the verify log (last 4) ==="
sudo tail -4 /var/tmp/beets-bulk/last-verify-v6.log 2>/dev/null | cut -c1-100
echo "=== the log (last 4) ==="
sudo grep "VERIFIED\|PARTIAL" "$CV/bulk-analysis.log" 2>/dev/null | tail -4 | cut -c1-100
