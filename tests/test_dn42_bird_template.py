from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = "roles/config-bird/templates/dn42_peer.conf.j2"
FILTER_PLUGIN_PATH = REPO_ROOT / "roles/config-bird/filter_plugins/dn42_bird.py"


def load_filter_module():
    spec = importlib.util.spec_from_file_location("dn42_bird_filter", FILTER_PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load filter plugin from {FILTER_PLUGIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILTER_MODULE = load_filter_module()
ANSIBLE_FILTER_ERROR = getattr(FILTER_MODULE, "AnsibleFilterError", ValueError)


def render_peer_template(peer: dict[str, object]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(REPO_ROOT)),
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters.update(FILTER_MODULE.FilterModule().filters())
    template = env.get_template(TEMPLATE_PATH)
    return template.render(
        item=peer,
        dn42_prefix="dn42_",
        dn42_peer_latency_map={},
        dn42_latency_community_default="64511",
        dn42_bandwidth_community_default=30,
    )


class Dn42BirdTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_peer = {
            "wg": {
                "peer4": "172.20.193.67",
                "peer6": "fd55:dead:beef::3",
            },
            "bgp": {
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": True,
                "extended_next_hop": True,
                "mp_bgp": True,
            },
        }

    def render(self, **overrides: object) -> str:
        peer = copy.deepcopy(self.base_peer)
        for section, values in overrides.items():
            if isinstance(values, dict):
                peer[section].update(values)
            else:
                peer[section] = values
        return render_peer_template(peer)

    def test_legacy_mp_bgp_defaults_to_ipv6_transport(self) -> None:
        rendered = self.render()

        self.assertIn("protocol bgp dn42_0298 from dnpeers {", rendered)
        self.assertNotIn("protocol bgp dn42_0298_v4", rendered)
        self.assertNotIn("protocol bgp dn42_0298_v6", rendered)
        self.assertIn("neighbor fd55:dead:beef::3 as 4242420298;", rendered)
        self.assertIn("ipv4 {", rendered)
        self.assertIn("ipv6 {", rendered)

    def test_split_sessions_render_per_family_protocols(self) -> None:
        rendered = self.render(
            bgp={
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": True,
                "extended_next_hop": False,
                "mp_bgp": False,
            }
        )

        self.assertIn("protocol bgp dn42_0298_v4 from dnpeers {", rendered)
        self.assertIn("neighbor 172.20.193.67 as 4242420298;", rendered)
        self.assertIn("protocol bgp dn42_0298_v6 from dnpeers {", rendered)
        self.assertIn("neighbor fd55:dead:beef::3 as 4242420298;", rendered)
        self.assertNotIn("extended next hop", rendered)

    def test_mp_bgp_over_ipv6_transport_renders_ipv4_extnh(self) -> None:
        rendered = self.render(
            wg={"peer4": None, "peer6": "fe80::298"},
            bgp={
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": True,
                "extended_next_hop": True,
                "mp_bgp": True,
                "mp_bgp_transport": "ipv6",
            },
        )

        self.assertIn("protocol bgp dn42_0298 from dnpeers {", rendered)
        self.assertIn("neighbor fe80::298 as 4242420298;", rendered)
        self.assertIn("extended next hop on;", rendered)
        self.assertNotIn("protocol bgp dn42_0298_v4", rendered)

    def test_mp_bgp_over_ipv4_transport_does_not_render_ipv6_extnh(self) -> None:
        rendered = self.render(
            wg={"peer4": "172.20.193.67", "peer6": "fd55:dead:beef::3"},
            bgp={
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": True,
                "extended_next_hop": False,
                "mp_bgp": True,
                "mp_bgp_transport": "ipv4",
            },
        )

        self.assertIn("protocol bgp dn42_0298 from dnpeers {", rendered)
        self.assertIn("neighbor 172.20.193.67 as 4242420298;", rendered)
        self.assertIn("ipv6 {", rendered)
        self.assertNotIn("extended next hop on;", rendered)
        self.assertNotIn("extended next hop off;", rendered)
        self.assertNotIn("protocol bgp dn42_0298_v6", rendered)

    def test_mp_bgp_over_ipv4_transport_allows_ipv6_without_peer6(self) -> None:
        rendered = self.render(
            wg={"peer4": "172.20.193.67", "peer6": None},
            bgp={
                "asn": 4242420298,
                "ipv4": False,
                "ipv6": True,
                "extended_next_hop": False,
                "mp_bgp": True,
                "mp_bgp_transport": "ipv4",
            },
        )

        self.assertIn("protocol bgp dn42_0298 from dnpeers {", rendered)
        self.assertIn("neighbor 172.20.193.67 as 4242420298;", rendered)
        self.assertIn("ipv6 {", rendered)
        self.assertNotIn("extended next hop", rendered)

    def test_mp_bgp_without_explicit_transport_falls_back_to_ipv4_when_only_peer4_exists(self) -> None:
        rendered = self.render(
            wg={"peer4": "172.20.193.67", "peer6": None},
            bgp={
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": False,
                "extended_next_hop": False,
                "mp_bgp": True,
            },
        )

        self.assertIn("protocol bgp dn42_0298 from dnpeers {", rendered)
        self.assertIn("neighbor 172.20.193.67 as 4242420298;", rendered)
        self.assertNotIn("neighbor fd55:dead:beef::3", rendered)

    def test_dual_addressed_mp_bgp_can_keep_native_cross_family_next_hops(self) -> None:
        rendered = self.render(
            bgp={
                "asn": 4242420298,
                "ipv4": True,
                "ipv6": True,
                "extended_next_hop": False,
                "mp_bgp": True,
                "mp_bgp_transport": "ipv4",
            }
        )

        self.assertIn("neighbor 172.20.193.67 as 4242420298;", rendered)
        self.assertIn("ipv6 {", rendered)
        self.assertNotIn("extended next hop", rendered)

    def test_ipv4_over_ipv6_transport_without_peer4_or_extnh_fails(self) -> None:
        with self.assertRaisesRegex(
            ANSIBLE_FILTER_ERROR,
            r"requires bgp\.extended_next_hop for ipv4 routes over ipv6 transport",
        ):
            self.render(
                wg={"peer4": None, "peer6": "fd55:dead:beef::3"},
                bgp={
                    "asn": 4242420298,
                    "ipv4": True,
                    "ipv6": False,
                    "extended_next_hop": False,
                    "mp_bgp": True,
                    "mp_bgp_transport": "ipv6",
                },
            )

    def test_extended_next_hop_over_ipv4_transport_fails(self) -> None:
        with self.assertRaisesRegex(
            ANSIBLE_FILTER_ERROR,
            r"can only enable bgp\.extended_next_hop with bgp\.mp_bgp_transport=ipv6",
        ):
            self.render(
                bgp={
                    "asn": 4242420298,
                    "ipv4": True,
                    "ipv6": True,
                    "extended_next_hop": True,
                    "mp_bgp": True,
                    "mp_bgp_transport": "ipv4",
                }
            )


if __name__ == "__main__":
    unittest.main()
