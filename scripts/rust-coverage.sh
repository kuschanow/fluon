#!/usr/bin/env bash
# Покрытие Rust-кода по cargo test и pytest вместе: PyO3-обёртки вызываются только из Python.
set -euo pipefail
cd "$(dirname "$0")/.."

# Инструментированная сборка — в отдельном target, чтобы не смешиваться с обычной.
export CARGO_TARGET_DIR="$PWD/target/coverage"

# После прогона вернуть в .venv обычное (неинструментированное) расширение.
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
    echo "Rust coverage: покрываемого кода нет"
    exit 0
fi
cargo llvm-cov report --fail-under-lines 100 --fail-under-regions 100 "$@"
