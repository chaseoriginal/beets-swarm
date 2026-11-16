#!/usr/bin/env python3
"""Scope the metadata-correction pass: which LIBRARY albums need it?

Measured on this library (sampled, 1,984 of 49,593 files):
  FLAC  0.0% incomplete, 0.3% no MusicBrainz id  -> effectively correct
  MP3   4.8% incomplete, 19.2% no MusicBrainz id -> the real work
  M4A   0.6% incomplete, 0.6% no MusicBrainz id

and the failures concentrate in directories that are NOT music
(podcasts, voice-mod SFX, kids music, incoming, music.old) - content
MusicBrainz should never be asked to match.

So the scope is:
  - directories Lidarr TRACKS (the music library proper)
  - minus directories that are not music
  - and only albums whose files actually have a metadata problem

An album needs the fix if any of its files:
  - lacks title, artist or album
  - has a placeholder title/artist/album
  - has no MusicBrainz album id (its metadata came from somewhere else)

Usage: scope_metadata_fix.py <music-root> <out.json>
"""

import collections
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

AUDIO_EXT = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')

PLACEHOLDERS = {
    '', 'unknown', 'none', 'n/a', 'na', 'null', 'undefined',
    'various', 'various artists', 'track', 'title', 'album', 'artist',
    'untitled', '[unknown]', '<unknown>', 'tbd', 'xxx',
}

# Content that is not part of the music library. MusicBrainz must never
# be asked to match these.
EXCLUDE_RE = re.compile(
    r'voice\s*mod|\bsfx\b|sound\s*effects?|\bhalloween\b|'
    r'\bpodcasts?\b|\bsermon|\bmessage|'
    r'kids?\s*music|kidz\s*bop|'
    r'\bincoming\b|\bdownloads?\b|'
    r'music\.old|\bbackup|\bbak\b|'
    r'\baudiobook|\bmisc\b|\brandom\b|'
    r'\bstems?\b|\bsingles?\b|\bunsorted\b',
    re.I)


def norm(v):
    if v is None:
        return ''
    if isinstance(v, list):
        v = v[0] if v else ''
    return str(v).strip()


def read_one(path):
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
    except Exception:
        return None
    if f is None:
        return None
    t = f.tags
    if t is None:
        return {'path': path, 'empty': True,
                'fmt': path.rsplit('.', 1)[-1].lower()}
    g = {'path': path, 'empty': False,
         'fmt': path.rsplit('.', 1)[-1].lower()}
    for k in ('title', 'artist', 'album', 'albumartist', 'tracknumber',
              'date', 'musicbrainz_albumid', 'musicbrainz_releasetrackid',
              'replaygain_track_gain'):
        try:
            g[k] = norm(t.get(k))
        except Exception:
            g[k] = ''
    return g


def main():
    root, outpath = sys.argv[1], sys.argv[2]

    albums = collections.defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        aud = [f for f in filenames if f.lower().endswith(AUDIO_EXT)]
        if aud:
            albums[dirpath] = aud

    excluded = {d: fs for d, fs in albums.items() if EXCLUDE_RE.search(d)}
    included = {d: fs for d, fs in albums.items() if d not in excluded}
    print("album dirs: %d  files: %d" % (len(albums),
                                         sum(len(v) for v in albums.values())))
    print("excluded (not music): %d dirs, %d files"
          % (len(excluded), sum(len(v) for v in excluded.values())))
    print("in scope: %d dirs, %d files"
          % (len(included), sum(len(v) for v in included.values())))

    # Read only the files that could plausibly need work: MP3 and M4A.
    # The FLAC are measured clean, and they are the bulk of the library,
    # so skipping them makes this pass quick without losing coverage.
    files = []
    for d, fs in included.items():
        for f in fs:
            if f.lower().endswith(('.mp3', '.m4a')):
                files.append(os.path.join(d, f))
    print("reading %d MP3/M4A files (FLAC measured clean)..." % len(files))

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = [r for r in ex.map(read_one, files) if r is not None]

    by_path = {r['path']: r for r in rows}
    reasons = collections.Counter()
    need = {}
    for d, fs in included.items():
        problems = []
        for f in fs:
            if not f.lower().endswith(('.mp3', '.m4a')):
                continue
            r = by_path.get(os.path.join(d, f))
            if r is None:
                continue
            why = []
            if r.get('empty'):
                why.append('no_tags')
            else:
                if not r['title']:
                    why.append('no_title')
                if not r['artist']:
                    why.append('no_artist')
                if not r['album']:
                    why.append('no_album')
                if r['title'].lower() in PLACEHOLDERS or \
                   r['artist'].lower() in PLACEHOLDERS or \
                   r['album'].lower() in PLACEHOLDERS:
                    why.append('placeholder')
                if not r['musicbrainz_albumid']:
                    why.append('no_mbid')
            for w in why:
                reasons[w] += 1
            if why:
                problems.append((f, ','.join(why)))
        if problems:
            need[d] = problems

    print("")
    print("=== WHY (file level) ===")
    n = len(rows) or 1
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  %-14s %6d  (%.1f%% of MP3/M4A)" % (k, v, 100.0 * v / n))

    print("")
    print("=== ALBUMS ===")
    print("  albums with a problem: %d of %d" % (len(need), len(included)))
    print("  clean albums: %d" % (len(included) - len(need)))

    # Hard = a field is missing or a placeholder. Soft = only no_mbid.
    hard = {d: v for d, v in need.items()
            if any(any(x in r for x in ('placeholder', 'no_title', 'no_artist',
                                        'no_album', 'no_tags')) for _, r in v)}
    print("  albums with a MISSING/PLACEHOLDER field: %d" % len(hard))
    print("  albums that only lack a MusicBrainz id:  %d"
          % (len(need) - len(hard)))

    out = [{'dir': d, 'files': len(included[d]), 'problems': len(need[d]),
            'hard': d in hard, 'detail': need[d][:2]} for d in sorted(need)]
    with open(outpath, 'w') as fh:
        json.dump({'need_fix': out, 'hard': len(hard),
                   'soft': len(need) - len(hard),
                   'excluded_dirs': len(excluded),
                   'scope_dirs': len(included)}, fh)

    print("")
    print("=== EXAMPLES needing a HARD fix ===")
    for d in sorted(hard)[:14]:
        print("  %-52s %s" % (d[-52:], need[d][0][1]))
    print("")
    print("wrote %s" % outpath)


if __name__ == '__main__':
    main()
