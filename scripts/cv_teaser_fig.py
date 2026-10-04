"""CV teaser figure for page 1-2 of the paper: (a) our tracker on a real licensed rally, (b) one real broadcast test
bounce drawn top-down, (c) the call-to-order timeline.

    python scripts/cv_teaser_fig.py                 # draw  -> results/cv_teaser/fig_cv_teaser.{pdf,png}, caption.txt,
                                                    #          teaser_numbers.json
    python scripts/cv_teaser_fig.py extract --work WORK/eval
                                                    # one-off: copy the per-frame track of the chosen test bounce out of
                                                    # run_eval.py's work table -> results/cv_teaser/bounce_example.json

What is drawn, and where every number comes from (every printed number is also written to teaser_numbers.json with
its source file and key):

(a) A real rally, NOT broadcast footage: "Tennis Players Playing Match" by Gelato Prod, Pexels (Pexels License, see
    results/viz/v60_assets/tennis_real/LICENSE.md: modification allowed, attribution optional, no trademark rights).
    Frame 206 of the trimmed clip, cropped below the stadium; the one sponsor board in the crop (behind the far
    player) is painted out with the windscreen colour, and nobody is named. Orange: our tracked ball centres for the
    shot in frames 172-206 (tennis_detections.json ball_xy, joined only across gaps of <= 3 frames, as in
    tennis_tracked.mp4). Dashed: the nine court lines projected with that frame's fitted homography (court_H).
    No in/out call is made on this clip (single-camera 3D error 0.7-1.2 m).

(b) One real TEST bounce of the TrackNet broadcast evaluation (results/tennis_tracking; test games 8-10, thresholds
    from games 1-7). No broadcast pixel is shown: everything is court metres. The bounce is picked by a fixed rule:
    among the test outs that the margin rule called OUT at the 33 ms slot on TrackNet's own track ("ground"
    predictor; the paper's bt.call.33 = 3 of 3), the one whose decision frame came earliest before the bounce.
    Dots: TrackNet's track projected onto the court frame by frame (the "ground" predictor IS the latest tracked
    point projected to the court, so the last orange dot is the predicted landing at the call; a ball still in the
    air projects beyond where it will land, hence the hook). Orange band: the no-call margin tau(33 ms) = 95th
    percentile of the signed out-distance error on the train games; the rule calls OUT only when the predicted
    landing clears the line by more than tau. Black cross: the labelled bounce.

(c) The order budget of the paper's Eq. (1), V + delta + D - l, on a clock whose zero is the moment the ball lands
    (the point is decided); time runs down. l = 162 ms is the live causal engine's median first-call lead on
    held-out TABLE TENNIS (results/engine/online_vs_offline.json, 4 of 41 misses called); V = 1 s feed is SIMULATED
    (no licensed feed); delta = our measured frame -> order-ready 54 ms (laptop, WebRTC, table-tennis footage) +
    65 ms network (results/e2e/summary.json); D = the venue's 1 s taker hold. The shaded band is the range of the
    MEDIAN book reprice after the point under three stamp-lag readings (0.84 / 1.35 / 1.98 s; inferred from 482 live
    WTA points, not measured). "Order live" = V + delta + D - l is derived here (a composite of two sports).

House style: docs/paper/figstyle.py (Source Sans 3, 11-12 pt at print size, orange = ours, grey = others).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs/paper"))
import figstyle as fs  # noqa: E402

fs.apply()
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402

OUT = ROOT / "results/cv_teaser"
REAL = ROOT / "results/viz/v60_assets/tennis_real"
TT = ROOT / "results/tennis_tracking"
T = fs.THIN
O, G, K, M = fs.ORANGE, fs.GREY, fs.INK, fs.MUTED

# court model (metres; x across, y towards the far baseline, origin at the centre): src/tennis_tracking/geometry.py
HALF_LEN, SINGLES_HALF_W, DOUBLES_HALF_W, SERVICE_Y = 11.885, 4.115, 5.485, 6.40
COURT_LINES = {
    "far_baseline": ((-DOUBLES_HALF_W, HALF_LEN), (DOUBLES_HALF_W, HALF_LEN)),
    "near_baseline": ((-DOUBLES_HALF_W, -HALF_LEN), (DOUBLES_HALF_W, -HALF_LEN)),
    "left_doubles": ((-DOUBLES_HALF_W, -HALF_LEN), (-DOUBLES_HALF_W, HALF_LEN)),
    "right_doubles": ((DOUBLES_HALF_W, -HALF_LEN), (DOUBLES_HALF_W, HALF_LEN)),
    "left_singles": ((-SINGLES_HALF_W, -HALF_LEN), (-SINGLES_HALF_W, HALF_LEN)),
    "right_singles": ((SINGLES_HALF_W, -HALF_LEN), (SINGLES_HALF_W, HALF_LEN)),
    "far_service": ((-SINGLES_HALF_W, SERVICE_Y), (SINGLES_HALF_W, SERVICE_Y)),
    "near_service": ((-SINGLES_HALF_W, -SERVICE_Y), (SINGLES_HALF_W, -SERVICE_Y)),
    "centre_service": ((0.0, -SERVICE_Y), (0.0, SERVICE_Y)),
}

# (a): the shot drawn on the real rally (far-side hit at frame ~172 to the near player at frame 206)
A_FRAME, A_FIRST = 206, 172
A_CROP = (432, 345, 1240, 1080)          # x0, y0, x1, y1 in 1920x1080 clip pixels (below the stadium)
A_BOARD = (546, 399, 602, 457)           # the sponsor board behind the far player (painted out, not named)
A_HEAD = ((551, 429), (6, 8))            # the far player's head (ellipse) and shirt (box) in front of it: kept
A_SHIRT = (532, 437, 566, 470)
SLOT_MS = 33                             # (b): the margin-rule lead slot of the paper's bt.call.33

# layout (inches): 6.5 in text width
FIG_H = 2.30
COL_A = (0.00, 2.12)                     # left, width
COL_B = (2.24, 1.80)
COL_C = (4.16, 2.34)

NUM: dict[str, dict] = {}


def rec(key: str, text: str, raw, source: str) -> str:
    """Remember a printed number with its source (written to teaser_numbers.json)."""
    NUM[key] = {"text": text, "raw": raw, "source": source}
    return text


def jload(p: Path):
    with open(p) as f:
        return json.load(f)


# ============================================================================================ extract (one-off)
def extract(work: Path) -> Path:
    """Copy the chosen test bounce's per-frame track out of run_eval.py's work table (table_tracknet.pkl, court metres
    only) and check it against the committed results/tennis_tracking files before writing it."""
    import pandas as pd
    S = jload(TT / "summary.json")
    mr = S["headline"]["tracknet"]["out_calls_margin_rule"]["ground"]["test_by_lead"][str(SLOT_MS)]
    C = pd.read_csv(TT / "predictions_at_leads.csv")
    fl = pd.read_csv(TT / "flights.csv").set_index("fid")
    tau = mr["tau_cm"] / 100.0
    c = C[(C.source == "tracknet") & (C.split == "test") & (C.lead == SLOT_MS)]
    called = c[c.ground_d > tau]
    assert len(called) == mr["calls"] and int(called.is_out.sum()) == mr["tp"], "calls do not match summary.json"
    called = called[called.is_out.astype(bool)].sort_values(["lead_ms", "d_true"], ascending=[False, True])
    pick = called.iloc[0]
    fid = int(pick.fid)
    tab = pd.read_pickle(work / "table_tracknet.pkl")
    x = tab[tab.fid == fid].sort_values("kdec")
    # the work table must reproduce the committed per-lead rows of this flight (same rounding as the CSV)
    cf = C[(C.source == "tracknet") & (C.fid == fid)].sort_values("lead")
    for _, r in cf.iterrows():
        row = x[x.lead_ms >= r.lead - 1e-6].sort_values("lead_ms").iloc[0]
        for k in ("lead_ms", "ground_x", "ground_y", "ground_d"):
            assert abs(round(float(row[k]), 4) - float(r[k])) < 1e-3, (k, r.lead, row[k], r[k])
    f = fl.loc[fid]
    for k in ("x_b", "y_b", "d_true"):
        assert abs(float(x[k].iloc[0]) - float(f[k])) < 1e-3, k
    kdec = int(x.loc[(x.lead_ms - float(pick.lead_ms)).abs().idxmin(), "kdec"])
    out = {
        "what": ("One TrackNet-dataset TEST bounce (broadcast tennis), court metres only (no image pixels): TrackNet's "
                 "own ball track projected onto the court at every decision frame (= the 'ground' predictor), the "
                 "labelled bounce and the margin-rule call at the 33 ms slot."),
        "selection_rule": (f"test outs called OUT by the margin rule at the {SLOT_MS} ms slot on the TrackNet track "
                           "(ground predictor; summary.json headline.tracknet.out_calls_margin_rule.ground."
                           f"test_by_lead.{SLOT_MS}); the one whose decision frame is earliest before the bounce "
                           "(ties: nearest the line)"),
        "candidates": called[["fid", "lead_ms", "d_true", "ground_d"]].round(4).to_dict(orient="records"),
        "fid": fid, "game": int(f.game), "clip": str(f["clip"]), "split": str(f.split), "serve": bool(f.serve),
        "fps": float(f.fps), "hit_frame": int(f.hit), "bounce_frame_subframe": float(f.tb),
        "bounce_xy_m": [float(f.x_b), float(f.y_b)], "d_true_m": float(f.d_true), "is_out": bool(f.is_out),
        "slot_ms": SLOT_MS, "tau_m": tau,
        "tau_source": f"results/tennis_tracking/summary.json::headline.tracknet.out_calls_margin_rule.ground."
                      f"test_by_lead.{SLOT_MS}.tau_cm",
        "call": {"kdec": kdec, "lead_ms": float(pick.lead_ms),
                 "ground_xy_m": [float(pick.ground_x), float(pick.ground_y)], "ground_d_m": float(pick.ground_d),
                 "err_cm": float(pick.ground_err_cm)},
        "frames": [dict(kdec=int(r.kdec), lead_ms=round(float(r.lead_ms), 4), n_obs=int(r.n_obs),
                        x=round(float(r.ground_x), 4), y=round(float(r.ground_y), 4), d=round(float(r.ground_d), 4))
                   for r in x.itertuples() if np.isfinite(r.ground_x)],
        "source": ("work table of src/tennis_tracking/run_eval.py --stage final (table_tracknet.pkl, the run behind "
                   "results/tennis_tracking/summary.json); checked here against predictions_at_leads.csv and "
                   "flights.csv for this flight"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "bounce_example.json"
    with open(p, "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote", p.relative_to(ROOT), "fid", fid)
    return p


# ============================================================================================ panel (a)
def paint_out_board(fr: np.ndarray) -> np.ndarray:
    """Replace the sponsor board behind the far player with the windscreen colour (row by row, sampled just right of
    the board), keeping the player's head and shirt; 1.5-level noise and a 1 px feather so it reads as windscreen."""
    import cv2
    f = fr.astype(np.float32)
    x0, y0, x1, y1 = A_BOARD
    fill = np.zeros(fr.shape[:2], bool)
    fill[y0:y1, x0:x1] = True
    keep = np.zeros(fr.shape[:2], np.uint8)
    cv2.ellipse(keep, A_HEAD[0], A_HEAD[1], 0, 0, 360, 1, -1)
    cv2.rectangle(keep, A_SHIRT[:2], A_SHIRT[2:], 1, -1)
    fill &= keep == 0
    out = f.copy()
    for y in range(y0, y1):
        out[y, fill[y]] = np.median(f[y, x1 + 4:x1 + 16], axis=0)
    out[fill] += np.random.default_rng(0).normal(0, 1.5, (int(fill.sum()), 3)).astype(np.float32)
    a = cv2.GaussianBlur(fill.astype(np.float32), (0, 0), 0.8)[..., None]
    return np.clip(f * (1 - a) + out * a, 0, 255).astype(np.uint8)


def panel_a(fig, ax) -> None:
    import cv2
    D = jload(REAL / "tennis_detections.json")
    clip = ROOT / D["clip"]["file"]
    cap = cv2.VideoCapture(str(clip))
    cap.set(cv2.CAP_PROP_POS_FRAMES, A_FRAME)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        fs.placeholder(ax, str(clip.relative_to(ROOT)))
        return
    fr = paint_out_board(fr)
    x0, y0, x1, y1 = A_CROP
    img = cv2.cvtColor(fr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)
    ax.imshow(img, extent=(x0, x1, y1, y0), interpolation="none", aspect="auto", zorder=0)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_axis_off()

    F = D["frames"]
    Hm = np.array(F[A_FRAME]["court_H"], float)

    def proj(p):
        v = Hm @ np.array([p[0], p[1], 1.0])
        return v[:2] / v[2]

    for a, b in COURT_LINES.values():
        pa, pb = proj(a), proj(b)
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=fs.ORANGE_LIGHT, lw=0.9, ls=(0, (3.0, 2.0)), zorder=2,
                clip_on=True)
    pts = [(f["i"], f["ball_xy"]) for f in F[A_FIRST:A_FRAME + 1] if f["ball_xy"] is not None]
    seg: list[list[float]] = []
    prev = None
    for i, p in pts:
        if prev is not None and i - prev > 3:
            ax.plot(*np.array(seg).T, color=O, lw=1.5, zorder=3, solid_capstyle="round")
            seg = []
        seg.append(p)
        prev = i
    if seg:
        ax.plot(*np.array(seg).T, color=O, lw=1.5, zorder=3, solid_capstyle="round")
    xy = np.array([p for _, p in pts])
    ax.plot(xy[:, 0], xy[:, 1], "o", ms=1.9, color="white", mec=O, mew=0.5, zorder=4)
    ax.add_patch(Circle(F[A_FRAME]["ball_xy"], 15, fill=False, ec=O, lw=1.1, zorder=5))
    n_det, n_fr = len(pts), A_FRAME - A_FIRST + 1
    rec("a.shot_frames", f"{n_fr}", n_fr, f"tennis_detections.json frames {A_FIRST}-{A_FRAME} (the drawn shot)")
    rec("a.shot_detected", f"{n_det}", n_det, f"tennis_detections.json frames[{A_FIRST}..{A_FRAME}].ball_xy non-null")
    share = D["stats"]["ball_detected_share"]
    rec("a.clip_share", f"{share * 100:.0f}%", share, "results/viz/v60_assets/tennis_real/tennis_detections.json::"
        "stats.ball_detected_share (267/300 frames; paper key tn.real.ball)")
    rec("a.court_px", fs.f(D["stats"]["court"]["line_fit_px_median_p90_max"][0], 2),
        D["stats"]["court"]["line_fit_px_median_p90_max"][0],
        "tennis_detections.json::stats.court.line_fit_px_median_p90_max[0] (paper key tn.real.court_px)")

    box = dict(boxstyle="square,pad=0.22", facecolor="#0B1030", edgecolor="none", alpha=0.74)
    lab = dict(fontsize=fs.FS_SMALL, color="white", zorder=8, bbox=box, linespacing=1.05, annotation_clip=False)
    arrow = dict(arrowstyle="-", color="white", lw=0.6, shrinkA=0, shrinkB=3.0)
    ax.annotate(f"tracked ball\n{n_det} of {n_fr} frames", xy=F[184]["ball_xy"], xytext=(x1 - 14, y0 + 84),
                ha="right", va="center", arrowprops=arrow, **lab)
    ax.annotate("court lines\nfitted per frame", xy=proj((-1.5, -SERVICE_Y)),
                xytext=(x0 + 16, y1 - 88), ha="left", va="center", arrowprops=arrow, **lab)


# ============================================================================================ panel (b)
def panel_b(fig, ax) -> None:
    B = jload(OUT / "bounce_example.json")
    S = jload(TT / "summary.json")
    hl = S["headline"]["tracknet"]["out_calls_margin_rule"]["ground"]
    slot = str(B["slot_ms"])
    tau = B["tau_m"]
    assert abs(tau - hl["test_by_lead"][slot]["tau_cm"] / 100) < 1e-9
    bx, by = B["bounce_xy_m"]
    call = B["call"]
    cx, cy = call["ground_xy_m"]
    kc = call["kdec"]

    W_in, H_in = (ax.get_position().width * fig.get_size_inches()[0],
                  ax.get_position().height * fig.get_size_inches()[1])
    xlo, xhi = -0.80, 4.75
    yhi = 14.80
    ylo = yhi - (xhi - xlo) * H_in / W_in           # equal metres per inch on both axes
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    # court surface, no-call margin outside the singles lines, painted lines
    ax.add_patch(Rectangle((-SINGLES_HALF_W, -HALF_LEN), 2 * SINGLES_HALF_W, 2 * HALF_LEN, color="#F0F0F0", lw=0,
                           zorder=0.5))
    m = tau
    ax.add_patch(Polygon([(-SINGLES_HALF_W - m, HALF_LEN + m), (SINGLES_HALF_W + m, HALF_LEN + m),
                          (SINGLES_HALF_W + m, -HALF_LEN), (SINGLES_HALF_W, -HALF_LEN), (SINGLES_HALF_W, HALF_LEN),
                          (-SINGLES_HALF_W, HALF_LEN), (-SINGLES_HALF_W - m, HALF_LEN)], closed=True,
                         facecolor=fs.ORANGE_LIGHT, edgecolor="none", alpha=0.6, zorder=0.8))
    for name, (a, b) in COURT_LINES.items():
        ax.plot([a[0], b[0]], [a[1], b[1]], color=fs.AXIS, lw=1.1 if name == "far_baseline" else 0.8, zorder=1.5,
                solid_capstyle="butt")
    # TrackNet track projected onto the court: up to the call (orange) and after it (hollow grey, not used)
    fr = B["frames"]
    pre = np.array([(f["x"], f["y"]) for f in fr if f["kdec"] <= kc])
    post = np.array([(f["x"], f["y"]) for f in fr if f["kdec"] > kc])
    ax.plot(pre[:, 0], pre[:, 1], "-", color=O, lw=0.7, alpha=0.55, zorder=2)
    ax.plot(pre[:-1, 0], pre[:-1, 1], "o", ms=2.3, color=O, mec="white", mew=0.3, alpha=0.8, zorder=2.2)
    if len(post):
        ax.plot(np.r_[pre[-1:, 0], post[:, 0]], np.r_[pre[-1:, 1], post[:, 1]], color=G, lw=0.6, ls=fs.DOT_LS,
                zorder=2)
        ax.plot(post[:, 0], post[:, 1], "o", ms=2.6, mfc="white", mec=G, mew=0.7, zorder=2.3)
    ax.plot([cx], [cy], "o", ms=5.8, color=O, mec="white", mew=0.8, zorder=4)
    ax.plot([bx], [by], "x", ms=5.4, color=K, mew=1.4, zorder=4.2)

    err_cm = 100 * float(np.hypot(cx - bx, cy - by))
    lead = call["lead_ms"]
    d_hat, d_true = call["ground_d_m"], B["d_true_m"]
    rec("b.lead_ms", f"{lead:.0f}", lead, "results/cv_teaser/bounce_example.json::call.lead_ms (= results/"
        "tennis_tracking/predictions_at_leads.csv lead_ms, fid 53, lead 33, source tracknet)")
    rec("b.tau_cm", f"{tau * 100:.0f}", tau * 100, B["tau_source"])
    rec("b.d_hat_m", fs.f(d_hat, 2), d_hat, "results/tennis_tracking/predictions_at_leads.csv ground_d "
        "(fid 53, lead 33, source tracknet)")
    rec("b.d_true_cm", f"{d_true * 100:.0f}", d_true * 100, "results/tennis_tracking/flights.csv d_true (fid 53)")
    rec("b.err_cm", f"{err_cm:.0f}", err_cm, "results/tennis_tracking/predictions_at_leads.csv ground_err_cm "
        "(fid 53, lead 33, source tracknet)")
    rec("b.game", f"{B['game']}", B["game"], "results/tennis_tracking/flights.csv game (fid 53)")
    calls = hl["test_by_lead"][slot]
    rec("b.slot_calls", f"{calls['tp']} of {calls['calls']}", [calls["tp"], calls["calls"]],
        f"results/tennis_tracking/summary.json::headline.tracknet.out_calls_margin_rule.ground.test_by_lead.{slot}."
        "{tp,calls} (paper key bt.call.33)")
    rec("b.maxlead", f"{hl['max_lead_ms_with_train_precision_ge_95_and_3plus_calls']}",
        hl["max_lead_ms_with_train_precision_ge_95_and_3plus_calls"],
        "results/tennis_tracking/summary.json::headline.tracknet.out_calls_margin_rule.ground."
        "max_lead_ms_with_train_precision_ge_95_and_3plus_calls (paper key bt.maxlead)")

    kw = dict(fontsize=fs.FS_SMALL, zorder=9, annotation_clip=False, linespacing=1.05)
    ln = dict(arrowstyle="-", lw=0.5, shrinkA=0.5, shrinkB=3.0)
    xl = 1.95
    ax.annotate(f"predicted\n{lead:.0f}{T}ms early", xy=(cx, cy), xytext=(xl, 14.05), ha="left", va="center",
                color=O, arrowprops={**ln, "color": O}, **kw)
    ax.annotate(f"bounce\n{d_true * 100:.0f}{T}cm out", xy=(bx, by), xytext=(xl, 12.75), ha="left", va="center",
                color=K, arrowprops={**ln, "color": K}, **kw)
    ax.text(xl + 0.45, HALF_LEN - 0.12, "baseline", ha="left", va="top", color=M, fontsize=fs.FS_SMALL, zorder=9)
    ax.annotate(f"{tau * 100:.0f}{T}cm margin\n(95%, train)", xy=(SINGLES_HALF_W + tau * 0.5, 10.25),
                xytext=(0.55, 10.25), ha="left", va="center", color=fs.ORANGE_LIGHT_TEXT,
                arrowprops={**ln, "color": fs.ORANGE_LIGHT_TEXT}, **kw)
    low = pre[pre[:, 1] > ylo + 0.25][0]          # the first track dot inside the window
    ax.text(low[0] + 0.22, low[1], "track", ha="left", va="center", color=O, fontsize=fs.FS_SMALL, zorder=9)


# ============================================================================================ panel (c)
def panel_c(fig, ax) -> dict:
    E = jload(ROOT / "results/e2e/summary.json")
    V = jload(ROOT / "results/engine/online_vs_offline.json")
    A = V["runs"]["fp16_cl_fuse_compile_b1_realtime"]["A_engine_calls"]["miss_first_call_lead_ms"]
    bud = E["budget_with_1s_simulated_feed"]
    lead = float(A["median"]) / 1e3
    feed = float(bud["feed_simulated_ms"]) / 1e3
    ours = float(E["our_pipeline_frame_to_order_ready_ms"]["p50"]) / 1e3
    net = float(bud["network_one_way_ms"]["p50"]) / 1e3
    hold = float(bud["venue_delay_ms"]["p50"]) / 1e3
    rp = [v / 1e3 for v in bud["reprice_band_ms"]]
    t_frame = -lead
    t_arrive = t_frame + feed
    t_ready = t_arrive + ours
    t_venue = t_ready + net
    t_live = t_venue + hold
    rec("c.lead_ms", f"{lead * 1e3:.0f}", lead * 1e3, "results/engine/online_vs_offline.json::runs."
        "fp16_cl_fuse_compile_b1_realtime.A_engine_calls.miss_first_call_lead_ms.median (table tennis, held out; "
        "paper key cv.eng.lead)")
    rec("c.lead_n", f"{A['n_called']} of {A['n_miss']}", [A["n_called"], A["n_miss"]],
        "results/engine/online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.A_engine_calls."
        "miss_first_call_lead_ms.{n_called,n_miss} (paper keys cv.eng.tp, cv.eng.nmiss)")
    rec("c.feed_s", f"{feed:g}", feed, "results/e2e/summary.json::budget_with_1s_simulated_feed.feed_simulated_ms "
        "(SIMULATED)")
    rec("c.ours_ms", f"{ours * 1e3:.0f}", ours * 1e3,
        "results/e2e/summary.json::our_pipeline_frame_to_order_ready_ms.p50 (paper key e2e.ours)")
    rec("c.net_ms", f"{net * 1e3:.0f}", net * 1e3,
        "results/e2e/summary.json::budget_with_1s_simulated_feed.network_one_way_ms.p50 (paper key e2e.net)")
    rec("c.hold_s", f"{hold:g}", hold, "results/e2e/summary.json::budget_with_1s_simulated_feed.venue_delay_ms.p50")
    rec("c.live_s", fs.f(t_live, 2), t_live, "D: feed + ours + net + hold - lead = e2e.total - cv.eng.lead "
        "(Eq. 1 left side; composite: table-tennis lead, tennis venue)")
    rec("c.reprice_band_s", f"{fs.f(rp[0], 2)}–{fs.f(rp[1], 2)}", rp,
        "results/e2e/summary.json::budget_with_1s_simulated_feed.reprice_band_ms (median reprice after the point "
        "under three stamp-lag readings; inferred, not measured)")
    rec("c.e2e_total_ms", f"{bud['total_ms']['p50']:,.0f}", bud["total_ms"]["p50"],
        "results/e2e/summary.json::budget_with_1s_simulated_feed.total_ms.p50 (no lead credited; paper key e2e.total)")

    # time runs DOWN the panel; x is layout only (bar column at 0-0.06, labels to the right)
    ytop, ybot = -0.62, 2.16
    ax.set_ylim(ybot, ytop)
    ax.set_xlim(0, 1)
    ax.axhspan(rp[0], rp[1], color=fs.SHADE, lw=0, zorder=0.2)
    ax.axhline(0.0, color=fs.REF, ls=fs.DOT_LS, lw=fs.LW_VREF, zorder=0.5)
    bx0, bw = 0.012, 0.05
    ax.bar(bx0, feed, bottom=t_frame, width=bw, align="edge", color="white", edgecolor=G, lw=0.8,
           ls=(0, (2.5, 1.5)), zorder=3)
    ax.bar(bx0, lead, bottom=t_frame, width=bw, align="edge", color=O, lw=0, zorder=3.2)
    ax.bar(bx0, ours, bottom=t_arrive, width=bw, align="edge", color=O, lw=0, zorder=3)
    ax.bar(bx0, net, bottom=t_ready, width=bw, align="edge", color=G, lw=0, zorder=3)
    ax.bar(bx0, hold, bottom=t_venue, width=bw, align="edge", color=G, lw=0, zorder=3)
    ax.plot([bx0 - 0.01, bx0 + bw + 0.03], [t_live, t_live], color=O, lw=1.1, zorder=3.5, solid_capstyle="butt")

    items = [
        dict(x=bx0 + bw, y=t_frame, color=O, dy_pt=7.0,
             text=f"median call {lead * 1e3:.0f}{T}ms early\n(table tennis, {A['n_called']} calls)"),
        dict(x=bx0 + bw, y=t_frame + feed * 0.62, text=f"{feed:g}{T}s feed (simulated)", color=K),
        dict(x=bx0 + bw, y=t_ready, text=f"order ready: +{ours * 1e3:.0f}{T}ms (ours)", color=O),
        dict(x=bx0 + bw, y=t_venue, text=f"at venue: +{net * 1e3:.0f}{T}ms network", color=K),
        dict(x=bx0 + bw, y=t_venue + hold / 2, text=f"{hold:g}{T}s venue hold", color=K),
        dict(x=bx0 + bw + 0.03, y=t_live, text=f"order executable: {fs.f(t_live, 2)}{T}s", color=O),
    ]
    fs.direct_label(ax, items, dx_pt=5.0, pad_pt=1.0, leader_min_pt=3.0, linespacing=1.05)
    ax.annotate("ball lands", xy=(0.995, 0.0), xytext=(0, -1.5), textcoords="offset points", ha="right",
                va="top", color=K, fontsize=fs.FS_SMALL, zorder=6)
    ax.text(0.995, t_venue + hold * 0.5 + (t_live - t_venue - hold * 0.5) / 2, "book reprices", ha="right",
            va="center", color=M, fontsize=fs.FS_SMALL, zorder=6)
    ax.spines["bottom"].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["0", f"1{T}s", f"2{T}s"])
    ax.spines["left"].set_bounds(ytop + 0.02, ybot)
    return dict(lead=lead, feed=feed, ours=ours, net=net, hold=hold, live=t_live, reprice=rp)


# ============================================================================================ figure
def draw() -> list[str]:
    W, H = fs.FIG_W, FIG_H
    fig = plt.figure(figsize=(W, H))
    ty = H - 0.17
    top = H - 0.30
    ax_a = fs.axes_in(fig, COL_A[0], 0.0, COL_A[1], top)
    ax_b = fs.axes_in(fig, COL_B[0], 0.0, COL_B[1], top)
    ax_c = fs.axes_in(fig, COL_C[0] + 0.28, 0.04, COL_C[1] - 0.28, top - 0.06)
    panel_a(fig, ax_a)
    panel_b(fig, ax_b)
    c = panel_c(fig, ax_c)
    fs.panel(ax_a, "a", "Real rally, our tracker", x_in=COL_A[0], y_in=ty)
    fs.panel(ax_b, "b", f"Out call {NUM['b.lead_ms']['text']}{T}ms early", x_in=COL_B[0], y_in=ty)
    fs.panel(ax_c, "c", f"Early call, order at {NUM['c.live_s']['text']}{T}s", x_in=COL_C[0], y_in=ty)
    paths = fs.save_fig(fig, "fig_cv_teaser", OUT, meta={"Creator": "scripts/cv_teaser_fig.py"})
    write_caption(c)
    with open(OUT / "teaser_numbers.json", "w") as f:
        json.dump({"script": "scripts/cv_teaser_fig.py", "numbers": NUM}, f, indent=1, ensure_ascii=False)
    return paths + ["results/cv_teaser/caption.txt", "results/cv_teaser/teaser_numbers.json"]


def write_caption(c: dict) -> None:
    n = {k: v["text"] for k, v in NUM.items()}
    cap = (
        f"(a) Our tracker on a freely licensed real rally (Pexels, Gelato Prod; not broadcast footage; sponsor board "
        f"painted out): the ball in {n['a.shot_detected']} of the shot's {n['a.shot_frames']} frames and the court "
        f"lines fitted on every frame; no in/out call is made on this clip. "
        f"(b) A held-out TrackNet broadcast bounce (test game {n['b.game']}), drawn in court metres: predicted "
        f"{n['b.lead_ms']} ms early, the landing was {n['b.err_cm']} cm off but cleared the {n['b.tau_cm']} cm margin "
        f"(95th percentile of train error), one of {n['b.slot_calls'].split(' of ')[1]} correct test calls at that "
        f"lead; only bounce-time calls met our 95% rule on the train games. "
        f"(c) Eq. (1) on a clock: the median call is {n['c.lead_ms']} ms early (held-out table tennis, "
        f"{n['c.lead_n']} misses called), ours plus network {n['c.ours_ms']} + {n['c.net_ms']} ms, but a simulated "
        f"{n['c.feed_s']} s feed and the {n['c.hold_s']} s venue hold make the order executable {n['c.live_s']} s "
        f"after the point, inside the {n['c.reprice_band_s']} s range of median reprice estimates (inferred, not "
        f"measured)."
    )
    (OUT / "caption.txt").write_text(cap + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="draw", choices=["draw", "extract"])
    ap.add_argument("--work", type=Path, help="run_eval.py work dir holding table_tracknet.pkl (extract only)")
    a = ap.parse_args()
    if a.stage == "extract":
        if not a.work:
            ap.error("extract needs --work")
        extract(a.work)
        return
    for p in draw():
        print("wrote", p)


if __name__ == "__main__":
    main()
