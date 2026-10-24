#!/usr/bin/env python3
"""Read-only byte verification of approved OTA and recovery downloads."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
REPO = 'thriveks/good-shepherd-ota-distribution'
SERVER = 'https://good-shepherd-server-j06f.onrender.com'
PUBLIC = 'https://github.com/' + REPO + '/releases/download/'
MAX_IMAGE = 0x1E0000


def safe_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {
        'github.com', 'release-assets.githubusercontent.com',
        'good-shepherd-server-j06f.onrender.com'
    } or 'good-shepherd-esp32-firmware' in parsed.path:
        raise ValueError('Unexpected download destination')
    # Never persist signed GitHub redirect queries.
    return parsed.scheme + '://' + parsed.netloc + parsed.path


class Redirects(HTTPRedirectHandler):
    def __init__(self):
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({'status': code, 'url': safe_url(newurl)})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_image(image, expected, version=None):
    if len(image) < 32 or len(image) > MAX_IMAGE or image[0] != 0xE9:
        raise ValueError('Invalid ESP32 application header/slot size')
    count = image[1]
    if not 1 <= count <= 16:
        raise ValueError('Invalid ESP32 segment count')
    offset = 24
    for _ in range(count):
        if offset + 8 > len(image):
            raise ValueError('Truncated ESP32 segment header')
        length = struct.unpack_from('<I', image, offset + 4)[0]
        offset += 8 + length
        if offset >= len(image):
            raise ValueError('Truncated ESP32 application segment/checksum')
    actual = hashlib.sha256(image).hexdigest()
    if actual != expected:
        raise ValueError('SHA-256 mismatch: expected ' + expected + ', actual ' + actual)
    if version and version.encode() + b'\0' not in image:
        raise ValueError('Expected firmware family/version absent from application')
    return actual


def verify_url(url, entry, size):
    redirects = Redirects()
    safe_url(url)
    with build_opener(redirects).open(Request(url, headers={
        'User-Agent': 'Good-Shepherd-OTA-Integrity'
    }), timeout=120) as response:
        if response.status != 200:
            raise ValueError('HTTP ' + str(response.status))
        image = response.read(MAX_IMAGE + 1)
        if len(image) != size:
            raise ValueError('Incomplete download/size mismatch: ' + str(len(image)))
        actual = validate_image(image, entry['sha256'], entry.get('version'))
        return dict(url=safe_url(url), status=response.status, size=len(image), sha256=actual,
                    segments=image[1], chip_id=struct.unpack_from('<H', image, 12)[0],
                    version_verified=bool(entry.get('version')), redirects=redirects.chain)


def release(tag):
    result = subprocess.run(['gh', 'api', 'repos/' + REPO + '/releases/tags/' + tag],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Release lookup failed: ' + tag)
    return json.loads(result.stdout)


def main():
    report = []
    for entry in json.loads((ROOT / 'approved-downloads.json').read_text()):
        identity = entry['tag'] + '/' + entry['filename']
        row = {'role': entry['role'], 'asset': identity}
        try:
            metadata = release(entry['tag'])
            if metadata.get('immutable') is not True or metadata.get('draft'):
                raise ValueError('Release is mutable or draft')
            assets = [a for a in metadata['assets'] if a['name'] == entry['filename']]
            if len(assets) != 1 or assets[0].get('digest') != 'sha256:' + entry['sha256']:
                raise ValueError('Required distribution asset missing or digest mismatch')
            public = PUBLIC + identity
            proxy = SERVER + ('/firmware/human-presence/download/' if entry['family'] == 'human-presence'
                              else '/firmware/download/') + identity
            # Legacy sketch is intentionally stored with a direct stable mirror URL.
            endpoints = [public] if entry['filename'] == 'sketch_jun28a.ino.bin' else [proxy, public]
            row['downloads'] = []
            for url in endpoints:
                row['checking_url'] = url
                row['downloads'].append(verify_url(url, entry, assets[0]['size']))
            row.pop('checking_url', None)
            row['status'] = 'PASS'
        except Exception as error:
            row['status'] = 'FAIL'
            row['error'] = ('HTTP ' + str(error.code) if isinstance(error, HTTPError)
                            else str(error) if isinstance(error, ValueError) else type(error).__name__)
        report.append(row)
        print(row['status'] + ': ' + entry['role'] + ' ' + identity +
              (' — ' + row['error'] if 'error' in row else ' (public/proxy bytes and immutability verified)'))
    Path('ota-download-report.json').write_text(json.dumps(report, indent=2) + '\n')
    if any(r['status'] != 'PASS' for r in report):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
