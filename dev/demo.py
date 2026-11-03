#!/usr/bin/env python3
"""Fake OpenBot setup for trying obwatch or taking screenshots, with no real agents.

  python3 dev/demo.py start    # create a fake HOME with demo agents and start demo processes
  HOME=/tmp/obwatch-demo/home ./obwatch coder
  python3 dev/demo.py stop     # stop the demo processes and delete the demo files

Uses only the standard library. Creates /tmp/obwatch-demo and /tmp/claude-<uid>/<demo workspace>.
"""
import datetime as dt, json, os, shutil, signal, sqlite3, subprocess, sys, tempfile, time

ROOT = os.path.join(tempfile.gettempdir(), "obwatch-demo")
HOME = f"{ROOT}/home"
SESSION = "5f0c2a1e-demo-4c1b-9d2e-0b5e7a9c1d23"
WORKSPACE = "/home/demo/OpenBot/Agents/agent-demo-coder"
PROJ = WORKSPACE.replace("/", "-")
TASKS = f"{tempfile.gettempdir()}/claude-{os.getuid()}/{PROJ}/{SESSION}/tasks"
LOGS = f"{ROOT}/app/logs"
PIDS = f"{ROOT}/pids"

AGENTS = [
    ("agent-demo-coder", {"name": "Coder", "title": "Builds and fixes the shop app", "provider": "claude",
                          "workspacePath": WORKSPACE}),
    ("agent-demo-research", {"name": "Researcher", "title": "Reads docs and compares options", "provider": "claude",
                             "workspacePath": "/home/demo/OpenBot/Agents/agent-demo-research"}),
    ("agent-demo-local", {"name": "Local model", "title": "opencode + a model served on the LAN",
                          "provider": "opencode", "workspacePath": "/home/demo/OpenBot/Agents/agent-demo-local"}),
    ("agent-demo-writer", {"name": "Writer", "title": "Drafts posts", "provider": "codex"}),
]

# The opencode agent: its session lives in opencode's database; shell output goes to shell/<project>/sh_*.out
OC_WS = "/home/demo/OpenBot/Agents/agent-demo-local"
OC_DIR = f"{HOME}/.local/share/opencode"
OC_SESSION, OC_PROJECT, OC_SHELL = "ses_demo0local0agent01", "demoproject0local0001", "sh_demo0bench0000001"
BENCH = r'''
import random, time
print("bench: 50 rounds of 200 lookups, cache ttl=600s", flush=True)
for i in range(1, 51):
    hit = min(97, 40 + i * 3) + random.random()
    print(f"round {i:2d}/50  p50={random.uniform(0.2, 0.6) if i > 1 else 180:.1f}ms  "
          f"p99={random.uniform(2, 9) if i > 1 else 420:.1f}ms  cache hits={hit:.1f}%", flush=True)
    time.sleep(1.5)
print("bench done", flush=True)
'''
RELAY = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line); sys.stdout.flush()"

# Programs the demo "agent" left running. Each writes slowly to its output file.
API_SERVER = r'''
import random, time
def log(level, msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), level.ljust(5), msg, flush=True)
log("INFO", "api-server 2.4.1 starting (env=dev)")
log("INFO", "connected to postgres://localhost:5432/shop")
log("INFO", "listening on 0.0.0.0:8080")
paths = ["/api/cart", "/api/checkout/totals", "/api/products?page=2", "/api/cart/items", "/healthz"]
n = 0
while True:
    n += 1
    p = random.choice(paths)
    log("INFO", f"GET {p} 200 {random.randint(3, 40)}ms")
    if n % 9 == 0:
        log("WARN", f"slow query on products ({random.randint(400, 900)}ms)")
    if n % 23 == 0:
        log("ERROR", "payment provider timeout after 5000ms (retrying 1/3)")
    time.sleep(random.uniform(0.3, 0.9))
'''
DOCKER = r'''
import time
steps = ["[internal] load build definition from Dockerfile", "[internal] load metadata for python:3.12-slim",
         "[build 1/6] FROM python:3.12-slim", "[build 2/6] WORKDIR /app", "[build 3/6] COPY requirements.txt .",
         "[build 4/6] RUN pip install --no-cache-dir -r requirements.txt"]
for i, s in enumerate(steps, 1):
    print(f"#{i} {s}", flush=True); time.sleep(0.3)
pkgs = ["fastapi", "uvicorn", "sqlalchemy", "psycopg", "pydantic", "httpx", "redis", "stripe", "orjson", "structlog"]
t = 3.0
while True:
    for p in pkgs:
        t += 1.7
        print(f"#6 {t:5.1f} Collecting {p}", flush=True); time.sleep(0.8)
        print(f"#6 {t + 0.4:5.1f}   Downloading {p}-latest-py3-none-any.whl", flush=True); time.sleep(0.6)
'''
PYTEST = r'''
import time
print("============================= test session starts ==============================", flush=True)
print("collected 42 items", flush=True)
tests = ["test_cart_totals_usd", "test_cart_totals_eur", "test_cart_without_currency", "test_discount_codes",
         "test_shipping_rates", "test_checkout_happy_path", "test_checkout_declined_card", "test_refund_flow"]
while True:
    for t in tests:
        print(f"tests/integration/test_checkout.py::{t} PASSED", flush=True); time.sleep(1.4)
'''


def iso(sec_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=sec_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def transcript():
    recs, n = [], [0]

    def add(kind, sec_ago, content):
        recs.append({"type": kind, "timestamp": iso(sec_ago), "sessionId": SESSION,
                     "message": {"role": kind, "content": content}})

    def tool(sec_ago, name, inp, result, result_ago=None, error=False):
        n[0] += 1
        tid = f"toolu_demo{n[0]:03d}"
        add("assistant", sec_ago, [{"type": "tool_use", "id": tid, "name": name, "input": inp}])
        if result is not None:
            add("user", result_ago if result_ago is not None else sec_ago - 1,
                [{"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": error}])

    add("user", 260, "Checkout returns a 500 for some carts since this morning's deploy. Find out why and fix it.")
    add("assistant", 255, [{"type": "text", "text": "Starting with the API server log to find the failing requests."}])
    tool(252, "Bash", {"command": "grep -n ERROR logs/api.log | tail -5",
                       "description": "Show recent errors in the API log"},
         "1841:2026-10-30T09:12:03Z ERROR POST /api/checkout/totals 500 KeyError: 'currency'\n"
         "1902:2026-10-30T09:14:41Z ERROR POST /api/checkout/totals 500 KeyError: 'currency'\n"
         "1977:2026-10-30T09:15:10Z ERROR POST /api/checkout/totals 500 KeyError: 'currency'")
    tool(246, "Read", {"file_path": "/home/demo/shop/src/checkout/totals.py"},
         "1\tfrom decimal import Decimal\n2\t\n3\tdef cart_total(cart):\n4\t    rate = RATES[cart['currency']]\n"
         "5\t    return sum(Decimal(i['price']) * i['qty'] for i in cart['items']) * rate")
    add("assistant", 240, [{"type": "text", "text": "Carts created before the deploy have no `currency` field, so "
                                                  "`cart_total` raises KeyError. I'll default them to the store currency."}])
    tool(236, "Edit", {"file_path": "/home/demo/shop/src/checkout/totals.py",
                       "old_string": "RATES[cart['currency']]", "new_string": "RATES[cart.get('currency', 'USD')]"},
         "The file /home/demo/shop/src/checkout/totals.py has been updated successfully.")
    tool(230, "Bash", {"command": "pytest tests/unit -q", "description": "Run the unit tests", "run_in_background": True},
         "Command running in background with ID: bdone0001. Output is being written to: " + TASKS + "/bdone0001.output")
    tool(200, "Bash", {"command": "(setsid nohup ./bin/api-server > logs/api.log 2>&1 &); sleep 2; tail -3 logs/api.log",
                       "description": "Restart the API server with the fix"},
         "INFO  api-server 2.4.1 starting (env=dev)\nINFO  connected to postgres://localhost:5432/shop\n"
         "INFO  listening on 0.0.0.0:8080")
    tool(190, "Bash", {"command": "curl -s -X POST localhost:8080/api/checkout/totals -d @fixtures/legacy-cart.json",
                       "description": "Retry a legacy cart against the fixed server"},
         '{"total": "48.20", "currency": "USD"}')
    tool(180, "Bash", {"command": "docker build -t shop-api:dev .", "description": "Build the Docker image",
                       "run_in_background": True},
         "Command running in background with ID: bdocker01. Output is being written to: " + TASKS + "/bdocker01.output")
    add("assistant", 175, [{"type": "text", "text": "Legacy carts now return a total instead of a 500. The unit "
                                                  "tests pass. The image is building; running the integration "
                                                  "tests while it does."}])
    tool(12, "Bash", {"command": "pytest tests/integration -v", "description": "Run the integration tests"}, None)
    return recs


def oc_messages():
    now = time.time() * 1000
    rows, n = [], [0]

    def msg(kind, sec_ago, data):
        n[0] += 1
        t = now - sec_ago * 1000
        data.setdefault("time", {"created": t, "completed": t + 500})
        rows.append((f"msg_demo{n[0]:03d}", OC_SESSION, kind, n[0], t, t + 500, json.dumps(data)))

    def tool(sec_ago, name, inp, out, meta=None):
        t = now - sec_ago * 1000
        return {"type": "tool", "id": f"call_{len(rows)}_{name}", "name": name, "time": {"created": t, "completed": t + 800},
                "state": {"status": "completed", "input": inp, "content": [{"type": "text", "text": out}],
                          "metadata": meta or {"status": "completed", "exit": 0}}}

    def think(sec_ago, text):
        t = now - sec_ago * 1000
        return {"type": "reasoning", "text": text, "time": {"created": t, "completed": t + 400}}

    msg("user", 95, {"text": "<openbot-developer-instructions>(OpenBot's instructions)</openbot-developer-instructions>\n"
                             "Add caching to the weather lookup and check that it actually helps."})
    msg("assistant", 92, {"agent": "build", "model": {"id": "local/coder-14b", "providerID": "lan"}, "content": [
        think(92, "The lookup calls the API on every request. A small TTL cache keyed by city should do it. "
                  "First check the current tests so I know what the function must keep doing."),
        tool(90, "shell", {"command": "pytest -q tests/test_weather.py", "description": "Run the weather tests"},
             "......\n6 passed in 0.41s"),
        tool(86, "read", {"path": "/home/demo/weather/src/lookup.py"},
             "def lookup(city):\n    return api.get(f'/current?q={city}').json()"),
        think(80, "Wrap lookup in a dict cache with a 10 minute expiry. Keep the signature the same."),
        tool(78, "edit", {"path": "/home/demo/weather/src/lookup.py", "oldString": "def lookup(city):",
                          "newString": "@ttl_cache(seconds=600)\ndef lookup(city):"},
             "Edited src/lookup.py (1 replacement)"),
        tool(74, "shell", {"command": "pytest -q tests/test_weather.py"}, "......\n6 passed in 0.39s"),
        think(70, "Tests still pass. The benchmark takes over a minute, so run it in the background and read its log."),
        tool(68, "shell", {"command": "python3 -u bench.py", "description": "Benchmark the cache", "background": True},
             f"Command moved to the background (shell ID: {OC_SHELL}).",
             {"status": "running", "shellID": OC_SHELL}),
        {"type": "text", "text": "The cache is in and the tests pass. The benchmark is running in the background; "
                                 "I'll report the hit rate when it finishes."},
    ]})
    return rows


def oc_sub_messages():
    now = time.time() * 1000
    sub = OC_SESSION + "_sub"

    def m(i, sec_ago, kind, data):
        t = now - sec_ago * 1000
        data.setdefault("time", {"created": t, "completed": t + 500})
        return (f"msg_sub{i}", sub, kind, i, t, t + 500, json.dumps(data))

    return [
        m(1, 40, "user", {"text": "Review the TTL cache added to src/lookup.py. Look for stale data and thread-safety issues."}),
        m(2, 35, "assistant", {"content": [
            {"type": "reasoning", "text": "Check how the cache is keyed and whether two requests can race on a miss.",
             "time": {"created": now - 35000, "completed": now - 34000}},
            {"type": "tool", "id": "call_sub_1", "name": "grep", "time": {"created": now - 33000, "completed": now - 32800},
             "state": {"status": "completed", "input": {"pattern": "ttl_cache", "path": "src"},
                       "content": [{"type": "text", "text": "src/lookup.py:3: @ttl_cache(seconds=600)\nsrc/cache.py:8: def ttl_cache(seconds):"}],
                       "metadata": {}}},
            {"type": "text", "text": "Keys are lower-cased city names, so 'Oslo' and 'oslo' share an entry. Checking the lock next."}]}),
    ]


def oc_setup():
    os.makedirs(f"{OC_DIR}/shell/{OC_PROJECT}", exist_ok=True)
    db = sqlite3.connect(f"{OC_DIR}/opencode.db")
    db.execute("create table project (id text, worktree text)")
    db.execute("create table session_v2 (id text, project_id text, parent_id text, directory text, time_updated integer, "
               "title text, agent text, time_created integer, time_busy integer, time_idle integer)")
    db.execute("create table session_message (id text, session_id text, type text, seq integer, "
               "time_created integer, time_updated integer, data text)")
    db.execute("insert into project values (?, ?)", (OC_PROJECT, OC_WS))
    now = int(time.time() * 1000)
    db.execute("insert into session_v2 values (?, ?, null, ?, ?, 'Cache the weather lookup', 'build', ?, ?, ?)",
               (OC_SESSION, OC_PROJECT, OC_WS, now, now - 95000, now - 95000, now - 60000))
    # a subagent the agent started to review its change; still busy
    db.execute("insert into session_v2 values (?, ?, ?, ?, ?, 'Review the cache change', 'general', ?, ?, null)",
               (OC_SESSION + "_sub", OC_PROJECT, OC_SESSION, OC_WS, now, now - 40000, now - 40000))
    db.executemany("insert into session_message values (?, ?, ?, ?, ?, ?, ?)", oc_messages() + oc_sub_messages())
    db.commit()
    with open(f"{ROOT}/app/bench.py", "w") as f:
        f.write(BENCH)
    # opencode reads the command's output through a pipe and writes it to the sh_*.out file itself
    out = open(f"{OC_DIR}/shell/{OC_PROJECT}/{OC_SHELL}.out", "w")
    relay = subprocess.Popen(["opencode", "-c", RELAY], executable=sys.executable, stdin=subprocess.PIPE, stdout=out,
                             start_new_session=True)
    sh = subprocess.Popen(["bash", "-c", "python3 -u bench.py"], stdout=relay.stdin, stderr=subprocess.STDOUT,
                          env=dict(os.environ, OPENCODE_SESSION_ID=OC_SESSION, OPENCODE="1"),
                          start_new_session=True, cwd=f"{ROOT}/app")
    with open(PIDS, "a") as pf:
        pf.write(f"{relay.pid}\n{sh.pid}\n")


def spawn(argv, code, out):
    """Run `code` with Python under the process name argv[0], so it looks like that program in obwatch."""
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=SESSION, PYTHONUNBUFFERED="1")
    f = open(out, "w")
    src = f"{ROOT}/app/.{argv[0]}.py"
    with open(src, "w") as sf:
        sf.write(code)
    # Python reads the program from stdin ("-"), so the command line shows only argv
    p = subprocess.Popen(argv[:1] + ["-"] + argv[1:] if argv[1:] else argv, executable=sys.executable,
                         stdin=open(src), stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True,
                         cwd=f"{ROOT}/app")
    with open(PIDS, "a") as pf:
        pf.write(f"{p.pid}\n")


def start():
    stop(quiet=True)
    for d in (f"{HOME}/.config/OpenBot", f"{HOME}/.claude/projects/{PROJ}", TASKS, LOGS, f"{ROOT}/app"):
        os.makedirs(d, exist_ok=True)
    db = sqlite3.connect(f"{HOME}/.config/OpenBot/openbot.db")
    db.execute("create table projection_agents (agent_id text, agent_json text, sort_order integer)")
    db.executemany("insert into projection_agents values (?, ?, ?)",
                   [(aid, json.dumps(d), i) for i, (aid, d) in enumerate(AGENTS)])
    db.commit()
    with open(f"{HOME}/.claude/projects/{PROJ}/{SESSION}.jsonl", "w") as f:
        for r in transcript():
            f.write(json.dumps(r) + "\n")
    research = f"{HOME}/.claude/projects/-home-demo-OpenBot-Agents-agent-demo-research"
    os.makedirs(research, exist_ok=True)
    with open(f"{research}/old-session.jsonl", "w") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": iso(7300), "message": {"content": [
            {"type": "text", "text": "Summary is in compare-queues.md."}]}}) + "\n")
    os.utime(f"{research}/old-session.jsonl", (time.time() - 7300,) * 2)
    with open(f"{TASKS}/bdone0001.output", "w") as f:
        f.write("........................................................... [ 61%]\n"
                "....................................                        [100%]\n"
                "97 passed in 4.81s\n")
    spawn(["api-server"], API_SERVER, f"{LOGS}/api.log")
    spawn(["docker", "build", "-t", "shop-api:dev", "."], DOCKER, f"{TASKS}/bdocker01.output")
    spawn(["pytest", "tests/integration", "-v"], PYTEST, f"{TASKS}/bfgtest01.output")
    oc_setup()
    print(f"Demo running. Try:\n  HOME={HOME} {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/obwatch coder\n"
          f"Stop it with: python3 {os.path.abspath(__file__)} stop")


def stop(quiet=False):
    if os.path.exists(PIDS):
        for line in open(PIDS):
            try:
                os.killpg(int(line), signal.SIGTERM)
            except (ProcessLookupError, ValueError, PermissionError):
                pass
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(os.path.dirname(os.path.dirname(TASKS)), ignore_errors=True)
    if not quiet:
        print("Demo stopped and removed.")


if __name__ == "__main__":
    {"start": start, "stop": stop}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
