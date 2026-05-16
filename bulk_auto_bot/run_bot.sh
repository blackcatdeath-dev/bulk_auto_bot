#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
python -m bulk_auto_bot.main "$@"
