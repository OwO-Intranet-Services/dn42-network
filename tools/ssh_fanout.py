#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

try:
    from tools.yaml_helpers import load_yaml_file
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from yaml_helpers import load_yaml_file

DEFAULT_INVENTORY = Path("inventory.yaml")
DEFAULT_ANSIBLE_CFG = Path("ansible.cfg")
DEFAULT_GROUP = "nodes"


@dataclass(frozen=True)
class HostTarget:
    name: str
    ssh_target: str


@dataclass(frozen=True)
class HostResult:
    name: str
    returncode: int
    output: str


def read_remote_user(ansible_cfg_path: Path) -> str | None:
    if not ansible_cfg_path.exists():
        return None

    config = configparser.ConfigParser()
    config.read(ansible_cfg_path)
    remote_user = config.get("defaults", "remote_user", fallback="").strip()
    return remote_user or None


def load_ssh_targets(
    inventory_path: Path,
    ansible_cfg_path: Path,
    group: str = DEFAULT_GROUP,
) -> list[HostTarget]:
    data = load_yaml_file(inventory_path)
    try:
        hosts = data["all"]["children"][group]["hosts"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"Unable to resolve group '{group}' from {inventory_path}"
        ) from exc

    if not isinstance(hosts, dict):
        raise ValueError(f"Inventory group '{group}' must expose a hosts mapping")

    remote_user = read_remote_user(ansible_cfg_path)
    targets: list[HostTarget] = []

    for host_name, host_vars in hosts.items():
        if host_vars is None:
            host_vars = {}
        if not isinstance(host_vars, dict):
            raise ValueError(f"Inventory entry for '{host_name}' must be a mapping")

        ansible_host = str(host_vars.get("ansible_host", host_name))
        ssh_target = ansible_host
        if remote_user and "@" not in ssh_target:
            ssh_target = f"{remote_user}@{ssh_target}"

        targets.append(HostTarget(name=str(host_name), ssh_target=ssh_target))

    return targets


def run_remote_command(target: HostTarget, command: list[str]) -> HostResult:
    try:
        completed = subprocess.run(
            ["ssh", target.ssh_target, *command],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return HostResult(name=target.name, returncode=255, output=f"{exc}\n")

    output = completed.stdout
    if completed.stderr:
        output += completed.stderr
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"Command exited with status {completed.returncode}\n"

    return HostResult(name=target.name, returncode=completed.returncode, output=output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a command across every host in the inventory nodes group."
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help=f"Inventory file to read (default: {DEFAULT_INVENTORY})",
    )
    parser.add_argument(
        "--ansible-cfg",
        type=Path,
        default=DEFAULT_ANSIBLE_CFG,
        help=f"Ansible config file to read (default: {DEFAULT_ANSIBLE_CFG})",
    )
    parser.add_argument(
        "--group",
        default=DEFAULT_GROUP,
        help=f"Inventory group to target (default: {DEFAULT_GROUP})",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run remotely, for example: hostname",
    )
    args = parser.parse_args()
    if not args.command:
        parser.error("a remote command is required")
    return args


def main() -> int:
    args = parse_args()
    targets = load_ssh_targets(args.inventory, args.ansible_cfg, args.group)

    with ThreadPoolExecutor(max_workers=max(len(targets), 1)) as executor:
        results_by_name = {
            result.name: result
            for result in executor.map(
                lambda target: run_remote_command(target, args.command),
                targets,
            )
        }

    exit_code = 0
    for target in targets:
        result = results_by_name[target.name]
        print(f"--- Output from {target.name} ---")
        if result.output:
            print(result.output, end="" if result.output.endswith("\n") else "\n")
        print("----------------------")
        if result.returncode != 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
