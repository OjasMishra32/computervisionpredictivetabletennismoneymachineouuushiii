"""The demo video's side panel and the demo runner's text fix-up read only what the demo logged.

  pytest engine/vision/tests -q
"""
import json

from engine.vision import demo_live
from engine.vision.render_demo_video import _esc, _usd, build_log


def _demo():
    call = lambda f, kind, action, t, oid=None, winner=1: dict(
        frame=f, call=kind, direction=1, latency_ms=150.0, t_frame_rel_s=t - 0.15, t_dec_rel_s=t,
        decision=dict(action=action, reason="" if action == "SEND" else ("no_point_decision" if kind == "BOUNCE"
                                                                         else "edge_below_cost"),
                      winner=winner, winner_name="Cristina Bucsa" if winner == 1 else "Xinran Sun", shares=100.0,
                      limit=0.52, ask=0.51, edge=0.007 if action == "SEND" else -0.004, order_id=oid))
    calls = [call(2312, "BOUNCE", "SKIP", -4.5), call(2766, "MISS", "SEND", -0.594, "o1", winner=0),
             call(2819, "MISS", "SEND", -0.133, "o2")]
    orders = [dict(id="o1", t_arrive_rel_s=-0.527, t_exec_rel_s=0.473, status="filled", reason=None),
              dict(id="o2", t_arrive_rel_s=-0.066, t_exec_rel_s=0.934, status="missed", reason="no_liquidity_in_limit")]
    fills = [dict(order_id="o1", shares=100.0, vwap=0.5, fee=1.25, t_exec_rel_s=0.473, token="A")]
    events = [dict(call="MISS", frame=2766, label="MISS", audit="rally_continues", actual_lead_ms=66.7, flight_f_net=2760),
              dict(call="MISS", frame=2819, label="MISS", audit=None, actual_lead_ms=325.0, flight_f_net=2819)]
    an = dict(winner=1, primary=dict(calls=calls, orders=orders, fills=fills))
    return dict(anchors=[an], vision=dict(events=events))


def test_side_panel_is_the_logged_sequence():
    log = build_log(_demo(), 0)
    assert [t for t, *_ in log] == sorted(t for t, *_ in log)
    kinds = [k for _, k, _, _ in log]
    assert kinds == ["bounce", "miss", "arrive", "miss", "arrive", "fill", "nofill"]
    text = " ".join(s for _, _, ls, _ in log for s in ls)
    assert "WRONG" in text and "right" in text                 # f2766 names the loser of the WTA point
    assert "FILLED 100 @ 0.500" in text and "no liquidity in limit" in text
    assert "67 ms after the call" in text and "325 ms after the call" in text


def test_money_text_is_not_mathtext():
    assert _usd(-6.52) == "-$6.52" and _usd(3) == "+$3.00"
    assert _esc("P&L -$1, fees $2") == r"P&L -\$1, fees \$2"


def test_players_sentence_names_this_runs_wrong_call(tmp_path):
    out = dict(mapping=dict(anchor_flight=dict(f_net=2819),
                            players="... can be wrong (the frame-2759 MISS was flagged 'rally_continues' by the label audit)."),
               vision=_demo()["vision"])
    p = tmp_path / "demo_run.json"
    p.write_text(json.dumps(out))
    demo_live.amend_players_text(p)
    m = json.loads(p.read_text())["mapping"]
    assert "2759" not in m["players"] and "frame-2766 MISS was flagged 'rally_continues'" in m["players"]
    assert m["players_amended_by"].startswith("engine/vision/demo_live.py")
