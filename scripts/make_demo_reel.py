"""Cut a ~40 s demo reel: title -> real-footage CV calls -> Hawk-Eye replay + real tape -> scorecard.

    .venv/bin/python scripts/make_demo_reel.py   ->  results/viz/courtside_demo_reel.mp4
"""
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path("results/viz/courtside_demo_reel.mp4")
TMP = Path("data/v2_video_frames/reel")
BG, INK, MUTED, RED, BLUE = "#07111b", "#e8eef4", "#8fa2b5", "#f06a52", "#3987e5"


def card(path: Path, lines: list[tuple[str, float, str, str]]):
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    for text, y, color, size in lines:
        ax.text(0.07, y, text, color=color, fontsize=size, fontweight="bold" if size > 26 else "normal",
                family="DejaVu Sans", va="center")
    fig.savefig(path, facecolor=BG); plt.close(fig)


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    c = json.loads(Path("results/v2/causal.json").read_text())
    is_, oos = c["causal/is_eval/slip0.0"], c["causal/burned_oos/slip0.0"]
    card(TMP / "title.png", [
        ("COURTSIDE", 0.66, INK, 64),
        ("Call the point before the ball lands. Trade before the market reprices.", 0.50, MUTED, 22),
        ("Gator Quant Hacks 2026 · Systematic Trading", 0.36, RED, 18)])
    card(TMP / "cv.png", [
        ("1  Computer vision on real 120 fps footage", 0.60, INK, 34),
        ("Held-out games · misses called before contact · 11 of 11 calls correct at 50 ms", 0.45, MUTED, 20),
        ("Footage: OpenTTGames (OSAI), CC BY-NC-SA 4.0", 0.33, MUTED, 14)])
    card(TMP / "tape.png", [
        ("2  Tennis: Hawk-Eye-class call → real Polymarket tape", 0.60, INK, 34),
        ("Simulated 340 fps call (±2.4 cm at 100 ms) beside a real 9.2¢ jump; fast-tier wallets in blue", 0.45, MUTED, 20)])
    card(TMP / "end.png", [
        ("v2 backtest · real fills · net of fees", 0.72, INK, 30),
        (f"In sample:      +{is_['per_share_c']:.2f}¢/share · Sharpe {is_['sharpe_ann']:.1f} · max DD {is_['max_dd_pct']:.1f}% · {is_['months_positive']}/{is_['months_total']} months", 0.57, BLUE, 22),
        (f"Out of sample:  +{oos['per_share_c']:.2f}¢/share · Sharpe {oos['sharpe_ann']:.1f} · max DD {oos['max_dd_pct']:.1f}%", 0.47, BLUE, 22),
        ("At the fast tier's own fills: the edge pays whoever is first. The CV call is how we get there.", 0.33, MUTED, 18),
        ("github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii", 0.20, MUTED, 14)])
    v = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p,setsar=1"
    inputs = ["-loop", "1", "-t", "3", "-i", str(TMP / "title.png"),
              "-loop", "1", "-t", "2.5", "-i", str(TMP / "cv.png"),
              "-i", "results/tracking/demo/supercut.mp4",
              "-loop", "1", "-t", "2.5", "-i", str(TMP / "tape.png"),
              "-i", "results/viz/courtside_replay.mp4",
              "-loop", "1", "-t", "5", "-i", str(TMP / "end.png")]
    fc = ";".join(f"[{i}:v]{v}[v{i}]" for i in range(6)) + ";" + "".join(f"[v{i}]" for i in range(6)) + "concat=n=6:v=1:a=0[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[out]",
                    "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)], check=True)
    for name, t in (("cv_call_frame", 11.0), ("tape_frame", 26.0)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(OUT), "-frames:v", "1",
                        str(OUT.parent / f"reel_{name}.png")], check=True)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
