#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

try:
    from tools.peer_config import dump_peer_yaml, load_peer_yaml_file, normalize_peer_file_data
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from peer_config import dump_peer_yaml, load_peer_yaml_file, normalize_peer_file_data

DEFAULT_PEER_GLOB = "host_vars/*/dn42_peers.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize host_vars/*/dn42_peers.yaml into canonical peer config form."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific peer files to normalize. Defaults to host_vars/*/dn42_peers.yaml.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any file would be rewritten.",
    )
    return parser.parse_args()


def iter_peer_paths(paths: list[Path]) -> list[Path]:
    if paths:
        return sorted(path.resolve() for path in paths)
    return sorted(Path(".").glob(DEFAULT_PEER_GLOB))


def main() -> int:
    args = parse_args()
    changed_paths: list[Path] = []
    invalid = False

    for path in iter_peer_paths(args.paths):
        try:
            original = path.read_text(encoding="utf-8")
            normalized = dump_peer_yaml(normalize_peer_file_data(load_peer_yaml_file(path)))
        except (ValueError, yaml.YAMLError) as exc:
            print(f"{path.as_posix()}: {exc}", file=sys.stderr)
            invalid = True
            continue
        if normalized == original:
            continue

        changed_paths.append(path)
        if not args.check:
            path.write_text(normalized, encoding="utf-8")

    if invalid:
        return 1

    if args.check and changed_paths:
        for path in changed_paths:
            print(path.as_posix())
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
