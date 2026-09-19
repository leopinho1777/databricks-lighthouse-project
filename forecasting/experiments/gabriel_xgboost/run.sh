#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
uv run --group forecasting python forecasting/experiments/gabriel_xgboost/train_xgboost.py
