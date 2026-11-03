# Changelog

All notable changes to obwatch. Versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] - 2026-11-03

### Fixed
- Processes that a tool started with a cleaned environment were missed, because they lose the agent's session variable. Children of the agent's processes now always count. Example: a build started through `systemd-run` whose workers kept dozens of cores busy showed as 0% CPU.
- opencode commands that drop the environment (e.g. `env -i …`) run directly under opencode with no session variable. They are now matched to the agent by start time against its `sh_*.out` files.
- `obwatch build` was refused as ambiguous when another agent's name also contains "build": an exact name now wins.
- `obwatch <agent>` on an unsupported provider now says so instead of failing.

### Changed
- The Processes tab starts at the top (it's a table, not a log) and shows total CPU in cores.
- The agent list follows the order of OpenBot's sidebar (sections first, then the rest), read from `openbot-sidebar-layout-v1.json`.
- The agent list shows "N processes" instead of "N running".
- Code cleanup: one agent class per provider instead of provider checks spread through the code, shared `/proc` helpers, named constants for timings and limits, files closed after reading.
- Faster: an agent's last-activity time is cached briefly instead of being read on every frame, and unchanged opencode messages aren't parsed again.

### Added
- Tests (`tests/`, standard library only) and a GitHub Actions workflow that runs them on Python 3.8–3.13.

## [0.2.0] - 2026-11-03

### Added
- **opencode agents**, including agents on a local model (LM Studio and similar). obwatch reads their sessions from opencode's database (read-only), shows the model's reasoning as `THINK` lines, finds their processes through `OPENCODE_SESSION_ID`, and gives background commands a live tab from opencode's `sh_*.out` files.
- **Processes tab** (tab 2): every process the agent started, as a tree with CPU, memory and run time, plus where each one's output goes (file, terminal, pipe or socket read by another program, `/dev/null`).
- Programs started with **`systemd-run`** count as the agent's, found by unit name or by the output pipe they share with `systemd-run --pipe`.
- A hint when Python writes to a file without `-u`, since its output then arrives in chunks.
- "waiting for the model" in the header while a model is still generating, so a slow local model doesn't look idle.
- The agent list shows each agent's provider.
- An opencode agent in `dev/demo.py`, and Processes and opencode screenshots.

### Fixed
- Text drawn in the wrong place after switching tabs: the screen is now repainted fully on every switch.
- Tab characters in commands broke the layout.
- Claude Code's wrapper (`eval '…' < /dev/null && pwd -P`) hid some commands.
- Nothing is drawn in a line's last column any more, which avoids wrapping glitches in some terminals.
- opencode commands that run a single program were missed: the shell `exec`s it, so it runs directly under opencode and was mistaken for an MCP server.
- An opencode command that writes to its own log file is now linked to the command that started it (by start time and command text), so its tab gets the right name.
- Multi-line commands no longer make multi-line tab names.

## [0.1.0] - 2026-10-30

First release.

### Added
- Activity tab with the agent's messages, commands with their stated purpose, other tools, and output.
- One live tab per output file of the agent's foreground, background and detached processes; running tabs first, finished after.
- Agent picker, `--plain` mode, `-f` to pin any log file, `x` / `X` to close tabs.
- `dev/demo.py` and `dev/screenshot.py`.

### Fixed
- A crash when a log contained NUL bytes.
- Closed tabs coming back on the next scan.
