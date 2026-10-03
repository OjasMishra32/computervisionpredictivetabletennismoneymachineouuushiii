"""Shared engine for the selection lens: data, walk-forward wallet qualification, shadow-book accounting.

All inputs are in-sample only (matches starting before 2026-08-25 14:15 UTC). Nothing here reads
data/locked/ or any OOS market data.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "v2_selection"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")
SHADOW_MAX_USD, MATCH_CAP_USD, CAPITAL_BUFFER = 1_000, 3_000, 3   # same sizing as run_all.shadow_book
FIRST_EVAL = 2                     # months[2:] are evaluated, exactly as src.fasttier.walk_forward
NESTED_MIN_HISTORY = 3             # nested choice needs >= 3 prior evaluated months; before that: baseline rule
REGIMES = ["3s/0%", "3s/3%", "1s/3%", "1s/5%"]


# ----------------------------------------------------------------------------------------------- data
def universe_is() -> pd.DataFrame:
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet")
    assert u.start.max() < OOS_START, "universe_is must be IS only"
    return u


def fee_now_by_month(u: pd.DataFrame, months) -> dict:
    """Fee rate known at the start of month m: the rate of the latest match that started before m."""
    s = u.sort_values("start")
    out = {}
    for m in months:
        t0 = m.to_timestamp().tz_localize("UTC")
        prev = s[s.start < t0]
        out[m] = float(prev.fee_rate.iloc[-1]) if len(prev) else 0.0
    return out


def load_prints() -> pd.DataFrame:
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "since", "fee_rate", "delay", "mo30", "mo_res"]
    d = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=cols)
    f = pd.read_parquet(CACHE / "feat_0_3s.parquet")
    assert (f.index == d.index).all()
    d = d.join(f).reset_index(drop=True)
    u = universe_is()
    assert d.cond.isin(set(u.cond)).all(), "a print outside the IS universe"
    d["month"] = pd.to_datetime(d.ts, unit="s").dt.to_period("M")
    d["date"] = pd.to_datetime(d.ts, unit="s", utc=True).dt.floor("D")
    d["pq"] = d.p * (1 - d.p)
    d["fee"] = d.fee_rate * d.pq
    d["net30"] = d.mo30 - d.fee
    d["net_res"] = d.mo_res - d.fee
    d["px"] = np.where(d.dir > 0, d.p, 1 - d.p)
    d["usd_in"] = np.minimum(d.usd, SHADOW_MAX_USD)
    d["shares"] = d.usd_in / d.px
    d["regime"] = np.select([(d.delay >= 3) & (d.fee_rate == 0), (d.delay >= 3) & (d.fee_rate > 0) & (d.fee_rate < 0.04),
                             (d.delay < 3) & (d.fee_rate > 0) & (d.fee_rate < 0.04), (d.delay < 3) & (d.fee_rate >= 0.04)],
                            REGIMES, "other")
    d["wid"] = d.wallet.astype("category").cat.codes.astype(np.int32)
    return d


def wallet_month_stats(d: pd.DataFrame) -> pd.DataFrame:
    """Sufficient statistics per (wallet, month) for every qualification variant."""
    x = d.assign(v=d.mo30.notna(), s1=d.mo30.fillna(0), s2=d.mo30.fillna(0) ** 2)
    g = x.groupby(["wid", "month"], observed=True).agg(
        n=("ts", "size"), nv=("v", "sum"), s1=("s1", "sum"), s2=("s2", "sum"), spq=("pq", "sum"),
        units=("cond", "nunique")).reset_index()
    return g


# --------------------------------------------------------------------------------------- qualification
@dataclass(frozen=True)
class Rule:
    look: str            # "all", "1m", "2m", "3m", "6m", "ew1", "ew2", "ew3" (half-life in months)
    score: str           # "t", "top", "tnet", "eb"
    thr: float           # t threshold, K, or minimum EB net edge (price units)
    mm: int = 10         # min matches (min prints = 3 * mm)

    @property
    def name(self) -> str:
        thr = f"{self.thr:g}" if self.score != "eb" else f"{self.thr * 100:g}c"
        return f"{self.look}|{self.score}{thr}|mm{self.mm}"


BASELINE = Rule("all", "t", 3.0, 10)


def _weights(age: np.ndarray, look: str) -> np.ndarray:
    if look == "all":
        return np.ones_like(age, dtype=float)
    if look.endswith("m"):
        return (age <= int(look[:-1])).astype(float)
    hl = float(look[2:])
    return 0.5 ** ((age - 1) / hl)


def wallet_scores(wm: pd.DataFrame, m, look: str, mm: int, fee_m: float) -> pd.DataFrame:
    """Per-wallet edge estimates from data strictly before month m."""
    past = wm[wm.month < m]
    age = np.array([(m - x).n for x in past.month])
    w = _weights(age, look)
    keep = w > 0
    past, w = past[keep], w[keep]
    z = pd.DataFrame({"wid": past.wid.to_numpy(), "wn": w * past.n, "wnv": w * past.nv, "w2nv": w * w * past.nv,
                      "ws1": w * past.s1, "ws2": w * past.s2, "wspq": w * past.spq,
                      "wu": w * past.units, "w2u": w * w * past.units})
    g = z.groupby("wid").sum()
    g = g[(g.wn >= 3 * mm) & (g.wu >= mm) & (g.wnv > 1)]
    mean = g.ws1 / g.wnv
    denom = g.wnv - g.w2nv / g.wnv
    var = ((g.ws2 - g.wnv * mean ** 2) / denom).clip(lower=0)
    sd = np.sqrt(var)
    nm_eff = g.wu ** 2 / g.w2u
    se = sd / np.sqrt(nm_eff)
    out = pd.DataFrame({"mean": mean, "sd": sd, "se": se, "nm": g.wu, "n": g.wn,
                        "fee_now": fee_m * g.wspq / g.wn})
    out = out[out.sd > 0]
    out["t"] = out["mean"] / out.se
    out["net_est"] = out["mean"] - out.fee_now
    out["tnet"] = out.net_est / out.se
    # empirical Bayes (DerSimonian-Laird random effects across all eligible wallets)
    if len(out) >= 5:
        wi = 1 / out.se ** 2
        mu_fe = (wi * out["mean"]).sum() / wi.sum()
        q = (wi * (out["mean"] - mu_fe) ** 2).sum()
        tau2 = max(0.0, (q - (len(out) - 1)) / (wi.sum() - (wi ** 2).sum() / wi.sum()))
        ws = 1 / (out.se ** 2 + tau2)
        mu0 = (ws * out["mean"]).sum() / ws.sum()
        b = tau2 / (tau2 + out.se ** 2) if tau2 > 0 else 0.0 * out.se
        out["eb"] = mu0 + b * (out["mean"] - mu0)
    else:
        out["eb"] = out["mean"]
    out["eb_net"] = out.eb - out.fee_now
    return out


def select(sc: pd.DataFrame, rule: Rule) -> np.ndarray:
    if sc.empty:
        return np.array([], dtype=np.int32)
    if rule.score == "t":
        s = sc.index[sc.t > rule.thr]
    elif rule.score == "top":
        c = sc[sc.t > 2]
        s = c.sort_values("t", ascending=False).index[: int(rule.thr)]
    elif rule.score == "tnet":
        s = sc.index[sc.tnet > rule.thr]
    elif rule.score == "eb":
        s = sc.index[sc.eb_net > rule.thr]
    else:
        raise ValueError(rule.score)
    return np.asarray(s, dtype=np.int32)


# ------------------------------------------------------------------------------------------ evaluation
def apply_cap(tr: pd.DataFrame) -> pd.DataFrame:
    """Per-match cap, in time order, exactly like run_all.shadow_book."""
    tr = tr.sort_values("ts", kind="stable")
    cum = tr.groupby("cond").usd_in.cumsum()
    return tr[cum <= MATCH_CAP_USD]


def month_rows(tr: pd.DataFrame) -> pd.DataFrame:
    """Per-month aggregates needed for reporting and for nested (re-priced) objectives."""
    t = tr.assign(sh_mo30=tr.shares * tr.mo30.fillna(0), sh_mores=tr.shares * tr.mo_res.fillna(0),
                  sh_pq=tr.shares * tr.pq, pnl=tr.shares * tr.net_res, pnl30=tr.shares * tr.net30)
    return t.groupby("month").agg(n=("ts", "size"), wallets=("wid", "nunique"), matches=("cond", "nunique"),
                                  shares=("shares", "sum"), usd_in=("usd_in", "sum"),
                                  net30_c=("net30", "mean"), net_res_c=("net_res", "mean"),
                                  pnl=("pnl", "sum"), pnl30=("pnl30", "sum"),
                                  sh_mo30=("sh_mo30", "sum"), sh_mores=("sh_mores", "sum"), sh_pq=("sh_pq", "sum"),
                                  fee_c=("fee", "mean")).assign(
        net30_c=lambda x: x.net30_c * 100, net_res_c=lambda x: x.net_res_c * 100, fee_c=lambda x: x.fee_c * 100)


def shadow_peak(tr: pd.DataFrame, u: pd.DataFrame) -> float:
    if tr.empty:
        return 0.0
    end = u.set_index("cond").end.map(lambda t: int(t.timestamp()) if pd.notna(t) else None)
    e = tr.cond.map(end).fillna(tr.ts + 4 * 3600).astype(int)
    ev = pd.concat([pd.DataFrame({"t": tr.ts, "d": tr.usd_in}), pd.DataFrame({"t": e, "d": -tr.usd_in})])
    return float(ev.sort_values("t", kind="stable").d.cumsum().max())


def summarize(tr: pd.DataFrame, u: pd.DataFrame, days: pd.DatetimeIndex | None = None, n_boot: int = 1000) -> dict:
    """Headline stats for a set of shadow trades (already capped)."""
    if tr.empty:
        return {"n_trades": 0}
    pnl = tr.shares * tr.net_res
    daily = pnl.groupby(tr.date).sum()
    if days is None:
        days = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(days, fill_value=0.0)
    peak = shadow_peak(tr, u)
    cap = CAPITAL_BUFFER * max(peak, 1.0)
    eq = cap + daily.cumsum()
    g = tr.groupby("cond").agg(s=("net_res", "sum"), n=("net_res", "count"), s30=("net30", "sum"), n30=("net30", "count"))
    rng = np.random.default_rng(0)
    k = len(g)
    bs, bs30 = [], []
    S, N, S30, N30 = (g[c].to_numpy() for c in ("s", "n", "s30", "n30"))
    for _ in range(n_boot):
        i = rng.integers(0, k, k)
        bs.append(S[i].sum() / max(N[i].sum(), 1))
        bs30.append(S30[i].sum() / max(N30[i].sum(), 1))
    lo, hi = np.percentile(bs, [2.5, 97.5]) * 100
    lo30, hi30 = np.percentile(bs30, [2.5, 97.5]) * 100
    monthly = pnl.groupby(tr.month).sum()
    return {
        "n_trades": int(len(tr)), "n_matches": int(k), "n_wallets": int(tr.wid.nunique()),
        "net_res_c": float(tr.net_res.mean() * 100), "net_res_ci_c": [float(lo), float(hi)],
        "net30_c": float(tr.net30.mean() * 100), "net30_ci_c": [float(lo30), float(hi30)],
        "net_res_share_wtd_c": float(pnl.sum() / tr.shares[tr.net_res.notna()].sum() * 100),
        "net30_share_wtd_c": float((tr.shares * tr.net30).sum() / tr.shares[tr.net30.notna()].sum() * 100),
        "fee_c": float(tr.fee.mean() * 100),
        "pnl_usd": float(pnl.sum()), "pnl30_usd": float((tr.shares * tr.net30).sum()),
        "usd_in": float(tr.usd_in.sum()),
        "sharpe_ann": float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else float("nan"),
        "max_dd_pct": float(((eq / eq.cummax()) - 1).min() * 100), "peak_locked_usd": peak, "capital": cap,
        "months_pos_pnl": int((monthly > 0).sum()), "months": int(len(monthly)),
        "days": int(len(days)),
    }


class Engine:
    """Holds the prints and the per-(wallet, month) stats; runs walk-forward selection for any Rule."""

    def __init__(self):
        self.u = universe_is()
        self.d = load_prints()
        self.months = sorted(self.d.month.unique())
        self.eval_months = self.months[FIRST_EVAL:]
        self.fee_now = fee_now_by_month(self.u, self.months)
        self.wm = wallet_month_stats(self.d)
        self.by_month = {m: g for m, g in self.d.groupby("month")}
        self._scores = {}
        self.eval_days = pd.date_range(self.eval_months[0].to_timestamp().tz_localize("UTC"),
                                       self.d.date.max(), freq="D")

    def scores(self, m, look, mm):
        key = (m, look, mm)
        if key not in self._scores:
            self._scores[key] = wallet_scores(self.wm, m, look, mm, self.fee_now[m])
        return self._scores[key]

    def selected(self, rule: Rule, m) -> np.ndarray:
        return select(self.scores(m, rule.look, rule.mm), rule)

    def trades(self, rule_for_month, cap: bool = True) -> pd.DataFrame:
        """rule_for_month: Rule, or callable month -> Rule (nested selection). Returns capped shadow trades."""
        parts = []
        for m in self.eval_months:
            r = rule_for_month(m) if callable(rule_for_month) else rule_for_month
            if r is None:          # nested rule chose to stand aside this month
                continue
            sel = self.selected(r, m)
            x = self.by_month[m]
            parts.append(x[np.isin(x.wid.to_numpy(), sel)].assign(n_sel=len(sel)))
        if not parts:
            return self.d.iloc[:0].assign(n_sel=0)
        tr = pd.concat(parts)
        return apply_cap(tr) if cap else tr


def regime_table(tr: pd.DataFrame) -> pd.DataFrame:
    t = tr.assign(pnl=tr.shares * tr.net_res)
    g = t.groupby("regime").agg(n=("ts", "size"), matches=("cond", "nunique"), net30_c=("net30", "mean"),
                                net_res_c=("net_res", "mean"), pnl=("pnl", "sum"), fee_c=("fee", "mean"))
    g[["net30_c", "net_res_c", "fee_c"]] *= 100
    return g.reindex([r for r in REGIMES if r in g.index])


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 5)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, pd.DataFrame):
        return jsonable(x.reset_index().to_dict("records"))
    if isinstance(x, pd.Period):
        return str(x)
    return x
