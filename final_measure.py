#!/usr/bin/env python3
"""The corrected final measurement, plus WHERE the untagged files are.

Two problems with the first pass:
  1. the metadata lookup used FLAC-style key names, so every MP3 and M4A
     read as "no title". ID3 uses TIT2/TPE1/TALB; MP4 uses the (c)-prefixed
     atoms. A per-format key map fixes it.
  2. 12,013 files have ZERO analysis atoms and the audit does not say
     WHERE they are. The likely answer: the directories that were
     deliberately EXCLUDED from the analysis run (podcasts, voice-mod
     SFX, kids music, music.old, incoming) were never in its album
     list. So they are not failures - they were never in scope.

This measures both properly.

Usage: final_measure.py <shard-index> <shard-count> <out.json>
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

# per-format key maps, for the RAW tag names
KEYMAPS = {
    'flac': {
        'title': ['title'],
        'artist': ['artist'],
        'album': ['album'],
        'albumartist': ['albumartist'],
        'mbid': ['musicbrainz_albumid'],
    },
    'mp3': {
        'title': ['TIT2'],
        'artist': ['TPE1'],
        'album': ['TALB'],
        'albumartist': ['TPE2'],
        'mbid': ['TXXX:MusicBrainz Album Id'],
    },
    'm4a': {
        'title': ['\xa9nam'],
        'artist': ['\xa9ART'],
        'album': ['\xa9alb'],
        'albumartist': ['aART'],
        'mbid': ['----:com.apple.iTunes:MUSICBRAINZ_ALBUMID'],
    },
}

# directories that were deliberately excluded from the analysis scope
EXCLUDE = ('/music/Podcasts', '/music/music.old', '/music/Incoming Music',
           '/music/Kids Music', '/music/General Music/Halloween',
           '/media/Multimedia/Music/Podcasts',
           '/media/Multimedia/Music/music.old',
           '/media/Multimedia/Music/Incoming Music',
           '/media/Multimedia/Music/Kids Music',
           '/media/Multimedia/Music/General Music/Halloween')


def category(path):
    for e in EXCLUDE:
        if path.startswith(e):
            return 'EXCLUDED (out of scope)'
    if '/General Music/' in path:
        return 'library'
    if '/Christian Music/' in path:
        return 'library'
    return 'other'


def one(path):
    ext = path.rsplit('.', 1)[-1].lower()
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        return {'err': 'read', 'fmt': ext}
    if f is None:
        return {'err': 'unreadable', 'fmt': ext}
    t = f.tags
    if t is None:
        return {'err': 'no_tags', 'fmt': ext}
    try:
        keys = {}
        for k in t.keys():
            ks = k.decode('latin1') if isinstance(k, bytes) else str(k)
            keys[ks.lower()] = k
    except Exception:
        return {'err': 'read', 'fmt': ext}

    analysis = [k for k in keys if 'replaygain' in k or 'acoustid' in k]
    km = KEYMAPS.get(ext, KEYMAPS['flac'])

    def g(field):
        for want in km.get(field, []):
            for k in keys:
                if k == want.lower():
                    try:
                        v = t[keys[k]]
                    except Exception:
                        v = None
                    if isinstance(v, list):
                        v = v[0] if v else ''
                    return str(v or '').strip()
        return ''

    title = g('title')
    artist = g('artist')
    album = g('album')
    return {'err': None, 'fmt': ext, 'n_analysis': len(analysis),
            'title': title, 'artist': artist, 'album': album,
            'albumartist': g('albumartist'), 'mbid': g('mbid'),
            'cat': category(path)}


def main():
    root = '/music'
    idx = int(sys.argv[1])
    nsh = int(sys.argv[2])
    out = sys.argv[3]

    files = []
    for dirpath, _d, fnames in os.walk(root):
        for f in fnames:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(dirpath, f))
    mine = [p for i, p in enumerate(sorted(files)) if i % nsh == idx]
    print('shard %d/%d: %d files' % (idx, nsh, len(mine)))
    sys.stdout.flush()

    st = collections.Counter()
    by_fmt = collections.defaultdict(collections.Counter)
    by_cat = collections.defaultdict(collections.Counter)
    hist = collections.Counter()
    missing_files = []

    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(one, mine)):
            fmt = r.get('fmt', '?')
            cat = r.get('cat', '?')
            st['files'] += 1
            by_fmt[fmt]['files'] += 1
            by_cat[cat]['files'] += 1
            if r['err']:
                st[r['err']] += 1
                by_fmt[fmt][r['err']] += 1
                by_cat[cat][r['err']] += 1
                continue
            hist[r['n_analysis']] += 1
            ok = r['n_analysis'] >= 4
            st['analysis_ok' if ok else 'analysis_missing'] += 1
            by_fmt[fmt]['analysis_ok' if ok else 'analysis_missing'] += 1
            by_cat[cat]['analysis_ok' if ok else 'analysis_missing'] += 1
            if not ok and len(missing_files) < 400:
                missing_files.append((r['n_analysis'], cat, fmt))
            miss = [k for k, v in (('title', r['title']), ('artist', r['artist']),
                                   ('album', r['album']))
                    if v.lower() in PLACEHOLDER]
            mok = not miss
            st['metadata_complete' if mok else 'metadata_incomplete'] += 1
            by_fmt[fmt]['metadata_complete' if mok else 'metadata_incomplete'] += 1
            by_cat[cat]['metadata_complete' if mok else 'metadata_incomplete'] += 1
            if r['mbid']:
                st['has_mbid'] += 1
            if r['albumartist']:
                st['has_albumartist'] += 1
            if i % 3000 == 0 and i:
                print('  shard %d: %d/%d' % (idx, i, len(mine)))
                sys.stdout.flush()

    with open(out, 'w') as fh:
        json.dump({'stats': dict(st),
                   'by_fmt': {k: dict(v) for k, v in by_fmt.items()},
                   'by_cat': {k: dict(v) for k, v in by_cat.items()},
                   'hist': dict(hist),
                   'missing_sample': missing_files}, fh)
    print('shard %d done: %d files' % (idx, st['files']))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
