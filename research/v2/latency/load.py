"""Loaders for the latency lens recordings in data/live_v2 (written by recorder.py).

Everything is keyed on "rt" = local receive time in ms. Score sources are turned into
"unit events" (a point or a game changes hands) oriented to the Polymarket moneyline:
winner = 0 means the player of outcome 0 (token index oi=0) won the unit.
"""
from __future__ import annotations

import datetime as dt
import difflib
import glob
import gzip
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import orjson
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "data" / "live_v2"
PRANK = {"0": 0, "15": 1, "30": 2, "40": 3, "A": 4, "AD": 4, "AV": 4, "G": 5}


def read(stream: str, live: Path = LIVE, with_run: bool = False):
    """Yield records of a stream across hourly/rotated files; with_run=True yields (run_tag, rec)
    (recorder.py restarts get a new run tag and a fresh asset-index space)."""
    files = sorted(glob.glob(str(live / f"{stream}_*.jsonl")) + glob.glob(str(live / f"{stream}_*.jsonl.gz")))
    files.sort(key=lambda f: f.replace(".gz", ""))
    for f in files:
        parts = Path(f).name.split(".")[0].split("_")
        run = "_".join(parts[1:3])
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rb") as fh:
                for line in fh:
                    try:
                        rec = orjson.loads(line)
                    except orjson.JSONDecodeError:
                        continue
                    yield (run, rec) if with_run else rec
        except (EOFError, OSError):
            continue


def iso_s(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ----------------------------------------------------------------------------- names
def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", s.replace("-", " ")).split())


def name_sim(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    # same surname (last token or any shared long token) and compatible first initial
    shared = {t for t in ta if len(t) > 2} & {t for t in tb if len(t) > 2}
    if shared:
        return 0.9 if ta[0][0] == tb[0][0] else 0.75
    return difflib.SequenceMatcher(None, a, b).ratio() * 0.85


# ----------------------------------------------------------------------------- polymarket meta
def load_meta(live: Path = LIVE) -> pd.DataFrame:
    rows = {}
    for run, rec in read("clobmeta", live, with_run=True):
        for i, m in (rec.get("tokens") or {}).items():
            rows[(run, int(i))] = {"run": run, "a": int(i), **m}
    df = pd.DataFrame(list(rows.values()))
    df["ra"] = list(zip(df.run, df.a))
    df["start_s"] = df.start.map(iso_s)
    return df


def events_table(meta: pd.DataFrame) -> pd.DataFrame:
    ml = meta[meta.smt == "moneyline"].drop_duplicates("tok")
    out = []
    for slug, g in ml.groupby("slug"):
        g = g.sort_values("oi")
        if len(g) != 2:
            continue
        out.append({"slug": slug, "gameId": g.gameId.iloc[0], "title": g.title.iloc[0], "start_s": g.start_s.iloc[0],
                    "n0": g.outcome.iloc[0], "n1": g.outcome.iloc[1], "tok0": g.tok.iloc[0], "tok1": g.tok.iloc[1],
                    "tick": float(g.tick.iloc[0] or 0.01), "doubles": "doubles" in slug, "src_meta": "v2"})
    ev = pd.DataFrame(out)
    lg = legacy_events()
    if len(lg):
        lg = lg[~lg.slug.isin(set(ev.slug))].assign(title=None, start_s=np.nan, tick=0.01, src_meta="legacy")
        ev = pd.concat([ev, lg[ev.columns]], ignore_index=True)
    return ev


def match_pair(na: str, nb: str, ev: pd.DataFrame, t_s: float, tol_h: float = 14.0):
    """Return (slug, flip) where flip=False means na <-> outcome 0. None if no confident match."""
    best = (0.0, None, None)
    cand = ev[(ev.start_s.isna() | (abs(ev.start_s - t_s) < tol_h * 3600)) & (~ev.doubles)]
    for r in cand.itertuples():
        s0 = min(name_sim(na, r.n0), name_sim(nb, r.n1))
        s1 = min(name_sim(na, r.n1), name_sim(nb, r.n0))
        s, flip = (s0, False) if s0 >= s1 else (s1, True)
        if s > best[0]:
            best = (s, r.slug, flip)
    return (best[1], best[2]) if best[0] >= 0.75 else (None, None)


# ----------------------------------------------------------------------------- score sources
def _games_total(sets: list[tuple[int, int]]) -> tuple[int, int]:
    return sum(a for a, _ in sets), sum(b for _, b in sets)


SEG = re.compile(r"(\d+)-(\d+)(?:\((\d+)-(\d+)\))?")


def parse_pm_score(score: str):
    segs = [s.strip() for s in (score or "").split(",") if s.strip()]
    out = []
    for s in segs:
        m = SEG.fullmatch(s)
        if not m:
            return None
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def game_units(obs: list[dict], src: str) -> list[dict]:
    """obs: time-ordered dicts with rt, slug, flip, sets=[(a,b),...] in source orientation (a = source player A).
    Emits one unit per change of total games; winner in outcome orientation (0/1)."""
    units = []
    prev = None
    for o in obs:
        sets = o["sets"]
        if sets is None:
            continue
        if prev is not None:
            ga0, gb0 = _games_total(prev)
            ga1, gb1 = _games_total(sets)
            da, db = ga1 - ga0, gb1 - gb0
            if (da, db) != (0, 0):
                amb = not ((da == 1 and db == 0) or (da == 0 and db == 1))
                wa = da > db
                # which set / game number changed
                k = max(i for i in range(max(len(sets), 1)) if i < len(sets)) if sets else 0
                for i in range(len(sets)):
                    p = prev[i] if i < len(prev) else (0, 0)
                    if sets[i] != p:
                        k = i
                g = sets[k][0] + sets[k][1] if sets else 0
                win_src = 0 if wa else 1
                units.append({"src": src, "slug": o["slug"], "rt": o["rt"], "level": "game", "amb": bool(amb),
                              "winner": win_src ^ int(o["flip"]), "set": k + 1, "game": g,
                              "pa": None, "pb": None, "state": str(sets)})
        prev = sets
    return units


def pm_sports_units(ev: pd.DataFrame, live: Path = LIVE) -> tuple[list[dict], dict]:
    by_gid = {int(r.gameId): r for r in ev.itertuples() if pd.notna(r.gameId)}
    per = defaultdict(list)
    seen_leagues = defaultdict(int)
    stream = list(read("pmsports", live)) + [dict(r, legacy=True) for r in read("sports", LEGACY)]
    for r in stream:
        if "gameId" not in r or "score" not in r:
            continue
        seen_leagues[r.get("leagueAbbreviation")] += 1
        e = by_gid.get(int(r["gameId"]))
        if e is None or e.doubles:
            continue
        s0 = name_sim(r.get("homeTeam", ""), e.n0)
        s1 = name_sim(r.get("homeTeam", ""), e.n1)
        flip = s1 > s0  # flip=True: home is outcome 1
        per[e.slug].append({"rt": r["rt"], "slug": e.slug, "flip": flip, "sets": parse_pm_score(r["score"]),
                            "live": r.get("live")})
    units = []
    for slug, obs in per.items():
        obs.sort(key=lambda o: o["rt"])
        units += game_units(obs, "pm_sports")
    return units, dict(seen_leagues)


def espn_units(ev: pd.DataFrame, live: Path = LIVE) -> list[dict]:
    per = defaultdict(list)
    cache = {}
    for r in read("espn", live):
        if r.get("st") not in ("in", "post") or len(r.get("p", [])) != 2:
            continue
        pa, pb = r["p"]
        key = (r["src"], r["id"])
        if key not in cache:
            cache[key] = match_pair(pa["n"], pb["n"], ev, r["rt"] / 1000)
        slug, flip = cache[key]
        if slug is None:
            continue
        la, lb = pa.get("ls") or [], pb.get("ls") or []
        sets = [(int(a or 0), int(b or 0)) for a, b in zip(la, lb)]
        per[(slug, r["src"])].append({"rt": r["rt"], "slug": slug, "flip": flip, "sets": sets,
                                      "first": r.get("first"), "st": r.get("st")})
    units = []
    for (slug, src), obs in per.items():
        obs.sort(key=lambda o: o["rt"])
        units += game_units(obs, "espn")
    return units


def _wta_sets(r: dict) -> list[tuple[int, int]]:
    out = []
    for k in (1, 2, 3):
        a, b = r.get(f"ScoreSet{k}A"), r.get(f"ScoreSet{k}B")
        if a in (None, "") and b in (None, ""):
            break
        out.append((int(a or 0), int(b or 0)))
    return out


def _pnorm(p) -> str:
    p = str(p or "0").strip().upper()
    return "A" if p in ("AD", "AV", "A") else p


def _prank(p: str, tb: bool) -> int:
    if tb:
        try:
            return int(p)
        except ValueError:
            return 0
    return PRANK.get(p, 0)


def wta_units(ev: pd.DataFrame, live: Path = LIVE, srcs=("wta_list", "wta_score")) -> tuple[list[dict], list[dict], dict]:
    """Point-level units from the WTA public API (earliest of list/score endpoints = source 'wta'),
    plus the official point-by-point log (one row per point with its timestamp)."""
    obs = defaultdict(list)
    pbp = {}
    names = {}
    cache = {}
    for r in read("wta", live):
        if r["src"] == "wta_pbp":
            k = (str(r["tid"]), r["mid"])
            n = r["pointNumber"]
            if (k, n) not in pbp:
                pbp[(k, n)] = r
            names[k] = r.get("names")
            continue
        if r["src"] not in srcs or r.get("DrawMatchType") != "S":
            continue
        k = (str(r["EventID"]), r["MatchID"])
        na = f'{r["PlayerNameFirstA"]} {r["PlayerNameLastA"]}'
        nb = f'{r["PlayerNameFirstB"]} {r["PlayerNameLastB"]}'
        if k not in cache:
            cache[k] = match_pair(na, nb, ev, r["rt"] / 1000)
        slug, flip = cache[k]
        if slug is None:
            continue
        obs[k].append({"rt": r["rt"], "src": r["src"], "slug": slug, "flip": flip, "sets": _wta_sets(r),
                       "pa": _pnorm(r.get("PointA")), "pb": _pnorm(r.get("PointB")), "state_src": r["MatchState"],
                       "first": r.get("first")})
    for r in cached_pbp():
        k = (str(r["tid"]), r["mid"])
        if (k, r["pointNumber"]) not in pbp:
            pbp[(k, r["pointNumber"])] = r
        if k not in cache and r.get("timestamp"):
            cache[k] = match_pair(r["_names"][0], r["_names"][1], ev, iso_s(r["timestamp"]))
    units = []
    for k, o in obs.items():
        o.sort(key=lambda x: x["rt"])
        seen = {}
        prev = None
        for x in o:
            st = (tuple(x["sets"]), x["pa"], x["pb"])
            if st in seen:          # an older CDN copy re-serving a state we already saw
                continue
            seen[st] = x["rt"]
            if prev is not None and not x["first"]:
                u = _wta_point_unit(prev, x)
                if u is not None:
                    units.append({**u, "src": "wta", "via": x["src"], "slug": x["slug"], "rt": x["rt"],
                                  "key": "|".join(k), "state": str(st)})
            prev = x
    pts = []
    for (k, n), r in pbp.items():
        slug, flip = cache.get(k, (None, None))
        pts.append({"key": "|".join(k), "slug": slug, "flip": flip, "n": n, "set": r["setNumber"], "game": r["gameNumber"],
                    "server": r.get("server"), "pw": r.get("pointWinner") or "",
                    "ga": str(r["scoreAfterPoint"]["gameScore"]["teamAScore"]),
                    "gb": str(r["scoreAfterPoint"]["gameScore"]["teamBScore"]),
                    "T": iso_s(r["timestamp"]) if r.get("timestamp") else np.nan, "rt_seen": r["rt"],
                    "first_poll": r.get("first")})
    P = pd.DataFrame(pts)
    if len(P):
        P = P.sort_values(["key", "n"]).reset_index(drop=True)
        P["winner_ab"] = _derive_pw(P)
        P["winner"] = np.where(P.winner_ab.isna(), np.nan,
                               (P.winner_ab == "B").astype(float).where(~P.flip.astype(bool), (P.winner_ab == "A").astype(float)))
        P["game_end"] = (P.ga == "G") | (P.gb == "G")
    return units, P.to_dict("records") if len(P) else [], {"wta_matches_seen": len(obs)}


def _derive_pw(P: pd.DataFrame) -> pd.Series:
    out = []
    prev_key = prev_game = None
    pa = pb = "0"
    for r in P.itertuples():
        if r.key != prev_key or (r.set, r.game) != prev_game:
            pa = pb = "0"
        tb = not (r.ga in PRANK and r.gb in PRANK)
        if r.pw in ("A", "B"):
            w = r.pw
        else:
            ra0, rb0, ra1, rb1 = _prank(pa, tb), _prank(pb, tb), _prank(r.ga, tb), _prank(r.gb, tb)
            if ra1 > ra0 and rb1 <= rb0:
                w = "A"
            elif rb1 > rb0 and ra1 <= ra0:
                w = "B"
            elif ra1 < ra0 and rb1 == rb0:   # lost advantage -> deuce
                w = "B"
            elif rb1 < rb0 and ra1 == ra0:
                w = "A"
            else:
                w = None
        out.append(w)
        pa, pb, prev_key, prev_game = r.ga, r.gb, r.key, (r.set, r.game)
    return pd.Series(out, index=P.index, dtype=object)


def _set_done(ab: tuple[int, int]) -> bool:
    a, b = ab
    return (max(a, b) >= 6 and abs(a - b) >= 2) or (max(a, b) == 7 and min(a, b) >= 5)


def _wta_point_unit(prev: dict, x: dict):
    ga0, gb0 = _games_total(prev["sets"])
    ga1, gb1 = _games_total(x["sets"])
    sets = x["sets"]
    cur = len(sets)
    if sets and sets[-1] == (0, 0) and len(sets) > 1:
        cur = len(sets) - 1
    if (ga1, gb1) != (ga0, gb0):
        da, db = ga1 - ga0, gb1 - gb0
        amb = not ((da == 1 and db == 0) or (da == 0 and db == 1))
        k = cur
        g = sets[k - 1][0] + sets[k - 1][1] if sets else 0
        w_src = 0 if da > db else 1
        return {"level": "game", "amb": bool(amb), "winner": w_src ^ int(x["flip"]), "set": k, "game": g,
                "pa": "G" if w_src == 0 else x["pa"], "pb": "G" if w_src == 1 else x["pb"]}
    if (prev["pa"], prev["pb"]) == (x["pa"], x["pb"]):
        return None
    tb = not (x["pa"] in PRANK and x["pb"] in PRANK)
    ra0, rb0 = _prank(prev["pa"], tb), _prank(prev["pb"], tb)
    ra1, rb1 = _prank(x["pa"], tb), _prank(x["pb"], tb)
    if ra1 > ra0 and rb1 <= rb0:
        w, amb = 0, (ra1 - ra0 > 1) or rb1 < rb0
    elif rb1 > rb0 and ra1 <= ra0:
        w, amb = 1, (rb1 - rb0 > 1) or ra1 < ra0
    elif ra1 < ra0 and rb1 == rb0 == 3:
        w, amb = 1, False
    elif rb1 < rb0 and ra1 == ra0 == 3:
        w, amb = 0, False
    else:
        return None
    if not sets:
        cur, g = 1, 1
    elif _set_done(sets[-1]):
        cur, g = len(sets) + 1, 1
    else:
        cur, g = len(sets), sets[-1][0] + sets[-1][1] + 1
    return {"level": "point", "amb": bool(amb), "winner": w ^ int(x["flip"]), "set": cur, "game": g,
            "pa": x["pa"], "pb": x["pb"]}


# ----------------------------------------------------------------------------- book
LEGACY = ROOT / "data" / "live"   # src/live_recorder.py (moneylines only, raw messages, since 09:46 UTC)


def legacy_events() -> pd.DataFrame:
    """Moneyline events seen by src/live_recorder.py (data/live/tokens_*), outcome order = token order."""
    rows = {}
    for rec in read("tokens", LEGACY):
        for tok, m in (rec.get("tokens") or {}).items():
            if m.get("tag") != "tennis":
                continue
            rows.setdefault(m["cond"], {"slug": m["slug"], "gameId": m.get("gameId"), "toks": []})
            if tok not in [t for t, _ in rows[m["cond"]]["toks"]]:
                rows[m["cond"]]["toks"].append((tok, m["outcome"]))
    out = []
    for c, r in rows.items():
        if len(r["toks"]) != 2:
            continue
        (t0, n0), (t1, n1) = r["toks"]
        out.append({"slug": r["slug"], "gameId": r["gameId"], "n0": n0, "n1": n1, "tok0": t0, "tok1": t1,
                    "doubles": "doubles" in r["slug"]})
    return pd.DataFrame(out)


def cached_pbp() -> list[dict]:
    """Point-by-point logs fetched by fetch_pbp.py (data/v2_latency/pbp/*.json)."""
    out = []
    for f in sorted((ROOT / "data" / "v2_latency" / "pbp").glob("pbp_*.json")):
        d = orjson.loads(f.read_bytes())
        for p in d.get("points") or []:
            out.append({"rt": np.nan, "src": "wta_pbp", "first": True, "tid": d["_tid"], "yr": d["_yr"],
                        "mid": d["_mid"], "names": [n.split(" ", 1) for n in d["_names"]], "_names": d["_names"], **p})
    return out


class Books:
    """Top of book for every token of interest + full depth replay for chosen tokens.

    Reads both recorders: research/v2/latency/recorder.py (data/live_v2/clob_*, all markets, compact)
    and src/live_recorder.py (data/live/market_*, moneylines only, raw). Keyed by CLOB token id."""

    def __init__(self, toks: set[str], depth_toks: set[str], idx2tok: dict[tuple, str], legacy: bool = True):
        top = defaultdict(list)
        self.dep = {"v2": defaultdict(list), "legacy": defaultdict(list)}
        trades = defaultdict(list)
        self.conns = []
        tok_of = {i: t for i, t in idx2tok.items() if t in toks or t in depth_toks}
        for run, r in read("clob", LIVE, with_run=True):
            e = r.get("e")
            if e == "pc":
                last = {}
                for a, p, sz, side, bb, ba in r["c"]:
                    t = tok_of.get((run, a))
                    if t is None:
                        continue
                    last[t] = (bb, ba)
                    if t in depth_toks:
                        self.dep["v2"][t].append((r["rt"], side, p, sz))
                for t, (bb, ba) in last.items():
                    top[t].append((r["rt"], bb, ba))
            elif e in ("bba", "b", "t"):
                t = tok_of.get((run, r["a"]))
                if t is None:
                    continue
                if e == "bba":
                    top[t].append((r["rt"], r["bb"], r["ba"]))
                elif e == "b":
                    bb = max((p for p, sz in r["b"] if sz > 0), default=np.nan)
                    ba = min((p for p, sz in r["k"] if sz > 0), default=np.nan)
                    top[t].append((r["rt"], bb, ba))
                    if t in depth_toks:
                        self.dep["v2"][t].append((r["rt"], "BOOK", r["b"], r["k"]))
                else:
                    trades[t].append((r["rt"], r["p"], r["s"], r.get("side")))
            elif e in ("conn", "error"):
                self.conns.append(r)
        if legacy:
            for r in read("market", LEGACY):
                et = r.get("event_type")
                if et == "price_change":
                    last = {}
                    for x in r.get("price_changes", []):
                        t = x.get("asset_id")
                        if t not in toks and t not in depth_toks:
                            continue
                        last[t] = (float(x.get("best_bid") or "nan"), float(x.get("best_ask") or "nan"))
                        if t in depth_toks:
                            self.dep["legacy"][t].append((r["rt"], (x.get("side") or "?")[0], float(x["price"]),
                                                          float(x["size"])))
                    for t, (bb, ba) in last.items():
                        top[t].append((r["rt"], bb, ba))
                elif et == "last_trade_price":
                    t = r.get("asset_id")
                    if t in toks:
                        trades[t].append((r["rt"], float(r.get("price") or "nan"), float(r.get("size") or 0), r.get("side")))
                elif et in ("book", "best_bid_ask"):
                    t = r.get("asset_id")
                    if t not in toks and t not in depth_toks:
                        continue
                    if et == "best_bid_ask":
                        top[t].append((r["rt"], float(r.get("best_bid") or "nan"), float(r.get("best_ask") or "nan")))
                    else:
                        b = [[float(x["price"]), float(x["size"])] for x in r.get("bids", [])]
                        k = [[float(x["price"]), float(x["size"])] for x in r.get("asks", [])]
                        top[t].append((r["rt"], max((p for p, sz in b if sz > 0), default=np.nan),
                                       min((p for p, sz in k if sz > 0), default=np.nan)))
                        if t in depth_toks:
                            self.dep["legacy"][t].append((r["rt"], "BOOK", b, k))
        self.top = {}
        for t, v in top.items():
            arr = np.array(v, dtype=float)
            self.top[t] = arr[np.argsort(arr[:, 0], kind="stable")]
        for k in self.dep:
            for t in self.dep[k]:
                self.dep[k][t].sort(key=lambda x: x[0])
        self._snap = {}
        self.trades = trades

    def mid_series(self, t: str, max_spread: float = 0.05):
        arr = self.top.get(t)
        if arr is None or not len(arr):
            return np.empty(0), np.empty(0), np.empty(0), np.empty(0)
        ts, bb, ba = arr[:, 0], arr[:, 1], arr[:, 2]
        ok = (bb > 0) & (ba < 1) & (ba > bb) & ((ba - bb) <= max_spread)
        return ts[ok], (bb[ok] + ba[ok]) / 2, bb[ok], ba[ok]

    def book_at(self, tok: str, t: float):
        """Full book (bids dict, asks dict) of token tok as of local time t (ms); prefers the v2 stream."""
        import bisect
        for k in ("v2", "legacy"):
            lst = self.dep[k].get(tok, [])
            if (k, tok) not in self._snap:
                idx = [i for i, x in enumerate(lst) if x[1] == "BOOK"]
                self._snap[(k, tok)] = (idx, [lst[i][0] for i in idx])
            idx, ts = self._snap[(k, tok)]
            j = bisect.bisect_right(ts, t) - 1
            if j < 0:
                continue
            bids, asks = {}, {}
            for x in lst[idx[j]:]:
                if x[0] > t:
                    break
                if x[1] == "BOOK":
                    bids = {p: sz for p, sz in x[2] if sz > 0}
                    asks = {p: sz for p, sz in x[3] if sz > 0}
                else:
                    _, side, p, sz = x
                    d = bids if side == "B" else asks
                    if sz > 0:
                        d[p] = sz
                    else:
                        d.pop(p, None)
            return bids, asks
        return {}, {}
