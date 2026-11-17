#!/usr/bin/env python3
"""Place the last 9 broken files - a TARGETED search.

The full-library index was too slow over CIFS (49,566 files, one
ffprobe each). But these 9 files all belong to 6 artists, and each
artist's folder is small. So search only the relevant subtrees:

  Static-X  -> General Music/Static*X/
  The Cure  -> General Music/Cure, The/
  Opeth     -> General Music/Opeth/
  Slipknot  -> General Music/Slipknot/
  Tool      -> General Music/SoundTracks/Escape from LA*/
  Lecrae    -> Christian Music/Lecrae/

Match on EXACT normalised title + EXACT normalised artist (article-
insensitive). The album is reported, not required - these are bonus
and live tracks that are not on the standard release, which is why the
album-scoped search could not place them.

Usage: place_targeted.py
"""
import collections
import json
import os
import re
import subprocess
import sys
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


def title_from_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'_\d{6,}$', '', stem).strip()
    stem = re.sub(r'^[-–]\s*', '', stem)
    stem = re.sub(r'^\d{1,3}\s*[.\-_]\s*', '', stem)
    stem = re.sub(r'^\d{1,3}\s+', '', stem)
    if ' - ' in stem:
        stem = stem.split(' - ')[-1]
    return stem.strip()


def main():
    plan = json.load(open('/tmp/repl_final.json'))
    left = []
    for e in plan:
        p = e['broken']
        d = os.path.dirname(p)
        stem = os.path.basename(p)
        try:
            if any(f.startswith(stem + '.broken-') for f in os.listdir(d)):
                continue
        except Exception:
            pass
        left.append(e)
    print('=== the %d files still to place ===' % len(left))
    for e in left:
        print('   %-44s' % os.path.basename(e['broken'])[-44:])

    # the artist subtree for each broken file.
    # The layout is /music/<Category>/<Artist>/<Album>/<file>, so the
    # artist folder is the child of the category folder.
    def subtree(path):
        d = os.path.dirname(path)
        parent = os.path.basename(os.path.dirname(d))
        if parent in ('General Music', 'Christian Music', 'SoundTracks'):
            return d                       # the ARTIST folder
        # one level deeper (a disc subfolder) - climb to the artist
        p = os.path.dirname(d)
        for _ in range(3):
            gp = os.path.basename(os.path.dirname(p))
            if gp in ('General Music', 'Christian Music', 'SoundTracks'):
                return p
            p = os.path.dirname(p)
        return os.path.dirname(path)

    roots = set()
    for e in left:
        roots.add(subtree(e['broken']))
    print('')
    print('searching these trees:')
    for r in sorted(roots):
        print('   %s' % r)

    index = collections.defaultdict(list)
    print('')
    print('indexing...')
    for r in sorted(roots):
        n = 0
        for dirpath, _s, fs in os.walk(r):
            for f in fs:
                if not f.lower().endswith(AUDIO):
                    continue
                q = os.path.join(dirpath, f)
                d = ff_tags(q)
                t = nk(d.get('title', ''))
                a = nk_artist(d.get('artist', ''))
                if t and a:
                    index[(t, a)].append((q, d))
                n += 1
        print('   %-58s %d files' % (r[-58:], n))
    print('   index size: %d' % len(index))

    found = 0
    print('')
    for e in left:
        p = e['broken']
        title = title_from_name(p)
        # the artist for the broken file: the artist FOLDER
        art_dir = os.path.basename(subtree(p))
        keys = [(nk(title), nk_artist(art_dir))]
        # also try the album tag of a readable sibling
        try:
            for f in sorted(os.listdir(os.path.dirname(p))):
                if not f.lower().endswith(AUDIO):
                    continue
                sd = ff_tags(os.path.join(os.path.dirname(p), f))
                if sd.get('artist'):
                    keys.append((nk(title), nk_artist(sd['artist'])))
                    break
        except Exception:
            pass
        cands = []
        seen = set()
        for k in keys:
            for q, d in index.get(k, []):
                if q in seen:
                    continue
                seen.add(q)
                if not (mutagen_ok(q) and has_audio(q)):
                    continue
                cands.append({'path': q, 'why': 'exact title+artist',
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
            print('   FOUND  %-42s album=%-20r <- %s'
                  % (os.path.basename(p)[-42:], cands[0]['album'][:20],
                     os.path.basename(cands[0]['path'])[-28:]))
        else:
            print('   NONE   %-42s title=%-24r artist=%r'
                  % (os.path.basename(p)[-42:], title[:24], art_dir))
    print('')
    print('placed: %d of %d' % (found, len(left)))
    with open('/tmp/repl_last.json', 'w') as fh:
        json.dump(plan, fh)
    print('wrote /tmp/repl_last.json')


if __name__ == '__main__':
    main()
