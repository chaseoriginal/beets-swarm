#!/usr/bin/env python3
"""Resolve the retry list for the v6 runner.

Reads the failed ledger and the list of albums whose files were
replaced, resolves any glob to the real path, and writes the merged,
deduplicated work list.

Kept as a separate script because the path list contains a curly
apostrophe and a glob, and embedding that in shell quoting is what
broke the launcher.

Usage: build_retry_list.py <worklist-path>
"""
import glob
import os
import sys

CV = '/var/lib/docker/volumes/beets-swarm_config/_data'
EXTRA = [
    '/media/Multimedia/Music/General Music/Fuel/(2023) All That*Burnt.1',
    '/media/Multimedia/Music/General Music/Nevermore/(1996)The Politics of Ecstasy',
    '/media/Multimedia/Music/General Music/Static*X/(2004) [Beneath... Between... Beyond]',
    '/media/Multimedia/Music/General Music/Slipknot/(2008) All Hope Is Gone',
    '/media/Multimedia/Music/General Music/Cure, The/(1991) Lullaby(single)',
    '/media/Multimedia/Music/General Music/Opeth/Sorceress (Deluxe Edition)  2016',
    '/media/Multimedia/Music/Christian Music/Lecrae/All Things Work Together (2017)',
]


def read_all(patterns):
    paths = []
    for pat in patterns:
        try:
            with open(pat, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    line = line.rstrip('\n')
                    if line.startswith('/media/Multimedia/Music'):
                        paths.append(line)
        except OSError:
            pass
    return paths


def main():
    out = sys.argv[1]
    failed = read_all([CV + '/bulk-analysis.failed.v6.shard%d' % i
                       for i in range(4)])
    done = set(read_all([CV + '/bulk-analysis.done.v6.shard%d' % i
                         for i in range(4)]))
    todo = [p for p in failed if p not in done]

    extra = []
    for pat in EXTRA:
        if '*' in pat:
            extra.extend(sorted(glob.glob(pat)))
        else:
            extra.append(pat)

    paths = sorted(set(todo) | set(extra))
    with open(out, 'w', encoding='utf-8') as fh:
        for p in paths:
            fh.write(p + '\n')
    print('failed=%d done=%d todo=%d extra=%d -> %d'
          % (len(failed), len(done), len(todo), len(extra), len(paths)))
    for p in paths[:6]:
        print('   %s' % p)


if __name__ == '__main__':
    main()
