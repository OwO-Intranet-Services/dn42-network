#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools.peer_config import load_peer_yaml_text, normalize_peer_entry_for_compare
    from tools.yaml_helpers import load_yaml_file
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from peer_config import load_peer_yaml_text, normalize_peer_entry_for_compare
    from yaml_helpers import load_yaml_file

DEFAULT_INVENTORY = Path("inventory.yaml")
DEFAULT_COMMON_VARS = Path("group_vars/all/common.yaml")
DEFAULT_DN42_PREFIX = "dn42_"
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class PeerSessionDiffError(ValueError):
    """Raised when peer session inputs are invalid for CI evaluation."""


def normalize_ref(ref: str) -> str:
    stripped = ref.strip()
    if stripped and set(stripped) == {"0"}:
        return EMPTY_TREE_SHA
    return stripped


def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def is_peer_file_path(path: Path) -> bool:
    return path.parts[:1] == ("host_vars",) and len(path.parts) == 3 and path.name == "dn42_peers.yaml"


def peer_host_from_path(path: Path) -> str:
    return path.parts[1]


def load_active_dn42_hosts(inventory_path: Path) -> set[str]:
    data = load_yaml_file(inventory_path)
    try:
        hosts = data["all"]["children"]["dn42"]["hosts"]
    except (KeyError, TypeError) as exc:
        raise PeerSessionDiffError(
            f"Unable to resolve dn42 hosts from {inventory_path}"
        ) from exc

    if not isinstance(hosts, dict):
        raise PeerSessionDiffError("Inventory dn42 group must expose a hosts mapping")

    return {str(host_name) for host_name in hosts}


def load_dn42_prefix(repo_root: Path) -> str:
    common_vars_path = repo_root / DEFAULT_COMMON_VARS
    if not common_vars_path.exists():
        return DEFAULT_DN42_PREFIX

    try:
        data = load_yaml_file(common_vars_path)
    except Exception:
        return DEFAULT_DN42_PREFIX

    if not isinstance(data, dict):
        return DEFAULT_DN42_PREFIX

    prefix = data.get("dn42_prefix")
    if isinstance(prefix, str) and prefix:
        return prefix

    return DEFAULT_DN42_PREFIX


def dn42_target_name(asn: int, prefix: str) -> str:
    return f"{prefix}{str(asn)[-4:]}"


def build_deploy_matrix(
    host_changes: dict[str, dict[str, list[dict[str, Any]]]],
    dn42_prefix: str,
) -> list[dict[str, Any]]:
    deploy_matrix: list[dict[str, Any]] = []

    for host in sorted(host_changes):
        targets = sorted(
            {
                dn42_target_name(entry["asn"], dn42_prefix)
                for change_type in ("added", "updated", "removed")
                for entry in host_changes[host][change_type]
            }
        )
        if targets:
            deploy_matrix.append({"host": host, "targets": targets})

    return deploy_matrix


def list_changed_peer_paths(repo_root: Path, base_ref: str, head_ref: str) -> list[Path]:
    completed = run_git(repo_root, "diff", "--name-only", base_ref, head_ref)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise PeerSessionDiffError(f"Unable to diff refs {base_ref}..{head_ref}: {stderr}")

    paths: list[Path] = []
    for line in completed.stdout.splitlines():
        candidate = Path(line.strip())
        if line.strip() and is_peer_file_path(candidate):
            paths.append(candidate)
    return sorted(paths)


def read_git_file(repo_root: Path, ref: str, path: Path) -> str | None:
    completed = run_git(repo_root, "show", f"{ref}:{path.as_posix()}")
    if completed.returncode == 0:
        return completed.stdout

    stderr = completed.stderr.lower()
    if "does not exist" in stderr or "exists on disk, but not in" in stderr:
        return None

    detail = completed.stderr.strip() or completed.stdout.strip()
    raise PeerSessionDiffError(f"Unable to read {path} from {ref}: {detail}")


def parse_peer_file(text: str, source: str) -> dict[int, dict[str, Any]]:
    try:
        data = load_peer_yaml_text(text)
    except Exception as exc:
        raise PeerSessionDiffError(f"{source}: invalid YAML: {exc}") from exc

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise PeerSessionDiffError(f"{source}: top-level YAML must be a mapping")

    peers = data.get("peers")
    if peers is None:
        peers = []
    if not isinstance(peers, list):
        raise PeerSessionDiffError(f"{source}: 'peers' must be a list")

    parsed: dict[int, dict[str, Any]] = {}
    for index, peer in enumerate(peers):
        item_source = f"{source} peer[{index}]"
        if not isinstance(peer, dict):
            raise PeerSessionDiffError(f"{item_source}: peer entry must be a mapping")

        bgp = peer.get("bgp")
        if not isinstance(bgp, dict):
            raise PeerSessionDiffError(f"{item_source}: missing 'bgp' mapping")
        if "asn" not in bgp:
            raise PeerSessionDiffError(f"{item_source}: missing 'bgp.asn'")

        try:
            asn = int(bgp["asn"])
        except (TypeError, ValueError) as exc:
            raise PeerSessionDiffError(f"{item_source}: invalid ASN {bgp['asn']!r}") from exc

        removed = peer.get("removed", False)
        if not isinstance(removed, bool):
            raise PeerSessionDiffError(f"{item_source}: 'removed' must be a boolean")

        try:
            normalized = normalize_peer_entry_for_compare(peer)
        except ValueError as exc:
            raise PeerSessionDiffError(f"{item_source}: {exc}") from exc

        if asn in parsed:
            raise PeerSessionDiffError(f"{source}: duplicate ASN {asn}")

        parsed[asn] = normalized

    return parsed


def peer_is_removed(peer: dict[str, Any] | None) -> bool:
    return bool(peer and peer.get("removed", False))


def compare_peer_sets(
    host: str,
    path: Path,
    base_peers: dict[int, dict[str, Any]],
    head_peers: dict[int, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    changes = {"added": [], "updated": [], "removed": []}
    errors: list[str] = []

    for asn in sorted(set(base_peers) | set(head_peers)):
        before = base_peers.get(asn)
        after = head_peers.get(asn)

        if before is None and after is None:
            continue

        if before is None:
            change_type = "removed" if peer_is_removed(after) else "added"
            payload = {"asn": asn, "before": None, "after": after}
            changes[change_type].append(payload)
            continue

        if after is None:
            changes["removed"].append({"asn": asn, "before": before, "after": None})
            continue

        if peer_is_removed(before) and peer_is_removed(after):
            continue

        if before == after:
            continue

        if not peer_is_removed(before) and peer_is_removed(after):
            change_type = "removed"
        elif peer_is_removed(before) and not peer_is_removed(after):
            change_type = "added"
        else:
            change_type = "updated"

        payload = {"asn": asn, "before": before, "after": after}
        changes[change_type].append(payload)

    for change_type in changes:
        changes[change_type].sort(key=lambda item: item["asn"])

    return changes, errors


def summarize_report(report: dict[str, Any]) -> str:
    lines = [
        "# Peer Session Diff",
        "",
        f"- Base: `{report['base_ref']}`",
        f"- Head: `{report['head_ref']}`",
    ]

    if report["deploy_hosts"]:
        lines.extend(
            [
                "",
                "## Deploy Hosts",
                *[
                    f"- `{entry['host']}`: {', '.join(f'`{target}`' for target in entry['targets'])}"
                    for entry in report["deploy_matrix"]
                ],
            ]
        )
    else:
        lines.extend(["", "No semantic peer-session changes detected on active DN42 hosts."])

    host_changes = report["host_changes"]
    if host_changes:
        lines.extend(["", "## Active Host Changes"])
        for host in sorted(host_changes):
            lines.extend(["", f"### {host}"])
            for change_type in ("added", "updated", "removed"):
                entries = host_changes[host][change_type]
                if not entries:
                    continue
                labels = ", ".join(f"AS{entry['asn']}" for entry in entries)
                lines.append(f"- {change_type.title()}: {labels}")

    if report["ignored_paths"]:
        lines.extend(
            [
                "",
                "## Ignored Inactive Peer Files",
                *[f"- `{path}`" for path in report["ignored_paths"]],
            ]
        )

    if report["errors"]:
        lines.extend(["", "## Errors", *[f"- {error}" for error in report["errors"]]])

    return "\n".join(lines).rstrip() + "\n"


def write_summary(markdown_summary: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown_summary)


def build_report(
    repo_root: Path,
    inventory_path: Path,
    base_ref: str,
    head_ref: str,
) -> dict[str, Any]:
    normalized_base = normalize_ref(base_ref)
    normalized_head = normalize_ref(head_ref)
    active_hosts = load_active_dn42_hosts(inventory_path)
    dn42_prefix = load_dn42_prefix(repo_root)
    changed_paths = list_changed_peer_paths(repo_root, normalized_base, normalized_head)

    host_changes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    hard_delete_errors: list[str] = []
    errors: list[str] = []
    ignored_paths: list[str] = []

    for path in changed_paths:
        host = peer_host_from_path(path)
        if host not in active_hosts:
            ignored_paths.append(path.as_posix())
            continue

        base_text = read_git_file(repo_root, normalized_base, path)
        head_text = read_git_file(repo_root, normalized_head, path)

        if head_text is None:
            message = (
                f"Active DN42 peer file {path} was deleted. Keep the file and mark removed peer sessions with removed: true instead."
            )
            hard_delete_errors.append(message)
            errors.append(message)
            continue

        try:
            base_peers = parse_peer_file(base_text, f"{normalized_base}:{path}") if base_text is not None else {}
            head_peers = parse_peer_file(head_text, f"{normalized_head}:{path}")
        except PeerSessionDiffError as exc:
            errors.append(str(exc))
            continue

        changes, compare_errors = compare_peer_sets(host, path, base_peers, head_peers)
        if compare_errors:
            hard_delete_errors.extend(compare_errors)
            errors.extend(compare_errors)

        if any(changes.values()):
            host_changes[host] = changes

    deploy_matrix = build_deploy_matrix(host_changes, dn42_prefix)
    deploy_hosts = [entry["host"] for entry in deploy_matrix]
    report = {
        "base_ref": normalized_base,
        "head_ref": normalized_head,
        "has_changes": bool(deploy_matrix),
        "deploy_hosts": deploy_hosts,
        "deploy_matrix": deploy_matrix,
        "host_changes": host_changes,
        "hard_delete_errors": hard_delete_errors,
        "errors": errors,
        "ignored_paths": ignored_paths,
    }
    report["markdown_summary"] = summarize_report(report)
    return report


def write_json_report(report: dict[str, Any], output: str) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        sys.stdout.write(payload + "\n")
        return

    output_path = Path(output)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect semantic DN42 peer session changes between two git refs."
    )
    parser.add_argument("--base-ref", required=True, help="Base git ref or SHA to compare from.")
    parser.add_argument("--head-ref", required=True, help="Head git ref or SHA to compare to.")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help=f"Inventory file to read active DN42 hosts from (default: {DEFAULT_INVENTORY})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root containing the git checkout and inventory file.",
    )
    parser.add_argument(
        "--json-output",
        default="-",
        help="Write JSON report to this path, or '-' for stdout (default: -).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    inventory_path = args.inventory if args.inventory.is_absolute() else repo_root / args.inventory

    try:
        report = build_report(repo_root, inventory_path, args.base_ref, args.head_ref)
    except PeerSessionDiffError as exc:
        report = {
            "base_ref": normalize_ref(args.base_ref),
            "head_ref": normalize_ref(args.head_ref),
            "has_changes": False,
            "deploy_hosts": [],
            "deploy_matrix": [],
            "host_changes": {},
            "hard_delete_errors": [],
            "errors": [str(exc)],
            "ignored_paths": [],
        }
        report["markdown_summary"] = summarize_report(report)
        write_summary(report["markdown_summary"])
        write_json_report(report, args.json_output)
        return 1

    write_summary(report["markdown_summary"])
    write_json_report(report, args.json_output)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
