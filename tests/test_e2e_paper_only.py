"""engine/e2e is paper only: the order payload is unsigned and never sent; the only venue HTTP call is GET /time."""
import re
import time

import engine.e2e.e2e_run as E
import engine.e2e.render as R
from engine.e2e import LABEL


def test_e2e_sources_have_no_order_endpoints_or_signing():
    for mod in (E, R):
        src = open(mod.__file__).read().lower()
        for bad in ("post_order", "create_order", "py_clob_client", "py_order_utils", "eth_account",
                    "clob.polymarket.com/order", "/order\"", "sign_order", "private_key =", "ws/user"):
            assert bad not in src, (mod.__name__, bad)
    src = open(E.__file__).read()
    assert '"POST"' not in src and "'POST'" not in src and "method=\"POST\"" not in src
    # the one request to the venue's REST host is a GET of its public clock endpoint
    assert re.findall(r'c\.request\("(\w+)"', src) == ["GET"]
    assert E.TIME_HOST == "clob.polymarket.com" and E.TIME_PATH == "/time"


def test_unsigned_order_payload_is_never_signed_or_sent():
    p = E.unsigned_order("123", 0.43, 100.0, 0.01, {"neg_risk": False})
    assert p["order"]["signature"] is None and p["owner"] is None
    assert p["order"]["maker"] == p["order"]["signer"] == E.ZERO_ADDR
    assert p["_paper"]["unsigned"] is True and p["_paper"]["sent"] is False
    assert p["order"]["makerAmount"] == "43000000" and p["order"]["takerAmount"] == "100000000"
    assert p["_paper"]["label"] == LABEL and "order not sent" in LABEL


def test_clock_maps_wall_to_monotonic():
    c = E.Clock(hz=50)
    w, m = time.time(), time.monotonic()
    assert abs(c.to_mono(w) - m) < 0.005
    assert abs(c.wall(m) - w) < 0.005
    c.stop()
