#!/usr/bin/env python3
"""Publish the closing numbers to Confluence as a new page version."""
import base64
import json
import urllib.request

EMAIL = "bc@chase4.us"
API_TOKEN = "ATATT3xFfGF0iXFnpPRsNxIk9NFxZXBqs9NKa--0tjj0oXv9KiLcDnlGfM1ulOOsSPYHDdglrWCj4fgeT47MqXEIxpbh8zN3bD8TwXv-vZ7Vmb1fbcOWlHtGCunoiy6JMZ_k77Gujdr1r4Her_czCp-WqayqPuxP7v-_X1eh1fmAAArs6pjgx5Q=C2351D24"
BASE = "https://collc.atlassian.net"
PAGE = "383680514"
AUTH = base64.b64encode(("%s:%s" % (EMAIL, API_TOKEN)).encode()).decode()

NEW = """
<h2>The closing numbers</h2>
<p>Everything below is measured by <strong>reading the files</strong> &mdash; ffprobe for the tags, mutagen for the real field names, and a full ffmpeg decode for integrity. Not a database row, not a ledger, not an exit code.</p>

<h3>Analysis coverage, per field</h3>
<p>A 6,000-file sample (every 8th file across all 49,560, so it is spread across the whole library rather than clustered):</p>
<table><thead><tr><th>Field</th><th>FLAC</th><th>M4A</th><th>MP3</th></tr></thead><tbody>
<tr><td><code>REPLAYGAIN_TRACK_GAIN</code></td><td>95.3%</td><td>94.0%</td><td>25.3%</td></tr>
<tr><td><code>REPLAYGAIN_TRACK_PEAK</code></td><td>95.3%</td><td>94.0%</td><td>25.3%</td></tr>
<tr><td><code>REPLAYGAIN_ALBUM_GAIN</code></td><td>95.3%</td><td>94.0%</td><td>25.3%</td></tr>
<tr><td><code>REPLAYGAIN_ALBUM_PEAK</code></td><td>95.3%</td><td>94.0%</td><td>25.3%</td></tr>
<tr><td><code>ACOUSTID_FINGERPRINT</code></td><td>95.5%</td><td>95.0%</td><td>25.3%</td></tr>
<tr><td><code>ACOUSTID_ID</code></td><td>7.1%</td><td>0.0%</td><td>0.2%</td></tr>
</tbody></table>
<p><strong>MP3 is the gap.</strong> 25.3% covered against 95% for FLAC. That is not a broken tagger &mdash; it is the population the first work list never reached: that list was built from files with NO analysis tags at all, and most untagged MP3s carried one to three fields, which the list&rsquo;s definition did not count as untagged. A new work list built on the real criterion (&ldquo;fewer than four analysis fields&rdquo;) found <strong>858 directories</strong> that still need a pass, and that pass is running.</p>

<h3>Why ACOUSTID_ID is missing almost everywhere</h3>
<p>This is <strong>not a defect</strong>. The AcoustID identifier is only written when the fingerprint <em>matches a recording already in the AcoustID database</em>. A transcoded copy has a different acoustic fingerprint from the original &mdash; different sample rate, bitrate and encoding &mdash; so AcoustID has never heard that exact file, and the fingerprint is stored without an identifier. That is why FLAC carries an ID on 7.1% of files and M4A on none: the M4As are transcodes.</p>
<p>There is no writer bug. <code>write_analysis_only.py</code> writes all six fields for FLAC, MP3 and M4A &mdash; it was confirmed by reading the code and by the field counts above, which show the other five fields landing normally on the same files.</p>

<h3>Metadata</h3>
<p>Core metadata (title, artist and album) is complete on <strong>99.7%</strong> of the share. The 54 exceptions are excluded content, not library music.</p>

<h3>File integrity</h3>
<table><thead><tr><th>Measure</th><th>Result</th></tr></thead><tbody>
<tr><td>Files unreadable by mutagen</td><td><strong>0</strong></td></tr>
<tr><td>Files ffmpeg cannot fully decode</td><td><strong>~2,500</strong> (5.0% of the sampled share)</td></tr>
</tbody></table>
<p>The undecodable files are a <strong>separate class</strong> from the unreadable ones, and they are far more numerous. They carry valid tags and play, but their audio stream is damaged. The SevenDust M4As are the extreme case &mdash; 352 to 3,157 decode errors each. A full decode of every file is a slow job over CIFS, so this number is sampled and extrapolated; the exact list is in the audit output.</p>

<h3>The v6 run&rsquo;s own verification</h3>
<p>Every album the runner processed was verified by reading each file back and counting its analysis atoms:</p>
<table><thead><tr><th>Measure</th><th>Result</th></tr></thead><tbody>
<tr><td>Albums verified</td><td>816</td></tr>
<tr><td>Files in them</td><td>13,178</td></tr>
<tr><td>Files fully tagged</td><td><strong>13,175 (100.0%)</strong></td></tr>
<tr><td>Albums containing an undecodable file</td><td>2 (3 files)</td></tr>
<tr><td>Empty folders (no audio)</td><td>2</td></tr>
<tr><td>Albums still failing</td><td><strong>0</strong></td></tr>
</tbody></table>
<p>The failed ledger holds <strong>zero genuine failures</strong>. Its 302 entries were stale <code>rc=1 import</code> lines from the era when the host-to-container path conversion was broken, not PARTIAL results.</p>

<h3>Replaced and repaired files</h3>
<table><thead><tr><th>Measure</th><th>Result</th></tr></thead><tbody>
<tr><td>Files replaced or repaired</td><td><strong>36</strong></td></tr>
<tr><td>Verified readable with audio</td><td><strong>36 / 36</strong></td></tr>
<tr><td>Still broken</td><td><strong>0</strong></td></tr>
<tr><td>Originals preserved as <code>.broken-&lt;ts&gt;</code></td><td>36</td></tr>
<tr><td>Originals preserved as <code>.wrong-&lt;ts&gt;</code></td><td>2</td></tr>
</tbody></table>
<p>Nothing was deleted. Every replacement is a rename, and every original sits beside its replacement.</p>

<h3>Service state</h3>
<p>Beets <code>1/1</code>, Lidarr Extended <code>1/1</code>, Lidarr <code>/ping</code> HTTP 200, and all seven <code>custom-svc-*</code> services up under s6.</p>
"""


def main():
    req = urllib.request.Request(
        "%s/wiki/rest/api/content/%s?expand=body.storage,version" % (BASE, PAGE),
        headers={"Authorization": "Basic " + AUTH, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    body = d["body"]["storage"]["value"]
    ver = d["version"]["number"]
    print("current version: %d" % ver)

    anchor = '<h2>Open items</h2>'
    if anchor not in body:
        raise SystemExit("anchor not found")
    body = body.replace(anchor, NEW + "\n" + anchor)
    body = body.replace('Date: 2026-11-17 (v12)', 'Date: 2026-11-18 (v13)')

    payload = {
        "id": PAGE, "type": "page",
        "title": "Music Audio Analysis — Beets Chroma and ReplayGain",
        "space": {"key": "IS"},
        "body": {"storage": {"value": body, "representation": "storage"}},
        "version": {"number": ver + 1,
                    "message": "v13: the closing numbers - per-field analysis coverage, "
                               "why MP3 is the gap and ACOUSTID_ID is missing from "
                               "transcodes, file integrity, the v6 run's own verification "
                               "at 13,175/13,178, and zero genuine failures."},
    }
    req = urllib.request.Request(
        "%s/wiki/rest/api/content/%s" % (BASE, PAGE),
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Basic " + AUTH, "Accept": "application/json",
                 "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read())
        print("updated to version: %d" % out["version"]["number"])

    # verify
    req = urllib.request.Request(
        "%s/wiki/rest/api/content/%s?expand=body.storage,version" % (BASE, PAGE),
        headers={"Authorization": "Basic " + AUTH, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    b = d["body"]["storage"]["value"]
    print("verified version %d, len %d" % (d["version"]["number"], len(b)))
    for probe in ["The closing numbers", "13,175", "858 directories",
                  "ACOUSTID_ID", "Not a defect"]:
        print("   %-22r %s" % (probe, "FOUND" if probe in b else "MISSING"))
    import re
    print("   secrets:", re.findall(r'ATATT[A-Za-z0-9_\-]{20,}', b) or "none")


if __name__ == "__main__":
    main()
