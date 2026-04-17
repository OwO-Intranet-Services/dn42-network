from __future__ import annotations

import unittest
from pathlib import Path

from tools.issue_dn42_certificate import (
    build_certbot_command,
    build_hook_command,
    extract_default_email,
)


class IssueDn42CertificateTests(unittest.TestCase):
    def test_extract_default_email_from_inventory_hostvars(self) -> None:
        inventory = {
            "_meta": {
                "hostvars": {
                    "ams-01": {"network_contacts": {"Email": "0.0@owo.li"}},
                }
            }
        }
        self.assertEqual(extract_default_email(inventory), "0.0@owo.li")

    def test_build_hook_command_includes_expected_arguments(self) -> None:
        command = build_hook_command(
            action="auth",
            hook_script=Path("tools/dn42_dns01_hook.py"),
            inventory=Path("inventory.yaml"),
            playbook=Path("playbooks/dns-acme-challenge.yaml"),
            state_file=Path(".artifacts/dns_acme_challenges.json"),
            zone="iris.dn42",
            group="anycast",
            ttl=60,
            propagation_seconds=10,
            limit="ams-01,lax-01",
        )

        self.assertIn("auth", command)
        self.assertIn("--limit", command)
        self.assertIn("ams-01,lax-01", command)

    def test_build_certbot_command_uses_manual_dns_hooks(self) -> None:
        command = build_certbot_command(
            certbot_bin="certbot",
            server="https://acme.burble.dn42/v1/dn42/acme/directory",
            email="0.0@owo.li",
            cert_name="anycast.iris.dn42",
            domains=["anycast.iris.dn42"],
            config_dir=Path(".artifacts/certbot/config"),
            work_dir=Path(".artifacts/certbot/work"),
            logs_dir=Path(".artifacts/certbot/logs"),
            auth_hook="python3 tools/dn42_dns01_hook.py auth",
            cleanup_hook="python3 tools/dn42_dns01_hook.py cleanup",
        )

        self.assertEqual(command[0:4], ["certbot", "certonly", "--manual", "--preferred-challenges"])
        self.assertIn("--manual-auth-hook", command)
        self.assertIn("--manual-cleanup-hook", command)
        self.assertIn("--keep-until-expiring", command)
        self.assertEqual(command[-2:], ["-d", "anycast.iris.dn42"])


if __name__ == "__main__":
    unittest.main()
