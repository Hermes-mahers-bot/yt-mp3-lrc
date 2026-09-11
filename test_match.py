#!/usr/bin/env python3
"""Check the risky part: YouTube title -> artist/track -> LRCLIB synced-lyrics match.

Uses REAL YouTube title strings and REAL LRCLIB API calls (needs internet).
Run:  python3 test_match.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yt2mp3lrc import find_synced_lyrics, pick_output_stem, safe_filename, split_artist_track

# (YouTube title as yt-dlp reports it, uploader, duration_seconds)
CASES = [
    ("Alan Walker - Faded", "Alan Walker", 212),
    ("Alan Walker - Faded (Official Music Video)", "Alan Walker", 212),
    ("Cartoon, Jéja - On & On (feat. Daniel Levi) | Electronic Pop | NCS - Copyright Free Music",
     "NoCopyrightSounds", 208),
    ("Alan Walker - Sing Me To Sleep", "Alan Walker", 189),
    ("Jim Yosef - Firefly | Drum & Bass | NCS - Copyright Free Music", "NoCopyrightSounds", 227),
    ("Avicii - Wake Me Up (Official Video)", "Avicii", 273),
    ("Linkin Park - Numb (Official Music Video) [4K UPGRADE]", "Linkin Park", 187),
    # instrumentals - expected misses
    ("Elektronomia - Sky High | Progressive House | NCS - Copyright Free Music",
     "NoCopyrightSounds", 189),
    ("TheFatRat - Xenogenesis", "TheFatRat", 235),
]

hits = misses = 0
for title, uploader, duration in CASES:
    info = {"title": title, "uploader": uploader, "duration": duration}
    artist, track, album = split_artist_track(info)
    stem = pick_output_stem(artist, track, "track")
    lyrics = find_synced_lyrics(artist, track, album, duration)
    if lyrics:
        hits += 1
        print(f"HIT   {stem:<52} {len(lyrics.splitlines()):>4} lines")
    else:
        misses += 1
        print(f"MISS  {stem:<52}  artist={artist!r} track={track!r}")

print(f"\n{hits} hits, {misses} misses (instrumentals are expected misses)")
print("filename sanitising:", safe_filename('AC/DC - Back:In Black? "Live"'))
