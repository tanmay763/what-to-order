# swiggy-food

This repository is the `swiggy-food` Claude Code plugin and its own marketplace. The
README covers the layout, the CLI, and where data lives.

## Checks

- Run the CLI from the checkout with `uv run swiggy-food <command>`.
- Load the plugin in place with `claude --plugin-dir .`.
- Run `claude plugin validate .` after you change anything under `.claude-plugin/`,
  `skills/`, or `bin/`. It must report `Validation passed` with no warnings.

This file is in `.claude/` and not at the repository root. The validator warns about a
`CLAUDE.md` at the plugin root.

## Versions

The plugin uses semantic versioning. Installed users stay on the version in
`.claude-plugin/plugin.json` until it changes, so a change they should receive needs a
version bump.

When a change touches what the plugin ships (`src/`, `skills/`, `bin/`,
`.claude-plugin/`, `pyproject.toml`), do these steps:

1. Propose a bump to the user and give the reason. Use **patch** for a fix that does not
   change behavior the skill or CLI documents. Use **minor** for a new command, flag, or
   skill capability. Use **major** for a removed or renamed command or flag, or a change
   to the data directory layout. While the version is `0.y.z`, a breaking change bumps
   the minor version.
2. Wait for the user to confirm the bump. Never change a version without confirmation.
3. Run `uv version --bump <patch|minor|major>`. This updates `pyproject.toml` and
   `uv.lock`.
4. Set `"version"` in `.claude-plugin/plugin.json` to the same value.
5. In `CHANGELOG.md`, move the `[Unreleased]` entries under a new
   `## [<version>] - <YYYY-MM-DD>` heading.
6. Make sure the versions match. This command must print the same value twice:
   `uv version --short; python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`

A change that ships nothing, such as a README edit, gets no bump. Add every change that
users notice to `[Unreleased]` in `CHANGELOG.md` when you make it.

## Privacy

The repository is public. Never commit saved places, cache contents, real addresses,
home coordinates, or personal email addresses. Examples use public localities such as
Koramangala or Indiranagar, or `<your address>`.
