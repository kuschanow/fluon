#!/usr/bin/env bash
# Rust coverage from cargo test and pytest combined: PyO3 wrappers are only exercised from Python.
set -euo pipefail
cd "$(dirname "$0")/.."

# Instrumented build goes to a separate target dir so it never mixes with the regular one.
export CARGO_TARGET_DIR="$PWD/target/coverage"

# Afterwards, reinstall the regular (non-instrumented) extension into .venv.
restore() { (unset CARGO_TARGET_DIR RUSTC_WRAPPER LLVM_PROFILE_FILE; uv sync --locked --reinstall-package fluon >/dev/null 2>&1); }
trap restore EXIT

eval "$(cargo llvm-cov show-env --sh 2>/dev/null)"
cargo llvm-cov clean --workspace
cargo test --workspace
(cd fluon && uv run maturin develop --uv)
uv run pytest --no-cov -q
regions=$(cargo llvm-cov report --json --summary-only \
    | uv run python -c 'import json, sys; print(json.load(sys.stdin)["data"][0]["totals"]["regions"]["count"])')
if [ "$regions" = 0 ]; then
    echo "Rust coverage: no coverable code"
    exit 0
fi
cargo llvm-cov report --fail-under-lines 100 --fail-under-regions 100 "$@"
