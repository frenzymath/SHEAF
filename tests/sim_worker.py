#!/usr/bin/env python3
"""A simulated worker for tests/sim_tasks.py. It reads the hidden true DAG (sim/truth.json) and does its task the way
roles/worker.md asks, or fails in one of the ways real workers fail. Started by tools/dispatch.py as
`python3 sim_worker.py [session]`; the task comes from SHEAF_TASK and the sandbox from SHEAF_GROUP.
"""
import hashlib, json, os, pathlib, random, sys, uuid

ROOT = pathlib.Path.cwd()
truth = json.loads((ROOT / "sim" / "truth.json").read_text())
P = truth["_params"]
tid, group = os.environ["SHEAF_TASK"], os.environ["SHEAF_GROUP"]
session = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
print(json.dumps({"thread_id": session}))
with open(ROOT / "sim" / "sessions.log", "a") as f:
    f.write(f"{session}\t{tid}\n")

sys.path.insert(0, str(ROOT / "tools"))
from tasks import safe  # noqa: E402
stem = safe(tid)


def fname(i):  # node files and modules are named by a hash: node ids may hold any character
    return "x" + hashlib.sha1(i.encode("utf-8")).hexdigest()[:12]
attempt_file = ROOT / "sim" / "attempts" / stem
attempt_file.parent.mkdir(parents=True, exist_ok=True)
attempt = int(attempt_file.read_text()) + 1 if attempt_file.exists() else 1
attempt_file.write_text(str(attempt))
rng = random.Random(int(hashlib.sha256(f"{P['seed']}:{tid}:{attempt}".encode()).hexdigest(), 16))

task = json.loads((ROOT / "coord" / "tasks" / f"{stem}.json").read_text())
sb = ROOT / "lean" / ".sandbox" / group / stem
(sb / "nodes").mkdir(parents=True, exist_ok=True)
(sb / "lean" / "Paper").mkdir(parents=True, exist_ok=True)
nodes = ROOT / "dag" / "nodes"
r = rng.random()
if r < P["p_crash"]:
    sys.exit(1)
deliv = {"task": tid, "result": "delivered", "nodes": [], "lean": [], "report": "sim"}


def out():
    (ROOT / "coord" / "deliveries" / f"{stem}.json").write_text(json.dumps(deliv))
    sys.exit(0)


if r < P["p_crash"] + P["p_giveup"]:
    deliv["result"] = "gave-up"; out()

kind = task["kind"]
if kind == "target-review":
    f = task["files"][0]
    (sb / "files" / f).parent.mkdir(parents=True, exist_ok=True)
    verdict = "defect" if rng.random() < P["p_defect"] else "locked"
    (sb / "files" / f).write_text(f"review of {task['node']}\n\nVerdict: {verdict}\n")
    deliv["files"] = [f]; out()
if kind == "challenge":
    (sb / "files" / "lean").mkdir(parents=True, exist_ok=True)
    (sb / "files" / "lean" / "Challenge.lean").write_text("-- the targets\n")
    deliv["files"] = ["lean/Challenge.lean"]; out()
if kind in ("dispute", "diagnose"):
    deliv["report"] = f"{kind}: nothing to change"; out()
if kind == "target-fix":
    m = task["module"]
    rel = m.replace(".", "/") + ".lean"
    old = (ROOT / "lean" / rel).read_text()
    (sb / "lean" / rel).parent.mkdir(parents=True, exist_ok=True)
    (sb / "lean" / rel).write_text(old + f"def fix_{attempt}_{rng.randint(0, 10**6)} : Nat := {attempt}\n")  # a changed statement
    deliv["lean"] = [rel]; out()

i = task["node"]
t = truth[i]
cur = json.loads((nodes / f"{fname(i)}.json").read_text())


def put(d):
    (sb / "nodes" / f"{fname(d['id'])}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    deliv["nodes"].append(f"{fname(d['id'])}.json")


if task["stage"] == 1:
    bad = r < P["p_crash"] + P["p_giveup"] + P["p_badnode"]
    d = dict(cur, kind=t["kind"], stmt_deps=list(t["stmt"]))
    if t["kind"] != "definition":
        d["proof"] = [{"step": f"s{k}", "uses": [u]} for k, u in enumerate(t["proof"])]
    if bad:
        d.setdefault("proof", []).append({"step": "ghost", "uses": ["ghost-node"]})
    put(d)
    for c in set(t["stmt"]) | set(t["proof"]):
        if not (nodes / f"{fname(c)}.json").exists():  # create what does not exist yet, unsplit, or a Mathlib leaf
            tc = truth[c]
            put({"id": c, "status": "mathlib", "mathlib": f"Mathlib.{c}"} if tc["leaf"] else {"id": c, "kind": tc["kind"]})
    out()

if task["stage"] == 2:
    m = f"Paper.{fname(i)}"
    d = dict(cur, lean={"module": m, "declaration": i})
    put(d)
    (sb / "lean" / "Paper" / f"{fname(i)}.lean").write_text(f"theorem {fname(i)} : True := by sorry\n")
    deliv["lean"].append(f"Paper/{fname(i)}.lean")
    out()

if task["stage"] == 3:
    if rng.random() < P["p_dispute"]:
        deliv["result"] = "disputed"; deliv["report"] = "looks false"; out()
    m = task["module"]
    keep_sorry = rng.random() < P["p_landed"]
    (sb / "lean" / "Paper" / f"{fname(i)}.lean").write_text(f"theorem {fname(i)} : True := " + ("by sorry\n" if keep_sorry else "trivial\n"))
    deliv["lean"].append(f"Paper/{fname(i)}.lean")
    if not keep_sorry and rng.random() < P["p_prune"]:
        uses = [u for s in cur.get("proof", []) for u in s.get("uses", [])]
        if len(uses) > 1:  # the Lean proof found a shorter route: one planned dependency is not used
            drop = rng.choice(uses)
            d = dict(cur, proof=[s for s in cur["proof"] if drop not in s.get("uses", [])] or cur["proof"][:1])
            put(d)
    out()
sys.exit(1)
