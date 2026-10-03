"""Split the rally frame ranges of every video into GPU work chunks of ~CHUNK frames.

Writes WORK/ranges/<video>_<k>.txt ("start end" per line) and WORK/chunks.txt
("<video> <k>" per line, one line per SLURM array task)."""
import os
import sys

from common import ALL, WORK, rally_ranges

CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
os.makedirs(os.path.join(WORK, "ranges"), exist_ok=True)
lines = []
for v in ALL:
    cur, n, k = [], 0, 0
    for s, e in rally_ranges(v):
        cur.append((s, e))
        n += e - s
        if n >= CHUNK:
            open(os.path.join(WORK, "ranges", f"{v}_{k}.txt"), "w").write("".join(f"{a} {b}\n" for a, b in cur))
            lines.append(f"{v} {k}")
            cur, n, k = [], 0, k + 1
    if cur:
        open(os.path.join(WORK, "ranges", f"{v}_{k}.txt"), "w").write("".join(f"{a} {b}\n" for a, b in cur))
        lines.append(f"{v} {k}")
open(os.path.join(WORK, "chunks.txt"), "w").write("\n".join(lines) + "\n")
print(len(lines), "chunks")
