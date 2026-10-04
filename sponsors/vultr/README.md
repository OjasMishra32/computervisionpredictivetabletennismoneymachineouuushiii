# COURTSIDE London — powered by Vultr

COURTSIDE's research question is about speed: can a vision call reach a still-stale tennis market before the book
reprices? Vultr makes that hypothesis measurable from another network location. This integration runs the same
read-only Polymarket tennis probe simultaneously on a **Vultr London server** and the team's **Florida laptop**.

The experiment records every public CLOB book message with both its exchange timestamp and nanosecond local receive
time. It also calls the public CLOB `/time` endpoint every two seconds. London records chrony's system-clock offset;
Florida records the available NTP offset and its uncertainty. That produces three judge-verifiable results:

1. exchange-to-receive feed latency p50/p90/p99;
2. public REST round-trip p50/p90/p99;
3. London's improvement over Florida at each percentile.

The headline uses a paired comparison: the analyzer matches identical updates by exchange timestamp, event type, and
market, then computes Florida arrival minus London arrival for every pair. It reports the matched-event count and the
share London received first. Clock offsets at both ends are interpolated across the run, while Florida's measured NTP
uncertainty remains visible in the evidence JSON.

Run the complete lifecycle:

```bash
.venv/bin/pip install -r sponsors/vultr/requirements.txt
set -a; source .env; set +a
.venv/bin/python sponsors/vultr/experiment.py --minutes 30 --yes-create-billable-instance
```

The generated evidence lives in [`out/summary.json`](out/summary.json) and [`out/dashboard.html`](out/dashboard.html).
See [`deploy.md`](deploy.md) for the exact instance and teardown details. The billable instance is deleted automatically,
including when capture or analysis fails.

## Measured result — October 4, 2026

The 30-minute run observed the same 370 tennis outcome tokens from both sites with a measured 38.3 ms probe-start
skew and zero capture errors. It matched **287,577 identical book updates** across the two streams:

- Vultr London received **99.74%** of matched updates first.
- London's paired median arrival advantage was **70.2 ms**; p90 was **162.2 ms**.
- After subtracting the full **30.3 ms** combined NTP uncertainty bound, the conservative median advantage was
  still **39.9 ms**.
- Median public CLOB REST RTT was **69.7 ms** from London and **184.4 ms** from Florida, a **114.7 ms** improvement.

The observed p99 contained multi-second Florida tail stalls, so the sponsor headline uses the median, p90, matched-event
count, and explicit clock uncertainty. These are public-feed measurements, not authenticated order or execution latency.

## Why this is a substantive Vultr integration

Vultr is the controlled experimental site, not a generic host. Region selection is the independent variable. The
runner freezes one discovered token manifest and gives that exact set to both sites; every message keeps its exchange timestamp, and the clock
offset is captured before and after. The one-command runner uses the Vultr API to provision the smallest instance,
wait for clock sync, deploy, retrieve the evidence, and destroy the machine.

The earlier smoke test also measured public endpoint latency from Newark, Los Angeles, and Amsterdam. Those compact
artifacts are kept in `out/probe_*.json`; the simultaneous London/Florida run is the sponsor result.

## Devpost copy

**Vultr — COURTSIDE London.** Our edge is speed, so we used Vultr as a controlled network experiment. The same
read-only Polymarket tennis probe ran for 30 minutes on a Vultr London server and our Florida laptop, with clock evidence
at both sites. Across 287,577 matched book updates, London received 99.74% first, by **70.2 ms at the median** and
**162.2 ms at p90**. Even subtracting the full clock-uncertainty bound leaves a 39.9 ms median advantage; median public
REST RTT improved by 114.7 ms. The runner provisions, deploys, collects the evidence, and destroys the Vultr instance
automatically. Paper trading only; no orders or trading credentials were used.
