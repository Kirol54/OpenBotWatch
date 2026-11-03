# Changelog

All notable changes to obwatch. Versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-03

The web page release: everything obwatch shows in the terminal, in a browser, plus a review view of what the agent changed and btop at the bottom of the page.

### Added

**Web page** (`obwatch --web`)
- **Overview** of every agent, with **working agents in their own section** at the top (green edge, pulsing "● working") and idle ones below: what each is running now, its last few actions, processes and CPU.
- **Agent page:** Activity with expandable outputs and reasoning, filters (commands, output, reasoning, messages, tools, errors, subagents), search, and auto-follow; tabs for subagents, live command logs and processes.
- **Keyboard controls** for everything; `?` lists them. Open agents with `1`–`9` or `j`/`k` and `Enter`. On an agent: `[` `]` for tabs, `a`/`c`/`p`, `j`/`k`/`Space` to scroll, `g`/`G`, `f` follow, `/` search, `s` subagents, `e` expand all. `\` and `<` `>` for the tab list.

**Changes: a review of what the agent changed**
- Every file the agent edited or wrote, **grouped by file**, Markdown first and expanded, other files collapsed until you open them, with +/− counts.
- **Side-by-side diffs** with line numbers. New files and pure removals use the full width. Failed edits (for example, text not found) are marked "failed, not applied" and left out of the counts.
- **Rendered Markdown** with the changes marked: green for added, yellow for changed, each with the time of the edit. "before" on a changed block shows what it replaced, word by word, and red markers show removed text.
- **Whole file, changes only, or diffs** (`m` switches). "Changes only" shows just the changed parts under their headings, with `⋯` for hidden parts (click to show).
- **Changes made any way are marked**, for files in a git repository. By default the view marks everything not committed yet, so changes made with shell commands or scripts show up too, marked "by a command". Edits made with edit tools keep their time. Diffs add one diff of everything not committed yet.
- **Which changes to mark** (`H` switches): not committed yet (git) or the edits after the file was written (outside git), everything the agent wrote, the last hour, the last 10 minutes, or the latest edit. A file written in one go and not edited since says so.
- Edits that were changed again later, for example by another agent, are matched by their lines.
- Files that no longer exist are listed last, marked "deleted". Edits from earlier days show their date.
- **The page stays still while you read:** when files change while you're scrolled down, a notice says so instead of redrawing; click it or press `r` to show the changes.

**btop at the bottom of every page**
- `t` or "▤ btop" opens a real terminal running btop on the server, in full color and properly aligned. It uses xterm.js (the terminal VS Code uses), downloaded once from the npm registry, checked against hashes built into obwatch and cached in `~/.cache/obwatch`. The browser loads it from obwatch, never from the internet.
- btop runs only while the pane is open, and stops when it closes, when the page goes away, or when obwatch exits.
- Resize the pane with S/M/L/XL, by dragging its top edge, or with `+`/`-`. Change the font with `Alt`+`+`/`-` so all CPU cores fit. The pane says when it's too small for btop.
- Click it or press `T` to type into btop; `Ctrl`+`]` gives the keys back to the page.

**Access and security**
- By default it listens on 127.0.0.1 only; reach it from your computer with `ssh -L`.
- `--lan` opens it to your **local network only**: it listens only on the default route's interface (not VPN or Docker), answers only clients inside that network, and refuses to start on a network that isn't private.
- The printed link (`/?token=…`) signs the browser in with a cookie (HttpOnly, SameSite=Strict), so every page, tab and reload works until obwatch restarts. Without it, the page says which link to open.
- Every request needs the token; requests addressed to any other host are refused, and the btop connection is refused from other origins.
- The terminal running `--web` **logs every connection attempt**: new clients, page loads, btop opened and closed, and refused requests with the reason (wrong token, wrong host, outside the network, https instead of http). Live updates are summarized once a minute. When nothing arrives, it suggests the firewall rule to check.

**Terminal view**
- **A tab per subagent**, for both Claude Code and opencode agents: `↳●` while it runs, `↳✓` when done, named after the subagent's description (opencode: its session title), showing its own commands and output.
- `s` toggles subagent lines in Activity. They're off by default, so Activity shows the main agent; each subagent has its own tab.

**For contributors**
- `AGENTS.md` (and `CLAUDE.md`, which points to it): rules for agents and people working on the repo, above all that nothing from the maintainer's machine, network or conversations may be committed.
- A privacy test (`test_no_personal_data`) that fails on real-looking IP addresses (examples must use the RFC 5737 documentation ranges), home directories, emails, UUIDs and session IDs, plus a private word list kept outside the repo (`~/.config/obwatch/private-words`). `dev/pre-commit` runs it as a git hook.
- Tests for the web server, the edit history, the git baseline and the terminal connection; `dev/demo.py` now includes Markdown edits.

### Fixed
- **Switching Claude accounts no longer freezes an agent's view.** OpenBot keeps each Claude account's sessions in its own folder (`~/.config/OpenBot/provider-accounts/<account>/projects`). obwatch only read `~/.claude/projects`, so after a switch it stopped seeing new activity. It now reads every account's folder, and picks up newly added accounts while it runs.
- A background Claude subagent no longer also shows up as a plain "task …" tab with its raw transcript.
- Activity is in time order. Before, lines from the main session and its subagents were grouped by file instead of interleaved by time.
- The opencode database connection failed when used from another thread.

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
