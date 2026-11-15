#!/usr/bin/env bash
# Bulk music analysis runner for the beets-swarm stack.
#
# Computes and WRITES, for every album in the library:
#   - MusicBrainz metadata match
#   - chroma / AcoustID acoustic fingerprints
#   - ReplayGain loudness tags
#
# THE PIPELINE (per album)
# -----------------------
#   1. import into a FRESH per-album library DB
#   2. beet replaygain -a -w -f   -> writes the gains to the FILES
#   3. beet fingerprint            -> writes the fingerprints to the FILES
#
# WHY A FRESH DB PER ALBUM
# -----------------------
# The shared library DB cannot be imported into reliably:
#
#   * beets keeps the incremental import state in a SEPARATE state file,
#     not in the library DB, so even a brand-new library DB is refused
#     with "Skipping previously-imported path". Passing -I (noincremental)
#     bypasses that.
#
#   * The album-level duplicate check refuses an album whose album already
#     exists in the library - which is the case for every album with a
#     sibling disc, because the first disc created the album. The message
#     is "This album is already in the library! Skipping." A fresh DB has
#     no such history.
#
#   * The shared DB holds a MIX of two path styles. Rows written by an
#     earlier import that had copy/move on carry the TEMPLATE path
#     ($albumartist/$album%aunique{}/$track - $title), where the album
#     directory name is mangled and the file name is rewritten. Rows
#     written with copy/move OFF carry the REAL on-disk path. So an album
#     directory and its DB rows routinely disagree, and matching them
#     requires title-based heuristics.
#     With copy: no and move: no (as configured), a fresh import always
#     records the REAL on-disk path, so the DB and the files agree and
#     no matching heuristic is needed.
#
# WHY THE WRITE IS A SEPARATE COMMAND
# ----------------------------------
# beets' replaygain PLUGIN computes the gains during import and stores
# them in the library DB, but its import handler calls
# handle_album(task.album, False, ...) - write=False. The FLAC only ends
# up carrying REPLAYGAIN_* tags as a side effect of some OTHER plugin
# doing a full tag write (embedart/scrub in the main config). With a
# restricted plugin set that side effect never happens and the file stays
# bare.
#
# The replaygain COMMAND is what writes the files: `replaygain -a -w -f`
# analyses and writes. The `fingerprint` command likewise writes
# ACOUSTID_FINGERPRINT to the files.
#
# The chroma plugin only fingerprints an album it MATCHED against
# MusicBrainz. Albums imported as-is never get a fingerprint, so the
# standalone `fingerprint` command is required to fill them in.
#
# OTHER DESIGN NOTES
# ------------------
#   * One album per invocation. A single invocation over thousands of
#     albums is one giant transaction with no progress visibility and no
#     way to resume after a container restart.
#   * Resumable. The done ledger means a restart does not redo work.
#   * Non-interactive: -q never prompts, -P disables the resume prompt,
#     --quiet-fallback=asis means albums that do not match confidently are
#     still analysed instead of being skipped.
#   * Enumerate the directories that ACTUALLY HOLD AUDIO, not a fixed
#     depth. The music share is Category/Artist/Album, so depth-2 gives
#     992 ARTIST directories and depth-3 gives 4641 - neither is the
#     album list. The correct list is "every directory that directly
#     contains audio files", which is 3658 directories.
#   * PATH TRANSLATION: albums are enumerated on the host under
#     /media/Multimedia/Music but beets runs inside the container where
#     that share is /music.
set -u

SHARD=${1:-0}
SHARDS=${2:-1}
CFG_VOL=/var/lib/docker/volumes/beets-swarm_config/_data
LOG="$CFG_VOL/bulk-analysis.log"
# The ledger records albums that are analysed AND written to disk.
# It is VERSIONED: each version means "done" has a stricter definition,
# so every earlier version's entries must be re-processed.
#   .v1 - imported only; the write pass did not work at all
#   .v2 - imported and written, but the write scope bled into other
#         albums and stripped their tags
#   .v3 - fresh per-album DB, but the DB name was shared, so a
#         concurrent process could poison it
#   .v4 - fresh per-album DB with a unique name, but the write was a
#         full tag write and Lidarr kept reverting it
#   .v5 - metadata-free analysis write; the tags survive
# Earlier ledger files are kept as history, never deleted.
#
# SHARDING: with more than one shard each shard has its OWN ledger, so
# two runners never append to the same file. The coverage report merges
# them.
SUFFIX=""
[ "$SHARDS" -gt 1 ] && SUFFIX=".shard$SHARD"
DONE="$CFG_VOL/bulk-analysis.done.v5$SUFFIX"
FAILED="$CFG_VOL/bulk-analysis.failed.v5$SUFFIX"
HOST_ROOT=/media/Multimedia/Music
CONT_ROOT=/music
WORK=/var/tmp/beets-bulk

# Top-level dirs that are not album collections.
SKIP_PARENTS='music\.old|Downloads-Music|Incoming Music|Incoming Downloads|[Pp]laylists|Lyrics|iPhone ringtones|Mp3s Junkbox|mood-creator|Podcasts|Automatically Add'

mkdir -p "$WORK"
cd "$WORK" || exit 1

to_container_path() {
  case "$1" in
    "$HOST_ROOT"/*) printf '%s/%s' "$CONT_ROOT" "${1#"$HOST_ROOT"/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

cname() { docker ps --filter name=beets-swarm --format '{{.Names}}' | head -1; }

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

  # A FRESH library DB per album, INSIDE the container. The DB path must
  # be a container path: a host path like /var/tmp/beets-bulk/album.blb
  # does not exist in the container, and beets then prompts to create the
  # directory - which fails under a non-interactive stdin.
  #
  # The name is unique per invocation ($$ is the shell PID). A shared
  # fixed name means a second runner - or a diagnostic script - can
  # collide with this one: the other process's album is already in the
  # DB, so this album's import is refused with "This album is already
  # in the library! Skipping.", the DB ends up holding the WRONG album,
  # and the write steps silently analyse nothing.
  local db="/tmp/bulk-album-$$.blb"

  # Step 1 - import: compute the gains into the DB.
  #
  # -A (--noautotag) imports the files' EXISTING metadata with no
  # MusicBrainz query. That is a 14x speedup (3.1s vs 43s per album)
  # and costs nothing here: the analysis config has import.write: no,
  # so the matched metadata is never written to the files anyway. The
  # search existed only to get chroma going, and the explicit
  # fingerprint pass below does that without it.
  #
  # -I (noincremental) bypasses the global incremental state, which
  # lives in a separate state file and would otherwise make beets skip
  # every album it has seen.
  docker exec "$c" sh -c \
    'cd /config && rm -f "$1" && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" import -q -A -I -C "$2"' \
    _ "$db" "$cdir" \
    >> "$WORK/last-import.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc import $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc import $dir" >> "$LOG"
    return $rc
  fi

  # Step 2 - compute the ReplayGain gains into the DB (NO file write).
  #
  # The plugin's import handler stores the gains in the DB with
  # write=False, so the values are already in the DB after the import.
  # Running `replaygain -a` without -w computes them for any item the
  # import did not cover, and still writes nothing to the files.
  docker exec "$c" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" replaygain -a' _ "$db" \
    >> "$WORK/last-rg.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc rg $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc rg $dir" >> "$LOG"
    return $rc
  fi

  # Step 3 - compute the acoustic fingerprints into the DB. The chroma
  # plugin only fingerprints MATCHED albums; this fills in the rest.
  docker exec "$c" sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" fingerprint' _ "$db" \
    >> "$WORK/last-fingerprint.log" 2>&1

  # Step 4 - write ONLY the analysis fields to the FILES.
  #
  # NOT a beets write. Lidarr watches its root folder, and any write to
  # a file Lidarr manages triggers its watcher: Lidarr refreshes the
  # album and REWRITES the file from its own database, dropping
  # REPLAYGAIN_* and ACOUSTID_* because it does not know them. Proven by
  # A/B: Lidarr running -> tags went 4 -> 0 in 65s; Lidarr stopped ->
  # 4 -> 4. FLAC survived (TagLib preserves unknown Vorbis comments),
  # MP3 did not - which is why the library measured FLAC 94/94 and MP3
  # 51/108.
  #
  # write_analysis_only.py uses mutagen to set only the six analysis
  # fields in place, leaving every other tag byte-for-byte alone. That
  # cannot be mistaken for a metadata change.
  docker exec "$c" python3 /config/write_analysis_only.py "$db" "$cdir" \
    >> "$WORK/last-write.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc write $dir" >> "$FAILED"
    echo "$(date -Is) rc=$rc write $dir" >> "$LOG"
    return $rc
  fi

  # Clean up the per-album DB so the container's /tmp does not fill up.
  docker exec "$c" rm -f "$db" 2>/dev/null

  echo "$dir" >> "$DONE"
  echo "$(date -Is) rc=0 ok $dir" >> "$LOG"
  return 0
}

enumerate_albums > "$WORK/albums.list"
total=$(wc -l < "$WORK/albums.list")
echo "$(date -Is) START shard=$SHARD/$SHARDS album_dirs=$total" >> "$LOG"

n=0
idx=0
while IFS= read -r dir; do
  # Shard selection: each runner takes every Nth album, so N runners
  # split the work without ever touching the same album.
  if [ $((idx % SHARDS)) -ne "$SHARD" ]; then
    idx=$((idx+1))
    continue
  fi
  idx=$((idx+1))

  parent=$(basename "$(dirname "$dir")")
  if echo "$parent" | grep -qE "$SKIP_PARENTS"; then continue; fi
  if grep -Fxq "$dir" "$DONE" 2>/dev/null; then continue; fi

  run_one "$dir"
  n=$((n+1))

  # Progress heartbeat + rate limiting for MusicBrainz / AcoustID.
  if [ $((n % 10)) -eq 0 ]; then
    echo "$(date -Is) PROGRESS shard=$SHARD processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
  fi
  sleep 2
done < "$WORK/albums.list"

echo "$(date -Is) RUN_COMPLETE shard=$SHARD processed=$n done_total=$(wc -l < "$DONE")" >> "$LOG"
