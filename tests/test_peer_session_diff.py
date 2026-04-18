from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.peer_session_diff import build_report


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class PeerSessionDiffTests(unittest.TestCase):
    def create_repo(self) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)

        git(root, "init")
        git(root, "config", "user.name", "CI Test")
        git(root, "config", "user.email", "ci@example.com")

        (root / "inventory.yaml").write_text(
            textwrap.dedent(
                """\
                all:
                  children:
                    nodes:
                      hosts:
                        lax-01:
                          ansible_host: lax-01.node.svc.moe
                        bom-01:
                          ansible_host: bom-01.node.svc.moe
                    dn42:
                      hosts:
                        lax-01:
                """
            ),
            encoding="utf-8",
        )
        return root

    def write_peer_file(self, root: Path, host: str, content: str) -> None:
        path = root / "host_vars" / host / "dn42_peers.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def commit_all(self, root: Path, message: str) -> str:
        git(root, "add", ".")
        git(root, "commit", "-m", message)
        return git(root, "rev-parse", "HEAD")

    def test_detects_added_updated_and_removed_peers(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                  peer4: null
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
              - comment: beta
                wg:
                  endpoint: beta.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420002
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                removed: true
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
              - comment: beta
                wg:
                  endpoint: beta-new.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420002
                  ipv4: true
                  ipv6: true
              - comment: gamma
                wg:
                  endpoint: gamma.example:21023
                  wg_pubkey: CCC
                  peer6: fe80::3
                bgp:
                  asn: 4242420003
                  ipv4: true
                  ipv6: true
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertEqual(report["deploy_hosts"], ["lax-01"])
        self.assertEqual(
            report["deploy_matrix"],
            [{"host": "lax-01", "targets": ["dn42_0001", "dn42_0002", "dn42_0003"]}],
        )
        self.assertEqual(
            [entry["asn"] for entry in report["host_changes"]["lax-01"]["added"]],
            [4242420003],
        )
        self.assertEqual(
            [entry["asn"] for entry in report["host_changes"]["lax-01"]["updated"]],
            [4242420002],
        )
        self.assertEqual(
            [entry["asn"] for entry in report["host_changes"]["lax-01"]["removed"]],
            [4242420001],
        )
        self.assertEqual(report["errors"], [])

    def test_hard_deleted_peer_entry_is_rejected(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers: []
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(len(report["hard_delete_errors"]), 1)
        self.assertIn("removed: true", report["hard_delete_errors"][0])

    def test_inactive_host_changes_are_ignored(self) -> None:
        root = self.create_repo()
        self.write_peer_file(root, "lax-01", "peers: []\n")
        self.write_peer_file(
            root,
            "bom-01",
            """\
            peers:
              - comment: remote
                wg:
                  endpoint: bom.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420999
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "bom-01",
            """\
            peers:
              - comment: remote-updated
                wg:
                  endpoint: bom-new.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420999
                  ipv4: true
                  ipv6: true
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["ignored_paths"], ["host_vars/bom-01/dn42_peers.yaml"])

    def test_null_and_order_only_changes_do_not_trigger_deploy(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                  own6: null
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
              - comment: beta
                wg:
                  endpoint: beta.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420002
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: beta
                wg:
                  endpoint: beta.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420002
                  ipv4: true
                  ipv6: true
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(report["errors"], [])

    def test_normalization_only_changes_do_not_trigger_deploy(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  port: 23914
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  psk: null
                  peer4: null
                  peer6: fe80::1
                  own6: null
                  keepalive: null
                bgp:
                  asn: 4242423914
                  ipv4: true
                  ipv6: true
                  extended_next_hop: true
                  mp_bgp: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242423914
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(report["host_changes"], {})
        self.assertEqual(report["errors"], [])

    def test_strategy_only_change_triggers_deploy(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
                  peering_strategy: downstream
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertTrue(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], ["lax-01"])
        self.assertEqual(
            report["deploy_matrix"],
            [{"host": "lax-01", "targets": ["dn42_0001"]}],
        )
        self.assertEqual(
            [entry["asn"] for entry in report["host_changes"]["lax-01"]["updated"]],
            [4242420001],
        )
        self.assertEqual(report["errors"], [])

    def test_explicit_full_table_normalizes_away_in_compare(self) -> None:
        root = self.create_repo()
        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
            """,
        )
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
                  peering_strategy: full_table
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(report["host_changes"], {})
        self.assertEqual(report["errors"], [])

    def test_duplicate_asn_is_reported_as_error(self) -> None:
        root = self.create_repo()
        self.write_peer_file(root, "lax-01", "peers: []\n")
        base_ref = self.commit_all(root, "base")

        self.write_peer_file(
            root,
            "lax-01",
            """\
            peers:
              - comment: alpha
                wg:
                  endpoint: alpha.example:21023
                  wg_pubkey: AAA
                  peer6: fe80::1
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
              - comment: alpha-dup
                wg:
                  endpoint: alpha2.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420001
                  ipv4: true
                  ipv6: true
            """,
        )
        head_ref = self.commit_all(root, "head")

        report = build_report(root, root / "inventory.yaml", base_ref, head_ref)

        self.assertFalse(report["has_changes"])
        self.assertEqual(report["deploy_hosts"], [])
        self.assertEqual(report["deploy_matrix"], [])
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn("duplicate ASN 4242420001", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
