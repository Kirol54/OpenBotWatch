# obwatch

**See what your OpenBot agents are actually doing.** A terminal viewer for OpenBot agents that run on **Claude Code** or **opencode**, including opencode agents on a local model (LM Studio, Ollama and similar). It shows the agent's messages, its reasoning where the harness records it, every command with its stated purpose, the output, a live process tree, and tabs for everything the agent left running.

> **⚠️ This is a personal tool I made for my own testing.** It's experimental and built on OpenBot, Claude Code and opencode internals that can change at any time. Don't expect it to work properly on your setup. Feel free to try it, open an issue, or fork it.

## Why

When I use OpenBot agents for coding, the chat only shows me the agent's summary. I wanted to see what the agent is actually running: the commands and their output. I also wanted to attach to the logs of whatever it starts in its terminal, like a build, a server or a test run, while it's still going. obwatch is the quick tool I wrote for that.

![Activity tab](docs/activity.png)

## Web page

Prefer a browser? `obwatch --web` serves the same information as a page:

![Overview of all agents](docs/web-overview.png)

![An agent's activity in the browser](docs/web-agent.png)

- **Overview:** every agent at once: working or idle, what it's running now, its last few actions, processes and CPU.
- **Agent page:** Activity with expandable outputs and reasoning, filters, search and auto-follow, plus tabs for subagents, live command logs and processes.
- **Changes:** files the agent edited, grouped by file with side-by-side diffs. Markdown files come first and are rendered, with the agent's edits marked:
  - green for added, yellow for changed, each with the time of the edit; "before" on a changed block shows what it replaced, word by word, and red markers show removed text;
  - **whole file** or **changes only** (just the changed parts, under their headings, with `⋯` for what's hidden), or plain **diffs** (`m` switches);
  - which changes to mark (`H` switches): by default, for a file in a git repository, **everything not committed yet**, however it was changed: lines from the agent's edit tools show the time of the edit, and lines changed by a shell command or another program say "by a command". Outside git, the default is the edits after the file was written. Or: everything the agent wrote, the last hour, the last 10 minutes, or only the latest edit.
  - in diffs, a git file also gets one diff of everything not committed yet.
  - edits from earlier days show their date, and files that no longer exist are listed last, marked "deleted".
- **btop at the bottom of every page** (`t`, or the "▤ btop" button): a real terminal in the page running btop on the server, in full color. btop runs only while the pane is open. Size it with S/M/L/XL, by dragging its top edge, or with `+`/`-`, and change the font with `Alt`+`+`/`-` until all your CPU cores fit. Click it (or press `T`) to type into btop; `Ctrl`+`]` gives the keys back to the page.
- **Keyboard:** press `?` on the page for all shortcuts.

![Changes: rendered Markdown with the agent's edits marked, changes only](docs/web-changes.png)

```bash
obwatch --web               # prints a link with a secret token; --port to change 8765
```

It only listens on the server itself (127.0.0.1). To open it from your computer, forward the port over SSH, then open the printed link:

```bash
ssh -L 8765:localhost:8765 you@your-server
```

Or open it to your **local network only**:

```bash
obwatch --web --lan         # e.g. http://192.0.2.50:8765/?token=…
```

- `--lan` listens only on the address of the network interface your server reaches the internet through (its default route), not on VPN or Docker interfaces.
- It only answers devices whose address is inside that network.
- It refuses to start if that network isn't a private one.
- The page is plain HTTP, so anyone who can watch traffic on your network could see the token. Use `--lan` on a network you trust.
- **If the page keeps loading forever**, a firewall on the server is probably dropping the port, and nothing shows up in obwatch's connection log. With ufw: `sudo ufw allow from 192.0.2.0/24 to 192.0.2.50 port 8765 proto tcp` (use the network and address obwatch prints).

The terminal running `--web` logs every connection attempt: new clients, page loads, and refused requests with the reason. The page's live updates are summarized once a minute.

The btop pane uses [xterm.js](https://xtermjs.org/), the terminal VS Code uses. To keep obwatch a single file, the first time you open the pane obwatch downloads xterm.js 6.0.0 from the npm registry, checks it against hashes built into obwatch, and keeps it in `~/.cache/obwatch`. Your browser loads it from obwatch, not from the internet. The pane needs `btop` installed on the server. btop's own keys work in it, including the ones that kill processes, and anyone with the link can use it, so the same care applies as for the link itself.

Open the printed link once: it signs that browser in with a cookie (HttpOnly, SameSite=Strict), so other pages, new tabs and reloads work until obwatch restarts. Each start makes a new token, so after a restart open the new link. The token is required for every request, and the page refuses requests addressed to any other host, so other websites in your browser can't read it. Don't share the link: transcripts can contain secrets.

## Features

- **Activity tab:** a live feed of the agent's session:
  - `IN`: messages the agent receives (from you, teammates, or task notifications)
  - `THINK`: the model's reasoning (opencode agents; see [Limitations](#limitations) for Claude)
  - `SAY`: what the agent writes
  - `#`: why it runs a command (the description it gives the command)
  - `$`: the command itself
  - `│` / `ERR`: the command's output, or its error
  - `TOOL`: file reads, edits, searches, and other tools
- **Processes tab:** every process the agent started, as a tree with CPU, memory and run time (with the total in cores, e.g. "CPU 2900% (≈29 cores)"), plus **where each one's output goes**: a file (with a tab), the terminal, a pipe or socket read by another program, or `/dev/null`. Programs launched through `systemd-run` are included too, although they run outside the agent's process tree.
- **A tab per subagent** (Claude Code and opencode): its own commands, output and messages, named after its description. Activity shows only the main agent unless you press `s`.
- **One tab per running process**, found automatically:
  - foreground commands while they run,
  - background jobs,
  - processes the agent detached with `nohup`/`setsid`, such as servers and long builds. These are followed through the log files they write to.
- **Running first, finished after.** `●` running, `✓` finished, `+N` new lines since you last looked. Error lines are red and warnings are yellow.
- **Agent list:** pick any agent and see whether it's working, idle, and how many processes it has running. Agents appear in the same order as in OpenBot's sidebar.
- **Read-only:** it never touches your agents and opens OpenBot's database read-only.
- **One file, no dependencies:** only Python's standard library.

![Processes tab](docs/processes.png)

![Log tab of a server the agent started](docs/log-tab.png)

![An opencode agent on a local model, with its reasoning](docs/opencode.png)

![Agent list](docs/agents.png)

## Requirements

- Linux, on the machine where OpenBot runs. obwatch reads `/proc`. It works fine over SSH.
- Python 3.8 or newer.
- Agents on the **Claude** or **opencode** provider. Agents on other providers appear in the list as "not supported".
- For the web page's btop pane only: `btop`, and internet access once to download xterm.js.

## Install

```bash
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/Kirol54/OpenBotWatch/main/obwatch -o ~/.local/bin/obwatch
chmod +x ~/.local/bin/obwatch
```

If `~/.local/bin` isn't on your `PATH`, add it:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
```

Update by running the same `curl` command again. Uninstall with `rm ~/.local/bin/obwatch`.

## Usage

```bash
obwatch                       # pick an agent from a list
obwatch coder                 # open the agent whose name contains "coder"
obwatch coder -f ~/app.log    # also pin any log file as a tab
obwatch coder --plain         # just print the activity feed, no tabs (good for piping or tmux panes)
obwatch --web                 # the web page (see above)
obwatch --version
```

### Keys

| Key | Action |
|---|---|
| `←` `→` `Tab` `Shift-Tab` | previous / next tab |
| `1`–`9` | jump to a tab |
| `↑` `↓` `PgUp` `PgDn` `g` | scroll (pauses the live view) |
| `G` / `End` | follow live output again |
| `e` | show shortened outputs in full |
| `s` | show or hide subagent lines in Activity |
| `x` | close this tab (a running process keeps running) |
| `X` | close all finished tabs |
| `a` / `Esc` | back to the agent list |
| | The Processes tab starts at the top; scrolling pauses it and `G` makes it live again. |
| `q` | quit |

### Tabs

- The tab bar is ordered: **Activity**, **Processes** (`⚙`), pinned files (`≡`), **running** tabs (subagents are marked `↳`) (oldest first), then a yellow `┃` and the **finished** tabs (most recent first).
- Tab numbers follow this order, so a number can change when something finishes.
- When there are more tabs than fit, `«3` and `5»` show how many are hidden on each side.
- Tabs are named after the agent's description of the command (e.g. "Build the Docker image"), or after the program (e.g. `api-server`, `docker build`), or after the log file.
- Finished tabs stay for 15 minutes, up to 12 at a time. Finished foreground commands disappear after 10 seconds, because their output is already in Activity.
- A closed tab stays closed until a new process starts writing to the same file.

## How it works

OpenBot doesn't run the agent loop itself. It hands each agent to a **harness**: Claude Code for the Claude provider, opencode for the opencode provider. The harness sends prompts to the model, runs the tools (shell, file edits) and keeps the history. For a local LLM, LM Studio only serves the model; opencode is still the harness. obwatch reads what each harness leaves on disk:

| What | Claude Code | opencode |
|---|---|---|
| Agent names and workspaces | `~/.config/OpenBot/openbot.db`, opened read-only; order from `openbot-sidebar-layout-v1.json` | same |
| Activity feed | `~/.claude/projects/<workspace>/*.jsonl` (or `$CLAUDE_CONFIG_DIR/projects`), plus `~/.config/OpenBot/provider-accounts/*/projects/<workspace>` for each Claude account you've added to OpenBot, including subagents | `~/.local/share/opencode/opencode.db` (or `$XDG_DATA_HOME/opencode`), opened read-only: sessions whose directory is the agent's workspace, plus the ones OpenBot recorded for it, plus their subagents |
| Which processes belong to the agent | they inherit `CLAUDE_CODE_SESSION_ID` | they inherit `OPENCODE_SESSION_ID` |
| Subagents | `<session>/subagents/agent-*.jsonl` with a `.meta.json` (description, type, finished) | child sessions in `opencode.db` (`parent_id`); title, agent, busy/idle times |
| Command output files | `/tmp/claude-<uid>/<workspace>/<session>/tasks/*.output` | `~/.local/share/opencode/shell/<project>/sh_*.out` |

Both session variables survive `setsid`/`nohup`, so detached servers and builds are found too. Children of those processes count as well, even when a tool started them with a cleaned environment. An opencode command that drops the environment itself (`env -i …`) is matched by start time against the agent's `sh_*.out` files. obwatch looks them up in `/proc` and follows the files they write to: their stdout/stderr, plus open files ending in `.log`, `.out`, `.output` or `.txt`. Programs started with `systemd-run` lose the variable; obwatch finds them by their systemd unit name (`--unit=`), or by the output pipe they share with `systemd-run --pipe`.

MCP servers that the harness starts are filtered out, so only the agent's own commands show up.

## Limitations

- **No reasoning for Claude agents.** OpenBot starts Claude Code without `--thinking-display summarized`, so the reasoning in the session files is empty. The `#` line, the reason the agent gives for each command, usually covers it. If OpenBot ever enables summaries, they appear automatically as `THINK` lines. opencode stores the model's reasoning as plain text, so opencode agents show it.
- **Output sent to a pipe or socket can't be shown live.** If a tool runs a program and reads its output itself (e.g. a test runner, or `systemd-run --pipe`), only that tool sees it. The Processes tab shows where it goes. To get a live tab, have the command write to a file, e.g. `... 2>&1 | tee run.log`.
- **Python output to a file arrives in chunks.** Python buffers stdout when it isn't a terminal, so a log can stay empty for a while. Run it with `python -u` or `PYTHONUNBUFFERED=1`; the Processes tab points this out.
- **Linux only**, because it relies on `/proc`.
- A program that writes to its own log file (not stdout) only becomes a tab if the file ends in `.log`, `.out`, `.output` or `.txt`. Pin anything else with `-f`.
- Processes inside Docker containers aren't visible. The `docker build` / `docker run` command's own output is.
- Changes lists the files the agent changed with its edit tools. A file it only ever changed with shell commands (`sed`, a script) isn't listed; for listed files in git, such changes are still marked.
- The file formats come from OpenBot, Claude Code and opencode internals and may change between versions. Tested with OpenBot 0.54.0, Claude Code 2.1.312–2.1.316 and opencode 2.2.5.

## Privacy

Session files can contain anything the agent has seen, including secrets that appear in command output. obwatch only shows them in your terminal or on the web page and sends nothing anywhere. Its only outgoing connection is the one-time xterm.js download when you first open the btop pane, which sends nothing about you or your agents. Take care when you share screenshots of it.

## Development

Tests use only the standard library:

```bash
python3 -m unittest discover -s tests
```

GitHub Actions runs them on Python 3.8 to 3.13 (`.github/workflows/test.yml`).

`dev/demo.py` creates a fake OpenBot setup: a Claude Code agent and an opencode agent with sessions and running processes, an idle agent, and one on an unsupported provider. Use it to try obwatch or work on it without real agents:

```bash
python3 dev/demo.py start
HOME=/tmp/obwatch-demo/home ./obwatch coder
python3 dev/demo.py stop
```

`dev/screenshot.py` regenerates the images in `docs/` from the demo. It needs `pyte`, `Pillow` and the DejaVu Sans Mono font (`pip install pyte pillow`; set `FONT_DIR` if the font isn't in `/usr/share/fonts/truetype/dejavu`):

```bash
python3 dev/demo.py start
HOME=/tmp/obwatch-demo/home python3 dev/screenshot.py docs/
python3 dev/demo.py stop
```

## Contributing

Read [AGENTS.md](AGENTS.md) first. This repo is public, and nothing from anyone's machine, network or agent conversations may be committed. The tests include a privacy check, and `dev/pre-commit` runs it before every commit.

## License

MIT, see [LICENSE](LICENSE).
