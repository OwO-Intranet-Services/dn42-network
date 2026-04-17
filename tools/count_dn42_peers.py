#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from tools.yaml_helpers import load_yaml_file
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from yaml_helpers import load_yaml_file

DEFAULT_PEER_DIR = Path("group_vars/dn42/peers")


def collect_unique_asns(peer_dir: Path) -> set[int]:
    unique_asns: set[int] = set()

    for peer_file in sorted(peer_dir.glob("*.yaml")):
        data = load_yaml_file(peer_file)
        if not isinstance(data, dict):
            raise ValueError(f"{peer_file} must contain a mapping at the top level")

        for node_config in data.values():
            if not isinstance(node_config, dict):
                continue

            peers = node_config.get("peers", [])
            if not isinstance(peers, list):
                raise ValueError(f"{peer_file} has a non-list 'peers' value")

            for peer in peers:
                if not isinstance(peer, dict) or peer.get("removed"):
                    continue

                bgp = peer.get("bgp", {})
                if not isinstance(bgp, dict) or "asn" not in bgp:
                    continue

                unique_asns.add(int(bgp["asn"]))

    return unique_asns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count distinct active DN42 peer ASNs from peer YAML files."
    )
    parser.add_argument(
        "--peer-dir",
        type=Path,
        default=DEFAULT_PEER_DIR,
        help=f"Peer directory to scan (default: {DEFAULT_PEER_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(len(collect_unique_asns(args.peer_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
