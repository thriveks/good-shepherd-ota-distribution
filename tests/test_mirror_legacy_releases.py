import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).parents[1] / "tools/mirror_legacy_releases.py"
spec = importlib.util.spec_from_file_location("legacy_ota_mirror", path)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)

def release(name="good_shepherd_esp32_motion.ino.bin", digest="sha256:" + "a" * 64):
    return {"draft": False, "immutable": True, "assets": [
        {"name": name, "digest": digest, "size": 1200000}]}

class LegacyMirrorTests(unittest.TestCase):
    def test_only_known_binary_names_are_accepted(self):
        self.assertIn("good_shepherd_esp32_motion.ino.bin", mirror.assets(release()))
        for filename in ("source.ino", "private.pem", "passwords.json", "other.bin"):
            with self.assertRaises(ValueError):
                mirror.assets(release(name=filename))

    def test_missing_or_duplicate_assets_are_rejected(self):
        with self.assertRaises(ValueError):
            mirror.assets({"assets": []})
        row = release()
        row["assets"].append(row["assets"][0])
        with self.assertRaises(ValueError):
            mirror.assets(row)
        with self.assertRaises(ValueError):
            mirror.assets(release(digest="invalid"))

    def test_target_must_be_immutable_and_checksum_identical(self):
        row = release()
        identity = mirror.assets(row)
        self.assertTrue(mirror.checked(row, identity))
        self.assertFalse(mirror.checked({**row, "immutable": False}, identity))
        self.assertFalse(mirror.checked({**row, "draft": True}, identity))
        self.assertFalse(mirror.checked(row, {"wrong.bin": ("a", 3)}))

if __name__ == "__main__":
    unittest.main()
