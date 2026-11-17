#!/usr/bin/env python3
"""The last 7 broken files - a direct, flexible search.

The earlier passes were too rigid, and each failure had a cause:

  "02 Sweat - Tool.mp3"       the title is "Sweat" and the ARTIST is
                              "Tool". Splitting on " - " and taking the
                              last part produced "Tool" as the title.
                              This file is a VARIOUS-ARTISTS soundtrack,
                              so the artist is in the filename, not the
                              folder.

  "12 Behind The Wall Of Sheep.mp3"
                              Static-X's track is "Behind the Wall of
                              BLOOD". "Sheep" is a different song by a
                              different band - the filename is simply
                              wrong, or it is a different release.

  "03 Homesick (Live).mp3"    the Cure single. The live version may not
                              be on the standard release.

So: try SEVERAL title interpretations of the filename, and search each
artist's tree for a title that CONTAINS the key words. Report every
candidate with its album so the match can be judged - do not apply
anything automatically unless the artist AND a strong title agree.

Usage: last7.py
"""
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
    return ''.join(ch for ch in s if ch.isalnum())


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


def stem_of(path):
    s = os.path.splitext(os.path.basename(path))[0]
    s = re.sub(r'_\d{6,}$', '', s).strip()
    s = re.sub(r'^[-–]\s*', '', s)
    return s


def title_variants(stem):
    """Every plausible title for this filename."""
    out = []
    # strip the track number prefix
    body = re.sub(r'^\d{1,3}\s*[.\-_]\s*', '', stem)
    body = re.sub(r'^\d{1,3}\s+', '', body)
    out.append(body)
    # "<title> - <artist>"  -> the title is the FIRST part
    if ' - ' in body:
        out.append(body.split(' - ')[0].strip())
        out.append(body.split(' - ')[-1].strip())
    # "<artist> - <title>"  -> the title is the LAST part
    parts = [p.strip() for p in stem.split(' - ') if p.strip()]
    for p in parts:
        if not re.fullmatch(r'\d{1,3}', p):
            out.append(p)
    # strip a trailing "(...)" qualifier
    b = re.sub(r'\s*\([^)]*\)\s*$', '', body).strip()
    out.append(b)
    if ' - ' in b:
        out.append(b.split(' - ')[0].strip())
    seen = set()
    res = []
    for t in out:
        k = nk(t)
        if k and k not in seen:
            seen.add(k)
            res.append(t)
    return res


def artist_tree(path):
    d = os.path.dirname(path)
    for _ in range(4):
        gp = os.path.basename(os.path.dirname(d))
        if gp in ('General Music', 'Christian Music', 'SoundTracks'):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(path)


def main():
    plan = json.load(open('/tmp/repl_last.json'))
    left = []
    for e in plan:
        p = e['broken']
        try:
            if any(f.startswith(os.path.basename(p) + '.broken-')
                   for f in os.listdir(os.path.dirname(p))):
                continue
        except Exception:
            pass
        left.append(e)
    print('=== the %d files still to place ===' % len(left))
    for e in left:
        p = e['broken']
        print('   %-44s  variants: %s'
              % (os.path.basename(p)[-44:],
                 ' | '.join(title_variants(stem_of(p)))))

    for e in left:
        p = e['broken']
        tree = artist_tree(p)
        vs = title_variants(stem_of(p))
        keys = set(nk(v) for v in vs)
        # the folder artist, plus any artist named in the filename
        arts = {nk_artist(os.path.basename(tree))}
        for v in vs:
            if ' - ' in v:
                arts.add(nk_artist(v.split(' - ')[-1]))
                arts.add(nk_artist(v.split(' - ')[0]))
        cands = []
        seen = set()
        for dirpath, _s, fs in os.walk(tree):
            for f in fs:
                if not f.lower().endswith(AUDIO):
                    continue
                q = os.path.join(dirpath, f)
                if q in seen:
                    continue
                seen.add(q)
                d = ff_tags(q)
                t = nk(d.get('title', ''))
                a = nk_artist(d.get('artist', ''))
                if not t:
                    continue
                # the candidate title must CONTAIN one of our variants
                # (or the other way round) as a whole word-prefix
                if not any(k and (t.startswith(k) or k.startswith(t))
                           for k in keys):
                    continue
                cands.append({'path': q, 'title': d.get('title', ''),
                              'artist': d.get('artist', ''),
                              'album': d.get('album', ''),
                              'artist_matches': a in arts})
        print('')
        print('   --- %s' % os.path.basename(p)[-44:])
        print('       tree=%s' % tree[-52:])
        if not cands:
            print('       NO CANDIDATE with a similar title in this tree')
            continue
        for c in cands[:14]:
            ok = 'ARTIST-OK' if c['artist_matches'] else 'artist-differs'
            print('       %-11s %-26r %-30r %r'
                  % (ok, c['title'][:26], c['artist'][:30], c['album'][:26]))


if __name__ == '__main__':
    main()
