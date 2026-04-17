#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from tools.dn42_dns01_hook import (
        DEFAULT_INVENTORY,
        DEFAULT_PLAYBOOK,
        DEFAULT_PROPAGATION_SECONDS,
        DEFAULT_STATE_FILE,
        DEFAULT_TARGET_GROUP,
        DEFAULT_TTL,
        DEFAULT_ZONE,
        load_inventory_data,
        resolve_group_hosts,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from dn42_dns01_hook import (
        DEFAULT_INVENTORY,
        DEFAULT_PLAYBOOK,
        DEFAULT_PROPAGATION_SECONDS,
        DEFAULT_STATE_FILE,
        DEFAULT_TARGET_GROUP,
        DEFAULT_TTL,
        DEFAULT_ZONE,
        load_inventory_data,
        resolve_group_hosts,
    )

DEFAULT_ACME_DIRECTORY = "https://acme.burble.dn42/v1/dn42/acme/directory"
DEFAULT_HOOK_SCRIPT = Path("tools/dn42_dns01_hook.py")
DEFAULT_CERTBOT_CONFIG_DIR = Path(".artifacts/certbot/config")
DEFAULT_CERTBOT_WORK_DIR = Path(".artifacts/certbot/work")
DEFAULT_CERTBOT_LOGS_DIR = Path(".artifacts/certbot/logs")


def extract_default_email(inventory_data: dict[str, object]) -> str | None:
    meta = inventory_data.get("_meta", {})
    if not isinstance(meta, dict):
        return None

    hostvars = meta.get("hostvars", {})
    if not isinstance(hostvars, dict):
        return None

    for host_name in sorted(hostvars):
        host_data = hostvars[host_name]
        if not isinstance(host_data, dict):
            continue

        contacts = host_data.get("network_contacts", {})
        if not isinstance(contacts, dict):
            continue

        email = contacts.get("Email")
        if email:
            return str(email)

    return None


def build_hook_command(
    action: str,
    hook_script: Path,
    inventory: Path,
    playbook: Path,
    state_file: Path,
    zone: str,
    group: str,
    ttl: int,
    propagation_seconds: int,
    limit: str | None,
) -> str:
    command = [
        sys.executable,
        str(hook_script.resolve()),
        action,
        "--inventory",
        str(inventory.resolve()),
        "--playbook",
        str(playbook.resolve()),
        "--state-file",
        str(state_file.resolve()),
        "--zone",
        zone,
        "--group",
        group,
        "--ttl",
        str(ttl),
        "--propagation-seconds",
        str(propagation_seconds),
    ]
    if limit:
        command.extend(["--limit", limit])

    return " ".join(shlex.quote(part) for part in command)


def build_certbot_command(
    certbot_bin: str,
    server: str,
    email: str,
    cert_name: str,
    domains: list[str],
    config_dir: Path,
    work_dir: Path,
    logs_dir: Path,
    auth_hook: str,
    cleanup_hook: str,
) -> list[str]:
    command = [
        certbot_bin,
        "certonly",
        "--manual",
        "--preferred-challenges",
        "dns",
        "--manual-public-ip-logging-ok",
        "--manual-auth-hook",
        auth_hook,
        "--manual-cleanup-hook",
        cleanup_hook,
        "--server",
        server,
        "--config-dir",
        str(config_dir.resolve()),
        "--work-dir",
        str(work_dir.resolve()),
        "--logs-dir",
        str(logs_dir.resolve()),
        "--cert-name",
        cert_name,
        "--agree-tos",
        "--non-interactive",
        "--keep-until-expiring",
        "--email",
        email,
    ]
    for domain in domains:
        command.extend(["-d", domain])
    return command


def install_certificate_outputs(
    config_dir: Path,
    cert_name: str,
    output_cert: Path,
    output_key: Path,
) -> None:
    live_dir = config_dir / "live" / cert_name
    source_cert = live_dir / "fullchain.pem"
    source_key = live_dir / "privkey.pem"

    output_cert.parent.mkdir(parents=True, exist_ok=True)
    output_key.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_cert, output_cert)
    shutil.copy2(source_key, output_key)
    output_cert.chmod(0o600)
    output_key.chmod(0o600)


def run_deploy_playbook(
    playbook: Path,
    inventory: Path,
    tags: str,
    limit: str | None,
) -> None:
    command = ["ansible-playbook", str(playbook), "-i", str(inventory), "--tags", tags]
    if limit:
        command.extend(["--limit", limit])
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Issue a DN42 certificate via certbot manual dns-01 hooks."
    )
    parser.add_argument(
        "--domain",
        dest="domains",
        action="append",
        required=True,
        help="Domain to include on the certificate; repeat for SANs.",
    )
    parser.add_argument("--cert-name", help="Certbot certificate name (defaults to first domain).")
    parser.add_argument("--output-cert", type=Path, required=True)
    parser.add_argument("--output-key", type=Path, required=True)
    parser.add_argument("--server", default=DEFAULT_ACME_DIRECTORY)
    parser.add_argument("--email", help="ACME registration email")
    parser.add_argument("--certbot-bin", default="certbot")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--hook-script", type=Path, default=DEFAULT_HOOK_SCRIPT)
    parser.add_argument("--hook-playbook", type=Path, default=DEFAULT_PLAYBOOK)
    parser.add_argument("--hook-state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--group", default=DEFAULT_TARGET_GROUP)
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    parser.add_argument(
        "--propagation-seconds",
        type=int,
        default=DEFAULT_PROPAGATION_SECONDS,
    )
    parser.add_argument("--limit", help="Optional Ansible limit pattern for hook runs")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CERTBOT_CONFIG_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_CERTBOT_WORK_DIR)
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_CERTBOT_LOGS_DIR)
    parser.add_argument(
        "--deploy-playbook",
        type=Path,
        help="Optional playbook to run after certificate files are written.",
    )
    parser.add_argument(
        "--deploy-tags",
        default="caddy",
        help="Tags to use with --deploy-playbook (default: caddy)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory_data = load_inventory_data(args.inventory)
    resolve_group_hosts(inventory_data, args.group)

    email = args.email or extract_default_email(inventory_data)
    if not email:
        raise SystemExit("Unable to determine ACME email; pass --email explicitly")

    cert_name = args.cert_name or args.domains[0]
    auth_hook = build_hook_command(
        action="auth",
        hook_script=args.hook_script,
        inventory=args.inventory,
        playbook=args.hook_playbook,
        state_file=args.hook_state_file,
        zone=args.zone,
        group=args.group,
        ttl=args.ttl,
        propagation_seconds=args.propagation_seconds,
        limit=args.limit,
    )
    cleanup_hook = build_hook_command(
        action="cleanup",
        hook_script=args.hook_script,
        inventory=args.inventory,
        playbook=args.hook_playbook,
        state_file=args.hook_state_file,
        zone=args.zone,
        group=args.group,
        ttl=args.ttl,
        propagation_seconds=0,
        limit=args.limit,
    )

    certbot_command = build_certbot_command(
        certbot_bin=args.certbot_bin,
        server=args.server,
        email=email,
        cert_name=cert_name,
        domains=args.domains,
        config_dir=args.config_dir,
        work_dir=args.work_dir,
        logs_dir=args.logs_dir,
        auth_hook=auth_hook,
        cleanup_hook=cleanup_hook,
    )
    subprocess.run(certbot_command, check=True)
    install_certificate_outputs(
        config_dir=args.config_dir,
        cert_name=cert_name,
        output_cert=args.output_cert,
        output_key=args.output_key,
    )

    if args.deploy_playbook:
        run_deploy_playbook(
            playbook=args.deploy_playbook,
            inventory=args.inventory,
            tags=args.deploy_tags,
            limit=args.limit,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
