# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-09

### Added

- `food-research` skill, packaged as the `swiggy-food` Claude Code plugin. The repository
  is also the plugin's marketplace.
- `swiggy-food` CLI with `locate`, `places`, `search`, `menu`, `near`, `recall`, and
  `cache` commands. The plugin puts it on the Bash `PATH` through `bin/swiggy-food`.
- 90-day response cache and a log of answered questions for `recall`.
- Saved places and the cache in `~/.local/share/swiggy-food/`, so they survive plugin
  updates.
