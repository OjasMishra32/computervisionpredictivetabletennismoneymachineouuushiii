import numpy as np
import pandas as pd

from src import tape
from src.tape import taker_fee


def test_fee_matches_polymarket_docs():
    # docs: 100 sports shares at p = 0.5 cost $1.25 at rate 0.05
    assert 100 * taker_fee(0.5, 0.05) == 1.25
    assert taker_fee(0.97, 0.05) < taker_fee(0.5, 0.05)


def test_side_of_book_classification(tmp_path, monkeypatch):
    monkeypatch.setattr(tape.pm, "RAW", tmp_path)
    (tmp_path / "trades").mkdir()
    df = pd.DataFrame({
        "timestamp": [1, 2, 3, 4], "side": ["BUY", "SELL", "BUY", "SELL"], "outcomeIndex": [0, 0, 1, 1],
        "price": [0.6, 0.58, 0.42, 0.40], "size": [10, 10, 10, 10], "proxyWallet": list("abcd"),
        "transactionHash": list("wxyz")})
    df["p0"] = df.price.where(df.outcomeIndex == 0, 1 - df.price)
    df.to_parquet(tmp_path / "trades" / "c.parquet")
    t = tape.load_tape("c")
    # BUY o0 and SELL o1 lift o0's ask; SELL o0 and BUY o1 hit o0's bid
    assert t.at_ask.tolist() == [True, False, False, True]
    assert np.allclose(t.p0, [0.6, 0.58, 0.58, 0.60])


def test_oos_is_last_fifth_and_disjoint():
    u = tape.universe()
    assert abs(u.oos.mean() - 0.2) < 0.001
    assert u.loc[~u.oos, "start"].max() <= u.loc[u.oos, "start"].min()
