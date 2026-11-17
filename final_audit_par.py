#!/usr/bin/env python3
"""THE FINAL AUDIT - parallel, with progress.

One process over 49,566 files over CIFS is too slow. This splits the
work into N shards by a hash of the file path, runs them as separate
processes, and merges the results.

Reports both halves of the goal:
  ANALYSIS  - does the file carry the ReplayGain / AcoustID atoms?
  METADATA  - does it carry title, artist and album, and are they
              placeholders?

Usage: final_audit_par.py <music-root> <shard-index> <shard-count> <out.json>
"""

import collections
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
PLACEHOLDER = ('', 'unknown', 'none', 'n/a', 'null', 'various',
               'various artists', 'track', 'title', 'album', 'artist',
               'untitled', '[unknown]', '<unknown>', 'tbd')


def one(path):
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        return {'err': 'read'}
    if f is None:
        return {'err': 'unreadable'}
    t = f.tags
    if t is None:
        return {'err': 'no_tags', 'fmt': path.rsplit('.', 1)[-1].lower()}
    try:
        keys = [k.decode('latin1').lower() if isinstance(k, bytes) else k.lower()
                for k in t.keys()]
    except Exception:
        keys = []
    an = [k for k in keys if 'replaygain' in k or 'acoustid' in k]

    def g(*names):
        for n in names:
            for k in keys:
                if k == n:
                    try:
                        v = t[k]
                    except Exception:
                        v = None
                    if isinstance(v, list):
                        v = v[0] if v else ''
                    return str(v or '').strip()
        return ''

    title = g('title', '\xa9nam')
    artist = g('artist', '\xa9art')
    album = g('album', '\xa9alb')
    aa = g('albumartist', 'aart')
    mbid = g('musicbrainz_albumid', '----:com.apple.iTunes:MUSICBRAINZ_ALBUMID')
    return {'err': None, 'fmt': path.rsplit('.', 1)[-1].lower(),
            'n_analysis': len(an), 'analysis_keys': an,
            'title': title, 'artist': artist, 'album': album,
            'albumartist': aa, 'mbid': mbid}


def main():
    root = sys.argv[1]
    idx = int(sys.argv[2])
    nsh = int(sys.argv[3])
    out = sys.argv[4]

    files = []
    for dirpath, _d, fnames in os.walk(root):
        for f in fnames:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(dirpath, f))
    mine = [p for i, p in enumerate(sorted(files)) if i % nsh == idx]
    print('shard %d/%d: %d of %d files' % (idx, nsh, len(mine), len(files)))
    sys.stdout.flush()

    st = collections.Counter()
    by_fmt = collections.defaultdict(collections.Counter)
    hist = collections.Counter()
    no_analysis = []
    bad_meta = []
    unread = []
    aa_present = 0

    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(one, mine)):
            fmt = r.get('fmt', '?')
            st['files'] += 1
            by_fmt[fmt]['files'] += 1
            if r['err']:
                st[r['err']] += 1
                by_fmt[fmt][r['err']] += 1
                unread.append(r['err'])
                continue
            hist[r['n_analysis']] += 1
            if r['n_analysis'] >= 4:
                st['analysis_ok'] += 1
                by_fmt[fmt]['analysis_ok'] += 1
            else:
                st['analysis_missing'] += 1
                by_fmt[fmt]['analysis_missing'] += 1
                if len(no_analysis) < 30:
                    no_analysis.append((r['n_analysis'],))
            miss = [k for k, v in (('title', r['title']), ('artist', r['artist']),
                                   ('album', r['album']))
                    if v.lower() in PLACEHOLDER]
            if miss:
                st['metadata_incomplete'] += 1
                by_fmt[fmt]['metadata_incomplete'] += 1
                if len(bad_meta) < 30:
                    bad_meta.append((','.join(miss),))
            else:
                st['metadata_complete'] += 1
                by_fmt[fmt]['metadata_complete'] += 1
            if r['mbid']:
                st['has_mbid'] += 1
                by_fmt[fmt]['has_mbid'] += 1
            if r['albumartist']:
                aa_present += 1
                st['has_albumartist'] += 1
            if i % 2000 == 0 and i:
                print('  shard %d: %d/%d' % (idx, i, len(mine)))
                sys.stdout.flush()

    with open(out, 'w') as fh:
        json.dump({'stats': dict(st),
                   'by_fmt': {k: dict(v) for k, v in by_fmt.items()},
                   'hist': dict(hist)}, fh)
    print('shard %d done: %d files' % (idx, st['files']))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
