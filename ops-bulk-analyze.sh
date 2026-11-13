#!/usr/bin/env bash
# Bulk music analysis runner for the beets-swarm stack.
#
# Imports each album directory in the music library so that beets computes:
#   - MusicBrainz metadata match
#   - chroma / AcoustID acoustic fingerprints
#   - ReplayGain loudness tags (written into the FLAC files)
#
# Design notes:
#   * One album per beets invocation. A single invocation over 992 albums
#     would be one giant transaction with no progress visibility and no way
#     to resume after a container restart.
#   * Resumable. beets' own incremental table skips albums already in the
#     library, and this script keeps its own DONE log so a restarted run
#     does not redo work.
#   * Non-interactive. -q (never prompt) + --quiet-fallback=asis means albums
#     that do not match confidently are imported AS-IS, so they still get
#     analysed, instead of being skipped. -P disables the resume prompt that
#     would otherwise block on stdin.
#   * No tag rewriting beyond the analysis tags. The restricted plugin set in
#     bulk-analyze.yaml means scrub/embedart/lastgenre never run.
#   * PATH TRANSLATION: albums are enumerated on the HOST under
#     /media/Multimedia/Music but beets runs INSIDE the container where that
#     same share is mounted at /music. Host paths must be rewritten before
#     being handed to the container, otherwise beets fails with
#     "no such file or directory".
set -u

CFG_VOL=/var/lib/docker/volumes/beets-swarm_config/_data
LOG="$CFG_VOL/bulk-analysis.log"
DONE="$CFG_VOL/bulk-analysis.done"
FAILED="$CFG_VOL/bulk-analysis.failed"
HOST_ROOT=/media/Multimedia/Music
CONT_ROOT=/music
WORK=/var/tmp/beets-bulk

mkdir -p "$WORK"
cd "$WORK" || exit 1

to_container_path() {
  case "$1" in
    "$HOST_ROOT"/*) printf '%s/%s' "$CONT_ROOT" "${1#"$HOST_ROOT"/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

cname() { docker ps --filter name=beets-swarm --format '{{.Names}}' | head -1; }

# Top-level dirs that are not album collections.
SKIP_PARENTS='music\.old|Downloads-Music|Incoming Music|Incoming Downloads|[Pp]laylists|Lyrics|iPhone ringtones|Mp3s Junkbox|mood-creator|Podcasts|Automatically Add'

find "$HOST_ROOT" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | sort > "$WORK/albums.list"
total=$(wc -l < "$WORK/albums.list")
echo "$(date -Is) START total_album_dirs=$total" >> "$LOG"

n=0
while IFS= read -r dir; do
  parent=$(basename "$(dirname "$dir")")
  if echo "$parent" | grep -qE "$SKIP_PARENTS"; then continue; fi
  # Skip dirs with no audio at all (avoids 1000 pointless container runs).
  cnt=$(find "$dir" -maxdepth 1 -type f \( -iname '*.flac' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.ogg' \) 2>/dev/null | wc -l)
  [ "$cnt" -eq 0 ] && continue
  if grep -Fxq "$dir" "$DONE" 2>/dev/null; then continue; fi

  c=$(cname)
  if [ -z "$c" ]; then
    echo "$(date -Is) NO_CONTAINER $dir" >> "$LOG"
    sleep 30
    continue
  fi

  cdir=$(to_container_path "$dir")
  docker exec "$c" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet -c /config/bulk-analyze.yaml \
       -l /config/musiclibrary.blb import -q -P --quiet-fallback=asis -C "$1"' _ "$cdir" \
    >> "$WORK/last-import.log" 2>&1
  rc=$?

  n=$((n+1))
  if [ $rc -eq 0 ]; then
    echo "$dir" >> "$DONE"
    echo "$(date -Is) rc=0 ok $dir" >> "$LOG"
  else
    echo "$(date -Is) rc=$rc $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc $dir" >> "$LOG"
  fi

  # Progress heartbeat + rate limiting for MusicBrainz / AcoustID.
  if [ $((n % 10)) -eq 0 ]; then
    echo "$(date -Is) PROGRESS processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
  fi
  sleep 2
done < "$WORK/albums.list"

echo "$(date -Is) RUN_COMPLETE processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
