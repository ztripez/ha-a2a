HA_DOMAIN ?= ha_a2a
HA_SSH_TARGET ?=

.PHONY: ha-check-ssh ha-deploy-dry ha-deploy ha-restart ha-logs test lint

ha-check-ssh:
	@test -n "$(HA_SSH_TARGET)" || (echo "Set HA_SSH_TARGET=<user@host or ssh-alias>" && exit 1)
	@ssh "$(HA_SSH_TARGET)" "echo connected: $$(hostname)"

ha-deploy-dry:
	@test -n "$(HA_SSH_TARGET)" || (echo "Set HA_SSH_TARGET=<user@host or ssh-alias>" && exit 1)
	@HA_SSH_TARGET="$(HA_SSH_TARGET)" HA_DOMAIN="$(HA_DOMAIN)" ./scripts/ha_rsync.sh dry-run

ha-deploy:
	@test -n "$(HA_SSH_TARGET)" || (echo "Set HA_SSH_TARGET=<user@host or ssh-alias>" && exit 1)
	@HA_SSH_TARGET="$(HA_SSH_TARGET)" HA_DOMAIN="$(HA_DOMAIN)" ./scripts/ha_rsync.sh deploy

ha-restart:
	@test -n "$(HA_SSH_TARGET)" || (echo "Set HA_SSH_TARGET=<user@host or ssh-alias>" && exit 1)
	@ssh "$(HA_SSH_TARGET)" "ha core restart"

ha-logs:
	@test -n "$(HA_SSH_TARGET)" || (echo "Set HA_SSH_TARGET=<user@host or ssh-alias>" && exit 1)
	@ssh "$(HA_SSH_TARGET)" "ha core logs --follow"

test:
	pytest tests/components/ha_a2a/test_models.py tests/components/ha_a2a/test_store.py

lint:
	python -m compileall custom_components/ha_a2a tests/components/ha_a2a
