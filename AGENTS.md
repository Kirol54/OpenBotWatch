# Working on this repo

Rules for AI agents and people changing obwatch. Read all of them before you edit or commit anything.

## 1. Privacy comes first

This repo is public. **Nothing from the maintainer's machine, network, accounts or OpenBot conversations may ever be committed:** not in code, comments, tests, docs, the changelog, commit messages or screenshots.

Never commit:
- **Network details:** real IP addresses, subnets, hostnames, ports or interface names of any network: home LAN, VPN (NetBird, WireGuard, Tailscale), Docker or cloud. For examples, use the documentation ranges only: `192.0.2.x`, `198.51.100.x`, `203.0.113.x` (RFC 5737), plus `127.0.0.1`.
- **The machine:** usernames, home directories (`/home/<user>`), hostnames, hardware details, installed tools and their paths. Write `~/…` or use the demo's `/home/demo/…`.
- **People and accounts:** names, emails, account IDs. The only exception is the GitHub handle `Kirol54` in `LICENSE` and the repo URLs.
- **Agents and conversations:** agent names and IDs, session or thread IDs, anything an agent said, ran or wrote, project names, file paths or command output from real agents, model names or model-server addresses from a real setup.
- **Secrets:** tokens, keys, passwords, cookies, even ones that look expired.
- **Screenshots or recordings** of anything except `dev/demo.py`.

How to stay within the rules:
- Take every example from `dev/demo.py` (made-up agents "Coder", "Researcher", "Local model"). Extend the demo if you need a new example; don't copy real data.
- Describe bugs generically in the changelog and commit messages ("a build whose workers used dozens of cores"), never the real run that showed the bug.
- If you're unsure whether something is personal, leave it out and ask the maintainer.

The test `test_no_personal_data` (in `tests/`) fails if it finds real-looking IP addresses, home paths, emails, UUIDs or session IDs. It also checks a **private word list** that lives only on the maintainer's machine, never in this repo: `~/.config/obwatch/private-words`, one word or phrase per line. Add to that file, not to the repo, when something new must never appear.

Before every commit:
```bash
python3 -m unittest discover -s tests
```
On the maintainer's machine, `dev/pre-commit` is installed as the git pre-commit hook and runs the privacy check automatically. Install it elsewhere with `ln -s ../../dev/pre-commit .git/hooks/pre-commit`.

## 2. Code

- `obwatch` stays **one file** that needs only Python's standard library (Python 3.8+), so it can be installed with one `curl`.
- The web page is plain HTML, CSS and JavaScript inside `obwatch`: no frameworks, no CDN or other network loads. Build page content with `textContent` and DOM nodes, never by inserting HTML from agent data.
- Everything obwatch reads is read-only: never write to OpenBot's, Claude Code's or opencode's files.
- The web server listens on 127.0.0.1 unless `--lan` is given, and every API request needs the token.

## 3. Docs and commits

- Update `CHANGELOG.md` with every change, and the README when behaviour changes.
- Run the tests, which include a syntax check of the page's JavaScript (it needs `node`).
- Regenerate screenshots only from the demo (`dev/demo.py`, `dev/screenshot.py`).
- Commit messages: a short summary line and a few bullet points. No `Co-Authored-By` or other AI attribution lines.
