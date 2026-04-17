#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

DEFAULT_INVENTORY = Path("inventory.yaml")
DEFAULT_PLAYBOOK = Path("playbooks/dns-acme-challenge.yaml")
DEFAULT_STATE_FILE = Path(".artifacts/dns_acme_challenges.json")
DEFAULT_ZONE = "iris.dn42"
DEFAULT_TARGET_GROUP = "anycast"
DEFAULT_TTL = 60
DEFAULT_PROPAGATION_SECONDS = 10


def normalize_domain(domain: str) -> str:
    normalized = domain.strip().rstrip(".")
    if normalized.startswith("*."):
        normalized = normalized[2:]
    if not normalized:
        raise ValueError("domain must not be empty")
    return normalized


def build_record_fqdn(domain: str, zone: str) -> str:
    normalized_domain = normalize_domain(domain)
    normalized_zone = normalize_domain(zone)

    if normalized_domain == normalized_zone:
        return f"_acme-challenge.{normalized_zone}"

    zone_suffix = f".{normalized_zone}"
    if not normalized_domain.endswith(zone_suffix):
        raise ValueError(
            f"domain '{normalized_domain}' is outside the managed zone '{normalized_zone}'"
        )

    relative_domain = normalized_domain[: -len(zone_suffix)]
    return f"_acme-challenge.{relative_domain}.{normalized_zone}"


def relative_record_name(record_fqdn: str, zone: str) -> str:
    normalized_record = normalize_domain(record_fqdn)
    normalized_zone = normalize_domain(zone)
    zone_suffix = f".{normalized_zone}"

    if normalized_record == f"_acme-challenge.{normalized_zone}":
        return "_acme-challenge"
    if not normalized_record.endswith(zone_suffix):
        raise ValueError(
            f"record '{normalized_record}' is outside the managed zone '{normalized_zone}'"
        )

    return normalized_record[: -len(zone_suffix)]


def load_state(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = payload.get("records", {})
    if not isinstance(raw_records, dict):
        raise ValueError("state file records must be a mapping")

    state: dict[str, list[str]] = {}
    for record_fqdn, values in raw_records.items():
        if not isinstance(values, list):
            raise ValueError(f"state entry for '{record_fqdn}' must be a list")
        state[str(record_fqdn)] = sorted({str(value) for value in values})

    return state


def save_state(path: Path, state: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {
        "records": {
            record_fqdn: sorted(values)
            for record_fqdn, values in sorted(state.items())
        }
    }
    path.write_text(
        f"{json.dumps(serialized, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def with_auth_value(
    state: dict[str, list[str]],
    record_fqdn: str,
    value: str,
) -> dict[str, list[str]]:
    updated = {name: list(values) for name, values in state.items()}
    values = updated.setdefault(record_fqdn, [])
    if value not in values:
        values.append(value)
        values.sort()
    return updated


def without_auth_value(
    state: dict[str, list[str]],
    record_fqdn: str,
    value: str,
) -> dict[str, list[str]]:
    updated = {name: list(values) for name, values in state.items()}
    values = [candidate for candidate in updated.get(record_fqdn, []) if candidate != value]
    if values:
        updated[record_fqdn] = values
    else:
        updated.pop(record_fqdn, None)
    return updated


def build_ansible_records(
    state: dict[str, list[str]],
    zone: str,
    ttl: int,
) -> list[dict[str, object]]:
    return [
        {
            "name": relative_record_name(record_fqdn, zone),
            "ttl": ttl,
            "values": list(values),
        }
        for record_fqdn, values in sorted(state.items())
    ]


def load_inventory_data(inventory_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        ["ansible-inventory", "-i", str(inventory_path), "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    if not isinstance(data, dict):
        raise ValueError("ansible-inventory returned a non-mapping payload")
    return data


def resolve_group_hosts(inventory_data: dict[str, object], group: str) -> list[str]:
    group_data = inventory_data.get(group)
    if not isinstance(group_data, dict):
        raise ValueError(f"Inventory group '{group}' was not found")

    raw_hosts = group_data.get("hosts", [])
    if not isinstance(raw_hosts, list):
        raise ValueError(f"Inventory group '{group}' does not expose a host list")
    if not raw_hosts:
        raise ValueError(f"Inventory group '{group}' has no hosts")

    return [str(host) for host in raw_hosts]


def run_challenge_playbook(
    playbook_path: Path,
    inventory_path: Path,
    target_group: str,
    records: list[dict[str, object]],
    limit: str | None,
) -> None:
    extra_vars = json.dumps(
        {
            "dns_acme_challenge_records": records,
            "dns_acme_challenge_target_group": target_group,
        }
    )
    command = [
        "ansible-playbook",
        str(playbook_path),
        "-i",
        str(inventory_path),
        "--extra-vars",
        extra_vars,
    ]
    if limit:
        command.extend(["--limit", limit])

    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish or remove dns-01 TXT records on authoritative DN42 nodes."
    )
    parser.add_argument("action", choices=("auth", "cleanup"))
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--playbook", type=Path, default=DEFAULT_PLAYBOOK)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--group", default=DEFAULT_TARGET_GROUP)
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    parser.add_argument(
        "--propagation-seconds",
        type=int,
        default=DEFAULT_PROPAGATION_SECONDS,
        help=f"Seconds to wait after auth publication (default: {DEFAULT_PROPAGATION_SECONDS})",
    )
    parser.add_argument("--limit", help="Optional Ansible limit pattern")
    parser.add_argument("--domain", help="Override CERTBOT_DOMAIN for manual testing")
    parser.add_argument(
        "--validation",
        help="Override CERTBOT_VALIDATION for manual testing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    domain = args.domain or os.environ.get("CERTBOT_DOMAIN")
    validation = args.validation or os.environ.get("CERTBOT_VALIDATION")

    if not domain:
        raise SystemExit("CERTBOT_DOMAIN or --domain is required")
    if not validation:
        raise SystemExit("CERTBOT_VALIDATION or --validation is required")

    inventory_data = load_inventory_data(args.inventory)
    resolve_group_hosts(inventory_data, args.group)

    record_fqdn = build_record_fqdn(domain, args.zone)
    current_state = load_state(args.state_file)
    if args.action == "auth":
        next_state = with_auth_value(current_state, record_fqdn, validation)
    else:
        next_state = without_auth_value(current_state, record_fqdn, validation)

    records = build_ansible_records(next_state, args.zone, args.ttl)
    run_challenge_playbook(
        playbook_path=args.playbook,
        inventory_path=args.inventory,
        target_group=args.group,
        records=records,
        limit=args.limit,
    )
    save_state(args.state_file, next_state)

    if args.action == "auth" and args.propagation_seconds > 0:
        time.sleep(args.propagation_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
