import os
import subprocess
import sys

completed = subprocess.run(
    ["git", "diff", "--name-only", os.environ["BASE_REF"], os.environ["HEAD_REF"]],
    check=True,
    capture_output=True,
    text=True,
)
changed_paths = [
    line.strip()
    for line in completed.stdout.splitlines()
    if line.strip().startswith("host_vars/") and line.strip().endswith("/dn42_peers.yaml")
]

if not changed_paths:
    print("No changed peer files to normalize.")
    raise SystemExit(0)

subprocess.run([sys.executable, "tools/normalize_peer_configs.py", *changed_paths], check=True)
print("Normalized peer files:")
for path in changed_paths:
    print(f"- {path}")
