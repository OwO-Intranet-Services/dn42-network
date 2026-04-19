from __future__ import annotations

import textwrap
import unittest

from tools.peer_config import dump_peer_yaml, load_peer_yaml_text, normalize_peer_file_data


class PeerConfigTests(unittest.TestCase):
    def test_normalize_peer_file_expands_defaults_and_preserves_vault_tags(self) -> None:
        data = load_peer_yaml_text(
            """\
            peers:
              - comment: alpha
                wg:
                  port: 23914
                  endpoint: alpha.example:21023
                  wg_pubkey: "AAA="
                  psk: !vault |
                    encrypted
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
                  peering_strategy: full_table
              - comment: beta
                wg:
                  endpoint: beta.example:21023
                  wg_pubkey: BBB
                  peer6: fe80::2
                bgp:
                  asn: 4242420002
                  ipv4: false
                  ipv6: true
                  extended_next_hop: false
                  mp_bgp: false
                  peering_strategy: downstream
                removed: true
            """
        )

        normalized = normalize_peer_file_data(data)
        rendered = dump_peer_yaml(normalized)

        self.assertIn('port: 23914', rendered)
        self.assertIn("comment: 'alpha'", rendered)
        self.assertIn("endpoint: 'alpha.example:21023'", rendered)
        self.assertIn("wg_pubkey: 'AAA='", rendered)
        self.assertIn('peer4: null', rendered)
        self.assertIn('own6: null', rendered)
        self.assertIn('keepalive: null', rendered)
        self.assertIn('mtu: null', rendered)
        self.assertIn('ipv4: true', rendered)
        self.assertIn('ipv6: true', rendered)
        self.assertIn('extended_next_hop: true', rendered)
        self.assertIn('mp_bgp: true', rendered)
        self.assertIn("psk: !vault |", rendered)
        self.assertIn('port: 20002', rendered)
        self.assertIn("removed: true", rendered)
        self.assertIn("ipv4: false", rendered)
        self.assertIn("extended_next_hop: false", rendered)
        self.assertIn("mp_bgp: false", rendered)
        self.assertIn("peering_strategy: 'downstream'", rendered)
        self.assertNotIn("peering_strategy: 'full_table'", rendered)
        self.assertNotIn("'peers':", rendered)
        self.assertNotIn("'comment':", rendered)

    def test_dump_quotes_all_string_values_and_preserves_empty_strings(self) -> None:
        rendered = dump_peer_yaml(
            {
                "peers": [
                    {
                        "comment": "@Auride",
                        "wg": {
                            "port": 23310,
                            "endpoint": "",
                            "wg_pubkey": "aC9pjzMWZhbA/sLPljUFGU1K28MSopHbKNj5yyv4uzg=",
                            "psk": "",
                            "peer4": "",
                            "peer6": "fe80::1023:3310",
                            "own6": "",
                            "keepalive": "",
                            "mtu": 1420,
                        },
                        "bgp": {
                            "asn": 4242423310,
                            "ipv4": True,
                            "ipv6": True,
                            "extended_next_hop": True,
                            "mp_bgp": True,
                        },
                        "autopeer": {
                            "managed": True,
                            "effective_mnt": "YUZU-MNT",
                            "auth_provider": "registry_pgp",
                        },
                    }
                ]
            }
        )

        self.assertIn("- comment: '@Auride'", rendered)
        self.assertIn("endpoint: ''", rendered)
        self.assertIn("wg_pubkey: 'aC9pjzMWZhbA/sLPljUFGU1K28MSopHbKNj5yyv4uzg='", rendered)
        self.assertIn("peer4: ''", rendered)
        self.assertIn("effective_mnt: 'YUZU-MNT'", rendered)
        self.assertIn("auth_provider: 'registry_pgp'", rendered)
        self.assertNotIn("'autopeer':", rendered)

    def test_normalize_peer_file_rejects_invalid_endpoint(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: 1:2
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: fe80::298
                    bgp:
                      asn: 4242420298
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"invalid wg\.endpoint"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_unspecified_peer6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: "::"
                    bgp:
                      asn: 4242420298
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"invalid wg\.peer6"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_allows_ipv4_only_session_without_peer6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 172.20.193.67
                      peer6: null
                    bgp:
                      asn: 4242420298
                      ipv4: true
                      ipv6: false
                      extended_next_hop: false
                      mp_bgp: false
                """
            )
        )

        normalized = normalize_peer_file_data(data)
        peer = normalized["peers"][0]
        self.assertEqual(peer["wg"]["peer4"], "172.20.193.67")
        self.assertIsNone(peer["wg"]["peer6"])
        self.assertFalse(peer["bgp"]["ipv6"])
        self.assertFalse(peer["bgp"]["mp_bgp"])

    def test_normalize_peer_file_allows_ipv4_routes_over_ipv6_mp_bgp(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: fd55:dead:beef::3
                    bgp:
                      asn: 4242420298
                      ipv4: true
                      ipv6: false
                      mp_bgp: true
                """
            )
        )

        normalized = normalize_peer_file_data(data)
        self.assertEqual(normalized["peers"][0]["wg"]["peer6"], "fd55:dead:beef::3")

    def test_normalize_peer_file_rejects_unspecified_peer4(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 0.0.0.0
                      peer6: fe80::298
                    bgp:
                      asn: 4242420298
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"invalid wg\.peer4"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_mp_bgp_without_peer6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 172.20.193.67
                      peer6: null
                    bgp:
                      asn: 4242420298
                      ipv4: true
                      ipv6: false
                      mp_bgp: true
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"requires wg\.peer6 when bgp\.mp_bgp is enabled"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_ipv6_without_peer6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 172.20.193.67
                      peer6: null
                    bgp:
                      asn: 4242420298
                      ipv4: false
                      ipv6: true
                      extended_next_hop: false
                      mp_bgp: false
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"requires wg\.peer6 for bgp\.ipv6"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_extended_next_hop_without_mp_bgp(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 172.20.193.67
                      peer6: null
                    bgp:
                      asn: 4242420298
                      ipv4: true
                      ipv6: false
                      extended_next_hop: true
                      mp_bgp: false
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"cannot enable bgp\.extended_next_hop without bgp\.mp_bgp"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_non_link_local_own6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: fe80::298
                      own6: fd00::1
                    bgp:
                      asn: 4242420298
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"invalid wg\.own6"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_own6_without_link_local_peer6(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: 172.20.193.67
                      peer6: fd55:dead:beef::3
                      own6: fe80::1
                    bgp:
                      asn: 4242420298
                      ipv4: true
                      ipv6: false
                      mp_bgp: true
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"can only set wg\.own6 when wg\.peer6 is link-local"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_disabled_bgp_families(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: fe80::298
                    bgp:
                      asn: 4242420298
                      ipv4: false
                      ipv6: false
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"at least one address family"):
            normalize_peer_file_data(data)

    def test_normalize_peer_file_rejects_unknown_peering_strategy(self) -> None:
        data = load_peer_yaml_text(
            textwrap.dedent(
                """\
                peers:
                  - wg:
                      endpoint: peer.example.net:21023
                      wg_pubkey: "GSYaBd8a2MkVBlp8iUOOKOPB4x4EVQWMsdJbTeSejEw="
                      peer4: null
                      peer6: fe80::298
                    bgp:
                      asn: 4242420298
                      peering_strategy: "random"
                """
            )
        )

        with self.assertRaisesRegex(ValueError, r"invalid bgp\.peering_strategy"):
            normalize_peer_file_data(data)


if __name__ == "__main__":
    unittest.main()
