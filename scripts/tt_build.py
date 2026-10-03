"""Table tennis dataset build for the pre-registered study (HYPOTHESIS_TT.md, commit 0f01362).

    python scripts/tt_build.py universe    # data/tt/universe.parquet: UTT with start/end/res0/oos/league
    python scripts/tt_build.py prints      # data/tt/prints.parquet: src.tiers.match_prints per UTT row (<= 3 processes)
    python scripts/tt_build.py liquidity   # research/tt/liquidity.csv: counts and USD volume by league x month
    python scripts/tt_build.py unlisted    # the same three steps for the zero-listed-volume markets that have
                                           # fills (found by tt_fetch.py zerocheck); NOT part of UTT, kept apart
                                           # in *_unlisted files for a sensitivity check (research/tt/DATA.md)

Tapes are read from the src.polymarket cache (data/raw/trades/{cond}.parquet, written by
scripts/tt_fetch.py with the unchanged fetch_trades parsing), as the pre-registration fixes.

`universe` and `prints` compute no statistic. `liquidity` counts markets, fills and USD only (TT4 is
descriptive); it computes no price, markout, calibration or P&L figure.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # src.polymarket caches under the relative path data/raw

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import polymarket as pm, tiers  # noqa: E402
from src.tape import in_play, load_tape  # noqa: E402

CAT = ROOT / "data/raw/events_table-tennis_2025-07-01_2026-10-03.parquet"
CAT_SHA256 = "daa48f2c41716309fd643fb02995fcaed3e1dffaf23bfee5abc732c53e9533f8"
OOS_FRAC = 0.20
OUT = ROOT / "data/tt"
RES = ROOT / "research/tt"
WORKERS = 3

# Counts the pre-registration states from the catalogue; universe() refuses to run if they differ.
EXPECT = {"n": 3588, "cut": pd.Timestamp("2026-09-16 05:30:00", tz="UTC"), "is": 2870, "oos": 718,
          "league": {"Setka": 2706, "WTT": 881, "other": 1}, "oos_league": {"Setka": 718},
          "res": {1.0: 1752, 0.0: 1819, 0.5: 17},
          "first": pd.Timestamp("2026-02-15 06:10", tz="UTC"), "last": pd.Timestamp("2026-10-03 01:30", tz="UTC")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def league_of(series: pd.Series) -> pd.Series:
    s = series.fillna("").str.lower()
    return pd.Series(np.select([s.str.startswith("wtt"), s.str.startswith("setka")], ["WTT", "Setka"], "other"),
                     index=series.index)


def universe(check: bool = True) -> pd.DataFrame:
    """UTT exactly as HYPOTHESIS_TT.md defines it, rows prepared as src.tape.universe() does."""
    got = sha256(CAT)
    assert got == CAT_SHA256, f"catalogue changed: {got}"
    c = pd.read_parquet(CAT)
    u = c[(c.volume > 0) & c.res0.isin([0.0, 0.5, 1.0])].copy()
    u["start"] = pd.to_datetime(u.start_time, utc=True)
    u["end"] = pd.to_datetime(u.finished.fillna(u.closed_time), utc=True, format="mixed")
    u["fee_rate"] = u.fee_rate.fillna(0.0)
    u["delay"] = u.seconds_delay.fillna(1).astype(int)
    u = u.sort_values("start", kind="stable").reset_index(drop=True)
    cut = u.start.iloc[int(len(u) * (1 - OOS_FRAC))]
    u["oos"] = u.start >= cut
    u["league"] = league_of(u.series)
    u["month"] = u.start.dt.strftime("%Y-%m")
    if check:
        assert len(u) == EXPECT["n"] and u.cond.is_unique, len(u)
        assert cut == EXPECT["cut"], cut
        assert (~u.oos).sum() == EXPECT["is"] and u.oos.sum() == EXPECT["oos"]
        assert u.league.value_counts().to_dict() == EXPECT["league"]
        assert u[u.oos].league.value_counts().to_dict() == EXPECT["oos_league"]
        assert u.res0.value_counts().to_dict() == EXPECT["res"]
        assert u.start.min() == EXPECT["first"] and u.start.max() == EXPECT["last"]
    return u


def write_universe() -> pd.DataFrame:
    u = universe()
    OUT.mkdir(parents=True, exist_ok=True)
    u.to_parquet(OUT / "universe.parquet")
    print(f"universe: {len(u)} markets, IS {(~u.oos).sum()}, OOS {u.oos.sum()}, cut {u[u.oos].start.min()}", flush=True)
    return u


def unlisted_universe() -> pd.DataFrame:
    """Catalogue rows with listed volume 0 whose data-api tape has >= 1 fill (tt_fetch.py zerocheck).

    Prepared exactly like UTT; the oos flag uses the pre-registered cut (it is not recomputed)."""
    assert sha256(CAT) == CAT_SHA256
    c = pd.read_parquet(CAT)
    z = pd.read_parquet(OUT / "zero_volume_check.parquet")
    assert z.error.isna().all() and set(z.cond) == set(c[c.volume <= 0].cond), "zerocheck incomplete"
    has = set(z[z.n_first_page > 0].cond)
    u = c[c.cond.isin(has) & c.res0.isin([0.0, 0.5, 1.0])].copy()
    u["start"] = pd.to_datetime(u.start_time, utc=True)
    u["end"] = pd.to_datetime(u.finished.fillna(u.closed_time), utc=True, format="mixed")
    u["fee_rate"] = u.fee_rate.fillna(0.0)
    u["delay"] = u.seconds_delay.fillna(1).astype(int)
    u = u.sort_values("start", kind="stable").reset_index(drop=True)
    u["oos"] = u.start >= EXPECT["cut"]
    u["league"] = league_of(u.series)
    u["month"] = u.start.dt.strftime("%Y-%m")
    u.to_parquet(OUT / "universe_unlisted.parquet")
    print(f"unlisted universe: {len(u)} markets ({len(has)} with a fill), IS {(~u.oos).sum()}, OOS {u.oos.sum()}",
          flush=True)
    return u


def _tape_path(cond: str) -> Path:
    return pm.RAW / "trades" / f"{cond}.parquet"


def _one(r: dict):
    """(cond, status, n_tape, n_inplay, prints or None, error). Status is a count-only label."""
    row = SimpleNamespace(**r)
    if not _tape_path(row.cond).exists():
        return row.cond, "no_tape", 0, 0, None, None
    try:
        t = load_tape(row.cond)
        if t is None:
            return row.cond, "empty_tape", 0, 0, None, None
        ip = in_play(t, row)
        n_in = len(ip)
    except Exception as err:  # recorded per cond, never silent
        return row.cond, "error", 0, 0, None, repr(err)
    try:
        d = tiers.match_prints(row)
        status = "ok" if d is not None else "lt20_inplay"
        return row.cond, status, len(t), n_in, d, None
    except Exception as err:
        # tiers.match_prints raises IndexError when a match has >= 20 in-play prints but no jump onset
        # (on_t is empty). The tennis builders (src/prints.py, scripts/tiers_is.py) drop such matches
        # through their except-return-None; here they are dropped the same way but labelled.
        ts = ip.timestamp.to_numpy().astype(float)
        no_jump = isinstance(err, IndexError) and not tiers.jump_onsets(ts, ip.p0.to_numpy(), ip.usd.to_numpy())
        return row.cond, "no_jump" if no_jump else "error", len(t), n_in, None, repr(err)


def prints(name: str = "") -> pd.DataFrame:
    if name == "" and not (OUT / "universe.parquet").exists():
        write_universe()
    u = pd.read_parquet(OUT / f"universe{name}.parquet")
    cols = ["cond", "start", "end", "fee_rate", "delay", "res0"]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(_one, u[cols].to_dict("records"), chunksize=16))
    parts = [r[4] for r in res if r[4] is not None]
    st = pd.DataFrame([r[:4] + (r[5],) for r in res], columns=["cond", "status", "n_tape", "n_inplay", "error"])
    st = st.merge(u[["cond", "league", "oos", "start"]], on="cond", how="left")
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(OUT / f"prints{name}.parquet")
    st.to_parquet(OUT / f"build_status{name}.parquet")
    print("prints:", len(df), "rows from", df.cond.nunique(), "matches;", st.status.value_counts().to_dict(), flush=True)
    return df


def _market_volume(r: dict) -> dict:
    """Fill counts and USD volume of one cached tape, split by the market's start/end (no prices used)."""
    f = _tape_path(r["cond"])
    out = {"cond": r["cond"], "fetched": f.exists(), "fills": 0, "shares": 0.0, "usd": 0.0, "pre_usd": 0.0, "inplay_usd": 0.0,
           "post_usd": 0.0, "pre_fills": 0, "inplay_fills": 0, "post_fills": 0, "first_ts": np.nan, "last_ts": np.nan}
    if not f.exists():
        return out
    t = pd.read_parquet(f)  # an empty tape is cached as a frame with no columns
    if t.empty:
        return out
    ts = t.timestamp.to_numpy(np.int64)
    usd = (t["size"] * t["price"]).to_numpy()
    s, e = int(r["start"].timestamp()), int(r["end"].timestamp())
    pre, post = ts < s, ts > e
    inp = ~pre & ~post
    out.update(fills=len(t), shares=float(t["size"].sum()), usd=float(usd.sum()), pre_usd=float(usd[pre].sum()), inplay_usd=float(usd[inp].sum()),
               post_usd=float(usd[post].sum()), pre_fills=int(pre.sum()), inplay_fills=int(inp.sum()),
               post_fills=int(post.sum()), first_ts=int(ts.min()), last_ts=int(ts.max()))
    return out


def _agg(g: pd.DataFrame) -> pd.Series:
    tape = g.usd[g.fetched]
    return pd.Series({
        "markets": len(g),
        "listed_usd": g.volume.sum(), "listed_usd_median": g.volume.median(),
        "tapes_fetched": int(g.fetched.sum()), "fetch_failed": int((~g.fetched).sum()),
        "markets_with_fills": int((g.fills > 0).sum()),
        "fills": int(g.fills.sum()), "tape_usd": tape.sum(),
        "tape_usd_mean": tape.mean(), "tape_usd_median": tape.median(), "tape_usd_p90": tape.quantile(0.9),
        "prestart_usd": g.pre_usd.sum(), "inplay_usd": g.inplay_usd.sum(), "after_end_usd": g.post_usd.sum(),
        "inplay_usd_median": g.inplay_usd[g.fetched].median(),
        "inplay_fills": int(g.inplay_fills.sum()),
        "matches_ge20_inplay": int((g.status == "ok").sum()),
        "tape_capped": int(g.capped.sum()),
    })


def liquidity(name: str = "") -> pd.DataFrame:
    u = pd.read_parquet(OUT / f"universe{name}.parquet")
    with ProcessPoolExecutor(WORKERS) as ex:
        mv = pd.DataFrame(list(ex.map(_market_volume, u[["cond", "start", "end"]].to_dict("records"), chunksize=32)))
    m = u[["cond", "league", "month", "oos", "volume", "start"]].merge(mv, on="cond")
    st = pd.read_parquet(OUT / f"build_status{name}.parquet")[["cond", "status"]]
    man = pd.read_parquet(OUT / f"fetch_manifest{name}.parquet")[["cond", "capped"]]
    m = m.merge(st, on="cond", how="left").merge(man, on="cond", how="left")
    m["capped"] = m.capped.fillna(False).astype(bool)
    # completeness: gamma's listed volume is the sum of fill sizes (shares) on the taker tape
    m["listed_matches_tape"] = (m.shares - m.volume).abs() <= 0.01 * m.volume.clip(lower=1)
    m.to_parquet(OUT / f"market_liquidity{name}.parquet")
    print(f"listed volume == tape share sum (1%): {int(m.listed_matches_tape.sum())}/{len(m)}", flush=True)
    m["period"] = np.where(m.oos, "OOS", "IS")
    rows = []
    for (lg, mo), g in m.groupby(["league", "month"]):
        rows.append({"league": lg, "month": mo, **_agg(g)})
    for lg, g in m.groupby("league"):
        for p, gp in g.groupby("period"):
            rows.append({"league": lg, "month": p, **_agg(gp)})
        rows.append({"league": lg, "month": "ALL", **_agg(g)})
    for p, gp in m.groupby("period"):
        rows.append({"league": "ALL", "month": p, **_agg(gp)})
    rows.append({"league": "ALL", "month": "ALL", **_agg(m)})
    out = pd.DataFrame(rows)
    num = out.select_dtypes("number").columns
    out[num] = out[num].round(2)
    RES.mkdir(parents=True, exist_ok=True)
    out.to_csv(RES / f"liquidity{name}.csv", index=False)
    summ = {"built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "by_league": out[out.month == "ALL"].set_index("league")[
                ["markets", "markets_with_fills", "fills", "tape_usd", "listed_usd", "matches_ge20_inplay"]
            ].to_dict("index")}
    print(json.dumps(summ, indent=1, default=float), flush=True)
    return out


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "universe"
    if stage == "unlisted":
        unlisted_universe()
        prints("_unlisted")
        liquidity("_unlisted")
    else:
        {"universe": write_universe, "prints": prints, "liquidity": liquidity}[stage]()
