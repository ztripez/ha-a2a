# HA rsync deploy loop

This project supports a local-to-Home Assistant deployment loop over SSH + rsync.

## 1) Configure SSH target

Use either a host alias in `~/.ssh/config` or raw `user@host`.

Example alias:

```sshconfig
Host ha-os
  HostName 192.168.1.50
  User root
  IdentityFile ~/.ssh/id_ed25519
```

## 2) Verify SSH access (read-only)

```bash
make ha-check-ssh HA_SSH_TARGET=ha-os
```

## 3) Dry-run deploy first

```bash
make ha-deploy-dry HA_SSH_TARGET=ha-os HA_DOMAIN=ha_a2a
```

## 4) Deploy

```bash
make ha-deploy HA_SSH_TARGET=ha-os HA_DOMAIN=ha_a2a
```

## 5) Restart core when needed

Use restart after changes like `manifest.json`, dependency changes, setup lifecycle changes, or when reload does not pick up behavior.

```bash
make ha-restart HA_SSH_TARGET=ha-os
```

## 6) Tail logs

```bash
make ha-logs HA_SSH_TARGET=ha-os
```

## Notes

- Source of truth stays local in git.
- Remote target path is `/config/custom_components/<domain>/`.
- Trailing slash behavior is intentional in `scripts/ha_rsync.sh`.
- Excludes are managed in `.rsync-exclude`.
