#!/usr/bin/env bash
# Deploy the fixed v6 runner and re-queue the albums that still need
# work.
set -u
CV=/var/lib/docker/volumes/beets-swarm_config/_data
WORK=/var/tmp/beets-bulk
NSHARD=3

PAT='beets_bulk_analyze_v6'
pkill -f "$PAT" 2>/dev/null
sleep 3

echo "=== build the retry list ==="
sudo python3 /tmp/build_retry_list.py "$WORK/untagged.list"

echo
echo "=== launch ==="
sudo chmod +x /var/tmp/beets_bulk_analyze_v6.sh
sudo rm -f $CV/bulk-analysis.failed.v6.shard*
for S in $(seq 0 $((NSHARD-1))); do
  sudo setsid nohup /var/tmp/beets_bulk_analyze_v6.sh "$S" "$NSHARD" \
    >/dev/null 2>&1 &
done
sleep 150
echo "   runners: $(pgrep -fc "$PAT")"
echo "   done:    $(sudo sh -c "cat $CV/bulk-analysis.done.v6.shard* 2>/dev/null | sort -u | wc -l")"
echo "   failed:  $(sudo sh -c "cat $CV/bulk-analysis.failed.v6.shard* 2>/dev/null | wc -l")"
echo "=== the verify log ==="
sudo tail -6 /var/tmp/beets-bulk/last-verify-v6.log 2>/dev/null | cut -c1-100
echo "=== the log ==="
sudo grep "VERIFIED\|PARTIAL\|DAMAGED" "$CV/bulk-analysis.log" 2>/dev/null | tail -6 | cut -c1-100
