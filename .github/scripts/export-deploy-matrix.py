import json
import os
import subprocess
import sys

event_name = os.environ["EVENT_NAME"]
if event_name == "pull_request":
    subprocess.run(
        [
            sys.executable,
            "tools/peer_session_diff.py",
            "--base-ref",
            os.environ["BASE_REF"],
            "--head-ref",
            os.environ["HEAD_REF"],
            "--json-output",
            "peer-session-report.json",
        ],
        check=True,
    )
    with open("peer-session-report.json", "r", encoding="utf-8") as handle:
        report = json.load(handle)
    has_changes = bool(report["has_changes"])
    deploy_matrix = report["deploy_matrix"]
else:
    deploy_host = os.environ["DEPLOY_HOST"].strip()
    raw_targets = os.environ["PEER_TARGETS"].strip()
    if not deploy_host:
        raise SystemExit("deploy_host is required")

    try:
        parsed = json.loads(raw_targets)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in raw_targets.split(",") if item.strip()]

    if isinstance(parsed, str):
        targets = [parsed]
    elif isinstance(parsed, list):
        targets = [str(item).strip() for item in parsed if str(item).strip()]
    else:
        raise SystemExit("peer_targets must be a JSON array, JSON string, or comma-separated list")

    if not targets:
        raise SystemExit("peer_targets must resolve to at least one peer")

    has_changes = True
    deploy_matrix = [{"host": deploy_host, "targets": targets}]

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
    handle.write(f"has_changes={'true' if has_changes else 'false'}\n")
    handle.write(f"deploy_matrix={json.dumps(deploy_matrix)}\n")
