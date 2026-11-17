#!/usr/bin/env python3
"""FINAL resolver for the REVIEW files - track and album both numeric-
and-token-aware.

Two things the previous pass got wrong:

  1. TRACK NUMBERS COMPARED AS STRINGS. "03" != "3", so every
     candidate whose own tag says "3" was rejected even though it is
     the same track. Compare them as integers.

  2. THE ALBUM CHECK ONLY USED TAGS. But many of these albums have
     NO readable sibling (every file in the folder is a stub), so the
     sibling album was empty and the check was skipped - which is how
     Static-X's "Breathe" got matched against The State's "Breathe".
     The album identity is ALSO in the FOLDER NAME, and that survives
     even when every file in it is broken:
        broken:  General Music/Static-X/(2004) [Beneath... Between... Beyond]/01 Breathe .mp3
        good:    .../Static-X - Between… Beyond… - 01 - Breathe.flac   (album tag + folder)
     So the album check compares the candidate's album TAG and its
     FOLDER NAME against the broken file's FOLDER NAME, on shared
     significant tokens. "beneath", "between", "beyond" all appear in
     both; the year and the brackets do not matter.

A candidate is accepted only when:
  - the track numbers match (as integers)
  - the titles match
  - the album matches by shared tokens (at least 2 significant
    tokens, or an exact normalised match)

Usage: resolve_final.py <repl_strict.json> <out.json>
"""
import collections
import json
import os
import re
import subprocess
import sys
import unicodedata

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
STOP = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'cd', 'disc',
        'deluxe', 'edition', 'remaster', 'remastered', 'expanded',
        'bonus', 'years', 'year', 'vol', 'volume', 'part', 'original',
        'soundtrack', 'ost', 'explicit', 'bonusdisc'}


def nk(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


def tokens(s):
    if not s:
        return set()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    words = re.findall(r'[a-z0-9]+', s)
    return set(w for w in words if w not in STOP and len(w) > 1)


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


def tracknum(d):
    t = d.get('track', '') or d.get('tracknumber', '')
    return t.split('/')[0].strip()


def ti(v):
    """Track number as an int, or None."""
    m = re.match(r'\s*(\d{1,3})', str(v or ''))
    return int(m.group(1)) if m else None


def parse_name(path):
    """(track_int, title) from a filename."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'_\d{6,}$', '', stem).strip()
    stem = re.sub(r'^[-–]\s*', '', stem)
    parts = [p.strip() for p in stem.split(' - ') if p.strip()]
    # shape A: "<artist> - <NN> - <title>"
    for i, p in enumerate(parts):
        if re.fullmatch(r'\d{1,3}', p) and i < len(parts) - 1:
            return ti(p), parts[-1]
    # shape B: "<NN> <title>"
    m = re.match(r'^(\d{1,3})[\s._-]+(.+)$', stem)
    if m:
        title = m.group(2).strip()
        if ' - ' in title:            # "<NN> <artist> - <title>"
            title = title.split(' - ')[-1].strip()
        return ti(m.group(1)), title
    # shape C: "<NN> <artist> - <title>"
    m = re.match(r'^(\d{1,3})\s+(.+)$', stem)
    if m:
        return ti(m.group(1)), m.group(2).split(' - ')[-1].strip()
    return None, stem


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


def album_match(broken_dir, cand_dir, cand_album, sib_album):
    """Do the two refer to the same album?"""
    bt = tokens(os.path.basename(broken_dir)) | tokens(sib_album or '')
    if not bt:
        return True, 'no-album-info'
    ct = tokens(os.path.basename(cand_dir)) | tokens(cand_album or '')
    if not ct:
        return True, 'no-album-info'
    exact = nk(os.path.basename(broken_dir)) and \
        nk(os.path.basename(broken_dir)) == nk(os.path.basename(cand_dir))
    shared = bt & ct
    if exact or len(shared) >= 2:
        return True, 'album ok (%d tokens)' % len(shared)
    if len(shared) == 1 and len(bt) == 1:
        return True, 'album ok (1 token)'
    return False, 'album mismatch (shared=%d)' % len(shared)


def main():
    plan = json.load(open(sys.argv[1]))
    outp = sys.argv[2]
    review = [e for e in plan if e['verdict'] == 'REVIEW']
    print('REVIEW files to resolve: %d' % len(review))

    ident = {}
    for e in review:
        p = e['broken']
        d = os.path.dirname(p)
        trk, title = parse_name(p)
        sib_album = ''
        try:
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith(AUDIO):
                    continue
                sp = os.path.join(d, f)
                if sp == p:
                    continue
                sd = ff_tags(sp)
                if sd.get('album'):
                    sib_album = sd['album']
                    break
        except Exception:
            pass
        ident[p] = {'track': trk, 'title': title, 'sibling_album': sib_album,
                    'dir': d}
        print('   %-42s trk=%-4s title=%-24r dir=%s'
              % (os.path.basename(p)[-42:], trk, title[:24],
                 os.path.basename(d)[:26]))

    print('')
    print('indexing...')
    by_key = collections.defaultdict(list)
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if not f.lower().endswith(AUDIO):
                continue
            q = os.path.join(root, f)
            st, stitle = parse_name(q)
            if st is None or not stitle:
                continue
            by_key[(st, nk(stitle))].append(q)
    print('   keys: %d' % len(by_key))

    resolved = 0
    for e in review:
        p = e['broken']
        v = ident[p]
        want_title = nk(v['title'])
        good = []
        seen = set()
        for q in by_key.get((v['track'], want_title), []):
            if q in seen:
                continue
            seen.add(q)
            if not (mutagen_ok(q) and has_audio(q)):
                continue
            qd = ff_tags(q)
            q_track = ti(tracknum(qd))
            if q_track is not None and v['track'] is not None \
                    and q_track != v['track']:
                continue
            ok, why = album_match(v['dir'], os.path.dirname(q),
                                  qd.get('album', ''), v['sibling_album'])
            if not ok:
                continue
            good.append({'path': q, 'why': 'track+title+' + why,
                         'album': qd.get('album', ''),
                         'same_format': q.rsplit('.', 1)[-1].lower()
                         == p.rsplit('.', 1)[-1].lower(),
                         'same_dir': os.path.dirname(q) == v['dir']})
        good.sort(key=lambda c: (not c['same_dir'], not c['same_format']))
        e['resolved'] = good[:6]
        e['ident_resolved'] = v
        if good:
            e['verdict'] = 'REPLACE'
            resolved += 1
            print('   RESOLVED   %-40s %-22s <- %s'
                  % (os.path.basename(p)[-40:], good[0]['why'],
                     os.path.basename(good[0]['path'])[-30:]))
        else:
            print('   UNRESOLVED %-39s trk=%s title=%r'
                  % (os.path.basename(p)[-39:], v['track'], v['title'][:22]))
    print('')
    print('resolved: %d of %d' % (resolved, len(review)))
    with open(outp, 'w') as fh:
        json.dump(plan, fh)


if __name__ == '__main__':
    main()
