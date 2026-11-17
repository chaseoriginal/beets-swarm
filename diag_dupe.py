#!/usr/bin/env python3
"""Why does SevenDust "All I See Is War (2018)" come back 12/24?

That album holds 24 files - each track as BOTH a .m4a and an .mp3.
The M4As come back with 5 analysis fields and the MP3s with 1.

Two candidate causes, and they need different fixes:

  A. THE DB ROWS FOR THE MP3s ARE EMPTY. The import merged the two
     formats into one album and computed the gains once; the second
     row per track has no values. Then the writer has nothing to
     write and no writer fix can help - the RUNNER must handle a
     multi-format album.

  B. THE WRITER COLLAPSES THE TWO ROWS. The writer's fallback index
     is keyed on (track, title), and setdefault keeps only the first
     row for a key. Both formats share that key, so one of them is
     never written.

This dumps: every DB row with its analysis values, the key the writer
computes for every row and every on-disk file, and how many rows
collide on each key. That settles it.

Usage: diag_dupe.py <container dir>
"""
import os
import re
import subprocess
import sqlite3
import sys

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus')


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def title_key(path):
    base = os.path.splitext(os.path.basename(path))[0]
    parts = base.split(" - ")
    title = parts[-1] if len(parts) > 1 else base
    track = ""
    for part in parts[:-1]:
        m = re.fullmatch(r"-?\s*(\d{1,3})", part.strip())
        if m:
            track = m.group(1)
            break
    return track, norm(title)


def list_audio(root):
    found = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path) and name.lower().endswith(AUDIO):
            found.append(path)
        elif os.path.isdir(path):
            for s2 in sorted(os.listdir(path)):
                p2 = os.path.join(path, s2)
                if os.path.isfile(p2) and s2.lower().endswith(AUDIO):
                    found.append(p2)
    return found


def main():
    d = sys.argv[1]
    db = '/tmp/dupe-check.blb'
    print('=== importing %s ===' % d)
    subprocess.run(['rm', '-f', db])
    r = subprocess.run(
        ['/lsiopy/bin/beet', '-c', '/config/bulk-analyze.yaml', '-l', db,
         'import', '-q', '-A', '-I', '-C', d],
        cwd='/config', capture_output=True, text=True,
        env={'BEETSDIR': '/config', 'PATH': '/lsiopy/bin:/usr/bin:/bin',
             'HOME': '/config'})
    print('   import rc=%d' % r.returncode)
    for l in (r.stdout or '').splitlines()[-6:]:
        print('   | %s' % l[:110])
    for l in (r.stderr or '').splitlines()[-4:]:
        print('   ! %s' % l[:110])

    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute('pragma table_info(items)')]
    want = [c for c in ('path', 'track', 'title', 'album', 'rg_track_gain',
                        'rg_album_gain', 'rg_track_peak', 'rg_album_peak',
                        'acoustid_id', 'acoustid_fingerprint') if c in cols]
    print('')
    print('=== the DB rows ===')
    print('   columns: %s' % want)
    rows = list(con.execute('select %s from items' % ','.join(want)))
    print('   %d rows' % len(rows))
    for row in rows[:30]:
        d0 = dict(zip(want, row))
        p = d0.get('path') or ''
        if isinstance(p, bytes):
            p = p.decode('utf-8', 'replace')
        key = title_key(p)
        gain = d0.get('rg_track_gain')
        print('   key=%-22s gain=%-9s ac=%-4s fp=%-4s %s'
              % (key, gain, bool(d0.get('acoustid_id')),
                 bool(d0.get('acoustid_fingerprint')),
                 os.path.basename(p)[-40:]))
    con.close()

    print('')
    print('=== key collisions among the DB rows ===')
    from collections import Counter
    keys = []
    for row in rows:
        p = row[0]
        if isinstance(p, bytes):
            p = p.decode('utf-8', 'replace')
        keys.append(title_key(p))
    c = Counter(keys)
    dupes = {k: v for k, v in c.items() if v > 1}
    print('   %d rows, %d distinct keys, %d keys shared by >1 row'
          % (len(keys), len(c), len(dupes)))
    for k, v in list(dupes.items())[:5]:
        print('      %r x%d' % (k, v))

    print('')
    print('=== the on-disk files ===')
    files = list_audio(d)
    print('   %d files' % len(files))
    ck = Counter(title_key(p) for p in files)
    for k, v in list(ck.items())[:5]:
        if v > 1:
            print('      %r x%d' % (k, v))


if __name__ == '__main__':
    main()
