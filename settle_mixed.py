#!/usr/bin/env python3
"""Settle the mixed-format album question, and fix it.

Observed on SevenDust "All I See Is War (2018)": 24 files, each track
present as BOTH .m4a and .mp3. After the import + replaygain + write
the M4As carry 5 analysis fields and the MP3s carry 1.

The DB shows the cause clearly: the .m4a rows have a gain and the
.mp3 rows have gain=None. So beets computed the gain for one format
and not the other.

Two things to check:
  1. HOW MANY ALBUMS did the import create? If the mixed formats
     became two albums, then the album-level gain ran on one and the
     other album's items were never computed.
  2. Did the ALBUM-level pass (`replaygain -a`) run at all, or did it
     error out?

The fix, whichever it is, is to process each FORMAT as its own album
so that every file gets its own gain computed. The simplest way to do
that without touching beets' internals: import the directory, then
run the per-TRACK gain pass (`replaygain` without -a) so every item
gets its track gain, and only the album-level pass is format-limited.

Actually the cleanest fix: run `replaygain` WITHOUT -a for the mixed
directories (per-track gain covers every item), and keep -a for the
rest. But the album gain is what players use for album-level
normalisation...

Better: split the import by format. Run the whole pipeline once per
FORMAT with a filtered file list. beets import accepts a path; the
album grouping comes from the album tag, so the same directory always
produces the same grouping.

So the real fix is at the FILE level: the writer must write the
values it HAS, and the runner must ensure every item HAS values. The
part where the gain is missing has to be fixed in the gain step.

This script:
  - imports the directory
  - dumps the ALBUMS table (album id, album name, item count)
  - runs `replaygain -a` and shows the output
  - dumps the DB again
  - runs `replaygain` (per track, no -a) and dumps again

Usage: settle_mixed.py <dir>
"""
import os
import subprocess
import sqlite3
import sys

BEET = '/lsiopy/bin/beet'
CFG = '/config/bulk-analyze.yaml'
ENV = {'BEETSDIR': '/config', 'PATH': '/lsiopy/bin:/usr/bin:/bin',
       'HOME': '/config'}


def run(db, *args):
    r = subprocess.run([BEET, '-c', CFG, '-l', db] + list(args),
                       cwd='/config', capture_output=True, text=True,
                       env=ENV, timeout=900)
    return r


def dump(db, label):
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute('pragma table_info(items)')]
    want = [c for c in ('path', 'rg_track_gain', 'rg_album_gain',
                        'rg_track_peak', 'rg_album_peak',
                        'acoustid_id') if c in cols]
    rows = list(con.execute('select %s from items' % ','.join(want)))
    withgain = 0
    for row in rows:
        d = dict(zip(want, row))
        if d.get('rg_track_gain') is not None:
            withgain += 1
    print('   %s: %d items, %d with a track gain' %
          (label, len(rows), withgain))
    # the albums table
    try:
        al = list(con.execute('select id, album, count(*) from albums '
                               'group by id limit 6'))
    except Exception:
        try:
            al = list(con.execute(
                'select a.id, a.album, count(i.id) from albums a '
                'left join items i on i.album_id=a.id group by a.id '
                'limit 6'))
        except Exception as e:
            al = [('ERR', str(e), 0)]
    for a in al:
        print('      album id=%s name=%r items=%s' % (a[0], str(a[1])[:44], a[2]))
    con.close()
    return withgain


def main():
    d = sys.argv[1]
    db = '/tmp/mixed.blb'
    subprocess.run(['rm', '-f', db])
    print('=== import ===')
    r = run(db, 'import', '-q', '-A', '-I', '-C', d)
    print('   rc=%d' % r.returncode)
    for l in (r.stdout or '').splitlines()[-4:]:
        print('   | %s' % l[:100])
    dump(db, 'after import')

    print('')
    print('=== replaygain -a (album level) ===')
    r = run(db, 'replaygain', '-a')
    print('   rc=%d' % r.returncode)
    for l in ((r.stdout or '') + (r.stderr or '')).splitlines()[-8:]:
        print('   | %s' % l[:110])
    dump(db, 'after replaygain -a')

    print('')
    print('=== replaygain -f -a (forced album level) ===')
    r = run(db, 'replaygain', '-f', '-a')
    print('   rc=%d' % r.returncode)
    for l in ((r.stdout or '') + (r.stderr or '')).splitlines()[-8:]:
        print('   | %s' % l[:110])
    dump(db, 'after replaygain -f -a')

    print('')
    print('=== replaygain -f (forced, per track) ===')
    r = run(db, 'replaygain', '-f')
    print('   rc=%d' % r.returncode)
    for l in ((r.stdout or '') + (r.stderr or '')).splitlines()[-6:]:
        print('   | %s' % l[:110])
    dump(db, 'after replaygain -f')


if __name__ == '__main__':
    main()
