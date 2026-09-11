#!/usr/bin/env python3
"""Tests for addlyrics.py - real LRCLIB calls, real ffmpeg, real-length files.

Run:  python3 test_addlyrics.py     (needs ffmpeg; writes into /tmp/alt)
"""
import hashlib, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ADD = HERE / "addlyrics.py"

D = Path("/tmp/alt"); shutil.rmtree(D, ignore_errors=True); D.mkdir(parents=True)


def make(path, artist="", title="", album="", seconds=8, freq=440):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
           f"sine=frequency={freq}:duration={seconds}", "-c:a", "libmp3lame", "-b:a", "192k"]
    for k, v in (("artist", artist), ("title", title), ("album", album)):
        if v:
            cmd += ["-metadata", f"{k}={v}"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def pcm(p):
    return hashlib.md5(subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "s16le", "-"],
                                      capture_output=True).stdout).hexdigest()


def tags(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(p)],
                       capture_output=True, text=True)
    return json.loads(r.stdout).get("format", {}).get("tags", {})


def run(*argv):
    r = subprocess.run([sys.executable, str(ADD), *argv], capture_output=True, text=True)
    return r.stdout + (("\n[stderr] " + r.stderr.strip()) if r.stderr.strip() else "")


def report(label, out):
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    print(out.strip())


# A) well tagged + real duration -> match from tags, embed, verify integrity
a = D / "A - tagged.mp3"; make(a, "Alan Walker", "Faded", "E", seconds=212)
before_a = pcm(a)
report("A) well-tagged file (Alan Walker / Faded, 212s)", run(str(a)))
assert pcm(a) == before_a, "audio must be bit-identical after embedding"
assert b"USLT" in a.read_bytes(), "lyrics tag must be present"
assert tags(a).get("title") == "Faded" and tags(a).get("artist") == "Alan Walker", "tags preserved"
assert (D / "A - tagged.lrc").exists(), "sidecar must be written"
print("PCM unchanged / USLT present / tags kept / sidecar written: OK")

# B) junk channel-style artist tag -> dropped, title-only fallback, must be flagged
b = D / "Let Me Down Slowly.mp3"; make(b, "ANN MUSIC", "Let Me Down Slowly", seconds=169)
out = run(str(b))
report("B) junk artist tag ('ANN MUSIC'), 169s -> title-only fallback", out)
assert "MATCHED ON THE TITLE ALONE" in out, "a title-only match must be flagged"

# C) no tags at all; the filename is the only clue
c = D / "Alan Walker - Sing Me To Sleep.mp3"; make(c, seconds=189)
out = run(str(c))
report("C) no tags, filename 'Alan Walker - Sing Me To Sleep'", out)
assert "Alan Walker - Sing Me To Sleep" in out

# D) dry run must not touch anything
d = D / "D - dry.mp3"; make(d, "Avicii", "Wake Me Up", seconds=273)
before_d = pcm(d)
report("D) --dry-run (Avicii / Wake Me Up)", run(str(d), "--dry-run"))
assert pcm(d) == before_d and not (D / "D - dry.lrc").exists(), "dry run must change nothing"
print("nothing changed: OK")

# E) explicit flags beat junk tags
e = D / "E.mp3"; make(e, "totally wrong", "also wrong", seconds=187)
out = run(str(e), "--artist", "Linkin Park", "--title", "Numb")
report("E) --artist/--title override junk tags", out)
assert "Numb" in out

# F) instrumental: must NOT pick up an unrelated same-title/same-duration song
f = D / "F.mp3"; make(f, "TheFatRat", "Xenogenesis", seconds=233)
out = run(str(f))
report("F) instrumental (Xenogenesis 233s) - must be a clean miss", out)
assert "3TEETH" not in out, "must not match the 3TEETH song of the same name"
assert "no lyrics found" in out

# G) --no-sidecar -> strictly one file
g = D / "G.mp3"; make(g, "Alan Walker", "Faded", seconds=212)
out = run(str(g), "--no-sidecar")
report("G) --no-sidecar", out)
assert sorted(x.name for x in D.glob("G*")) == ["G.mp3"], "must leave exactly one file"

# H) non-mp3 refused
h = D / "H.ogg"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=3",
                "-c:a", "libvorbis", str(h)], check=True)
out = run(str(h))
report("H) .ogg must be refused", out)
assert "only .mp3 is supported" in out

# I) rerun on A is a no-op
out = run(str(a))
report("I) rerun on A", out)
assert "already present" in out

# L) --link with several files is refused
out = run(str(a), str(g), "--link", "https://x")
report("L) --link + 2 files must error", out)
assert "single file" in out

print("\nALL ADDLYRICS TESTS PASSED")
