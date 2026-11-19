#!/usr/bin/env python3
"""THE CLOSING NUMBERS.

Two sources, both measured from the FILES rather than from a ledger:

  1. THE V6 RUNNER'S OWN VERIFICATION. Every album it processed was
     verified by reading each file back and counting its analysis
     atoms. Those per-album "VERIFIED ok/total" lines cover 776
     albums and are summed here. This is free - the measurement was
     already made.

  2. A SAMPLED AUDIT. Every Nth file, so it is spread across the
     whole library rather than clustered, measured for metadata
     completeness, analysis coverage, readability and decodability.
     The sample is extrapolated for the corrupt count, and the
     whole-share totals are reported exactly as sampled.

Usage: closing_numbers.py [sample_size] [out.json]
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
LIB_PREFIX = ('/music/General Music', '/music/Christian Music')
BAD = ('Invalid data found', 'Error while decoding', 'Invalid packet',
       'Packet corrupt', 'error while decoding', 'Invalid nal unit')
# The log lives on the HOST, in the config volume. The container sees
# the volume mounted at /config, so try both.
LOG_CANDIDATES = [
    '/config/bulk-analysis.log',
    '/var/lib/docker/volumes/beets-swarm_config/_data/bulk-analysis.log',
]


def aggregate_log():
    """Sum the runner's own per-album verification."""
    ok = tot = 0
    albums = 0
    damaged_albums = 0
    dmg_files = 0
    empty = 0
    partials = []
    fh = None
    for cand in LOG_CANDIDATES:
        try:
            fh = open(cand, encoding='utf-8', errors='replace')
            break
        except OSError:
            continue
    if fh is None:
        print('   could not find the log in %s' % LOG_CANDIDATES)
        return {'albums': 0, 'ok': 0, 'total': 0, 'damaged_albums': 0,
                'damaged_files': 0, 'empty': 0, 'partials': []}
    try:
        with fh:
            for line in fh:
                m = re.search(r'VERIFIED (\d+)/(\d+)', line)
                if m:
                    albums += 1
                    ok += int(m.group(1))
                    tot += int(m.group(2))
                    if 'undecodable' in line:
                        damaged_albums += 1
                m2 = re.search(r'PARTIAL (\d+)/(\d+)', line)
                if m2:
                    partials.append(line.strip()[:120])
                m3 = re.search(r'DAMAGED (\d+) file', line)
                if m3:
                    dmg_files += int(m3.group(1))
                if 'EMPTY (no audio)' in line:
                    empty += 1
    except OSError as exc:
        print('   could not read the log: %s' % exc)
    return {'albums': albums, 'ok': ok, 'total': tot,
            'damaged_albums': damaged_albums, 'damaged_files': dmg_files,
            'empty': empty, 'partials': partials[-10:]}


def probe(p):
    out = {'p': p, 'ext': os.path.splitext(p)[1].lower(),
           'meta': False, 'an': 0, 'unreadable': False, 'damaged': False}
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=120)
        o = r.stdout.splitlines()
    except Exception:
        out['unreadable'] = True
        return out
    tags = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            tags[k.split(':')[-1].strip().lower()] = v.strip()
    out['an'] = len([k for k in tags
                     if 'replaygain' in k or 'acoustid' in k])
    out['meta'] = all(tags.get(k) for k in ('title', 'artist', 'album'))
    try:
        import mutagen
        m = mutagen.File(p, easy=True)
        if m is None or m.tags is None:
            out['unreadable'] = True
    except Exception:
        out['unreadable'] = True
    try:
        r2 = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=300)
        if any(b in (r2.stderr or '') for b in BAD):
            out['damaged'] = True
    except Exception:
        out['damaged'] = True
    return out


def main():
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/closing.json'

    print('=== 1. the runner\'s own verification, summed ===')
    agg = aggregate_log()
    print('   albums verified:      %d' % agg['albums'])
    print('   files in them:        %d' % agg['total'])
    print('   files fully tagged:   %d (%.1f%%)'
          % (agg['ok'], agg['ok'] * 100.0 / max(1, agg['total'])))
    print('   albums with an undecodable file: %d (%d files)'
          % (agg['damaged_albums'], agg['damaged_files']))
    print('   empty folders (no audio): %d' % agg['empty'])
    if agg['partials']:
        print('   still PARTIAL:')
        for p in agg['partials']:
            print('      %s' % p)

    print('')
    print('=== 2. the sampled audit ===')
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    step = max(1, len(files) // sample)
    sampled = files[::step][:sample]
    print('   %d files total, sampling %d (every %dth)'
          % (len(files), len(sampled), step))

    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=6) as ex:
        for res in ex.map(probe, sampled, chunksize=4):
            results.append(res)
            done += 1
            if done % 1000 == 0:
                print('   %d/%d' % (done, len(sampled)), flush=True)

    def report(name, subset):
        n = len(subset)
        if not n:
            return {}
        byext = Counter(r['ext'] for r in subset)
        meta = sum(1 for r in subset if r['meta'])
        an = sum(1 for r in subset if r['an'] >= 4)
        unread = sum(1 for r in subset if r['unreadable'])
        dmg = sum(1 for r in subset if r['damaged'])
        print('')
        print('   --- %s (n=%d) ---' % (name, n))
        print('      by format:         %s' % dict(sorted(byext.items())))
        print('      metadata complete: %d (%.1f%%)'
              % (meta, meta * 100.0 / n))
        print('      analysis tagged:   %d (%.1f%%)' % (an, an * 100.0 / n))
        print('      unreadable:        %d (%.2f%%)'
              % (unread, unread * 100.0 / n))
        print('      undecodable:       %d (%.2f%%)'
              % (dmg, dmg * 100.0 / n))
        return {'n': n, 'byext': dict(byext), 'meta': meta, 'analysis': an,
                'unreadable': unread, 'damaged': dmg,
                'damaged_rate': dmg * 100.0 / n}

    lib = [r for r in results if r['p'].startswith(LIB_PREFIX)]
    allr = report('WHOLE SHARE (sampled)', results)
    libr = report('MUSIC LIBRARY (sampled)', lib)
    if allr:
        print('')
        print('   extrapolated to the whole share: %d undecodable, %d unreadable'
              % (int(allr['damaged_rate'] / 100 * len(files)),
                 int(allr['unreadable'] * 100.0 / allr['n'] * len(files))))

    with open(outp, 'w') as fh:
        json.dump({'runner': agg, 'sample_all': allr, 'sample_lib': libr,
                   'sample_size': len(sampled), 'total_files': len(files),
                   'unreadable': [r['p'] for r in results if r['unreadable']],
                   'damaged': [r['p'] for r in results if r['damaged']]},
                  fh)
    print('')
    print('wrote %s' % outp)


if __name__ == '__main__':
    main()
