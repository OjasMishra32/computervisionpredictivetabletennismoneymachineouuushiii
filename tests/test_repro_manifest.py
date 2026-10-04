"""Input manifest: a byte-identical snapshot verifies; drift, a changed universe or a changed model does not."""
import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.repro import manifest as M  # noqa: E402

EVENTS = "data/raw/events_tennis_2025-07-01_2026-10-03.parquet"


def tape(i: int, n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": [1_750_000_000 + 60 * k + i for k in range(n)], "side": ["BUY"] * n,
                         "outcomeIndex": [0] * n, "price": [0.5 + 0.01 * k for k in range(n)], "size": [10.0] * n,
                         "proxyWallet": [f"0xw{k}" for k in range(n)], "transactionHash": [f"0xt{i}{k}" for k in range(n)],
                         "p0": [0.5 + 0.01 * k for k in range(n)]})


@pytest.fixture
def snap(tmp_path, monkeypatch):
    """A 10-match universe (8 IS + 2 OOS) with tapes, a frozen id list, a model and one archived input."""
    monkeypatch.chdir(tmp_path)
    conds = [f"0x{i:02d}" for i in range(10)]
    start = pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC")
    ev = pd.DataFrame({"cond": conds, "slug": [f"atp-m{i}" for i in range(10)], "series": "atp", "league": "atp",
                       "title": "m", "volume": 10_000.0, "start_time": start.astype(str),
                       "finished": (start + pd.Timedelta(hours=2)).astype(str), "closed_time": None,
                       "fee_rate": 0.0, "seconds_delay": 1, "res0": 1.0, "tok0": "a", "tok1": "b"})
    (tmp_path / "data/raw/trades").mkdir(parents=True)
    ev.to_parquet(tmp_path / EVENTS)
    for i, c in enumerate(conds):
        tape(i).to_parquet(tmp_path / f"data/raw/trades/{c}.parquet")
    (tmp_path / "results").mkdir()
    with gzip.open(tmp_path / "results/universe_conds.txt.gz", "wt") as fh:
        fh.write("\n".join(conds))
    (tmp_path / "models/vision").mkdir(parents=True)
    (tmp_path / "models/vision/frozen_call_model.pkl").write_bytes(b"frozen model")
    (tmp_path / "results/repro/inputs/factors").mkdir(parents=True)
    (tmp_path / "results/repro/inputs/factors/f.csv").write_text("a,b\n1,2\n")
    man = M.create(tmp_path, workers=1)
    return tmp_path, conds, man


def drift(root):
    return json.loads((root / "results/repro/input_drift.json").read_text())


def test_create_records_split_and_every_tape(snap):
    root, conds, man = snap
    assert man["universe"]["n_matches"] == 10 and man["universe"]["n_is"] == 8 and man["universe"]["n_oos"] == 2
    assert man["universe"]["conds_equal_frozen_list"] is True
    assert man["groups"]["tapes"]["n"] == 10
    assert [a["path"] for a in man["groups"]["archived"]] == ["results/repro/inputs/factors/f.csv"]
    assert len(M.read_tsv(root / M.TAPES_TSV)) == 10


def test_identical_inputs_verify(snap):
    root, _, _ = snap
    assert M.verify(root, workers=1) == 0
    assert drift(root)["snapshot_inputs"] is True


def test_reordered_rows_are_the_same_tape(snap):
    root, conds, _ = snap
    tape(3).iloc[::-1].to_parquet(root / f"data/raw/trades/{conds[3]}.parquet")   # new bytes, same trades
    assert M.verify(root, workers=1) == 0
    assert drift(root)["tapes"]["bytes_differ_rows_identical"] == 1


def test_changed_trade_is_drift(snap):
    root, conds, _ = snap
    t = tape(4)
    t.loc[2, "price"] += 0.01                              # one trade differs
    t.to_parquet(root / f"data/raw/trades/{conds[4]}.parquet")
    assert M.verify(root, workers=1) == 3
    d = drift(root)
    assert d["drift"]["tapes_rows_differ"][0]["cond"] == conds[4] and d["snapshot_inputs"] is False
    assert M.verify(root, allow_drift=True, workers=1) == 0   # recorded, run labelled, not silently "snapshot"
    assert drift(root)["snapshot_inputs"] is False


def test_missing_tape_is_drift(snap):
    root, conds, _ = snap
    (root / f"data/raw/trades/{conds[0]}.parquet").unlink()
    assert M.verify(root, workers=1) == 3
    assert drift(root)["drift"]["tapes_missing"] == [conds[0]]


def test_archived_input_change_is_drift(snap):
    root, _, _ = snap
    (root / "results/repro/inputs/factors/f.csv").write_text("a,b\n1,3\n")
    assert M.verify(root, workers=1) == 3
    assert drift(root)["drift"]["archived"] == ["results/repro/inputs/factors/f.csv"]


def test_model_change_is_fatal(snap):
    root, _, _ = snap
    (root / "models/vision/frozen_call_model.pkl").write_bytes(b"another model")
    assert M.verify(root, allow_drift=True, workers=1) == 1


def test_extra_match_changes_the_split_and_is_fatal(snap):
    root, _, _ = snap
    ev = pd.read_parquet(root / EVENTS)
    extra = ev.iloc[[-1]].assign(cond="0x99", start_time=str(pd.Timestamp("2026-02-01", tz="UTC")))
    pd.concat([ev, extra], ignore_index=True).to_parquet(root / EVENTS)
    assert M.verify(root, allow_drift=True, workers=1) == 1
    assert any(f.startswith("universe.n_matches") for f in drift(root)["fatal"])


def test_missing_event_list_is_fatal(snap):
    root, _, _ = snap
    (root / EVENTS).unlink()
    assert M.verify(root, workers=1) == 1


def test_committed_manifest_matches_the_frozen_assets():
    """The committed manifest pins the same frozen model and universe file as the reproduction contract."""
    man = json.loads((ROOT / "results/provenance/inputs_manifest.json").read_text())
    from scripts.repro.common import sha256_file
    assert man["schema"] == M.SCHEMA
    assert man["universe"]["n_matches"] == 13084 and man["universe"]["n_is"] == 10467
    assert man["universe"]["n_oos"] == 2617 and man["universe"]["oos_start_utc"].startswith("2026-08-25T14:15:00")
    assert man["universe"]["conds_sha256"] == sha256_file(ROOT / "results/universe_conds.txt.gz")
    model = {m["path"]: m["sha256"] for m in man["groups"]["models"]}
    assert model["models/vision/frozen_call_model.pkl"] == sha256_file(ROOT / "models/vision/frozen_call_model.pkl")
    for a in man["groups"]["archived"]:
        assert sha256_file(ROOT / a["path"]) == a["sha256"], a["path"]
    assert sha256_file(ROOT / man["groups"]["tapes"]["files_tsv_gz"]) == man["groups"]["tapes"]["files_tsv_gz_sha256"]
