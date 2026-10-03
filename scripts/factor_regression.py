"""Is the edge just market, size, value or momentum? Regress v2 daily returns on Fama-French factors.

Factor data: Kenneth French data library (daily F-F 3 factors + momentum), downloaded by this script.
    .venv/bin/python scripts/factor_regression.py   ->  results/v2/factor_regression.json
"""
import io, json, sys, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import requests

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
CAPITAL = json.loads(Path("results/v2/causal.json").read_text())["causal/is_eval/slip0.0"]["capital_usd"]


def french(name: str, cols: list[str]) -> pd.DataFrame:
    cache = Path("data/factors") / name.replace("_CSV.zip", ".csv")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        z = zipfile.ZipFile(io.BytesIO(requests.get(BASE + name, timeout=60).content))
        cache.write_bytes(z.read(z.namelist()[0]))
    rows = []
    for line in cache.read_text(errors="ignore").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == len(cols) + 1 and parts[0].isdigit() and len(parts[0]) == 8:
            rows.append([pd.Timestamp(parts[0])] + [float(x) / 100 for x in parts[1:]])
    return pd.DataFrame(rows, columns=["date"] + cols).set_index("date")


if __name__ == "__main__":
    ff = french("F-F_Research_Data_Factors_daily_CSV.zip", ["MktRF", "SMB", "HML", "RF"]).join(
        french("F-F_Momentum_Factor_daily_CSV.zip", ["Mom"]), how="inner")
    tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
    tr = tr[tr.month >= "2026-02"]
    d = tr.groupby(pd.to_datetime(tr.ts, unit="s").dt.floor("D").dt.tz_localize(None)).pnl.sum() / CAPITAL
    df = pd.DataFrame({"r": d}).join(ff, how="inner").dropna()
    X = np.column_stack([np.ones(len(df)), df[["MktRF", "SMB", "HML", "Mom"]].to_numpy()])
    y = df.r.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    # Newey-West (5 lags) standard errors
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, 6):
        w = 1 - L / 6
        G = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S += w * (G + G.T)
    se = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))
    r2 = 1 - resid.var() / y.var()
    names = ["alpha_daily", "MktRF", "SMB", "HML", "Mom"]
    out = {"n_days": int(n), "period": [str(df.index.min().date()), str(df.index.max().date())],
           "coef": dict(zip(names, beta.round(6))), "t": dict(zip(names, (beta / se).round(2))), "r2": round(float(r2), 4),
           "alpha_annualised_pct": round(float(beta[0] * 252 * 100), 1),
           "corr_with_market": round(float(np.corrcoef(y, df.MktRF)[0, 1]), 3)}
    Path("results/v2/factor_regression.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
