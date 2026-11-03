"""Tests for obwatch. Standard library only: python3 -m unittest discover -s tests"""
import importlib.machinery, importlib.util, json, os, sqlite3, tempfile, time, unittest

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


if __name__ == "__main__":
    unittest.main()
