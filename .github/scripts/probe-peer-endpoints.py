import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import yaml


class AnsibleSafeLoader(yaml.SafeLoader):
    pass

AnsibleSafeLoader.add_constructor(
    "!vault", lambda loader, node: loader.construct_scalar(node)
)

host = os.environ["DEPLOY_HOST"]
targets = set(json.loads(os.environ["DEPLOY_TARGETS"]))
peers_file = Path("host_vars") / host / "dn42_peers.yaml"
if not peers_file.is_file():
    print(f"::error title=Preflight failed::{peers_file} not found.")
    sys.exit(1)

inv = yaml.safe_load(Path("inventory.yaml").read_text())
host_vars = (
    inv.get("all", {}).get("children", {}).get("nodes", {}).get("hosts", {}).get(host)
    or {}
)
ip_support = host_vars.get("ip_support", "dual")

data = yaml.load(peers_file.read_text(), Loader=AnsibleSafeLoader) or {}
peer_list = data.get("peers") or []

endpoints: list[tuple[str, str]] = []
seen_targets: set[str] = set()
for entry in peer_list:
    bgp = entry.get("bgp") or {}
    asn = bgp.get("asn")
    if asn is None:
        continue
    target = f"dn42_{str(asn)[-4:]}"
    if target not in targets:
        continue
    seen_targets.add(target)
    wg = entry.get("wg") or {}
    endpoint = wg.get("endpoint")
    if not endpoint:
        continue
    if str(endpoint).lstrip().startswith("$ANSIBLE_VAULT;"):
        vault_pass_file = Path(".secrets/vault_pass.txt")
        if not vault_pass_file.is_file():
            print(f"::notice::{target} endpoint is vault-encrypted; no vault password available, skipping")
            continue
        try:
            decrypted = subprocess.run(
                ["ansible-vault", "decrypt", "--vault-password-file", str(vault_pass_file), "--output", "-"],
                input=str(endpoint),
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            if not decrypted:
                print(f"::notice::{target} vault-encrypted endpoint decrypted to empty; skipping")
                continue
            host_part = decrypted.rsplit(":", 1)[0].strip("[]")
            print(f"::add-mask::{host_part}")
            print(f"::add-mask::{decrypted}")
            try:
                for info in socket.getaddrinfo(host_part, None):
                    print(f"::add-mask::{info[4][0]}")
            except OSError:
                pass
            endpoints.append((target, host_part))
        except subprocess.CalledProcessError:
            print(f"::warning::{target} endpoint vault decryption failed; skipping reachability check")
        continue
    host_part = endpoint.rsplit(":", 1)[0].strip("[]")
    print(f"::add-mask::{host_part}")
    print(f"::add-mask::{endpoint}")
    try:
        for info in socket.getaddrinfo(host_part, None):
            print(f"::add-mask::{info[4][0]}")
    except OSError:
        pass
    endpoints.append((target, host_part))

missing = targets - seen_targets
if missing:
    print(f"::notice::Targets not in peers file (likely removals): {sorted(missing)}")

if not endpoints:
    print("No active peer endpoints to verify; skipping reachability check.")
    sys.exit(0)

required_families: set[int] = set()
if ip_support in ("dual", "ipv4"):
    required_families.add(socket.AF_INET)
if ip_support in ("dual", "ipv6"):
    required_families.add(socket.AF_INET6)

failures: list[tuple[str, str, str]] = []
for target, host_part in endpoints:
    try:
        results = socket.getaddrinfo(host_part, None, socket.AF_UNSPEC, socket.SOCK_DGRAM)
    except OSError as e:
        failures.append((target, host_part, f"DNS resolution failed: {e}"))
        continue

    resolved_families = {r[0] for r in results}
    matched = resolved_families & required_families
    if matched:
        af_names = ", ".join(
            "IPv4" if f == socket.AF_INET else "IPv6" for f in sorted(matched)
        )
        print(f"{target}: {host_part} resolves with {af_names} (node ip_support={ip_support}) ✓")
    else:
        resolved_names = ", ".join(
            "IPv4" if f == socket.AF_INET else "IPv6" for f in sorted(resolved_families)
        )
        failures.append((
            target,
            host_part,
            f"resolves to {resolved_names} but node requires {ip_support}",
        ))

if failures:
    for target, host_part, reason in failures:
        print(
            f"::error title=Preflight failed::Peer {target} endpoint "
            f"{host_part}: {reason}"
        )
    sys.exit(1)
