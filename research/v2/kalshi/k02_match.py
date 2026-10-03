"""Step 2: match Kalshi ATP/WTA match markets to Polymarket IS matches.

Keys: series (atp/wta), both player surnames (accent/hyphen-insensitive token match),
event date within +-2 days, and both venues' close times within 3 h. Validation:
the Kalshi result for the player mapped to Polymarket outcome 0 must equal res0.
Output: data/v2_kalshi/matched.parquet (one row per Polymarket cond).
"""
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalshi_api as ka

OUT = Path("research/v2/kalshi/out")
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def toks(name: str) -> set[str]:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return {t for t in re.split(r"[^a-z]+", s) if len(t) >= 3}


def surname(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    t = [x for x in re.split(r"[^a-z]+", s) if x]
    return t[-1] if t else ""


def same_player(pm: str, ks: str) -> int:
    """2 = surnames agree both ways, 1 = one-way token match, 0 = no match."""
    a, b = toks(pm), toks(ks)
    if not (a and b):
        return 0
    s1, s2 = surname(pm) in b, surname(ks) in a
    return 2 if (s1 and s2) else int(s1 or s2)


def kalshi_events() -> pd.DataFrame:
    rows = []
    for s, ser in [("KXATPMATCH", "atp"), ("KXWTAMATCH", "wta")]:
        m = ka.list_markets(s)
        for ev, g in m.groupby("event_ticker"):
            if len(g) != 2:
                continue
            g = g.sort_values("ticker")
            dm = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ev)
            if not dm:
                continue
            d = pd.Timestamp(2000 + int(dm.group(1)), MON[dm.group(2)], int(dm.group(3)), tz="UTC")
            rows.append({"series": ser, "event_ticker": ev, "date": d,
                         "tkA": g.ticker.iloc[0], "nameA": g.yes_name.iloc[0], "resA": g.result.iloc[0],
                         "tkB": g.ticker.iloc[1], "nameB": g.yes_name.iloc[1], "resB": g.result.iloc[1],
                         "setA": g.settle_value.iloc[0], "setB": g.settle_value.iloc[1],
                         "volA": g.volume.iloc[0], "volB": g.volume.iloc[1],
                         "k_close": g.close_time.max(), "k_open": g.open_time.min(),
                         "k_occ": g.occurrence.min(), "k_exp": g.expected_exp.min()})
    return pd.DataFrame(rows)


def main():
    u = pd.read_parquet("data/derived/universe_is.parquet")
    u = u[u.start < ka.OOS_CUTOFF]
    k = kalshi_events()
    k["d"] = k.date.dt.normalize()
    out = []
    by_ser = {s: g for s, g in k.groupby("series")}
    for r in u.itertuples():
        g = by_ser.get(r.series)
        if g is None:
            continue
        d0 = r.start.normalize()
        c = g[(g.d >= d0 - pd.Timedelta(days=2)) & (g.d <= d0 + pd.Timedelta(days=2))]
        hits = []
        for e in c.itertuples():
            sa = (same_player(r.out0, e.nameA), same_player(r.out1, e.nameB))  # PM outcome 0 = Kalshi market A
            sb = (same_player(r.out0, e.nameB), same_player(r.out1, e.nameA))
            ka_, kb_ = (min(sa) > 0) * sum(sa), (min(sb) > 0) * sum(sb)
            if ka_ == kb_ == 0 or ka_ == kb_:
                continue  # no match, or orientation ambiguous (e.g. 'Maria Sakkari' vs 'Tatjana Maria')
            hits.append((e, "A" if ka_ > kb_ else "B"))
        if not hits:
            continue
        # prefer the closest close time
        hits.sort(key=lambda h: abs((h[0].k_close - r.end).total_seconds()) if pd.notna(r.end) else 1e9)
        e, side = hits[0]
        tk0 = e.tkA if side == "A" else e.tkB
        tk1 = e.tkB if side == "A" else e.tkA
        kres0 = e.resA if side == "A" else e.resB
        kset0 = e.setA if side == "A" else e.setB
        out.append({"cond": r.cond, "slug": r.slug, "series": r.series, "start": r.start, "end": r.end,
                    "res0": r.res0, "fee_rate": r.fee_rate, "delay": r.delay, "pm_volume": r.volume,
                    "out0": r.out0, "out1": r.out1, "event_ticker": e.event_ticker,
                    "k_tk0": tk0, "k_tk1": tk1, "k_res0": kres0, "k_settle0": kset0,
                    "k_vol0": e.volA if side == "A" else e.volB, "k_vol1": e.volB if side == "A" else e.volA,
                    "k_close": e.k_close, "k_open": e.k_open, "n_hits": len(hits)})
    m = pd.DataFrame(out)
    m["close_gap_min"] = (m.k_close - m.end).dt.total_seconds() / 60
    m["res_ok"] = ((m.k_res0 == "yes") & (m.res0 == 1)) | ((m.k_res0 == "no") & (m.res0 == 0))
    # keep in-play-relevant matches: both settled binary and agree, OR Polymarket binary while Kalshi settled
    # at a 'fair price' (retirement-rule basis risk; kept so the hedge P&L carries that risk)
    m["basis_event"] = m.res0.isin([0.0, 1.0]) & ~m.res_ok
    m["ok"] = (m.res_ok | (m.res0.isin([0.0, 1.0]) & (m.k_res0 == "scalar"))) & (m.k_close >= m.start - pd.Timedelta(hours=1)) & (m.k_close <= m.end + pd.Timedelta(hours=3))
    OUT.mkdir(parents=True, exist_ok=True)
    m.to_parquet(ka.CACHE / "matched_all.parquet")
    good = m[m.ok].drop_duplicates("event_ticker").reset_index(drop=True)
    good.to_parquet(ka.CACHE / "matched.parquet")
    print("PM IS matches", len(u), "kalshi events", len(k))
    print("name+date hits", len(m), "res agree", int(m.res_ok.sum()), "res+close ok", int(m.ok.sum()),
          "unique ok", len(good))
    print("binary-PM settlement disagreements among close-time-consistent matches:",
          m[m.ok & m.basis_event][["slug", "res0", "k_res0", "k_settle0"]].to_dict("records"))
    print("close gap (min) quantiles", m.close_gap_min.quantile([.05, .25, .5, .75, .95]).round(1).to_dict())
    print(good.groupby(good.start.dt.strftime("%Y-%m")).size().to_dict())
    print(good.groupby(["fee_rate", "delay"]).size())
    print("kalshi/pm volume ratio median", float((good.k_vol0 + good.k_vol1).median() / good.pm_volume.median()))


if __name__ == "__main__":
    main()
