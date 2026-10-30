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
    ("agent-demo-writer", {"name": "Writer", "title": "Drafts posts", "provider": "opencode"}),
]

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


def spawn(name, code, out):
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=SESSION, PYTHONUNBUFFERED="1")
    f = open(out, "w")
    p = subprocess.Popen([name, "-c", code], executable=sys.executable, stdout=f, stderr=subprocess.STDOUT,
                         env=env, start_new_session=True, cwd=f"{ROOT}/app")
    with open(PIDS, "a") as pf:
        pf.write(f"{p.pid}\n")


def start():
    stop(quiet=True)
    for d in (f"{HOME}/.config/OpenBot", f"{HOME}/.claude/projects/{PROJ}", TASKS, LOGS):
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
    spawn("api-server", API_SERVER, f"{LOGS}/api.log")
    spawn("docker", DOCKER, f"{TASKS}/bdocker01.output")
    spawn("pytest", PYTEST, f"{TASKS}/bfgtest01.output")
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
