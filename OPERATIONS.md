# Operations

Run commands from the repo root so `ansible.cfg` and `inventory.yaml` are picked up automatically.

## Setup Playbooks

- `ansible-playbook setup.yaml`
- `ansible-playbook setup-wg.yaml`
- `ansible-playbook setup-bird.yaml`
- `ansible-playbook setup-dns.yaml`
- `ansible-playbook setup-peer-update.yaml --limit <host> -e peer_update_targets=dn42_4242`
- `ansible-playbook setup-remove-node.yaml --limit <host>`
- `ansible-playbook setup-lg-proxy.yaml`
- `ansible-playbook setup-lg-server.yaml`
- `ansible-playbook setup-websites.yaml`

## Maintenance Playbooks

- `ansible-playbook playbooks/maintenance/reboot_nodes.yaml`
- `ansible-playbook playbooks/maintenance/backup_node_configs.yaml`

Backups are written under `./backups/node_configs/<host>/`.

## Local Tools

- `python3 tools/ssh_fanout.py hostname`
- `python3 tools/count_dn42_peers.py`

`tools/ssh_fanout.py` resolves hosts from the `nodes` inventory group and uses `ansible.cfg` `remote_user` when present.

## Secrets

Use `ansible-vault encrypt_string` directly instead of a wrapper script:

```bash
printf '%s' 'secret-value' | ansible-vault encrypt_string --stdin-name example_name
```
