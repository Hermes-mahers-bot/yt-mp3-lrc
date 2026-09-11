#!/usr/bin/env python3
"""Tests for the risky part: YouTube title -> artist/track -> LRCLIB lyric match.

Needs internet (calls the real LRCLIB API). Run:  python3 test_match.py
Exits non-zero if any expectation fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yt2mp3lrc import (artist_matches, find_lyrics, pick_output_stem, safe_filename,
                       split_artist_track, title_matches)

# ---- offline unit checks (no network) ----
UNIT = [
    # want, got, expected
    ("Alan Walker", "Alan Walker", True),
    ("Cartoon, Jéja", "Cartoon feat Daniel Levi", True),
    ("TheFatRat", "3TEETH", False),          # regression: wrote metal lyrics on an EDM track
    ("Jim Yosef", "Mura Masa feat. NAO", False),   # regression: wrong "Firefly"
    ("TheFatRat", "TheFatRat & NEFFEX", True),
    ("Linkin Park", "Linkin Park", True),
]
unit_fail = 0
print("=== artist guard (offline) ===")
for want, got, expect in UNIT:
    ok = artist_matches(want, got) is expect
    unit_fail += not ok
    print(f"  {'ok  ' if ok else 'FAIL'}  {want!r:<20} vs {got!r:<26} -> {artist_matches(want, got)}")

print("\n=== title guard (offline) ===")
# Deliberately loose: it shares "numb" with "Comfortably Numb" and passes. That is fine because
# the artist guard is the strict one - Pink Floyd would be rejected against Linkin Park there.
for want, got, expect in [("Firefly", "Firefly", True), ("Faded", "Faded", True),
                          ("Faded", "Faded (Remix)", True), ("Numb", "Comfortably Numb", True),
                          ("On & On", "On and On", True)]:
    ok = title_matches(want, got) is expect
    unit_fail += not ok
    print(f"  {'ok  ' if ok else 'FAIL'}  {want!r:<12} vs {got!r:<20} -> {title_matches(want, got)}")

# ---- live LRCLIB matching ----
# (YouTube title as yt-dlp reports it, uploader, duration, expect_lyrics)
CASES = [
    ("Alan Walker - Faded", "Alan Walker", 212, True),
    ("Alan Walker - Faded (Official Music Video)", "Alan Walker", 212, True),
    ("Cartoon, Jéja - On & On (feat. Daniel Levi) | Electronic Pop | NCS - Copyright Free Music",
     "NoCopyrightSounds", 208, True),
    ("Alan Walker - Sing Me To Sleep", "Alan Walker", 189, True),
    ("Jim Yosef - Firefly | Drum & Bass | NCS - Copyright Free Music", "NoCopyrightSounds", 227, False),
    # ^ LRCLIB has no lyrics for this track. Before the artist guard existed this matched
    #   "Firefly" by Mura Masa (224s) and wrote the wrong song's lyrics. Expect: nothing.
    ("Avicii - Wake Me Up (Official Video)", "Avicii", 273, True),
    ("Linkin Park - Numb (Official Music Video) [4K UPGRADE]", "Linkin Park", 187, True),
    # instrumentals: must NOT get lyrics (Xenogenesis is the 3TEETH false-positive case)
    ("TheFatRat - Xenogenesis", "TheFatRat", 235, False),
    ("Elektronomia - Sky High | Progressive House | NCS - Copyright Free Music",
     "NoCopyrightSounds", 189, False),
]

print("\n=== live LRCLIB matching ===")
fails = 0
for title, uploader, duration, expect in CASES:
    info = {"title": title, "uploader": uploader, "duration": duration}
    artist, track, album = split_artist_track(info)
    stem = pick_output_stem(artist, track, "track")
    found = find_lyrics(artist, track, album, duration)
    got = bool(found)
    ok = got is expect
    fails += not ok
    if found:
        kind = "synced" if found["synced"] else "plain"
        n = len((found["synced"] or found["plain"]).splitlines())
        detail = f"{kind}, {n} lines"
    else:
        detail = "no lyrics"
    print(f"  {'ok  ' if ok else 'FAIL'}  {stem:<50} expect={'lyrics' if expect else 'none':<7} got={detail}")

print("\nfilename sanitising:", safe_filename('AC/DC - Back:In Black? "Live"'))
total_fail = unit_fail + fails
print(f"\n{'ALL TESTS PASSED' if total_fail == 0 else f'{total_fail} FAILURE(S)'}")
sys.exit(1 if total_fail else 0)
