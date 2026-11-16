#!/usr/bin/env bash
# THE METADATA-CORRECTION RUNNER (production).
#
# VERIFIED DESIGN, from the end-to-end tests:
#
# 1. `beet write -f` writes the item's WHOLE tag set, and it CARRIES the
#    analysis tags as long as the DB holds them. Verified on MP3 and
#    FLAC: import -> replaygain -a -> fingerprint -> write -f left 5
#    analysis tags on the file alongside the written metadata.
#
# 2. ORDER MATTERS. The analysis values must be in the DB BEFORE the
#    write, or the write strips them. So the sequence per album is:
#        import (WITH MusicBrainz matching) -> replaygain -a -> fingerprint -> write -f
#
# 3. IT WORKS WITH LIDARR RUNNING. Tested on real albums: after the
#    combined pass, a forced RefreshAlbum left the analysis tags intact
#    (5/5 on every album tested). The corrected metadata agrees with
#    Lidarr's own MusicBrainz data, so Lidarr has nothing to correct
#    and does not rewrite the file. No outage needed.
#
# 4. SCOPE. The library's metadata is largely correct already (FLAC
#    0.0% incomplete, 0.3% without a MusicBrainz id). The failures are
#    concentrated in MP3 (4.8% incomplete, 19.2% no id) and in
#    directories that are not music at all (podcasts, voice-mod SFX,
#    kids music, incoming, music.old). MusicBrainz must never be asked
#    to match those. So the work list is the scoped album list.
#
# The list format is "<host-album-dir>|<container-album-dir>".
set -u
SHARD="${1:-0}"
NSHARD="${2:-1}"
C=$(docker ps --filter name=beets-swarm --format '{{.Names}}' | head -1)
CV=/var/lib/docker/volumes/beets-swarm_config/_data
WORK=/var/tmp/beets-meta
LEDGER="$CV/bulk-metadata.done.v1.shard$SHARD"
FAILED="$CV/bulk-metadata.failed.v1.shard$SHARD"
LOG="$WORK/meta-runner.log"
LIST="$WORK/meta-albums.list"
mkdir -p "$WORK"

run_one() {
  local cdir="$1" cpath="$2"
  local db="/tmp/meta-$$.blb"

  # 1. import WITH MusicBrainz matching -> corrected metadata in the DB
  docker exec "$C" sh -c \
    'cd /config && rm -f "$1" && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" import -q -P -I \
       --quiet-fallback=asis -C "$2"' _ "$db" "$cpath" \
    >> "$WORK/last-meta-import.log" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc import $cdir" >> "$FAILED"
    docker exec "$C" rm -f "$db" 2>/dev/null
    return 1
  fi

  # 2. the analysis values MUST be in the DB before the write, or the
  #    write strips them from the file
  docker exec "$C" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" replaygain -a' _ "$db" \
    >> "$WORK/last-meta-rg.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc replaygain $cdir" >> "$FAILED"
    docker exec "$C" rm -f "$db" 2>/dev/null
    return 1
  fi
  docker exec "$C" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" fingerprint' _ "$db" \
    >> "$WORK/last-meta-fp.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc fingerprint $cdir" >> "$FAILED"
    docker exec "$C" rm -f "$db" 2>/dev/null
    return 1
  fi

  # 3. the write: corrected metadata AND the analysis, together
  docker exec "$C" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" write -f' _ "$db" \
    >> "$WORK/last-meta-write.log" 2>&1
  rc=$?
  docker exec "$C" rm -f "$db" 2>/dev/null
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc write $cdir" >> "$FAILED"
    return 1
  fi

  echo "$cdir" >> "$LEDGER"
  echo "$(date -Is) rc=0 ok $cdir" >> "$LOG"
  return 0
}

n=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  cdir="${line%%|*}"
  cpath="${line#*|}"
  n=$((n+1))
  if [ $((n % NSHARD)) -ne "$SHARD" ]; then continue; fi
  if grep -Fxq "$cdir" "$LEDGER" 2>/dev/null; then continue; fi
  run_one "$cdir" "$cpath"
  sleep 3
done < "$LIST"
echo "$(date -Is) shard $SHARD complete" >> "$LOG"
