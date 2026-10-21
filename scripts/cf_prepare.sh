#!/usr/bin/env bash
# Prepare the repo for `cf push`: the Python buildpack needs requirements.txt, and the API serves
# the prebuilt console from ui/dist.
set -euo pipefail
cd "$(dirname "$0")/.."
uv export --no-hashes --no-dev --no-emit-project --extra aicore --format requirements-txt > requirements.txt
echo "." >> requirements.txt   # install the synapsesupply package itself
(cd ui && npm ci --no-audit --no-fund && npm run build)
echo "Ready: requirements.txt ($(grep -vc '^#' requirements.txt) lines) and ui/dist. Now: cf push --var team=<team>"
