#!/usr/bin/env bash
# Bulk music analysis runner - v6.
#
# WHY v6: the v5 runner reported "0 failures" while 9,928 files were
# left untagged. It trusted its own exit code. v6 VERIFIES THE FILES ON
# DISK after every album and requeues anything that did not actually
# land.
#
# Per album:
#   1. import -q -A -I -C into a FRESH per-album DB (container-local)
#   2. beet replaygain -a     -> gains into the DB
#   3. beet fingerprint       -> fingerprints into the DB
#   4. write_analysis_only.py -> writes ONLY the six analysis fields
#   5. VERIFY by reading the files back off disk
#
# The write is metadata-free, so it creates no managed-metadata
# difference and Lidarr leaves the file alone.
#
# Usage: beets_bulk_analyze_v6.sh <shard-index> <shard-count>
set -u
SHARD=${1:-0}
NSHARD=${2:-4}
CFG_VOL=/var/lib/docker/volumes/beets-swarm_config/_data
WORK=/var/tmp/beets-bulk
LOG="$CFG_VOL/bulk-analysis.log"
FAILED="$CFG_VOL/bulk-analysis.failed.v6.shard$SHARD"
DONE="$CFG_VOL/bulk-analysis.done.v6.shard$SHARD"
LIST="${ALBUM_LIST:-$WORK/untagged.list}"

mkdir -p "$WORK"
touch "$FAILED" "$DONE"

cname() { docker ps --filter name=beets-swarm --format '{{.Names}}' | head -1; }

# Run a command in the beets container, resolving the container NAME at
# the moment of use and retrying once if the container was recreated
# underneath us.
#
# The container ID changes every time the swarm recreates the task, so
# resolving it once at the start of the script is not enough - every
# exec then hits a stale ID and silently fails. That is what filled
# the log with PARTIAL entries: the runner was talking to a container
# that no longer existed.
C=""
cget() {
  if [ -z "$C" ] || ! docker inspect "$C" >/dev/null 2>&1; then
    C=$(cname)
  fi
  [ -n "$C" ] || return 1
  return 0
}
dexec() {
  cget || return 1
  # docker requires the OPTIONS before the container name:
  #     docker exec -i CONTAINER COMMAND
  # Passing them the other way round ("docker exec CONTAINER -i")
  # makes the exec fail, which then consumed the heredoc on the
  # retry and produced an empty verification.
  local opts=""
  if [ "${1:-}" = "-i" ]; then
    opts="-i"
    shift
  fi
  # The exec can fail with "OCI runtime exec failed" when the host is
  # loaded - several shards execing at once against a container under
  # I/O pressure over CIFS. Retry with a short backoff rather than
  # recording a false failure.
  local n
  for n in 1 2 3 4 5; do
    if docker exec $opts "$C" "$@" 2>/dev/null; then
      return 0
    fi
    # the container may have been recreated - re-resolve it
    C=$(cname)
    [ -z "$C" ] && return 1
    sleep $((n * 3))
  done
  return 1
}

# container path <-> host path
#   host:   /media/Multimedia/Music/General Music/...
#   container: /music/General Music/...
# The container path MUST keep the /music prefix - dropping it gives
# "no such file or directory: /General Music/...".
host2cont() { echo "/music${1#/media/Multimedia/Music}"; }
cont2host() { echo "/media/Multimedia/Music${1#/music}"; }

verify_album() {
  # $1 = container dir. Reads every audio file back and counts how many
  # carry at least 4 analysis atoms.
  # NOTE: docker exec needs -i to forward the heredoc on stdin. Without
  # it python reads nothing and prints nothing.
  dexec -i python3 - "$1" <<'PYEOF'
import os, sys, subprocess
d = sys.argv[1]
A = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
total = ok = 0
bad = []
damaged = []
for dirpath, _s, fs in os.walk(d):
    for f in fs:
        if not f.lower().endswith(A):
            continue
        p = os.path.join(dirpath, f)
        total += 1
        try:
            o = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
                 '-of', 'default=nw=1', p],
                capture_output=True, text=True, timeout=60).stdout
        except Exception:
            o = ''
        n = len([l for l in o.splitlines()
                 if 'replaygain' in l.lower() or 'acoustid' in l.lower()])
        if n >= 4:
            ok += 1
            continue
        if len(bad) < 3:
            bad.append(os.path.basename(p))
        # a file ffmpeg cannot DECODE can never carry a full set. That
        # is a file problem, not an analysis problem, and it must not
        # hold up the album - it is reported separately.
        try:
            r = subprocess.run(
                ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
                capture_output=True, text=True, timeout=240)
            err = r.stderr or ''
            if ('Invalid data' in err or 'Error while decoding' in err
                    or 'Invalid packet' in err):
                damaged.append(os.path.basename(p))
        except Exception:
            pass
print('VERIFY total=%d ok=%d bad=%s damaged=%d' % (total, ok, bad, len(damaged)))
for x in damaged[:5]:
    print('   DAMAGED %s' % x)
PYEOF
}

process_album() {
  dir="$1"                 # host path
  cget || { echo "$(date -Is) NO CONTAINER $dir" >> "$FAILED"; return 1; }
  cdir=$(host2cont "$dir")
  db="/tmp/bulk-v6-$SHARD-$$.blb"

  # 1. import
  dexec sh -c \
    'cd /config && rm -f "$1" && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" import -q -A -I -C "$2"' \
    _ "$db" "$cdir" >> "$WORK/last-import-v6.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$(date -Is) rc=$rc import $dir" >> "$FAILED"
    return $rc
  fi

  # 2. THE GAIN PASSES.
  #    A file ffmpeg cannot decode makes ffmpeg exit non-zero, and
  #    beets raises on that - so ONE damaged file killed the album
  #    gain for every track beside it. Three passes fix it:
  #      a. album gain PER FORMAT - a damaged file of one format
  #         cannot poison another format's album gain
  #      b. the whole album - the common single-format case
  #      c. FORCED per-track gain - each item analysed on its own, so
  #         a damaged file only affects itself. It also fills in
  #         files that already carried partial gain data, which beets
  #         skips without -f.
  for f in $(dexec sh -c "ls -1 '$cdir' 2>/dev/null | sed 's/.*\.//' | tr 'A-Z' 'a-z' | sort -u | grep -E '^(flac|mp3|m4a|mp4|ogg|opus|wma|aac)$'"); do
    FMT=$(echo "$f" | tr 'a-z' 'A-Z')
    dexec sh -c \
      'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
         -c /config/bulk-analyze.yaml -l "$1" replaygain -a -f \
         "format:$2"' \
      _ "$db" "$FMT" >> "$WORK/last-rg-v6.log" 2>&1
  done
  dexec sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" replaygain -a -f' \
    _ "$db" >> "$WORK/last-rg-v6.log" 2>&1
  dexec sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" replaygain -f' \
    _ "$db" >> "$WORK/last-rg-v6.log" 2>&1

  # 3. fingerprint
  dexec sh -c \
    'cd /config && BEETSDIR=/config /lsiopy/bin/beet \
       -c /config/bulk-analyze.yaml -l "$1" fingerprint' \
    _ "$db" >> "$WORK/last-fp-v6.log" 2>&1

  # 4. the metadata-free write
  out=$(dexec python3 /config/write_analysis_only.py "$db" "$cdir" 2>&1)
  echo "$out" >> "$WORK/last-write-v6.log"

  # 5. VERIFY THE FILES. This is what v5 did not do.
  v=$(verify_album "$cdir")
  echo "$v" | sed "s|^|$(date -Is) |" >> "$WORK/last-verify-v6.log"
  tot=$(echo "$v" | sed -n 's/.*total=\([0-9]*\).*/\1/p')
  good=$(echo "$v" | sed -n 's/.*ok=\([0-9]*\).*/\1/p')
  dmg=$(echo "$v" | sed -n 's/.*damaged=\([0-9]*\).*/\1/p')
  tot=${tot:-0}; good=${good:-0}; dmg=${dmg:-0}

  # A file that ffmpeg cannot DECODE can never carry a complete set
  # of analysis fields. It is a FILE problem, not an analysis
  # problem, so it does not hold up the album - but it is recorded.
  if [ "$dmg" -gt 0 ]; then
    echo "$(date -Is) DAMAGED $dmg file(s) in $dir" >> "$LOG"
  fi

  # A directory with no audio at all is not a failure - there was
  # nothing to analyse. (Some library folders hold only artwork or
  # text.) Only a directory that HAS files and did not get all of them
  # tagged is a real partial.
  if [ "$tot" -eq 0 ]; then
    echo "$(date -Is) EMPTY (no audio) $dir" >> "$LOG"
    return 0
  fi

  if [ "$good" -eq "$tot" ]; then
    echo "$dir" >> "$DONE"
    echo "$(date -Is) VERIFIED $good/$tot $dir" >> "$LOG"
    return 0
  fi

  # The shortfall is exactly the number of files ffmpeg cannot decode.
  # Those are FILE problems, not analysis problems - they are recorded
  # separately and must not keep the album in the retry queue forever.
  short=$((tot - good))
  if [ "$dmg" -ge "$short" ] && [ "$short" -gt 0 ]; then
    echo "$dir" >> "$DONE"
    echo "$(date -Is) VERIFIED $good/$tot (dmg=$dmg, undecodable) $dir" >> "$LOG"
    return 0
  fi

  # not all files landed - requeue it, do not claim success
  echo "$(date -Is) PARTIAL $good/$tot $dir" >> "$FAILED"
  echo "$(date -Is) PARTIAL $good/$tot $dir" >> "$LOG"
  return 1
}

cget || { echo "no beets container"; exit 1; }

n=0
while IFS= read -r dir; do
  [ -z "$dir" ] && continue
  if grep -Fxq "$dir" "$DONE" 2>/dev/null; then continue; fi
  # a directory that already FAILED in a previous run is retried, but
  # not in a tight loop - the failed ledger is checked by the caller.
  idx=$((n % NSHARD))
  n=$((n+1))
  [ "$idx" -ne "$SHARD" ] && continue
  process_album "$dir"
done < "$LIST"

echo "$(date -Is) RUN_COMPLETE shard=$SHARD done=$(wc -l < "$DONE") failed=$(wc -l < "$FAILED")" >> "$LOG"