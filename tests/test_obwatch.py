"""Tests for obwatch. Standard library only: python3 -m unittest discover -s tests"""
import importlib.machinery, importlib.util, json, os, re, sqlite3, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("obwatch", os.path.join(HERE, "..", "obwatch"))
ow = importlib.util.module_from_spec(importlib.util.spec_from_loader("obwatch", _loader))
_loader.exec_module(ow)


def proc(pid, ppid, cmd, sid=None, out=None, unit="", start=1000.0):
    return dict(pid=pid, ppid=ppid, cmd=cmd, sid=sid, out=out, unit=unit, start=start, cpu=0, rss=0, unbuffered=False)


class Helpers(unittest.TestCase):
    def test_ago(self):
        self.assertEqual(ow.ago(5), "5s")
        self.assertEqual(ow.ago(125), "2m")
        self.assertEqual(ow.ago(3 * 3600 + 5 * 60), "3h05m")
        self.assertEqual(ow.ago(-3), "0s")

    def test_fmt_mem(self):
        self.assertEqual(ow.fmt_mem(512), "512B")
        self.assertEqual(ow.fmt_mem(3 * 1024 * 1024), "3.0M")

    def test_short_cmd(self):
        self.assertEqual(ow.short_cmd("ls -la"), "ls -la")
        self.assertEqual(ow.short_cmd('python3 -c "import time\nprint(1)"'), 'python3 -c "import time…')
        self.assertTrue(ow.short_cmd("x" * 100).endswith("…"))

    def test_unquote(self):
        self.assertEqual(ow.unquote('python3 -c "print(\'a\')"'), ow.unquote("python3 -c print('a')"))

    def test_task_id(self):
        self.assertEqual(ow.task_id("/tmp/claude-1/x/s/tasks/b2rpnuaos.output"), "b2rpnuaos")
        self.assertEqual(ow.task_id("/h/.local/share/opencode/shell/p/sh_abc.out"), "sh_abc")
        self.assertIsNone(ow.task_id("/var/log/app.log"))

    def test_unit_arg(self):
        self.assertEqual(ow.unit_arg(["systemd-run", "--user", "--unit=build-1", "make"]), "build-1")
        self.assertEqual(ow.unit_arg(["systemd-run", "-u", "x", "make"]), "x")
        self.assertIsNone(ow.unit_arg(["systemd-run", "--pipe", "make"]))

    def test_pretty_cmd_unwraps_claude_wrapper(self):
        wrapped = ["/usr/bin/zsh", "-c", "source snap.sh && eval 'npm test -- --watch=false' < /dev/null && pwd -P >| /tmp/x"]
        self.assertEqual(ow.pretty_cmd(wrapped), "zsh -c npm test -- --watch=false")
        self.assertEqual(ow.pretty_cmd(["python3", "-c", "a\tb\nc"]), "python3 -c a b ⏎ c")

    def test_clip_and_wrap(self):
        text = "\n".join(str(i) for i in range(20))
        clipped = ow.clip(text, 6).split("\n")
        self.assertEqual(len(clipped), 7)
        self.assertIn("more lines", clipped[2])
        self.assertEqual(ow.wrap("abcdef", 4), ["abcd", "ef"])

    def test_tool_detail(self):
        self.assertEqual(ow.tool_detail("Read", {"file_path": "/a"}), "/a")
        self.assertEqual(ow.tool_detail("edit", {"path": "/b"}), "/b")
        self.assertEqual(ow.tool_detail("execute", {"code": "return 1"}), "return 1")


class SidebarOrder(unittest.TestCase):
    def agents(self, *ids):
        return [ow.Agent(i, {"name": i}) for i in ids]

    def test_follows_agent_order(self):
        layout = {"order": ["people", "unassigned"], "agentOrder": ["c", "a", "b"]}
        self.assertEqual([a.id for a in ow.sidebar_order(self.agents("a", "b", "c", "d"), layout)], ["c", "a", "b", "d"])

    def test_sections_come_first_in_their_order(self):
        layout = {"order": ["work", "unassigned"], "sections": [{"id": "work", "name": "Work"}],
                  "agentAssignments": {"b": "work"}, "agentOrder": ["a", "b", "c"]}
        self.assertEqual([a.id for a in ow.sidebar_order(self.agents("a", "b", "c"), layout)], ["b", "a", "c"])


class AgentProcs(unittest.TestCase):
    """Which processes belong to an agent."""

    def test_claude_shell_children_kept_and_mcp_servers_dropped(self):
        procs = {p["pid"]: p for p in [
            proc(10, 1, ["/x/claude"], sid="S"),
            proc(11, 10, ["zsh", "-c", "make"], sid="S"),
            proc(12, 11, ["make"], sid="S"),
            proc(13, 10, ["mcp-server"], sid="S"),               # MCP server
            proc(14, 1, ["server"], sid="S"),                     # detached with setsid
            proc(15, 1, ["other"], sid="T"),                      # another agent
        ]}
        got = {p["pid"] for p in ow.agent_procs(procs, {"S"})}
        self.assertEqual(got, {11, 12, 14})

    def test_opencode_exec_child_kept(self):
        procs = {p["pid"]: p for p in [
            proc(20, 1, ["/x/opencode", "serve"]),
            proc(21, 20, ["python3", "-c", "loop"], sid="ses_1"),  # shell exec'd the command
            proc(22, 20, ["mcp-server"]),                          # MCP server: no session variable
        ]}
        self.assertEqual({p["pid"] for p in ow.agent_procs(procs, {"ses_1"})}, {21})

    def test_children_without_session_variable_included(self):
        procs = {p["pid"]: p for p in [
            proc(40, 1, ["python3", "ci.py"], sid="S"),
            proc(41, 40, ["make", "-j30"]),            # started with a cleaned environment
            proc(42, 41, ["cc", "a.c"]),
            proc(43, 1, ["unrelated"]),
        ]}
        self.assertEqual({p["pid"] for p in ow.agent_procs(procs, {"S"})}, {40, 41, 42})

    def test_systemd_run_unit_included(self):
        procs = {p["pid"]: p for p in [
            proc(30, 1, ["bash", "run.sh"], sid="S"),
            proc(31, 30, ["systemd-run", "--user", "--pipe", "--unit=job-1", "python3", "job.py"], sid="S", out="pipe:[9]"),
            proc(32, 2, ["python3", "job.py"], unit="job-1.service", out="pipe:[9]"),
            proc(33, 2, ["python3", "unrelated.py"], unit="other.service"),
        ]}
        got = {p["pid"]: p for p in ow.agent_procs(procs, {"S"})}
        self.assertEqual(set(got), {30, 31, 32})
        self.assertEqual(got[32].get("via"), "systemd-run")


class ClaudeFeed(unittest.TestCase):
    def test_parses_commands_and_results(self):
        agent = ow.ClaudeAgent("a", {"name": "A", "provider": "claude", "workspacePath": "/w"})
        feed = ow.Feed(agent)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        feed.add({"type": "user", "timestamp": ts, "message": {"content": "fix it"}})
        feed.add({"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "make", "description": "Build", "run_in_background": True}}]}})
        self.assertEqual(feed.running()[0][1], "Build")
        feed.add({"type": "user", "timestamp": ts, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "Command running in background with ID: bxyz123."}]}})
        kinds = [e["kind"] for e in feed.events]
        self.assertEqual(kinds, ["msg", "cmd", "out"])
        self.assertEqual(feed.task_desc["bxyz123"], "Build")
        self.assertEqual(feed.running(), [])


class Subagents(unittest.TestCase):
    def test_subagent_events_split_from_main_and_time_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            agent = ow.ClaudeAgent("a", {"name": "A", "provider": "claude", "workspacePath": "/w"})
            agent.projdir = d
            sub = os.path.join(d, "s1", "subagents")
            os.makedirs(sub)
            now = time.time()
            iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
            with open(os.path.join(d, "s1.jsonl"), "w") as f:
                f.write(json.dumps({"type": "assistant", "timestamp": iso(now - 30), "message": {"content": [
                    {"type": "text", "text": "main first"}]}}) + "\n")
                f.write(json.dumps({"type": "assistant", "timestamp": iso(now - 10), "message": {"content": [
                    {"type": "text", "text": "main last"}]}}) + "\n")
            path = os.path.join(sub, "agent-x.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"type": "assistant", "isSidechain": True, "timestamp": iso(now - 20),
                                    "message": {"content": [{"type": "text", "text": "sub work"}]}}) + "\n")
            with open(os.path.join(sub, "agent-x.meta.json"), "w") as f:
                json.dump({"description": "Map the code", "agentType": "Explore"}, f)
            feed = agent.make_feed()
            feed.poll()
            self.assertEqual([r[3] for r in feed.rows(False)], ["main first", "sub work", "main last"])
            self.assertEqual([r[3] for r in feed.rows(False, main_only=True)], ["main first", "main last"])
            self.assertEqual([r[3] for r in feed.rows(False, src=path)], ["sub work"])
            self.assertEqual([(os.path.basename(x["key"]), x["label"], x["kind"]) for x in agent.subagents()],
                             [("agent-x.jsonl", "Map the code", "Explore")])
            view = ow.View(agent)
            view.poll()
            view.refresh({})
            tab = view.tabs[path]
            self.assertTrue(tab.alive)
            self.assertEqual((tab.label, tab.kind), ("Map the code", "Explore"))


class OpencodeFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = ow.OC_DB, ow.OcDB.conn
        ow.OC_DB, ow.OcDB.conn = os.path.join(self.tmp.name, "opencode.db"), None
        db = sqlite3.connect(ow.OC_DB)
        db.execute("create table project (id text, worktree text)")
        db.execute("create table session_v2 (id text, project_id text, parent_id text, directory text, time_updated integer, "
                   "title text, agent text, time_created integer, time_busy integer, time_idle integer)")
        db.execute("create table session_message (id text, session_id text, type text, seq integer, "
                   "time_created integer, time_updated integer, data text)")
        now = int(time.time() * 1000)
        db.execute("insert into session_v2 values ('ses_1', 'p', null, '/w', ?, 'Main', 'build', ?, ?, null)", (now, now, now))
        db.execute("insert into session_v2 values ('ses_2', 'p', 'ses_1', '/elsewhere', ?, 'Find the tests', 'explore', ?, ?, null)",
                   (now, now, now))   # a subagent, still busy
        msgs = [
            ("m1", "user", {"text": "<openbot-developer-instructions>x</openbot-developer-instructions>\nhello"}),
            ("m2", "assistant", {"time": {"created": now, "completed": now + 1}, "content": [
                {"type": "reasoning", "text": "think first", "time": {"created": now, "completed": now}},
                {"type": "tool", "id": "c1", "name": "shell", "time": {"created": now},
                 "state": {"status": "completed", "input": {"command": "sleep 99", "background": True},
                           "content": [{"type": "text", "text": "moved to background"}],
                           "metadata": {"status": "running", "shellID": "sh_9"}}},
                {"type": "tool", "id": "c2", "name": "shell", "time": {"created": now},
                 "state": {"status": "completed", "input": {"command": "false"}, "content": [],
                           "metadata": {"exit": 1}}},
                {"type": "text", "text": "done"}]}),
            ("m3", "assistant", {"time": {"created": now}, "content": []}),   # model still generating
        ]
        for i, (mid, kind, data) in enumerate(msgs):
            db.execute("insert into session_message values (?, 'ses_1', ?, ?, ?, ?, ?)",
                       (mid, kind, i, now + i, now + i, json.dumps(data)))
        db.execute("insert into session_message values ('s1', 'ses_2', 'assistant', 0, ?, ?, ?)", (now + 5, now + 5, json.dumps(
            {"time": {"created": now + 5, "completed": now + 6}, "content": [{"type": "text", "text": "found 3 test files"}]})))
        db.commit()
        db.close()

    def tearDown(self):
        if ow.OcDB.conn:
            ow.OcDB.conn.close()
        ow.OC_DB, ow.OcDB.conn = self.old
        self.tmp.cleanup()

    def test_command_without_session_variable_found_by_start_time(self):
        agent = ow.OpencodeAgent("a", {"name": "A", "provider": "opencode", "workspacePath": "/w"})
        shell = os.path.join(self.tmp.name, "shell", "p")
        os.makedirs(shell)
        open(os.path.join(shell, "sh_1.out"), "w").close()
        born = os.path.getctime(os.path.join(shell, "sh_1.out"))
        old = ow.OC_DATA
        ow.OC_DATA = self.tmp.name
        try:
            db = sqlite3.connect(ow.OC_DB)
            db.execute("insert into project values ('p', '/w')")
            db.commit()
            db.close()
            procs = {p["pid"]: p for p in [
                proc(50, 1, ["/x/opencode", "serve"]),
                proc(51, 50, ["bash", "-c", "loop"], start=born + 0.5),      # env -i: no session variable
                proc(52, 51, ["sleep", "1"], start=born + 1),
                proc(53, 50, ["mcp-server"], start=born - 3600),          # MCP server started long before
            ]}
            got = {p["pid"] for p in ow.agent_procs(procs, agent.sessions(), agent)}
        finally:
            ow.OC_DATA = old
        self.assertEqual(got, {51, 52})

    def test_subagent_tab(self):
        agent = ow.OpencodeAgent("a", {"name": "A", "provider": "opencode", "workspacePath": "/w"})
        self.assertEqual([(x["key"], x["label"], x["kind"], x["finished"]) for x in agent.subagents()],
                         [("ses_2", "Find the tests", "explore", False)])
        view = ow.View(agent)
        view.poll()
        view.refresh({})
        tab = view.tabs["ses_2"]
        self.assertTrue(tab.alive)
        self.assertEqual(tab.poll(), 1)
        self.assertEqual([r[3] for r in tab.all_rows()], ["found 3 test files"])

    def test_sessions_include_subagents(self):
        agent = ow.OpencodeAgent("a", {"name": "A", "provider": "opencode", "workspacePath": "/w"})
        self.assertEqual(agent.sessions(), {"ses_1", "ses_2"})

    def test_feed(self):
        agent = ow.OpencodeAgent("a", {"name": "A", "provider": "opencode", "workspacePath": "/w"})
        feed = agent.make_feed()
        feed.poll()
        kinds = [(e["kind"], e["text"]) for e in feed.events]
        self.assertEqual(kinds[0], ("msg", "hello"))                  # OpenBot's instructions stripped
        self.assertIn(("think", "think first"), kinds)
        self.assertIn(("err", "(no output)"), kinds)                 # exit 1 counts as an error
        self.assertIn(("say", "done"), kinds)
        self.assertEqual([r[3] for r in feed.rows(False, src="ses_2")], ["found 3 test files"])
        self.assertNotIn("found 3 test files", [r[3] for r in feed.rows(False, main_only=True)])
        self.assertEqual(feed.bg_shells, {"sh_9"})
        self.assertEqual(feed.shell_cmd["sh_9"], "sleep 99")
        self.assertEqual([r[1] for r in feed.running()], ["waiting for the model"])
        before = feed.total
        feed.poll()                                                   # nothing new: nothing added
        self.assertEqual(feed.total, before)


class Web(unittest.TestCase):
    """The web server answers only with the token, and only to requests addressed to localhost."""

    def test_token_and_host_checks(self):
        import http.client, threading
        from http.server import ThreadingHTTPServer
        state = ow.WebState.__new__(ow.WebState)
        state.lock, state.agents, state.views, state.focus = threading.Lock(), [], {}, {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), ow.web_handler(state, "secret-token", 0))
        port = server.server_address[1]
        server.RequestHandlerClass = ow.web_handler(state, "secret-token", port)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def get(path, **headers):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path, headers=dict({"Host": f"localhost:{port}"}, **headers))
            r = c.getresponse()
            return r.status, r.read()
        try:
            self.assertEqual(get("/")[0], 200)
            self.assertEqual(get("/api/agents")[0], 403)
            self.assertEqual(get("/api/agents", **{"X-Obwatch-Token": "wrong"})[0], 403)
            self.assertEqual(get("/api/agents", **{"X-Obwatch-Token": "secret-token"}), (200, b'{"agents": []}'))
            self.assertEqual(get("/api/agents", Host="evil.example", **{"X-Obwatch-Token": "secret-token"})[0], 403)
            self.assertEqual(get("/api/agent?id=nope", **{"X-Obwatch-Token": "secret-token"})[0], 404)
            # the printed link sets a cookie, which then works without the header
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/?token=secret-token", headers={"Host": f"localhost:{port}"})
            r = c.getresponse(); r.read()
            self.assertEqual(r.status, 303)
            cookie = r.getheader("Set-Cookie")
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            self.assertEqual(get("/api/agents", Cookie=cookie.split(";")[0])[0], 200)
            self.assertEqual(get("/api/agents", Cookie=f"obwatch_{port}=wrong")[0], 403)
            self.assertEqual(get("/?token=wrong")[0], 200)   # the page loads and tells you to use the right link
        finally:
            server.shutdown()
            server.server_close()

    def test_access_log(self):
        import io
        out = io.StringIO()
        log = ow.AccessLog(out)
        log.request("192.0.2.23", "GET / HTTP/1.1", 200)
        log.request("192.0.2.23", "GET /api/agents HTTP/1.1", 200)
        log.request("192.0.2.23", "GET /api/agents HTTP/1.1", 403, "missing or wrong token")
        text = out.getvalue()
        self.assertIn("new client", text)
        self.assertIn("GET / HTTP/1.1  → 200", text)
        self.assertNotIn("GET /api/agents HTTP/1.1  → 200", text)     # live updates are summarized
        self.assertIn("→ 403  missing or wrong token", text)
        log.flushed -= 61
        log.request("192.0.2.23", "GET /api/agents HTTP/1.1", 200)
        self.assertIn("2 live updates OK in the last minute", out.getvalue())

    def test_page_javascript_parses(self):
        import shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        page = ow.WEB_PAGE
        js = page[page.index("<script>") + 8:page.rindex("</script>")]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
        try:
            r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(f.name)

    def test_client_allowed(self):
        import ipaddress
        lan = ipaddress.ip_network("192.0.2.0/24")
        self.assertTrue(ow.client_allowed("192.0.2.23", lan))
        self.assertTrue(ow.client_allowed("127.0.0.1", lan))
        self.assertFalse(ow.client_allowed("198.51.100.5", lan))      # a VPN peer
        self.assertFalse(ow.client_allowed("203.0.113.2", lan))       # a container
        self.assertFalse(ow.client_allowed("192.0.2.23", None))    # without --lan: this machine only

    def test_file_change_diffs(self):
        c = ow.file_change("Edit", {"file_path": "/x/a.py", "old_string": "a = 1", "new_string": "a = 2"})
        self.assertEqual(c["file"], "/x/a.py")
        self.assertIn("-a = 1", c["diff"])
        self.assertIn("+a = 2", c["diff"])
        self.assertIn("+++ b/x/a.py", c["diff"])
        self.assertEqual(ow.file_change("edit", {"path": "b"}, {"files": [{"patch": "P"}]})["diff"], "P")
        self.assertIsNone(ow.file_change("Read", {"file_path": "/x"}))


class ClaudeAccounts(unittest.TestCase):
    def test_sessions_found_in_every_account_folder(self):
        """OpenBot keeps each Claude account's sessions in its own folder; switching accounts moves new ones there."""
        saved = ow.PROJECTS, ow.PROVIDER_ACCOUNTS, ow.HOME, ow._roots
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ow.HOME, ow.PROJECTS = tmp, os.path.join(tmp, ".claude", "projects")
                ow.PROVIDER_ACCOUNTS, ow._roots = os.path.join(tmp, "accounts"), (0, [])
                a = ow.make_agent("agent-demo", {"name": "Demo", "provider": "claude", "workspacePath": "/home/demo/ws"})
                old = os.path.join(ow.PROJECTS, "-home-demo-ws")
                new = os.path.join(tmp, "accounts", "acct2", "projects", "-home-demo-ws")
                for d, sid in ((old, "s-old"), (new, "s-new")):
                    os.makedirs(d)
                    with open(os.path.join(d, sid + ".jsonl"), "w") as f:
                        f.write(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z",
                                            "message": {"role": "user", "content": sid}}) + "\n")
                self.assertEqual(a.sessions(), {"s-old", "s-new"})
                feed = a.make_feed(); feed.poll()
                self.assertEqual(sorted(e["text"] for e in feed.events), ["s-new", "s-old"])
            finally:
                ow.PROJECTS, ow.PROVIDER_ACCOUNTS, ow.HOME, ow._roots = saved


class MarkdownHistory(unittest.TestCase):
    """file_history: when each line of a Markdown file got its text, from the agent's edits."""

    def edit(self, old, new, all=False):
        return dict(ops=[dict(old=old, new=new, all=all)])

    def test_lines_get_the_edit_that_wrote_them(self):
        steps = [dict(ops=[dict(write="# T\n\nintro\n\n- a\n- b\n")]),
                 self.edit("- b\n", "- b\n- c\n"),
                 self.edit("intro", "intro changed"),
                 self.edit("- a\n- b\n", "- b\n"),       # removes a line (edits carry some context)
                 self.edit("missing", "zzz")]             # failed or overwritten: can't be traced
        h = ow.file_history("# T\n\nintro changed\n\n- b\n- c\n", steps)
        self.assertEqual(h["lines"], [0, 0, 2, 0, 0, 1])
        self.assertEqual(h["kind"], ["add", "add", "mod", "add", "add", "add"])
        self.assertEqual(h["unmatched"], 1)
        mods = [r for r in h["removed"] if r["mod"]]
        gone = [r for r in h["removed"] if not r["mod"]]
        self.assertEqual((mods[0]["at"], mods[0]["text"], mods[0]["step"]), (2, "intro", 2))
        self.assertEqual((gone[0]["at"], gone[0]["text"], gone[0]["step"]), (4, "- a", 3))

    def test_edit_changed_again_elsewhere_is_matched_by_content(self):
        steps = [dict(ops=[dict(write="intro\n")]),
                 self.edit("intro\n", "intro\nA long line the agent added\nshort\n")]
        h = ow.file_history("intro\nA long line the agent added\nshort, edited by someone else\n", steps)
        self.assertEqual(h["unmatched"], 1)
        self.assertEqual(h["lines"], [0, 1, 0])

    def test_file_older_than_the_session(self):
        h = ow.file_history("x\nnew\ny\n", [self.edit("x\ny", "x\nnew\ny")])
        self.assertEqual(h["lines"], [-1, 0, -1])   # -1: was there before the agent's edits

    def test_undo_edit_picks_the_only_safe_place(self):
        self.assertEqual(ow.undo_edit("a b a", dict(old="c", new="b")), "a c a")
        self.assertEqual(ow.undo_edit("x x", dict(old="y", new="x", all=True)), "y y")
        self.assertIsNone(ow.undo_edit("abc", dict(old="q", new="z")))
        # "X" twice: undoing the second would leave "aX" twice, which Edit wouldn't have allowed
        self.assertEqual(ow.undo_edit("aX X", dict(old="aX", new="X")), "aaX X")
        self.assertIsNone(ow.undo_edit("ok ok", dict(old="z", new="ok")))   # either place fits: don't guess

    def test_ops_kept_for_history_but_not_sent_to_the_page(self):
        c = ow.file_change("Edit", {"file_path": "/x/a.md", "old_string": "a", "new_string": "b"})
        self.assertEqual(c["ops"], [dict(old="a", new="b", all=False)])
        e = ow.WebState.event(dict(seq=1, ts="", kind="tool", text="", change=c))
        self.assertNotIn("ops", e["change"])


class Uncommitted(unittest.TestCase):
    def test_git_baseline_marks_everything_not_committed(self):
        """Changes made with shell commands have no edit to trace; git still shows them."""
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            git = lambda *a: subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=" + "t" + "@" + "example.com", *a],
                                            cwd=d, check=True, capture_output=True)
            git("init", "-q")
            path = os.path.join(d, "notes.md")
            with open(path, "w") as f:
                f.write("# Notes\n\nold line\n\nkept\n")
            git("add", "."); git("commit", "-qm", "start")
            self.assertIsNone(ow.git_base(os.path.join(d, "new.md"))["text"])   # not committed yet
            base = ow.git_base(path)
            self.assertEqual(base["text"], "# Notes\n\nold line\n\nkept\n")
            # one edit made with an edit tool after the commit, one line changed by a command
            text = "# Notes\n\nnew line\n\nkept\n\nadded by edit\n"
            steps = [dict(ops=[dict(old="kept\n", new="kept\n\nadded by edit\n")], epoch=base["time"] + 60)]
            hist, extra = ow.mark_uncommitted(text, ow.file_history(text, steps), steps, base, base["time"] + 90)
            self.assertEqual(hist["fresh"], [False, False, True, False, False, True, True])
            self.assertEqual(hist["lines"][2], 1)                  # the extra "by a command" step
            self.assertEqual(hist["lines"][6], 0)                  # the traced edit keeps its time
            self.assertTrue(extra and extra[0]["outside"])
            self.assertEqual([(r["text"], r["fresh"]) for r in hist["removed"]], [("old line", True)])
        self.assertIsNone(ow.git_base("/nonexistent/x.md"))


class Terminal(unittest.TestCase):
    def test_websocket_frames(self):
        import socket
        a, b = socket.socketpair()
        try:
            for size in (5, 300, 70000):
                payload = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
                mask = b"\x01\x02\x03\x04"   # browsers mask what they send
                frame = bytearray(ow.ws_frame(payload, 2))
                frame[1] |= 0x80
                hdr = 2 + (2 if size >= 126 else 0) + (6 if size >= 65536 else 0)
                a.sendall(bytes(frame[:hdr]) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))
                self.assertEqual(ow.ws_read(b), (2, payload))
            a.close()
            with self.assertRaises(EOFError):
                ow.ws_read(b)
        finally:
            b.close()
        self.assertEqual(ow.ws_accept("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")   # RFC 6455's example

    def test_terminal_needs_sign_in_and_same_origin(self):
        import http.client, threading
        from http.server import ThreadingHTTPServer
        state = ow.WebState.__new__(ow.WebState)
        state.lock, state.agents, state.views, state.focus = threading.Lock(), [], {}, {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), ow.web_handler(state, "secret-token", 0))
        port = server.server_address[1]
        server.RequestHandlerClass = ow.web_handler(state, "secret-token", port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        ws = {"Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
              "Sec-WebSocket-Version": "13", "Host": f"localhost:{port}"}

        def get(path, **headers):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path, headers=dict(ws, **headers))
            r = c.getresponse()
            return r.status
        try:
            me = f"http://localhost:{port}"
            self.assertEqual(get("/term", Origin=me), 403)                                   # not signed in
            self.assertEqual(get("/term", **{"X-Obwatch-Token": "secret-token", "Origin": "http://evil.example"}), 403)
            self.assertEqual(get("/term", **{"X-Obwatch-Token": "secret-token"}), 403)      # no origin
            self.assertEqual(get("/assets/xterm.js"), 403)
            self.assertEqual(get("/assets/passwd", **{"X-Obwatch-Token": "secret-token"}), 404)
        finally:
            server.shutdown()
            server.server_close()


class Privacy(unittest.TestCase):
    """The repo is public: nothing from the maintainer's machine, network or agents may be committed (see AGENTS.md).
    With OBWATCH_CHECK_STAGED=1 (the pre-commit hook) it checks what is staged instead of the working tree."""
    ROOT = os.path.dirname(HERE)
    EXAMPLE_IPS = ("127.", "0.0.0.0", "192.0.2.", "198.51.100.", "203.0.113.")   # loopback, RFC 5737
    PUBLIC = {"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"}   # published constants, not personal: the WebSocket handshake key (RFC 6455)
    CHECKS = [
        ("a home directory", re.compile(r"/home/(?!demo\b)[\w.-]+")),
        ("an email address", re.compile(r"\b[\w.+-]+@(?!github\.com\b)[\w-]+(?:\.[\w-]+)+\b")),
        ("a UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
        ("an OpenBot agent id", re.compile(r"\bagent-[0-9a-f]{8}\b")),
        ("an opencode session id", re.compile(r"\bses_(?!demo)[A-Za-z0-9]{12,}")),
    ]

    def files(self):
        import subprocess
        if os.environ.get("OBWATCH_CHECK_STAGED"):
            names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd=self.ROOT,
                                   capture_output=True, text=True).stdout.split()
            for n in names:
                data = subprocess.run(["git", "show", ":" + n], cwd=self.ROOT, capture_output=True).stdout
                yield n, data
            return
        for d, dirs, fs in os.walk(self.ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
            for f in fs:
                with open(os.path.join(d, f), "rb") as fh:
                    yield os.path.relpath(os.path.join(d, f), self.ROOT), fh.read()

    @staticmethod
    def private_words():
        path = os.path.expanduser("~/.config/obwatch/private-words")   # never part of the repo
        try:
            with open(path) as f:
                return [w.strip().lower() for w in f if w.strip() and not w.startswith("#")]
        except OSError:
            return []

    def test_no_personal_data(self):
        words, problems = self.private_words(), []
        ip = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
        for name, data in self.files():
            if name.endswith((".png", ".jpg", ".gif")):
                continue
            text = data.decode("utf-8", "replace")
            for n, line in enumerate(text.splitlines(), 1):
                where = f"{name}:{n}"
                for m in ip.finditer(line):
                    if all(int(x) <= 255 for x in m.group(1).split(".")) and not m.group(1).startswith(self.EXAMPLE_IPS):
                        problems.append(f"{where}: an IP address outside the example ranges: {m.group(1)}")
                for what, rx in self.CHECKS:
                    for m in rx.finditer(line):
                        if m.group(0) not in self.PUBLIC:
                            problems.append(f"{where}: {what}: {m.group(0)}")
                low = line.lower()
                problems += [f"{where}: a word from the private list" for w in words if w in low]
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
