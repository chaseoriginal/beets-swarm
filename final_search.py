#!/usr/bin/env python3
"""The last 11 broken files: search by EXACT TITLE + EXACT ARTIST.

The album-based search could not place them because the good copy is a
different edition (a bonus track that is not on the standard release,
a live track from a different single). But the TITLE and the ARTIST are
exact, and together they are a strong identity - "S.O.M" by Static-X is
not "S.O.M" by anyone else.

So: index every working file on the share by (normalised title,
normalised artist) and require an EXACT match on both. The album is
reported but not required, so a human can see what was matched.

The candidates are printed with their album and folder so the match can
be eyeballed before anything is written.

Usage: final_search.py
"""
import collections
import json
import os
import re
import subprocess
import unicodedata

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')


def nk(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


def nk_artist(s):
    s = nk(s)
    for a in ('the',):
        if s.startswith(a) and len(s) > len(a):
            s = s[len(a):]
        elif s.endswith(a) and len(s) > len(a):
            s = s[:-len(a)]
    return s


def ff_tags(p):
    try:
        o = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=60).stdout.splitlines()
    except Exception:
        return {}
    d = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            d[k.split(':')[-1].strip().lower()] = v.strip()
    return d


def mutagen_ok(p):
    try:
        import mutagen
        f = mutagen.File(p)
    except Exception:
        return False
    return f is not None and f.tags is not None


def has_audio(p):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=60)
        return r.returncode == 0 and 'audio' in r.stdout
    except Exception:
        return False


def dir_artist(path):
    p = os.path.dirname(path)
    for _ in range(3):
        parent = os.path.basename(os.path.dirname(p))
        if parent in ('General Music', 'Christian Music', 'SoundTracks'):
            return os.path.basename(p)
        p = os.path.dirname(p)
    return ''


def main():
    res = json.load(open('/tmp/repl_final.json'))
    left = [e for e in res if not e.get('resolved')]
    print('=== the %d files still to place ===' % len(left))

    # the broken files' own identity - from their filename and folder
    want = {}
    for e in left:
        p = e['broken']
        i = e.get('ident_resolved', {})
        title = i.get('title') or ''
        # strip a leading track number from the title
        title = re.sub(r'^\d{1,3}[\s._-]+', '', title)
        title = re.sub(r'^\d{1,3}\s+', '', title)
        artist = dir_artist(p)
        want[(nk(title), nk_artist(artist))] = e
        print('   %-42s title=%-24r artist=%r'
              % (os.path.basename(p)[-42:], title[:24], artist))

    print('')
    print('indexing every working file by (title, artist)...')
    index = collections.defaultdict(list)
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if not f.lower().endswith(AUDIO):
                continue
            q = os.path.join(root, f)
            d = ff_tags(q)
            t = nk(d.get('title', ''))
            a = nk_artist(d.get('artist', ''))
            if t and a:
                index[(t, a)].append((q, d))
    print('   index size: %d' % len(index))

    print('')
    found = 0
    for e in left:
        p = e['broken']
        i = e.get('ident_resolved', {})
        title = i.get('title') or ''
        title = re.sub(r'^\d{1,3}[\s._-]+', '', title)
        title = re.sub(r'^\d{1,3}\s+', '', title)
        artist = dir_artist(p)
        key = (nk(title), nk_artist(artist))
        cands = []
        for q, d in index.get(key, []):
            if not (mutagen_ok(q) and has_audio(q)):
                continue
            cands.append({'path': q,
                          'why': 'exact title+artist',
                          'album': d.get('album', ''),
                          'same_format': q.rsplit('.', 1)[-1].lower()
                          == p.rsplit('.', 1)[-1].lower(),
                          'same_dir': os.path.dirname(q)
                          == os.path.dirname(p)})
        cands.sort(key=lambda c: (not c['same_dir'], not c['same_format']))
        e['resolved'] = cands[:5]
        if cands:
            e['verdict'] = 'REPLACE'
            found += 1
            print('   FOUND  %-42s album=%-22r <- %s'
                  % (os.path.basename(p)[-42:], cands[0]['album'][:22],
                     os.path.basename(cands[0]['path'])[-30:]))
        else:
            print('   NONE   %-42s (title=%r artist=%r)'
                  % (os.path.basename(p)[-42:], title[:18], artist))

    print('')
    print('placed: %d of %d' % (found, len(left)))
    with open('/tmp/repl_final2.json', 'w') as fh:
        json.dump(res, fh)
    print('wrote /tmp/repl_final2.json')


if __name__ == '__main__':
    main()
