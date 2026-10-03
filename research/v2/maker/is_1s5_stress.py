#!/usr/bin/env python3
"""IS 1s/5% reference for every maker v1 stress (IS data only; no OOS read, no peek).

Why: the OOS sample is entirely in the 1 s delay / 5% fee regime, but the IS column of RESULTS.md's stress table
came from `is_reference.json`, which pools Feb-Aug across all four regimes (a cell chosen in hindsight). That
comparator runs about 1c high against the OOS regime (audit of the OOS run, 2026-10-03). This script re-runs the
same IS code test (`oos_test.istest`'s path: IS walk-forward b, months >= 2026-02, maker_base_fee assumed 1000)
and reports each book restricted to the 1s/5% regime with `oos_test.cut`, which is how RESULTS.md's IS 1s/5%
book-1 figure (+2.02c [+0.53, +3.48], n = 4,159) was produced.

Run from the repo root:  .venv/bin/python research/v2/maker/is_1s5_stress.py
Writes research/v2/maker/is_reference_1s5.json.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import oos_test as ot  # noqa: E402

REGIME = "1s/5%"


def main() -> dict:
    ot.check_frozen()
    pr, ends, *_ = ot.is_prepared()
    pr = pr[pr.month >= ot.FIRST_EVAL].copy()
    pr["maker_base_fee"] = 1000.0                      # as in istest(): IS catalogue did not keep the field
    res, books, c = ot.evaluate(pr, ends, maker_fee_stress=True, partial={"2026-08": "partial (Aug 1-25, IS)"})
    out = {"label": ("IS reference restricted to the 1s/5% regime (the whole OOS is 1s/5%). IS data only, same "
                     "code path as is_reference.json; computed after the OOS run for comparability, changes "
                     "nothing"),
           "utc": dt.datetime.now(dt.timezone.utc).isoformat(), "regime": REGIME, "books": {}}
    for k, b in books.items():
        g = b[b.regime == REGIME]
        out["books"][k] = ot.cut(g) if len(g) else {"n": 0}
    d = [r for r in res["diagnostics"] if r["regime"] == REGIME]
    out["diagnostics"] = d
    (HERE / "is_reference_1s5.json").write_text(json.dumps(out, indent=1, default=float))
    for k, v in out["books"].items():
        if v.get("n"):
            print(f"{k:<22} n {v['n']:>5}  matches {v['matches']:>4}  net {v['net_c']:+.2f}c "
                  f"[{v['ci'][0]:+.2f}, {v['ci'][1]:+.2f}]  $ {v['pnl_usd']:+.0f}")
    return out


if __name__ == "__main__":
    main()
