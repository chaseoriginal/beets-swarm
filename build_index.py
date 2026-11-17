#!/usr/bin/env python3
"""Build a PERSISTENT title+artist index of the whole library, using
mutagen (not ffprobe - mutagen reads the tag block only, which is
roughly 20x faster over CIFS).

The index is written once to /tmp/lib_index.json and reused by every
later query. The earlier full-library searches died because they called
ffprobe 49,000 times; mutagen does it in a fraction of the time.

Usage: build_index.py
"""
import json
import os
import sys
import unicodedata

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
OUT = '/tmp/lib_index.json'


def nk(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    s = ''.join(ch for ch in s if ch.isalnum())
    return s


def nk_artist(s):
    s = nk(s)
    for a in ('the',):
        if s.startswith(a) and len(s) > len(a):
            s = s[len(a):]
        elif s.endswith(a) and len(s) > len(a):
            s = s[:-len(a)]
    return s


def main():
    import mutagen
    rows = []
    n = 0
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if not f.lower().endswith(AUDIO):
                continue
            p = os.path.join(root, f)
            try:
                m = mutagen.File(p, easy=True)
            except Exception:
                m = None
            if m is None:
                continue
            t = getattr(m, 'title', None)
            a = getattr(m, 'artist', None)
            al = getattr(m, 'album', None)
            rows.append({
                'p': p,
                't': nk(t[0] if isinstance(t, list) else (t or '')),
                'a': nk_artist(a[0] if isinstance(a, list) else (a or '')),
                'al': (al[0] if isinstance(al, list) else (al or ''))[:60],
            })
            n += 1
            if n % 5000 == 0:
                print('   %d files...' % n, flush=True)
    print('   indexed %d files' % len(rows))
    with open(OUT, 'w') as fh:
        json.dump(rows, fh)
    print('wrote %s' % OUT)


if __name__ == '__main__':
    main()
