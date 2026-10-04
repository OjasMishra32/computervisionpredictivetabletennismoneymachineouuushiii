# Deployment and teardown

`experiment.py` owns the complete lifecycle. It creates one Vultr Cloud Compute instance, waits for cloud-init and
chrony, uploads the public-data probe, starts London and Florida captures together, downloads the London artifact,
builds the summary/dashboard, and deletes the instance in a `finally` block.

## Configuration

- Region: `lhr` (London)
- Plan: `vc2-1c-1gb` (1 shared vCPU, 1 GB RAM, 25 GB SSD)
- OS: Ubuntu 24.04 x64 (`os_id=2284`)
- Duration: 30 minutes by default
- Credentials on the server: none. The probe uses public Gamma, CLOB REST, and CLOB websocket endpoints.
- Vultr token: read only from the local root `.env` as `VULTR_API_KEY`; it is never uploaded or printed.
- Clock proof: chrony is installed before capture and `chronyc tracking` is stored at the beginning and end.

```bash
python3 -m venv .venv
.venv/bin/pip install -r sponsors/vultr/requirements.txt
set -a; source .env; set +a
.venv/bin/python sponsors/vultr/experiment.py --minutes 30 --yes-create-billable-instance
```

To summarize existing raw captures again:

```bash
.venv/bin/python sponsors/vultr/summarize.py \
  sponsors/vultr/out/probe_london.jsonl sponsors/vultr/out/probe_florida.jsonl
```

The raw JSONL files are gitignored because they contain repetitive message-level telemetry. `summary.json`,
`dashboard.html`, and the non-secret `run_manifest.json` are review artifacts. The run manifest must say
`"instance_deleted": true`; also verify the account has no `courtside-london-probe` instance after every run.

This is a read-only network experiment. It does not sign or place orders, use an authenticated market endpoint, or
claim that a measured public-feed delay equals order execution latency.

## Completed run

The evidence run used `lhr` / `vc2-1c-1gb` from 04:17:07 to 04:47:08 UTC on October 4, 2026. The runner deleted
instance `9c0a9adb-8fbb-466d-93dc-179eac3d02b9` at 04:47:31 UTC, and a follow-up Vultr API check returned zero
remaining instances tagged `courtside`. See `out/run_manifest.json` for the lifecycle record.
