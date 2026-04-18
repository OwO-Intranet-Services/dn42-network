from __future__ import annotations

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
                removed: true
            """
        )

        normalized = normalize_peer_file_data(data)
        rendered = dump_peer_yaml(normalized)

        self.assertIn('port: 23914', rendered)
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


if __name__ == "__main__":
    unittest.main()
