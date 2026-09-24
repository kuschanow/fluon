.PHONY: sync check-license lint typecheck test rust rust-coverage check build upload

sync:
	uv sync

check-license:
	cmp LICENSE fluon/LICENSE && cmp LICENSE graph/LICENSE

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports

typecheck:
	uv run mypy fluon/python graph/src
	uv run pyright

test:
	uv run pytest

rust:
	cargo fmt --all --check
	cargo clippy --workspace --all-targets -- -D warnings
	cargo test --workspace

rust-coverage:
	./scripts/rust-coverage.sh

check: check-license rust lint typecheck test rust-coverage

# make build PKG=fluon-graph
build:
	uv build --package $(PKG) --out-dir dist/$(PKG)

# make upload PKG=fluon-graph PYPI_TOKEN=...
upload:
	uv publish --token "$(PYPI_TOKEN)" dist/$(PKG)/*
