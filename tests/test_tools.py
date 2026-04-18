from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.count_dn42_peers import collect_unique_asns
from tools.ssh_fanout import load_ssh_targets


class CountDn42PeersTests(unittest.TestCase):
    def test_collect_unique_asns_ignores_removed_peers_and_unknown_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            peer_dir = Path(tmpdir)
            (peer_dir / "lax-01").mkdir()
            (peer_dir / "ams-01").mkdir()
            (peer_dir / "lax-01" / "dn42_peers.yaml").write_text(
                textwrap.dedent(
                    """\
                    peers:
                      - comment: active
                        wg:
                          psk: !vault |
                            encrypted
                        bgp:
                          asn: 4242420001
                      - comment: removed
                        removed: true
                        bgp:
                          asn: 4242420002
                    """
                ),
                encoding="utf-8",
            )
            (peer_dir / "ams-01" / "dn42_peers.yaml").write_text(
                textwrap.dedent(
                    """\
                    peers:
                      - comment: duplicate
                        bgp:
                          asn: 4242420001
                      - comment: active
                        bgp:
                          asn: 4242420003
                    """
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                collect_unique_asns(peer_dir),
                {4242420001, 4242420003},
            )


class SshFanoutTests(unittest.TestCase):
    def test_load_ssh_targets_uses_inventory_order_and_ansible_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inventory_path = root / "inventory.yaml"
            ansible_cfg_path = root / "ansible.cfg"

            inventory_path.write_text(
                textwrap.dedent(
                    """\
                    all:
                      children:
                        nodes:
                          hosts:
                            alpha:
                              ansible_host: alpha.example
                            beta:
                        other:
                          hosts:
                            gamma:
                    """
                ),
                encoding="utf-8",
            )
            ansible_cfg_path.write_text(
                textwrap.dedent(
                    """\
                    [defaults]
                    remote_user = iris
                    """
                ),
                encoding="utf-8",
            )

            targets = load_ssh_targets(inventory_path, ansible_cfg_path)

            self.assertEqual([target.name for target in targets], ["alpha", "beta"])
            self.assertEqual(
                [target.ssh_target for target in targets],
                ["iris@alpha.example", "iris@beta"],
            )


if __name__ == "__main__":
    unittest.main()
