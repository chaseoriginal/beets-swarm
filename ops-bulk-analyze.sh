#!/usr/bin/env bash
# Bulk music analysis runner for the beets-swarm stack.
#
# Computes and WRITES, for every album in the library:
#   - MusicBrainz metadata match
#   - chroma / AcoustID acoustic fingerprints
#   - ReplayGain loudness tags
#
# TWO things this had to get right, both learned the hard way:
#
# 1. THE IMPORT ALONE DOES NOT WRITE THE ANALYSIS TAGS TO THE FILES.
#    beets' replaygain plugin computes the gains during import and stores
#    them in the library DB, but its import handler calls
#        handle_album(task.album, False, ...)
#    with write=False. The FLAC file only ends up with the REPLAYGAIN_*
#    tags as a side effect of some OTHER plugin doing a full tag write
#    (embedart/scrub in the main config). With a restricted plugin set
#    that side effect never happens and the file is left bare.
#    Proven: import with the restricted plugin set -> 0 tags on disk;
#    the same import with the full config -> 6 tags on disk.
#    The fix is a second pass over the library:
#        beet replaygain -a -w -f
#    which writes the stored gains into the files. -f forces re-analysis
#    of albums that already have gains.
#
# 2. ENUMERATE THE DIRECTORIES THAT ACTUALLY HOLD AUDIO, NOT A FIXED
#    DEPTH. The music share is Category/Artist/Album, so depth-2 gives
#    992 ARTIST directories and depth-3 gives 4641 - neither is the
#    album list. The correct list is "every directory that directly
#    contains audio files", which is 3658 directories. Enumerating by
#    depth silently analysed only part of the library.
#
# Design notes:
#   * One album per invocation. A single invocation over thousands of
#     albums is one giant transaction with no progress visibility and no
#     way to resume after a container restart.
#   * Resumable. The done ledger means a restart does not redo work.
#   * Non-interactive: -q never prompts, -P disables the resume prompt,
#     --quiet-fallback=asis means albums that do not match confidently are
#     still analysed instead of being skipped.
#   * No tag rewriting beyond the analysis tags. The restricted plugin set
#     in bulk-analyze.yaml means scrub/embedart/lastgenre never run.
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

# Every directory that DIRECTLY contains audio files, at any depth. This is
# the album list; a fixed -maxdepth gives artist dirs or a mixed bag.
enumerate_albums() {
  find "$HOST_ROOT" -type f \
    \( -iname '*.flac' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.ogg' \) \
    2>/dev/null | sed 's|/[^/]*$||' | sort -u
}

run_one() {
  local dir="$1" c rc cdir
  c=$(cname)
  if [ -z "$c" ]; then
    echo "$(date -Is) NO_CONTAINER $dir" >> "$LOG"
    return 75
  fi
  cdir=$(to_container_path "$dir")

  # Pass 1 - import: match, fingerprint, and store the gains in the DB.
  docker exec "$c" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet -c /config/bulk-analyze.yaml \
       -l /config/musiclibrary.blb import -q -P --quiet-fallback=asis -C "$1"' _ "$cdir" \
    >> "$WORK/last-import.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc $dir" >> "$LOG"
    return $rc
  fi

  # Pass 2 - write the stored gains into the FILES. Without this the
  # analysis exists only in the library database and never reaches the
  # music files that the streaming servers actually read.
  docker exec "$c" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet -c /config/bulk-analyze.yaml \
       -l /config/musiclibrary.blb replaygain -a -w -f "$1"' _ "$cdir" \
    >> "$WORK/last-rg.log" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "$dir" >> "$DONE"
    echo "$(date -Is) rc=0 ok $dir" >> "$LOG"
  else
    echo "$(date -Is) rc=$rc rg $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc rg $dir" >> "$LOG"
  fi
  return $rc
}

enumerate_albums > "$WORK/albums.list"
total=$(wc -l < "$WORK/albums.list")
echo "$(date -Is) START album_dirs=$total" >> "$LOG"

n=0
while IFS= read -r dir; do
  parent=$(basename "$(dirname "$dir")")
  if echo "$parent" | grep -qE "$SKIP_PARENTS"; then continue; fi
  if grep -Fxq "$dir" "$DONE" 2>/dev/null; then continue; fi

  run_one "$dir"
  n=$((n+1))

  # Progress heartbeat + rate limiting for MusicBrainz / AcoustID.
  if [ $((n % 10)) -eq 0 ]; then
    echo "$(date -Is) PROGRESS processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
  fi
  sleep 2
done < "$WORK/albums.list"

echo "$(date -Is) RUN_COMPLETE processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
