#!/usr/bin/env python3
"""Test the FIX for a mixed-format album, and verify it on disk.

THE CAUSE (measured):
  SevenDust "All I See Is War (2018)" holds 24 files - each track as
  both .m4a and .mp3. beets imports them as ONE album of 24 items.
  The ALBUM-level gain pass then fails:
      replaygain: ffmpeg exited with status 234
  so the rows for the second format keep gain=None, and the writer
  has nothing to write for them. The M4As (imported first) came out
  tagged and the MP3s did not.

  The FORCED PER-TRACK pass computes every item:
      replaygain -f   ->  24 items, 24 with a track gain

THE FIX:
  Compute the album gain PER FORMAT. beets' query language can
  select a format, and each format's set is a single-format album
  that ffmpeg can handle:
      beet replaygain -a -f "format:MP3"
      beet replaygain -a -f "format:M4A"
  Then the per-track forced pass catches anything left over.

This script runs the candidate sequence and then VERIFIES by reading
the files back off the disk.

Usage: test_mixed_fix.py <dir>
"""
import os
import subprocess
import sqlite3
import sys

BEET = '/lsiopy/bin/beet'
CFG = '/config/bulk-analyze.yaml'
ENV = {'BEETSDIR': '/config', 'PATH': '/lsiopy/bin:/usr/bin:/bin',
       'HOME': '/config'}
AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus')


def run(db, *args):
    return subprocess.run([BEET, '-c', CFG, '-l', db] + list(args),
                          cwd='/config', capture_output=True, text=True,
                          env=ENV, timeout=1200)


def extensions(d):
    exts = set()
    for dirpath, _s, fs in os.walk(d):
        for f in fs:
            e = os.path.splitext(f)[1].lower()
            if e in AUDIO:
                exts.add(e)
    return sorted(exts)


def db_gains(db):
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute('pragma table_info(items)')]
    want = [c for c in ('path', 'rg_track_gain', 'rg_album_gain',
                        'rg_track_peak', 'rg_album_peak',
                        'acoustid_id', 'acoustid_fingerprint')
            if c in cols]
    rows = list(con.execute('select %s from items' % ','.join(want)))
    con.close()
    return rows, want


def main():
    d = sys.argv[1]
    db = '/tmp/fix.blb'
    subprocess.run(['rm', '-f', db])

    print('=== 1. import ===')
    r = run(db, 'import', '-q', '-A', '-I', '-C', d)
    print('   rc=%d' % r.returncode)

    exts = extensions(d)
    print('   formats: %s' % exts)

    print('')
    print('=== 2. album gain PER FORMAT ===')
    for e in exts:
        fmt = e.lstrip('.').upper()
        r = run(db, 'replaygain', '-a', '-f', 'format:%s' % fmt)
        errs = [l for l in ((r.stdout or '') + (r.stderr or '')).splitlines()
                if 'error' in l.lower() or 'status' in l.lower()]
        print('   format:%-5s rc=%d %s' % (fmt, r.returncode,
                                           errs[:2] if errs else ''))

    print('')
    print('=== 3. forced per-track gain (catches the rest) ===')
    r = run(db, 'replaygain', '-f')
    print('   rc=%d' % r.returncode)

    print('')
    print('=== 4. fingerprint ===')
    r = run(db, 'fingerprint')
    print('   rc=%d' % r.returncode)
    for l in ((r.stdout or '') + (r.stderr or '')).splitlines()[-3:]:
        print('   | %s' % l[:100])

    print('')
    print('=== 5. the DB ===')
    rows, want = db_gains(db)
    tg = sum(1 for r in rows if dict(zip(want, r)).get('rg_track_gain')
             is not None)
    ag = sum(1 for r in rows if dict(zip(want, r)).get('rg_album_gain')
             is not None)
    print('   %d items, %d with a track gain, %d with an album gain'
          % (len(rows), tg, ag))

    print('')
    print('=== 6. the metadata-free write ===')
    r = subprocess.run(['python3', '/config/write_analysis_only.py', db, d],
                       cwd='/config', capture_output=True, text=True,
                       env=ENV, timeout=900)
    for l in (r.stdout or '').splitlines()[:6]:
        print('   | %s' % l[:100])

    print('')
    print('=== 7. VERIFY on disk ===')
    ok = bare = 0
    for dirpath, _s, fs in os.walk(d):
        for f in sorted(fs):
            if not f.lower().endswith(AUDIO):
                continue
            p = os.path.join(dirpath, f)
            o = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
                 '-of', 'default=nw=1', p], capture_output=True, text=True,
                timeout=60).stdout.splitlines()
            an = len([l for l in o if 'replaygain' in l.lower()
                      or 'acoustid' in l.lower()])
            if an >= 4:
                ok += 1
            else:
                bare += 1
                print('   BARE an=%d %s' % (an, f[-46:]))
    print('   tagged: %d   bare: %d' % (ok, bare))


if __name__ == '__main__':
    main()
