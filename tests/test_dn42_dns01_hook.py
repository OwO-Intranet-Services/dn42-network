from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.dn42_dns01_hook import (
    build_ansible_records,
    build_record_fqdn,
    load_state,
    relative_record_name,
    resolve_group_hosts,
    save_state,
    with_auth_value,
    without_auth_value,
)


class Dn42Dns01HookTests(unittest.TestCase):
    def test_build_record_fqdn_for_subdomain_and_wildcard(self) -> None:
        self.assertEqual(
            build_record_fqdn("anycast.iris.dn42", "iris.dn42"),
            "_acme-challenge.anycast.iris.dn42",
        )
        self.assertEqual(
            build_record_fqdn("*.iris.dn42", "iris.dn42"),
            "_acme-challenge.iris.dn42",
        )

    def test_relative_record_name_for_zone_apex_and_subdomain(self) -> None:
        self.assertEqual(
            relative_record_name("_acme-challenge.iris.dn42", "iris.dn42"),
            "_acme-challenge",
        )
        self.assertEqual(
            relative_record_name("_acme-challenge.network.iris.dn42", "iris.dn42"),
            "_acme-challenge.network",
        )

    def test_state_updates_and_ansible_record_rendering(self) -> None:
        state = {}
        state = with_auth_value(state, "_acme-challenge.anycast.iris.dn42", "token-b")
        state = with_auth_value(state, "_acme-challenge.anycast.iris.dn42", "token-a")
        state = with_auth_value(state, "_acme-challenge.network.iris.dn42", "token-c")

        self.assertEqual(
            build_ansible_records(state, "iris.dn42", 60),
            [
                {
                    "name": "_acme-challenge.anycast",
                    "ttl": 60,
                    "values": ["token-a", "token-b"],
                },
                {
                    "name": "_acme-challenge.network",
                    "ttl": 60,
                    "values": ["token-c"],
                },
            ],
        )

        state = without_auth_value(state, "_acme-challenge.anycast.iris.dn42", "token-a")
        self.assertEqual(
            state["_acme-challenge.anycast.iris.dn42"],
            ["token-b"],
        )

        state = without_auth_value(state, "_acme-challenge.anycast.iris.dn42", "token-b")
        self.assertNotIn("_acme-challenge.anycast.iris.dn42", state)

    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dns_acme_challenges.json"
            original = {
                "_acme-challenge.anycast.iris.dn42": ["token-b", "token-a"],
            }
            save_state(path, original)
            self.assertEqual(
                load_state(path),
                {"_acme-challenge.anycast.iris.dn42": ["token-a", "token-b"]},
            )

    def test_resolve_group_hosts_requires_existing_non_empty_group(self) -> None:
        inventory = {"anycast": {"hosts": ["ams-01", "lax-01"]}}
        self.assertEqual(resolve_group_hosts(inventory, "anycast"), ["ams-01", "lax-01"])

        with self.assertRaises(ValueError):
            resolve_group_hosts({}, "anycast")


if __name__ == "__main__":
    unittest.main()
