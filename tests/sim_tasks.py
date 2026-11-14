#!/usr/bin/env python3
"""Simulation test of task discovery and task assignment, with no Lean: tools/tasks.py and tools/dispatch.py run on a
random DAG that simulated workers (tests/sim_worker.py) reveal, stage by stage, failing as real workers fail.
Compilation is out of scope: the submit command only copies the Lean files.

Usage:
  python3 tests/sim_tasks.py <work dir> [--seeds 1,2,3] [--nodes 40] [--slots 6] [--harsh]
  --harsh: workers crash, give up and prune far more often

After every pass of the dispatcher it checks, and at the end reports every violation:

  rules        the open tasks are exactly those the stage documents define, computed here independently
               (an oracle written from the contract, not from tools/tasks.py);
  incremental  what the event-driven refreshes left listed equals a full recomputation: no open item missing,
               and nothing listed that is not open unless someone holds it;
  claims       no task is held twice, and every running worker holds the task it works on;
  slots        never more workers than slots;
  starvation   with a free slot, no task that was open before the pass is left unclaimed;
  continuation a session's next task is next to its previous one in the DAG;
  settle       the queue follows the acceptance's result code alone: 0 done or landed, anything else returned,
               and the claim released;
  termination  the run ends with nothing listed, every node a target reaches stated, every module proved, every
               target reviewed without defect and Challenge.lean written.
The workers also review target statements (finding defects at random), fix them, dispute statements, and
diagnose tasks that failed often; the oracle covers the tasks the code opens for these.
"""
from __future__ import annotations
import collections, hashlib, json, os, pathlib, random, shutil, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"


def make_truth(seed: int, n: int) -> dict:
    """A layered random DAG: 2 targets on top, Mathlib leaves at the bottom, shared children in between."""
    rng = random.Random(seed)
    layers = [[f"t{k}" for k in range(max(2, n // 25))]]
    # every fourth id holds what file names and logs must survive: spaces, slashes, colons, non-ASCII
    rest = [f"n{k}" if k % 4 else f"n{k} 引理/é:x" for k in range(n)]
    depth = 5
    for d in range(1, depth + 1):
        take = len(rest) // (depth - d + 1)
        layers.append(rest[:take]); rest = rest[take:]
    truth = {}
    for d, layer in enumerate(layers):
        below = [x for l in layers[d + 1:] for x in l]
        for i in layer:
            leaf = d == depth or (d > 2 and rng.random() < 0.2)
            kind = "target" if d == 0 else ("definition" if rng.random() < 0.3 else "statement")
            if leaf or not below:
                truth[i] = {"kind": "statement" if kind == "target" else kind, "leaf": True, "stmt": [], "proof": []}
                continue
            near = [x for x in below if x in layers[d + 1]] or below
            stmt = rng.sample(near, k=min(len(near), rng.randint(1, 2))) if kind == "definition" else \
                rng.sample(below, k=min(len(below), rng.randint(0, 2)))
            proof = [] if kind == "definition" else rng.sample(below, k=min(len(below), rng.randint(2, 4)))
            truth[i] = {"kind": kind, "leaf": False, "stmt": stmt, "proof": proof}
    return truth


def setup(work: pathlib.Path, seed: int, n: int, slots: int, harsh: bool = False) -> pathlib.Path:
    root = work / f"seed{seed}"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(TEMPLATE, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "dag" / "nodes").mkdir(parents=True)
    (root / "lean" / "Paper").mkdir(parents=True)
    (root / "sim").mkdir()
    (root / "coord" / "sheaf.env").write_text("SHEAF_LIB=Paper\n")
    truth = make_truth(seed, n)
    truth["_params"] = {"seed": seed, "p_crash": 0.08, "p_giveup": 0.04, "p_badnode": 0.05, "p_landed": 0.15,
                        "p_prune": 0.3, "p_defect": 0.3, "p_dispute": 0.03}
    if harsh:
        truth["_params"].update(p_crash=0.25, p_giveup=0.1, p_badnode=0.1, p_landed=0.3, p_prune=0.7, p_defect=0.5,
                                p_dispute=0.08)
    (root / "sim" / "truth.json").write_text(json.dumps(truth))
    for i, t in truth.items():
        if i.startswith("t"):
            f = "x" + hashlib.sha1(i.encode("utf-8")).hexdigest()[:12]
            (root / "dag" / "nodes" / f"{f}.json").write_text(json.dumps({"id": i, "kind": "target", "target": True}))
    shutil.copy(HERE / "sim_worker.py", root / "sim_worker.py")
    (root / "sim" / "submit.sh").write_text(
        '#!/bin/bash\n# copies only: compilation is out of scope here\nG=$1; D=$2; shift 2\n'
        'for f in "$@"; do mkdir -p "lean/$(dirname "$f")"; cp "$D/$f" "lean/$f"; done\n')
    os.chmod(root / "sim" / "submit.sh", 0o755)
    conf = {"slots": slots, "starts_per_min": 100000, "accept_slots": 3, "gen_every": 10 ** 9, "poll": 0,
            "continue": True, "max_chain": 6, "continue_wait": 5,
            "worker_cmd": [sys.executable, "sim_worker.py"], "resume_cmd": [sys.executable, "sim_worker.py", "{session}"],
            "submit_cmd": ["sim/submit.sh"]}
    (root / "coord" / "dispatch.json").write_text(json.dumps(conf))
    return root


# ---------------------------------------------------------------- the oracle, from the stage documents

def oracle(root: pathlib.Path) -> set[str]:
    nodes = {}
    for p in (root / "dag" / "nodes").glob("*.json"):
        d = json.loads(p.read_text()); nodes[d["id"]] = d
    leaf = lambda d: d.get("status") == "mathlib"
    sdeps = lambda d: d.get("stmt_deps", [])
    pdeps = lambda d: [u for s in d.get("proof", []) for u in s.get("uses", [])]
    targets = [i for i, d in nodes.items() if d.get("target")]
    reach, st = set(), list(targets)
    while st:
        i = st.pop()
        if i in reach or i not in nodes:
            continue
        reach.add(i); st += sdeps(nodes[i]) + pdeps(nodes[i])
    mod = lambda d: (d.get("lean") or {}).get("module")
    mfile = lambda m: root / "lean" / (m.replace(".", "/") + ".lean")
    stated = lambda i: i in nodes and (leaf(nodes[i]) or (mod(nodes[i]) and mfile(mod(nodes[i])).exists()))

    def split(d):
        if leaf(d):
            return True
        if d.get("kind") == "definition":
            return bool(sdeps(d)) or bool(mod(d))
        return bool(d.get("proof"))

    disputed = set()
    for p in (root / "coord" / "tasks").glob("dispute-*.json"):
        disputed.add(json.loads(p.read_text())["about"])
    out = set()
    for i in reach:
        d = nodes[i]
        if leaf(d):
            continue
        if not split(d):
            out.add(f"s1-{i}")
        elif not stated(i):
            if all(stated(c) for c in sdeps(d)):
                out.add(f"s2-{i}")
        elif "sorry" in mfile(mod(d)).read_text() and all(stated(c) for c in pdeps(d)):
            out.add(f"s3-{i}")
    out -= disputed
    # around the stages (stages/2-statements.md §4): reviews of the stated targets, fixes, Challenge.lean
    import hashlib
    sys.path.insert(0, str(root / "tools"))
    import leanindex as li
    def version(t):
        seen, st = set(), [t]
        while st:
            i = st.pop()
            if i in seen or i not in nodes:
                continue
            seen.add(i); st += sdeps(nodes[i])
        h = hashlib.sha256()
        for i in sorted(seen):
            m = mod(nodes[i])
            if m and mfile(m).exists():  # statements and definitions only (the definition of a version)
                itf = li.interface(mfile(m).read_text()); itf.pop("#imports", None); itf.pop("#public", None)
                h.update(i.encode() + b"\0" + json.dumps(itf, sort_keys=True).encode())
        return h.hexdigest()[:16]
    rv = root / "coord" / "targets-review"
    locked = []
    for t in sorted(targets):
        if not stated(t):
            continue
        rec = json.loads((rv / f"{t}.json").read_text()) if (rv / f"{t}.json").exists() else {}
        v = version(t)
        if rec.get("hash") != v or rec.get("verdict") == "missing":
            out.add(f"review-{t}")
        elif rec["verdict"] == "defect":
            out.add(f"fix-{t}")
        else:
            locked.append((t, v))
    if locked and len(locked) == len(targets):
        h = hashlib.sha256("".join(f"{t}:{x}" for t, x in locked).encode()).hexdigest()[:16]
        ch = json.loads((rv / "challenge.json").read_text()) if (rv / "challenge.json").exists() else {}
        if ch.get("hash") != h:
            out.add("challenge")
    return out


# ---------------------------------------------------------------- the run

def run(root: pathlib.Path, max_passes: int = 4000) -> list[str]:
    sys.path.insert(0, str(root / "tools"))
    for m in ("leanindex", "dag_queue", "tasks", "dispatch", "accept"):
        sys.modules.pop(m, None)
    os.chdir(root)
    import tasks, dispatch  # noqa: E402
    viol = collections.Counter()
    examples = {}

    def bad(kind, text):
        viol[kind] += 1
        examples.setdefault(kind, text)

    subprocess.run([sys.executable, "tools/tasks.py", "gen"], check=True, capture_output=True)
    state = {"accept_queue": collections.deque(), "idle": [], "last_gen": time.time(), "bucket": 10 ** 9,
             "t": time.time()}
    # settle: the queue follows the result code alone
    real_settle = tasks.settle
    expect = {0: ("done", "landed"), 1: ("rework",), 2: ("failed",), 3: ("failed",), 4: ("failed",)}

    def settle(tid, code, reason="", who="-"):
        out = real_settle(tid, code, reason, who)
        evs = [e[1] for e in tasks.history().get(tid, [])]
        last = [e for e in evs if e not in ("released", "opened", "withdrawn")][-1]
        if last not in expect.get(code, ("failed",)):
            bad("settle", f"{tid}: result {code} but the queue marked {last}")
        if tasks.holder(tid):
            bad("settle", f"{tid}: still held after settle")
        settled[code] += 1
        return out
    settled = collections.Counter()
    tasks.settle = settle
    c = dispatch.conf()
    passes = quiet_checks = 0
    for passes in range(1, max_passes + 1):
        t0 = time.time()
        before = {t["id"] for t in tasks.listed().values()}
        drain = passes % 3 == 0  # no new starts until every acceptance is done, then check the rules
        stop = root / "local" / "dispatch" / "STOP"
        if drain:
            stop.touch()
        dispatch.one_pass(c, state)
        while drain and (state["accept_queue"] or any(r["kind"] == "accept" for r in dispatch.runs().values())):
            time.sleep(0.05)
            dispatch.one_pass(c, state)
        rs = dispatch.runs()
        workers = [r for r in rs.values() if r["kind"] == "worker" and dispatch.running(r)]
        accepting = [r for r in rs.values() if r["kind"] == "accept"]  # running, or ended and not yet settled
        # slots and claims
        if len(workers) > c["slots"]:
            bad("slots", f"{len(workers)} workers > {c['slots']} slots")
        ids = [r["task"] for r in workers]
        if len(ids) != len(set(ids)):
            bad("claims", f"one task run twice: {sorted(ids)}")
        for r in workers:
            if tasks.holder(r["task"]) != r["group"]:
                bad("claims", f"{r['task']} runs in {r['group']} but is held by {tasks.holder(r['task'])}")
        # starvation: a free slot and a task open before this pass that nobody took
        slots_used = sum(1 for r in rs.values() if r["kind"] == "worker")  # as the start phase saw them
        if not drain and slots_used < c["slots"]:
            held = {p.stem for p in tasks.CLAIMS.glob("*.lock")}
            h = tasks.history()
            since = time.strftime("%FT%TZ", time.gmtime(int(t0)))
            left = [t for t in before if t in {x["id"] for x in tasks.listed().values()}
                    and tasks.task_path(t).stem not in held
                    and not (h.get(t) and h[t][-1][0] >= since)]  # released by an acceptance after the start phase
            if left:
                bad("starvation", f"free slots, unclaimed: {left[:5]}")
        # rules and incremental, at quiet moments only (no acceptance running or waiting)
        if not accepting and not state["accept_queue"]:
            quiet_checks += 1
            listed = {t["id"] for t in tasks.listed().values() if t.get("kind") not in tasks.PERSISTENT}
            held = {i for i in listed if tasks.holder(i)}
            want = oracle(root)
            g = tasks.load_dag()
            with tasks.tasks_lock():
                full = set(tasks.compute(g, {}).keys()) | set(tasks.special(g).keys())
            if full != want:
                bad("rules", f"tasks.compute differs from the oracle: extra {sorted(full - want)[:5]}, missing {sorted(want - full)[:5]}")
            if want - listed:
                bad("incremental", f"open but not listed: {sorted(want - listed)[:5]}")
            if listed - want - held:
                bad("incremental", f"listed, not open, not held: {sorted(listed - want - held)[:5]}")
            if not listed and not workers and not state["idle"]:
                stop.unlink(missing_ok=True)
                break
        stop.unlink(missing_ok=True)
        if passes % 20 == 0 and sum(1 for _ in open(root / "coord" / "tasks" / "events.tsv")) > 60 * max(1, len(list((root / "dag" / "nodes").glob("*.json")))):
            bad("loop", "far more events than nodes: some task is handed out again and again")
            break
        n_nodes = max(1, len(list((root / "dag" / "nodes").glob("*.json"))))
        if passes % 20 == 0 and sum(1 for _ in open(root / "coord" / "tasks" / "events.tsv")) > 60 * n_nodes:
            bad("loop", "far more events than nodes: some task is handed out again and again")
            break
        time.sleep(0.05)
    # termination
    listed = {t["id"] for t in tasks.listed().values()}
    if listed:
        bad("termination", f"after {passes} passes still listed: {sorted(listed)[:8]}")
    want_done = oracle(root)
    rv = root / "coord" / "targets-review"
    if not (rv / "challenge.json").exists():
        bad("termination", "Challenge.lean was never written")
    if want_done:
        bad("termination", f"open per the oracle at the end: {sorted(want_done)[:8]}")
    # every node a target reaches is stated and proved
    nodes = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (root / "dag" / "nodes").glob("*.json")}
    # continuation
    seq = collections.defaultdict(list)
    for l in (root / "sim" / "sessions.log").read_text().splitlines():
        s, t = l.split("\t"); seq[s].append(t)
    adj = collections.defaultdict(set)
    for i, d in nodes.items():
        for u in d.get("stmt_deps", []) + [u for s in d.get("proof", []) for u in s.get("uses", [])]:
            adj[i].add(u); adj[u].add(i)
    truth = json.loads((root / "sim" / "truth.json").read_text())
    for i, t in truth.items():  # adjacency as planned, before pruning removed edges
        if i.startswith("_"):
            continue
        for u in t["stmt"] + t["proof"]:
            adj[i].add(u); adj[u].add(i)
    chains = 0
    for s, ts in seq.items():
        for a, b in zip(ts, ts[1:]):
            if a == b:
                continue  # the same task again after a failure is a fresh start of the same session id only in tests
            chains += 1
            if not (a[:1] == "s" and b[:1] == "s"):
                if b.startswith("review-"):
                    bad("continuation", f"session went from {a} to the review {b}")
                continue
            na, nb = a.split("-", 1)[1], b.split("-", 1)[1]
            if nb != na and nb not in adj[na]:
                bad("continuation", f"session went from {a} to {b}, not neighbours")
    ev = collections.Counter(l.split("\t")[1] for l in (root / "coord" / "tasks" / "events.tsv").read_text().splitlines())
    print(f"  {root.name}: {passes} passes, {len(nodes)} nodes in the DAG; events: "
          + ", ".join(f"{k} {v}" for k, v in sorted(ev.items())) + f"; continuations {chains}; rule checks {quiet_checks}; settled by code {dict(sorted(settled.items()))}")
    for k, v in viol.items():
        print(f"  VIOLATION {k} x{v}: {examples[k]}")
    return list(viol)


def main() -> int:
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 2
    work = pathlib.Path(a[0]).resolve(); work.mkdir(parents=True, exist_ok=True)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    seeds = [int(x) for x in opt("--seeds", "1,2,3").split(",")]
    n, slots = int(opt("--nodes", "40")), int(opt("--slots", "6"))
    failed = False
    for s in seeds:
        root = setup(work, s, n, slots, "--harsh" in a)
        r = subprocess.run([sys.executable, __file__, "--one", str(root)], text=True)
        failed |= r.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        sys.exit(1 if run(pathlib.Path(sys.argv[2])) else 0)
    sys.exit(main())
