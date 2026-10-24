import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('verify', Path(__file__).resolve().parents[1] / 'tools/verify_downloads.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class Integrity(unittest.TestCase):
    def test_tampered_and_truncated_image(self):
        image = bytearray(24)
        image[0:2] = bytes([0xe9, 1])
        image += struct.pack('<II', 0x3f400020, 8) + b'version\0' + b'\0'
        digest = hashlib.sha256(image).hexdigest()
        self.assertEqual(v.validate_image(image, digest, 'version'), digest)
        for broken in [image[:-2], b'html', image + b'changed']:
            with self.assertRaises(ValueError):
                v.validate_image(broken, digest)
        with self.assertRaises(ValueError):
            v.validate_image(image, digest, 'wrong-family-version')

    def test_unexpected_redirects_rejected_and_signed_queries_redacted(self):
        for url in ['http://github.com/asset', 'https://evil.example/asset',
                    'https://github.com/thriveks/good-shepherd-esp32-firmware/releases/download/x/y']:
            with self.assertRaises(ValueError):
                v.safe_url(url)
        self.assertEqual(v.safe_url('https://release-assets.githubusercontent.com/asset?sig=secret'),
                         'https://release-assets.githubusercontent.com/asset')
