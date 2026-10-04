"""Shared pieces of COURTSIDE Warehouse: repo paths, .env loading, the Snowflake connection, and the tables.

Every table is built from files already committed under results/ and tests/fixtures/. Nothing here reads data/,
calls a market API or changes a result: the warehouse is a read-only copy of what the paper already reports.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
QUERIES = HERE / "queries.sql"
NUMBERS = ROOT / "results/paper/numbers.json"
VULTR_SUMMARY = ROOT / "sponsors/vultr/out/summary.json"   # Yoan's branch; loaded only if present


# ---------------------------------------------------------------- environment and connection

def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines from the repo-root .env into os.environ (existing variables win). Never printed."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def settings() -> dict:
    load_env()
    return {"database": os.environ.get("SNOWFLAKE_DATABASE", "COURTSIDE"),
            "schema": os.environ.get("SNOWFLAKE_SCHEMA", "WAREHOUSE"),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")}


def connect(with_db: bool = True):
    """Open a Snowflake session from .env. Auth, first match wins: SNOWFLAKE_TOKEN (programmatic access token),
    SNOWFLAKE_PRIVATE_KEY_PATH (key pair: the default for scripts, no MFA prompt), SNOWFLAKE_AUTHENTICATOR (e.g.
    externalbrowser, only for accounts with SAML single sign-on), SNOWFLAKE_PASSWORD."""
    import snowflake.connector

    s = settings()
    env = os.environ
    for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"):
        if not env.get(k):
            raise SystemExit(f"{k} is not set: copy sponsors/snowflake/.env.example into the repo-root .env and fill it in")
    kw = dict(account=env["SNOWFLAKE_ACCOUNT"], user=env["SNOWFLAKE_USER"], warehouse=s["warehouse"],
              session_parameters={"QUERY_TAG": "courtside-warehouse"}, client_store_temporary_credential=True)
    if env.get("SNOWFLAKE_ROLE"):
        kw["role"] = env["SNOWFLAKE_ROLE"]
    if with_db:
        kw.update(database=s["database"], schema=s["schema"])
    if env.get("SNOWFLAKE_TOKEN"):
        kw.update(authenticator="PROGRAMMATIC_ACCESS_TOKEN", token=env["SNOWFLAKE_TOKEN"])
    elif env.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
        kw["private_key_file"] = os.path.expanduser(env["SNOWFLAKE_PRIVATE_KEY_PATH"])
        if env.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
            kw["private_key_file_pwd"] = env["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]
    elif env.get("SNOWFLAKE_AUTHENTICATOR"):
        kw["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    elif env.get("SNOWFLAKE_PASSWORD"):
        kw["password"] = env["SNOWFLAKE_PASSWORD"]
    else:
        raise SystemExit("no Snowflake credential in .env (SNOWFLAKE_PRIVATE_KEY_PATH, SNOWFLAKE_TOKEN, "
                         "SNOWFLAKE_AUTHENTICATOR or SNOWFLAKE_PASSWORD); see sponsors/snowflake/README.md")
    return snowflake.connector.connect(**kw)


# ---------------------------------------------------------------- tables

def _upper(df: pd.DataFrame) -> pd.DataFrame:
    """Snowflake folds unquoted identifiers to upper case; name the columns that way so plain SQL finds them."""
    df = df.copy()
    df.columns = [str(c).upper() for c in df.columns]
    return df


def _flatten(x, prefix: str = ""):
    """Leaves of a JSON document as (dotted path, value); keys are kept verbatim, so paths match the paper's
    source strings (results/paper/numbers.json, e.g. 'causal/is_eval/slip0.0.per_share_c')."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    else:
        yield prefix, x


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def latency_sweep() -> pd.DataFrame:
    """Profit / Sharpe vs feed (video) delay: the 944 seed-mean rows behind the paper's latency curve."""
    return pd.read_csv(ROOT / "results/tier0/latency_sweep.csv")


def capacity_grid() -> pd.DataFrame:
    """Capital-capacity cells for the CV strategy (size grid x reading x coverage x period), seed means."""
    d = pd.read_csv(ROOT / "results/capacity/cv_cells.csv")
    d["coverage"] = d["coverage"].astype(str)
    return d


def backtest_metrics() -> pd.DataFrame:
    """The v2 backtest's metric files, one row per JSON leaf (file, path, numeric value, text value)."""
    rows = []
    for name in ("causal.json", "cost_stress.json", "note_metrics.json"):
        for path, v in _flatten(json.loads((ROOT / "results/v2" / name).read_text())):
            rows.append({"source_file": name, "json_path": path, "value_num": _num(v),
                         "value_text": v if isinstance(v, str) else json.dumps(v)})
    return pd.DataFrame(rows)


def cv_calls() -> pd.DataFrame:
    """172 calls emitted by the real-time CV engine (NVIDIA L4 run) on table-tennis test footage."""
    rows = []
    for line in (ROOT / "results/engine/online_events_L4.jsonl").read_text().splitlines():
        e = json.loads(line)
        x = e.get("extra") or {}
        rows.append({"call": e["call"], "video": e.get("video"), "source": e.get("source"), "frame": e["frame"],
                     "t_frame": e["t_frame"], "t_emit": e["t_emit"], "p_miss": e["p_miss"], "lead_ms": e["lead_ms"],
                     "latency_ms": e.get("latency_ms"), "direction": e.get("direction"),
                     "flight_t0": e.get("flight_t0"), "rule": e.get("rule"), "gate_open": _num(x.get("gate_open")),
                     "tau_end_ms": _num(x.get("tau_end_ms"))})
    return pd.DataFrame(rows)


TRACE_STAMPS = ["capture", "frame_sent", "frame_received", "handoff", "detected", "call_emitted", "decision",
                "risk_checked", "order_ready", "probe_start", "probe_end", "network_arrival", "executable",
                "fill_computed"]


def pipeline_stages() -> pd.DataFrame:
    """One row per CV call in the timed end-to-end run, with its raw monotonic stage timestamps (seconds), so SQL
    computes every stage duration itself. complete_order_trace marks the calls with an order, a fill and both ends
    timed: the paper's 24 traces (engine/e2e/e2e_run.py, 'full')."""
    rows = []
    for line in (ROOT / "results/e2e/trace.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r.get("type") != "call":
            continue
        t = r.get("t") or {}
        o = r.get("order") or {}
        rows.append({"rid": r.get("rid"), "pass_idx": r.get("pass_idx"), "call": r.get("call"),
                     "market_slug": (r.get("market") or {}).get("slug"), "order_kind": o.get("kind"),
                     "complete_order_trace": bool(r.get("order") and r.get("fill") and t.get("capture") is not None
                                                  and t.get("executable") is not None),
                     **{f"t_{k}": t.get(k) for k in TRACE_STAMPS}})
    return pd.DataFrame(rows)


def clob_sample() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The 10-minute recorded Polymarket CLOB sample (tests/fixtures), one row per message level:
    price changes (one row per changed level, with the best bid/ask after it), book snapshots (one row per
    level) and trades. Also the token index (asset -> match, outcome, market type)."""
    tokens, rows = [], []
    with gzip.open(ROOT / "tests/fixtures/live_sample.jsonl.gz", "rt") as f:
        for n, line in enumerate(f, 1):
            m = json.loads(line)
            e = m.get("e")
            if "tokens" in m:
                for idx, t in m["tokens"].items():
                    tokens.append({"asset_idx": int(idx), "token_id": t.get("tok"), "slug": t.get("slug"),
                                   "title": t.get("title"), "outcome": t.get("outcome"), "market_type": t.get("smt"),
                                   "match_start": t.get("start"), "tick": t.get("tick")})
                continue
            base = {"line_no": n, "rt_ms": m.get("rt"), "ts_ms": m.get("ts"), "event": e}
            if e == "pc":
                for a, p, s, side, bb, ba in m["c"]:
                    rows.append({**base, "asset_idx": a, "side": side, "price": p, "size": s,
                                 "best_bid": bb, "best_ask": ba, "level": None})
            elif e == "b":
                levels = [(side, lvl, p, s) for side, key in (("BID", "b"), ("ASK", "k"))
                          for lvl, (p, s) in enumerate(m.get(key) or [])]
                for side, lvl, p, s in levels or [(None, None, None, None)]:   # an empty book still counts
                    rows.append({**base, "asset_idx": m["a"], "side": side, "price": p, "size": s,
                                 "best_bid": None, "best_ask": None, "level": lvl})
            elif e == "t":
                rows.append({**base, "asset_idx": m["a"], "side": m.get("side"), "price": m.get("p"),
                             "size": m.get("s"), "best_bid": None, "best_ask": None, "level": None})
            elif e == "market_resolved":
                rows.append({**base, "asset_idx": None, "side": None, "price": None, "size": None,
                             "best_bid": None, "best_ask": None, "level": None})
    return pd.DataFrame(rows), pd.DataFrame(tokens)


def paper_numbers() -> pd.DataFrame:
    """Every number printed in the paper (results/paper/numbers.json): key, printed text, raw value, source."""
    n = json.loads(NUMBERS.read_text())["numbers"]
    return pd.DataFrame([{"paper_key": k, "printed": x.get("value"), "raw_num": _num(x.get("raw")),
                          "raw_text": json.dumps(x.get("raw")), "source": x.get("source")} for k, x in n.items()])


def vultr_probe() -> pd.DataFrame | None:
    """Yoan's London vs Florida feed-latency probe summary, flattened, if that branch's output is present."""
    if not VULTR_SUMMARY.exists():
        return None
    rows = [{"json_path": p, "value_num": _num(v), "value_text": v if isinstance(v, str) else json.dumps(v)}
            for p, v in _flatten(json.loads(VULTR_SUMMARY.read_text()))]
    return pd.DataFrame(rows)


def tables() -> dict[str, pd.DataFrame]:
    """All warehouse tables, upper-cased for Snowflake."""
    clob, tok = clob_sample()
    out = {"LATENCY_SWEEP": latency_sweep(), "CAPACITY_GRID": capacity_grid(), "BACKTEST_METRICS": backtest_metrics(),
           "CV_CALLS": cv_calls(), "PIPELINE_STAGES": pipeline_stages(), "CLOB_SAMPLE": clob, "CLOB_TOKENS": tok,
           "PAPER_NUMBERS": paper_numbers()}
    v = vultr_probe()
    if v is not None:
        out["VULTR_PROBE"] = v
    return {k: _upper(df) for k, df in out.items()}


# ---------------------------------------------------------------- queries.sql

def read_queries(path: Path = QUERIES) -> list[dict]:
    """Split queries.sql on '-- name: <id>' lines. Each block keeps its comment lines as the description."""
    blocks, cur = [], None
    for line in path.read_text().splitlines():
        if line.startswith("-- name:"):
            if cur:
                blocks.append(cur)
            cur = {"name": line.split(":", 1)[1].strip(), "doc": [], "sql": []}
        elif cur is not None:
            (cur["doc"] if line.startswith("--") and not cur["sql"] else cur["sql"]).append(line)
    if cur:
        blocks.append(cur)
    for b in blocks:
        b["doc"] = " ".join(l.lstrip("- ").strip() for l in b["doc"]).strip()
        b["sql"] = "\n".join(b["sql"]).strip().rstrip(";")
    return blocks
