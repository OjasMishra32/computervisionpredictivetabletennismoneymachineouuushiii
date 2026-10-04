"""Run the simultaneous Florida/Vultr-London experiment and always destroy the server."""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
import requests

from probe import discover_tennis_tokens

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
API = "https://api.vultr.com/v2"


class Vultr:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(6):
            try:
                response = requests.request(method, API + path, headers=self.headers, timeout=30, **kwargs)
            except requests.RequestException:
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt, 20))
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt == 5:
                break
            time.sleep(min(2 ** attempt, 20))
        if response.status_code >= 400:
            raise RuntimeError(f"Vultr API {method} {path} failed with HTTP {response.status_code}")
        return {} if response.status_code == 204 else response.json()

    def create(self, region: str, plan: str) -> dict:
        cloud = """#cloud-config
package_update: true
packages: [chrony, python3-venv]
runcmd:
  - [systemctl, enable, --now, chrony]
"""
        return self.request("POST", "/instances", json={
            "region": region, "plan": plan, "os_id": 2284,
            "label": "courtside-london-probe", "hostname": "courtside-london",
            "tags": ["courtside", "latency-probe"], "enable_ipv6": False,
            "user_data": base64.b64encode(cloud.encode()).decode(),
        })["instance"]

    def instance(self, instance_id: str) -> dict:
        return self.request("GET", f"/instances/{instance_id}")["instance"]

    def delete(self, instance_id: str) -> None:
        self.request("DELETE", f"/instances/{instance_id}")


def wait_instance(api: Vultr, instance_id: str, timeout: float = 600) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        instance = api.instance(instance_id)
        if (instance.get("status") == "active" and instance.get("server_status") == "ok"
                and instance.get("main_ip") not in (None, "", "0.0.0.0")):
            return instance
        time.sleep(8)
    raise TimeoutError("Vultr instance did not become ready")


def wait_ssh(instance: dict, timeout: float = 360) -> paramiko.SSHClient:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(instance["main_ip"], username="root", password=instance["default_password"],
                           timeout=15, look_for_keys=False, allow_agent=False)
            return client
        except Exception as exc:
            last_error = exc
            client.close()
            time.sleep(8)
    raise TimeoutError(f"SSH did not become ready: {type(last_error).__name__}")


def remote(client: paramiko.SSHClient, command: str, timeout: float = 900) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output, error = stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {error[-500:]}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--region", default="lhr")
    parser.add_argument("--plan", default="vc2-1c-1gb")
    parser.add_argument("--yes-create-billable-instance", action="store_true")
    args = parser.parse_args()
    if not args.yes_create_billable_instance:
        raise SystemExit("refusing to create a billable instance without --yes-create-billable-instance")
    token = os.environ.get("VULTR_API_KEY")
    if not token:
        raise SystemExit("missing VULTR_API_KEY")

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"experiment": "COURTSIDE London", "region": args.region, "plan": args.plan,
                "minutes": args.minutes, "started_at": datetime.now(timezone.utc).isoformat(),
                "instance_deleted": False}
    api, instance_id, client = Vultr(token), None, None
    try:
        created = api.create(args.region, args.plan)
        instance_id = created["id"]
        manifest["instance_id"] = instance_id
        instance = wait_instance(api, instance_id)
        manifest["public_ip"] = instance["main_ip"]
        client = wait_ssh(instance)
        remote(client, "cloud-init status --wait >/dev/null && mkdir -p /opt/courtside")
        with client.open_sftp() as sftp:
            sftp.put(str(HERE / "probe.py"), "/opt/courtside/probe.py")
            sftp.put(str(HERE / "requirements.txt"), "/opt/courtside/requirements.txt")
        remote(client, "python3 -m venv /opt/courtside/venv && "
                       "/opt/courtside/venv/bin/pip install -q -r /opt/courtside/requirements.txt")
        tokens = discover_tennis_tokens()
        token_manifest = OUT / "token_manifest.json"
        token_manifest.write_text(json.dumps(tokens, separators=(",", ":")))
        manifest["frozen_token_count"] = len(tokens)
        with client.open_sftp() as sftp:
            sftp.put(str(token_manifest), "/opt/courtside/token_manifest.json")
        remote_path = "/opt/courtside/probe_london.jsonl"
        command = (f"nohup /opt/courtside/venv/bin/python /opt/courtside/probe.py --site london "
                   f"--minutes {args.minutes} --tokens-file /opt/courtside/token_manifest.json "
                   f"--out {remote_path} >/opt/courtside/probe.log 2>&1 & echo $!")
        launch_request_ns = time.time_ns()
        remote_pid = int(remote(client, command).strip())
        launch_ack_ns = time.time_ns()
        manifest["remote_pid"] = remote_pid
        estimated_remote_start_ns = (launch_request_ns + launch_ack_ns) // 2
        local = subprocess.Popen([sys.executable, str(HERE / "probe.py"), "--site", "florida",
                                  "--minutes", str(args.minutes), "--tokens-file", str(token_manifest),
                                  "--out", str(OUT / "probe_florida.jsonl")])
        manifest["estimated_start_skew_ms"] = round((time.time_ns() - estimated_remote_start_ns) / 1e6, 3)
        manifest["ssh_launch_round_trip_ms"] = round((launch_ack_ns - launch_request_ns) / 1e6, 3)
        if local.wait() != 0:
            raise RuntimeError("Florida probe failed")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if remote(client, f"kill -0 {remote_pid} >/dev/null 2>&1; echo $?", timeout=30).strip() != "0":
                break
            time.sleep(5)
        with client.open_sftp() as sftp:
            sftp.get(remote_path, str(OUT / "probe_london.jsonl"))
        subprocess.run([sys.executable, str(HERE / "summarize.py"),
                        str(OUT / "probe_london.jsonl"), str(OUT / "probe_florida.jsonl")], check=True)
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        if client:
            client.close()
        if instance_id:
            try:
                api.delete(instance_id)
                manifest["instance_deleted"] = True
                manifest["deleted_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                manifest["delete_error"] = type(exc).__name__
        (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not manifest["instance_deleted"]:
        raise SystemExit("probe completed, but automatic instance deletion needs attention")


if __name__ == "__main__":
    main()
