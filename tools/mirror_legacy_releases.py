#!/usr/bin/env python3
"""Copy existing public OTA assets byte-for-byte, without importing Git history."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

OLD = "thriveks/good-shepherd-esp32-firmware"
NEW = "thriveks/good-shepherd-ota-distribution"
BINS = {"good_shepherd_esp32_motion.ino.bin",
        "good_shepherd_esp32_human_presence.ino.bin",
        "sketch_jun28a.ino.bin"}
REQUIRED = {"v2.1.1-ghost-pir-test1-20261011",
            "v2.4.8-recommission-20260924",
            "v2.4.7-recommission-20260924"}

def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("GitHub release operation failed")
    return result.stdout

def releases(repo):
    return [r for page in json.loads(gh("api", "repos/" + repo +
            "/releases?per_page=100", "--paginate", "--slurp")) for r in page]

def assets(release):
    expected = {}
    for a in release["assets"]:
        name, digest = a["name"], a.get("digest", "")
        if name not in BINS | {"request.json"} or not re.fullmatch(
                r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("Unapproved asset or digest")
        if name in expected:
            raise ValueError("Duplicate asset")
        expected[name] = (digest, a["size"])
    if not (set(expected) & BINS):
        raise ValueError("Firmware binary missing")
    return expected

def checked(release, expected):
    if release.get("draft") or release.get("immutable") is not True:
        return False
    return assets(release) == expected

def main():
    source = releases(OLD)
    if len(source) < 33 or not REQUIRED.issubset({r["tag_name"] for r in source}):
        raise ValueError("Incomplete historical inventory")
    target = {r["tag_name"]: r for r in releases(NEW)}
    wanted = {r["tag_name"]: assets(r) for r in source}
    if len(wanted) != len(source) or set(target) - set(wanted):
        raise ValueError("Duplicate or unexpected release tags")
    for tag, release in target.items():
        if not checked(release, wanted[tag]):
            raise ValueError("Existing destination tag is mutable or mismatched")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # Verify every old asset before writing any new release.
        for r in source:
            tag = r["tag_name"]
            folder = root / tag
            folder.mkdir()
            gh("release", "download", tag, "-R", OLD, "-D", str(folder))
            for filename, (digest, length) in wanted[tag].items():
                blob = (folder / filename).read_bytes()
                if len(blob) != length or "sha256:" + hashlib.sha256(blob).hexdigest() != digest:
                    raise ValueError("Original release checksum mismatch")
                if filename in BINS and (blob[:1] != b"\xe9" or length > 0x1E0000):
                    raise ValueError("Invalid ESP32 application image")
                if filename == "request.json":
                    parsed = json.loads(blob)
                    if set(parsed) != {"family", "firmwareVersion", "sha256",
                                      "sourceRevision", "runId", "tag"} or parsed["tag"] != tag:
                        raise ValueError("Unexpected provenance metadata")
        copied = 0
        for r in source:
            tag = r["tag_name"]
            if tag in target:
                continue
            gh("release", "create", tag, "-R", NEW, "--target", "main",
               "--draft", "--title", (r.get("name") or tag)[:160],
               "--notes", "Byte-identical historical OTA binary mirror")
            paths = [str(root / tag / name) for name in wanted[tag]]
            gh("release", "upload", tag, *paths, "-R", NEW)
            flags = ["--prerelease"] if r.get("prerelease") else []
            gh("release", "edit", tag, "-R", NEW, "--draft=false",
               "--latest=false", *flags)
            final = json.loads(gh("api", "repos/" + NEW + "/releases/tags/" + tag))
            if not checked(final, wanted[tag]):
                raise ValueError("New release not immutable or checksum-identical")
            copied += 1
    print(json.dumps({"historical_release_count": len(source),
                      "new_releases": copied, "all_checked": True}))

if __name__ == "__main__":
    main()
