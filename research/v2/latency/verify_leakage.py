"""Adversarial re-check of the latency lens (reviewer script; does not touch the lens outputs).

Independent of research/v2/latency/load.py + analyze.py for the headline:
  * official clock: parses data/v2_latency/pbp/*.json directly (pointWinner, timestamp);
  * book: ONLY the legacy recorder (data/live/market_*, src/live_recorder.py), grep-prefiltered to
    the moneyline tokens of the WTA matches, own top-of-book / mid builder, own reprice rule
    (+-8 s window, half of the net move, net move >= 1c), plus a model-free event study;
  * clock check: Polymarket server "timestamp" vs local receive time "rt"; the same reprice rule on
    server time;
  * sources: own parsers for ESPN, PM sports websocket (both recorders) and the WTA public API,
    matched to the official log WITHOUT the lens's "T_p <= t_source + 2 s" filter, so a source that
    beat the official stamp would be visible.
Everything is cut at the lens snapshot (2026-10-03 12:45:15.7 UTC) so the numbers are comparable.
Also: leakage scan of the lens code + data window, and a lookahead audit of the cross-market P&L.

    .venv/bin/python research/v2/latency/verify_leakage.py
Writes research/v2/latency/out_verify/verify_summary.json (nothing else in the lens dir is touched).
"""
from __future__ import annotations

import datetime as dt
import glob
import gzip
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import orjson
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LENS = ROOT / "research" / "v2" / "latency"
OUTV = LENS / "out_verify"
CUT_MS = 1791031515700           # 2026-10-03T12:45:15.7Z = lens snapshot (summary.json book_last_utc)
OOS_START = dt.datetime(2026, 8, 25, 14, 15, tzinfo=dt.timezone.utc).timestamp() * 1000


def iso_ms(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", s.replace("-", " ")).split())


def same_player(a: str, b: str) -> bool:
    ta = {t for t in fold(a).split() if len(t) > 2}
    tb = {t for t in fold(b).split() if len(t) > 2}
    return bool(ta & tb)


def q(x):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], float)
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "median": round(float(np.median(x)), 3), "p10": round(float(np.percentile(x, 10)), 3),
            "p90": round(float(np.percentile(x, 90)), 3), "min": round(float(x.min()), 3), "max": round(float(x.max()), 3),
            "share_gt_1p3": round(float(np.mean(x > 1.3)), 4), "n_gt_1p3": int(np.sum(x > 1.3)),
            "share_gt_0": round(float(np.mean(x > 0)), 4)}


def jsonl(pattern: str):
    for f in sorted(glob.glob(pattern)):
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rb") as fh:
                for line in fh:
                    try:
                        yield orjson.loads(line)
                    except orjson.JSONDecodeError:
                        continue
        except (EOFError, OSError):
            continue


# ============================================================================ 1. official log
def load_pbp() -> pd.DataFrame:
    rows = []
    for f in sorted((ROOT / "data" / "v2_latency" / "pbp").glob("pbp_*.json")):
        d = json.loads(f.read_text())
        for p in d.get("points") or []:
            if not p.get("timestamp"):
                continue
            gs = p["scoreAfterPoint"]["gameScore"]
            rows.append({"key": f"{d['_tid']}|{d['_mid']}", "nA": d["_names"][0], "nB": d["_names"][1],
                         "n": p["pointNumber"], "set": p["setNumber"], "game": p["gameNumber"],
                         "pw": p.get("pointWinner"), "ga": str(gs["teamAScore"]).upper(), "gb": str(gs["teamBScore"]).upper(),
                         "T": iso_ms(p["timestamp"])})
    P = pd.DataFrame(rows).sort_values(["key", "n"]).reset_index(drop=True)
    P["T_prev"] = P.groupby("key").T.shift(1)
    P["T_next"] = P.groupby("key").T.shift(-1)
    last = P.groupby(["key", "set", "game"]).n.transform("max")
    P["game_end"] = P.n == last
    # official after-state (games per set, trailing 0-0 stripped, + game points) for point-level matching
    st = []
    for key, g in P.groupby("key", sort=False):
        games = []
        for r in g.itertuples():
            while len(games) < r.set:
                games.append([0, 0])
            if r.game_end:
                games[r.set - 1][0 if r.pw == "A" else 1] += 1
                ga = gb = "0"
            else:
                ga, gb = norm_pt(r.ga), norm_pt(r.gb)
            gt = [tuple(x) for x in games]
            while gt and gt[-1] == (0, 0):
                gt.pop()
            st.append((r.Index, (tuple(gt), ga, gb)))
    sd = dict(st)
    P["state"] = P.index.map(lambda i: sd.get(i))
    return P


def norm_pt(p) -> str:
    p = str(p or "0").strip().upper()
    return "A" if p in ("A", "AD", "AV") else p


# ============================================================================ 2. tokens + book (legacy recorder only)
def legacy_tokens() -> dict:
    conds = defaultdict(list)
    for r in jsonl(str(ROOT / "data/live/tokens_*.jsonl*")):
        for tok, m in (r.get("tokens") or {}).items():
            if m.get("tag") == "tennis" and tok not in [x[0] for x in conds[m["cond"]]]:
                conds[m["cond"]].append((tok, m["outcome"], m["slug"]))
    return conds


def map_matches(P: pd.DataFrame, conds: dict) -> dict:
    out = {}
    for key, g in P.groupby("key"):
        nA, nB = g.nA.iloc[0], g.nB.iloc[0]
        for c, toks in conds.items():
            if len(toks) != 2 or "doubles" in toks[0][2]:
                continue
            (t0, o0, sl), (t1, o1, _) = toks
            if same_player(nA, o0) and same_player(nB, o1):
                out[key] = {"tokA": t0, "tokB": t1, "slug": sl}
            elif same_player(nA, o1) and same_player(nB, o0):
                out[key] = {"tokA": t1, "tokB": t0, "slug": sl}
    return out


def load_tops(toks: set[str], tmpdir: Path) -> dict:
    pat = tmpdir / "toks.txt"
    pat.write_text("\n".join(sorted(toks)) + "\n")
    filt = tmpdir / "filtered.jsonl"
    with open(filt, "wb") as fo:
        for f in sorted(glob.glob(str(ROOT / "data/live/market_*.jsonl*"))):
            cat = ["gzip", "-dc", f] if f.endswith(".gz") else ["cat", f]
            p1 = subprocess.Popen(cat, stdout=subprocess.PIPE)
            subprocess.run(["grep", "-F", "-f", str(pat)], stdin=p1.stdout, stdout=fo, env={"LC_ALL": "C"})
            p1.wait()
    top = defaultdict(list)
    lag = []
    with open(filt, "rb") as fh:
        for line in fh:
            try:
                r = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            if not isinstance(r, dict):
                continue
            rt = r.get("rt")
            if rt is None or rt > CUT_MS + 60_000:
                continue
            et = r.get("event_type")
            ts = float(r.get("timestamp") or "nan")
            if et == "price_change":
                last = {}
                for x in r.get("price_changes", []):
                    if x.get("asset_id") in toks:
                        last[x["asset_id"]] = (float(x.get("best_bid") or "nan"), float(x.get("best_ask") or "nan"))
                for t, (bb, ba) in last.items():
                    top[t].append((rt, ts, bb, ba))
                if last:
                    lag.append(rt - ts)
            elif et == "best_bid_ask" and r.get("asset_id") in toks:
                top[r["asset_id"]].append((rt, ts, float(r.get("best_bid") or "nan"), float(r.get("best_ask") or "nan")))
            elif et == "book" and r.get("asset_id") in toks:
                bb = max((float(x["price"]) for x in r.get("bids", []) if float(x["size"]) > 0), default=np.nan)
                ba = min((float(x["price"]) for x in r.get("asks", []) if float(x["size"]) > 0), default=np.nan)
                top[r["asset_id"]].append((rt, ts, bb, ba))
    out = {}
    for t, v in top.items():
        a = np.array(v, float)
        a = a[np.argsort(a[:, 0], kind="stable")]
        ok = (a[:, 2] > 0) & (a[:, 3] < 1) & (a[:, 3] > a[:, 2]) & (a[:, 3] - a[:, 2] <= 0.05)
        out[t] = a[ok]
    filt.unlink(missing_ok=True)
    return out, np.array(lag)


def asof(ts, x, t):
    i = np.searchsorted(ts, t, "right") - 1
    return x[i] if i >= 0 else np.nan


def reprice(ts, mid, T, s, w_pre, w_post, min_move=0.01):
    """own rule: ref = mid as of T-w_pre, end = mid as of T+w_post, D = s*(end-ref) >= min_move;
    reprice = first quote in (T-w_pre, T+w_post] at >= half of D in the winner's direction."""
    ref, end = asof(ts, mid, T - w_pre), asof(ts, mid, T + w_post)
    if not (np.isfinite(ref) and np.isfinite(end)):
        return None, np.nan
    D = s * (end - ref)
    if D < min_move - 1e-9:
        return None, D
    a, b = np.searchsorted(ts, T - w_pre, "right"), np.searchsorted(ts, T + w_post, "right")
    mv = s * (mid[a:b] - ref)
    hit = np.nonzero(mv >= 0.5 * D - 1e-9)[0]
    return (float(ts[a + hit[0]]) if len(hit) else None), D


def book_vs_official(P, mm, tops):
    rows, curves = [], []
    grid = np.arange(-8.0, 8.01, 0.1)
    for r in P.itertuples():
        if r.key not in mm or r.pw not in ("A", "B") or r.T > CUT_MS - 30_000:
            continue
        a = tops.get(mm[r.key]["tokA"])
        if a is None or not len(a) or not (a[0, 0] + 60_000 <= r.T <= a[-1, 0] - 30_000):
            continue
        s = 1 if r.pw == "A" else -1
        gp = (r.T - r.T_prev) if np.isfinite(r.T_prev) else 20_000
        gn = (r.T_next - r.T) if np.isfinite(r.T_next) else 20_000
        w_pre, w_post = min(8_000, gp / 2), min(8_000, gn - 5_000)
        if w_post < 2_000:
            continue
        rt_ts, srv_ts, mid = a[:, 0], a[:, 1], (a[:, 2] + a[:, 3]) / 2
        th, D = reprice(rt_ts, mid, r.T, s, w_pre, w_post)
        o = np.argsort(srv_ts, kind="stable")
        th_srv, _ = reprice(srv_ts[o], mid[o], r.T, s, w_pre, w_post)
        th05, _ = reprice(rt_ts, mid, r.T, s, w_pre, w_post, min_move=0.005)
        rows.append({"key": r.key, "slug": mm[r.key]["slug"], "n": r.n, "T": r.T, "game_end": r.game_end, "D": D,
                     "t_book": th, "book_vs_T_s": (th - r.T) / 1000 if th else np.nan,
                     "book_srv_vs_T_s": (th_srv - r.T) / 1000 if th_srv else np.nan,
                     "book_vs_T_s_min05c": (th05 - r.T) / 1000 if th05 else np.nan})
        if gp >= 20_000 and gn >= 20_000:
            ref = asof(rt_ts, mid, r.T - 8_000)
            curves.append([s * (asof(rt_ts, mid, r.T + g * 1000) - ref) for g in grid])
    B = pd.DataFrame(rows)
    C = np.array(curves)
    es = {}
    if len(C):
        mc = np.nanmean(C, 0)
        half = 0.5 * mc[-1]
        es = {"n_points": int(len(C)), "mean_move_at_+8s_c": round(float(mc[-1] * 100), 3),
              "mean_move_at_T_c": round(float(mc[np.argmin(abs(grid))] * 100), 3),
              "mean_move_at_T-1s_c": round(float(mc[np.argmin(abs(grid + 1))] * 100), 3),
              "mean_move_at_T-2s_c": round(float(mc[np.argmin(abs(grid + 2))] * 100), 3),
              "share_of_move_done_by_T": round(float(mc[np.argmin(abs(grid))] / mc[-1]), 3),
              "mean_curve_half_crossing_s": round(float(grid[np.argmax(mc >= half)]), 2)}
    return B, es


# ============================================================================ 3. sources (no 2 s filter)
def game_changes(obs):
    """obs: time-sorted (rt, sets[(a,b)...], first) in A/B orientation -> [(rt, set_no, game_no, winner)]"""
    out, prev = [], None
    for rt, sets, first in obs:
        if sets is None:
            continue
        if prev is not None and not first:
            da = sum(a for a, _ in sets) - sum(a for a, _ in prev)
            db = sum(b for _, b in sets) - sum(b for _, b in prev)
            if (da, db) in ((1, 0), (0, 1)):
                k = max([i for i in range(len(sets)) if i >= len(prev) or sets[i] != prev[i]], default=None)
                if k is not None:
                    out.append((rt, k + 1, sets[k][0] + sets[k][1], "A" if da else "B"))
        prev = sets
    return out


def parse_pm(score):
    out = []
    for s in [x.strip() for x in (score or "").split(",") if x.strip()]:
        m = re.fullmatch(r"(\d+)-(\d+)(?:\(\d+-\d+\))?", s)
        if not m:
            return None
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def source_units(P):
    names = {k: (g.nA.iloc[0], g.nB.iloc[0]) for k, g in P.groupby("key")}

    def which(n1, n2):
        for k, (a, b) in names.items():
            if same_player(n1, a) and same_player(n2, b):
                return k, False
            if same_player(n1, b) and same_player(n2, a):
                return k, True
        return None, None

    units = []
    # ESPN (both endpoints, each its own state; earliest per game kept later)
    per = defaultdict(list)
    for r in jsonl(str(ROOT / "data/live_v2/espn_*.jsonl*")):
        if r.get("rt", 0) > CUT_MS or r.get("st") not in ("in", "post") or len(r.get("p", [])) != 2:
            continue
        k, flip = which(r["p"][0]["n"], r["p"][1]["n"])
        if k is None:
            continue
        sets = [(int(a or 0), int(b or 0)) for a, b in zip(r["p"][0].get("ls") or [], r["p"][1].get("ls") or [])]
        if flip:
            sets = [(b, a) for a, b in sets]
        per[(k, "espn", r["src"])].append((r["rt"], sets, bool(r.get("first"))))
    # PM sports websocket, both recorders
    for tag, pat in (("v2", "data/live_v2/pmsports_*.jsonl*"), ("legacy", "data/live/sports_*.jsonl*")):
        for r in jsonl(str(ROOT / pat)):
            if "gameId" not in r or "score" not in r or r.get("rt", 0) > CUT_MS:
                continue
            k, flip = which(r.get("homeTeam", ""), r.get("awayTeam", ""))
            if k is None:
                continue
            sets = parse_pm(r["score"])
            if sets is not None and flip:
                sets = [(b, a) for a, b in sets]
            per[(k, "pm_sports", tag)].append((r["rt"], sets, False))
    # WTA public API (list + score endpoints), keyed by official ids
    wta_pts = defaultdict(list)
    for r in jsonl(str(ROOT / "data/live_v2/wta_*.jsonl*")):
        if r.get("src") not in ("wta_list", "wta_score") or r.get("DrawMatchType") != "S" or r.get("rt", 0) > CUT_MS:
            continue
        k = f"{r['EventID']}|{r['MatchID']}"
        if k not in names:
            continue
        sets = []
        for i in (1, 2, 3):
            a, b = r.get(f"ScoreSet{i}A"), r.get(f"ScoreSet{i}B")
            if a in (None, "") and b in (None, ""):
                break
            sets.append((int(a or 0), int(b or 0)))
        per[(k, "wta_api", "both")].append((r["rt"], sets, bool(r.get("first"))))
        gt = list(sets)
        while gt and gt[-1] == (0, 0):
            gt.pop()
        wta_pts[k].append((r["rt"], (tuple(gt), norm_pt(r.get("PointA")), norm_pt(r.get("PointB"))), bool(r.get("first"))))
    for (k, src, sub), obs in per.items():
        obs.sort(key=lambda x: x[0])
        if src == "wta_api":   # CDN may re-serve older copies: keep first sighting of each state only
            seen, o2 = set(), []
            for rt, sets, first in obs:
                key_ = tuple(sets)
                if key_ in seen:
                    continue
                seen.add(key_)
                o2.append((rt, sets, first))
            obs = o2
        for rt, sn, gn, w in game_changes(obs):
            units.append({"key": k, "src": src, "sub": sub, "level": "game", "rt": rt, "set": sn, "game": gn, "winner": w})
    # WTA point level: first sighting of each official after-state that is unique in the official log
    for k, obs in wta_pts.items():
        obs.sort(key=lambda x: x[0])
        g = P[P.key == k]
        cnt = g.state.value_counts()
        seen, started = set(), False
        for rt, st, first in obs:
            if st in seen:
                continue
            seen.add(st)
            if first or not started:
                started = True
                continue
            if cnt.get(st, 0) == 1:
                p = g[g.state == st].iloc[0]
                if not p["game_end"]:
                    units.append({"key": k, "src": "wta_api", "sub": "point", "level": "point", "rt": rt,
                                  "n_point": int(p["n"])})
    return pd.DataFrame(units)


def poll_resumes():
    t = defaultdict(list)
    for r in jsonl(str(ROOT / "data/live_v2/polls_*.jsonl*")):
        if r.get("code") == 200:
            fam = {"espn_atp": "espn", "espn_wta": "espn", "wta_list": "wta_api", "wta_score": "wta_api"}.get(r.get("src"))
            if fam:
                t[fam].append(r["rt"])
    out = {}
    for f, v in t.items():
        v = np.unique(v)
        out[f] = np.append(v[1:][np.diff(v) > 10_000], v[:1])
    pm = np.unique([r["rt"] for r in jsonl(str(ROOT / "data/live_v2/pmsports_*.jsonl*")) if "gameId" in r] +
                   [r["rt"] for r in jsonl(str(ROOT / "data/live/sports_*.jsonl*")) if "gameId" in r])
    out["pm_sports"] = np.append(pm[1:][np.diff(pm) > 60_000], pm[:1])
    return out


def match_sources(U, P, B):
    rows = []
    bk = B.set_index(["key", "n"])
    for u in U.itertuples():
        g = P[P.key == u.key]
        if u.level == "game":
            c = g[(g.set == u.set) & (g.game == u.game) & g.game_end]
            if c.empty:
                continue
            p = c.iloc[0]
            win_ok = p["pw"] == u.winner
        else:
            p = g[g.n == u.n_point].iloc[0]
            win_ok = True
        pn, pT = int(p["n"]), float(p["T"])
        tb = bk.t_book.get((u.key, pn), np.nan) if (u.key, pn) in bk.index else np.nan
        rows.append({"key": u.key, "src": u.src, "sub": u.sub, "level": u.level, "rt": u.rt, "n": pn,
                     "delay_vs_T_s": (u.rt - pT) / 1000, "winner_ok": bool(win_ok),
                     "lead_vs_book_s": (tb - u.rt) / 1000 if tb is not None and np.isfinite(tb) else np.nan})
    S = pd.DataFrame(rows)
    # earliest observation per (source family, level, official point)
    S = S.sort_values("rt").drop_duplicates(["src", "level", "key", "n"], keep="first")
    return S


# ============================================================================ 4. leakage + lookahead audits
def leakage_scan():
    code = {f.name: f.read_text() for f in LENS.glob("*.py") if f.name != "verify_leakage.py"}
    bad = ["data/locked", "locked/", "is_prints", "universe", "derived/", "data/raw", "shadow_is", "walkforward_is",
           "jumps_is", "data-api.polymarket.com", "prices-history", "/trades?"]
    hits = {b: [n for n, s in code.items() if b in s] for b in bad}
    rts = []
    for pat in ("data/live_v2/*.jsonl*", "data/live/*.jsonl*"):
        for f in glob.glob(str(ROOT / pat)):
            if "market_" in f and f.endswith(".jsonl") and Path(f).stat().st_size > 1e8:
                continue          # 2 GB legacy file: checked through the filtered book instead
            for r in jsonl(f):
                if isinstance(r, dict) and "rt" in r:
                    rts.append(r["rt"])
                    break
    return {"forbidden_path_hits_in_lens_code": {k: v for k, v in hits.items() if v},
            "earliest_first_record_rt_utc": pd.Timestamp(min(rts), unit="ms").isoformat() if rts else None,
            "all_recordings_after_oos_start_i.e._forward_data": bool(min(rts) > OOS_START) if rts else None}


def cross_market_audit():
    X = pd.read_csv(LENS / "out" / "cross_market.csv")
    st = X[X.stale_sh.notna()] if "stale_sh" in X else X.iloc[0:0]
    return {
        "n_pairs": int(len(X)), "n_rows_with_pnl": int(len(st)),
        "pnl_rows_require_future_side_move_and_lag_gt_1p3": True,
        "share_pairs_that_moved": round(float(X.moved.mean()), 3),
        "pnl_hold_by_dir_known": st.groupby("dir_known").stale_net_usd.sum().round(1).to_dict(),
        "pnl_exit_by_dir_known": st.groupby("dir_known").stale_net_exit_usd.sum().round(1).to_dict(),
        "pnl_hold_by_smt": st.groupby("smt").stale_net_usd.sum().round(1).to_dict(),
        "pnl_exit_by_smt": st.groupby("smt").stale_net_exit_usd.sum().round(1).to_dict(),
        "set_winner_rows_dir_known_share": round(float(X[X.smt == "tennis_set_winner"].dir_known.mean()), 3),
    }


def lens_filter_audit():
    """How many lens source units on official-log matches never reached m1_source_leads.csv
    (the lens requires T_p <= t_source + 2 s, which structurally hides early observations)."""
    sys.path.insert(0, str(LENS))
    import load as L  # lens code, used ONLY to count what its matcher drops
    meta = L.load_meta()
    ev = L.events_table(meta)
    pm_u, _ = L.pm_sports_units(ev)
    U = pd.DataFrame(pm_u + L.espn_units(ev) + L.wta_units(ev)[0])
    U = U[~U.amb]
    S1 = pd.read_csv(LENS / "out" / "m1_source_leads.csv")
    M1 = pd.read_csv(LENS / "out" / "m1_points.csv")
    U = U[U.slug.isin(set(M1.slug)) & (U.rt <= CUT_MS)]
    U["ukey"] = U.apply(lambda r: f"{r.src}|{r.slug}|{r.set}|{r.game}|{r.level}|{r.pa}|{r.pb}", axis=1)
    U = U.sort_values("rt").drop_duplicates("ukey")
    got = set(zip(S1.src, S1.slug, S1.rt.round()))
    U["matched"] = [(s, sl, round(rt)) in got for s, sl, rt in zip(U.src, U.slug, U.rt)]
    return {"units_on_pbp_matches": U.groupby("src").size().to_dict(),
            "matched_into_m1_source_leads": U.groupby("src").matched.sum().astype(int).to_dict()}


# ============================================================================ main
def main():
    OUTV.mkdir(exist_ok=True)
    P = load_pbp()
    conds = legacy_tokens()
    mm = map_matches(P, conds)
    toks = {v["tokA"] for v in mm.values()}
    cache = ROOT / "data" / "v2_latency" / "verify_tops_cache.pkl"   # data/ is gitignored
    import pickle
    if cache.exists():
        tops, lag = pickle.loads(cache.read_bytes())
    else:
        with tempfile.TemporaryDirectory() as td:
            tops, lag = load_tops(toks, Path(td))
        cache.write_bytes(pickle.dumps((tops, lag)))
    B, es = book_vs_official(P, mm, tops)
    ok = B[B.t_book.notna()]
    res = {"matches_mapped": {k: v["slug"] for k, v in mm.items()},
           "ws_receive_minus_server_ts_ms": q(lag[np.isfinite(lag)]),
           "book_vs_T": {"own_rule_rt": q(ok.book_vs_T_s), "own_rule_server_ts": q(B.book_srv_vs_T_s),
                         "own_rule_min_move_0.5c": q(B.book_vs_T_s_min05c),
                         "game_end_points": q(ok[ok.game_end].book_vs_T_s), "D_ge_3c": q(ok[ok.D >= 0.03].book_vs_T_s),
                         "n_points_evaluated": int(len(B)), "share_with_reprice": round(float(B.t_book.notna().mean()), 3),
                         "share_net_move_to_loser": round(float((B.D < 0).mean()), 3),
                         "by_match_median": ok.groupby("slug").book_vs_T_s.median().round(2).to_dict(),
                         "by_match_n": ok.groupby("slug").size().to_dict()},
           "event_study": es}
    U = source_units(P)
    S = match_sources(U, P, B)
    res_ = poll_resumes()
    fam = {"espn": "espn", "pm_sports": "pm_sports", "wta_api": "wta_api"}
    S["post_outage"] = [bool(np.any((rt >= res_.get(fam[s], np.empty(0))) &
                                    (rt <= res_.get(fam[s], np.empty(0)) + (60_000 if s == "pm_sports" else 10_000))))
                        for s, rt in zip(S.src, S.rt)]
    src = {}
    for (s, lev), g in S.groupby(["src", "level"]):
        g2 = g[~g.post_outage]
        src[f"{s}:{lev}"] = {"delay_vs_official_T_s": q(g2.delay_vs_T_s), "lead_vs_book_s": q(g2.lead_vs_book_s),
                             "winner_agrees": round(float(g2.winner_ok.mean()), 3),
                             "incl_post_outage_lead_vs_book": q(g.lead_vs_book_s),
                             "n_before_official_T": int((g.delay_vs_T_s < 0).sum())}
    allL = S[~S.post_outage].lead_vs_book_s.dropna()
    res["sources_no_2s_filter"] = src
    res["sources_total"] = {"n_with_book": int(len(allL)), "n_lead_gt_1p3": int((allL > 1.3).sum()),
                            "max_lead_s": round(float(allL.max()), 2), "n_any_source_before_official_T":
                            int((S.delay_vs_T_s < 0).sum())}
    res["leakage_scan"] = leakage_scan()
    res["cross_market_audit"] = cross_market_audit()
    try:
        res["lens_matcher_filter_audit"] = lens_filter_audit()
    except Exception as e:  # pragma: no cover
        res["lens_matcher_filter_audit"] = {"error": repr(e)}
    S.to_csv(OUTV / "verify_source_leads.csv", index=False)
    B.to_csv(OUTV / "verify_book_vs_T.csv", index=False)
    (OUTV / "verify_summary.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
