#!/usr/bin/env bash
# =============================================================================
# Build FunctionGraph deployment packages for the VPC Network Access Analyzer
# automation (Huawei Cloud).
#
# Thin wrapper around scripts/build_packages.py (which does the real work in
# Python so it works unchanged on Linux CI and Windows Git-Bash).
#
# Produces under infra/build/: deps.zip, run_analysis.zip, check_analysis.zip,
# send_findings.zip. See build_packages.py for details.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

"$PYTHON" "$ROOT/scripts/build_packages.py"
