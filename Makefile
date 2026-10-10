# The checks CI runs on every PR.
check: lint validate smoke

lint:
	uv run ruff check .
	uv run ruff format --check .

# plugin.json pins the version users install, so it must match pyproject.toml.
validate:
	claude plugin validate --strict .
	test "$$(uv version --short)" = "$$(python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])")"

# Offline: an empty data directory, no Swiggy or geocoding calls.
smoke:
	XDG_DATA_HOME="$$(mktemp -d)" scripts/swiggy-food places
	XDG_DATA_HOME="$$(mktemp -d)" scripts/swiggy-food cache

.PHONY: check lint validate smoke
