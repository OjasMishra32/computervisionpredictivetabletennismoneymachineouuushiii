"""COURTSIDE end-to-end timing proof (paper only; no order is ever sent).

engine/e2e/e2e_run.py streams our held-out clip over WebRTC into the vision engine, maps each CallEvent onto a
live Polymarket tennis book for timing, builds an UNSIGNED order payload, adds the measured network leg and the
market's own order delay, and paper-fills against the live book at the executable instant. engine/e2e/render.py
draws the waterfall figure and the timeline video from the trace alone. scripts/e2e_proof.sh runs both.
"""
LABEL = ("paper; order not sent; CV call on our own streamed footage mapped to a live tennis market for timing "
         "(different sport); feed baseline 1 s is simulated (licensed feed not purchased)")
