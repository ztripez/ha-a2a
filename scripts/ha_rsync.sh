#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dry-run}"

: "${HA_SSH_TARGET:?Set HA_SSH_TARGET, for example root@ha-os or ssh-alias}"
: "${HA_DOMAIN:=ha_a2a}"

LOCAL_DIR="./custom_components/${HA_DOMAIN}/"
REMOTE_DIR="/config/custom_components/${HA_DOMAIN}/"

if [[ ! -d "${LOCAL_DIR}" ]]; then
  echo "Local integration path not found: ${LOCAL_DIR}" >&2
  exit 1
fi

RSYNC_ARGS=(
  -azv
  --delete
  --exclude-from=".rsync-exclude"
  -e ssh
  "${LOCAL_DIR}"
  "${HA_SSH_TARGET}:${REMOTE_DIR}"
)

if [[ "${MODE}" == "dry-run" ]]; then
  RSYNC_ARGS=(-n "${RSYNC_ARGS[@]}")
elif [[ "${MODE}" != "deploy" ]]; then
  echo "Unsupported mode: ${MODE}. Use 'dry-run' or 'deploy'." >&2
  exit 1
fi

echo "Sync mode: ${MODE}"
echo "SSH target: ${HA_SSH_TARGET}"
echo "Domain: ${HA_DOMAIN}"
echo "Local: ${LOCAL_DIR}"
echo "Remote: ${REMOTE_DIR}"

rsync "${RSYNC_ARGS[@]}"
