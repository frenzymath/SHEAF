#!/usr/bin/env python3
"""Tasks: one file per piece of work that is open now, in every stage at once.

Usage:
  tools/tasks.py gen                      compute the open items of all three stages and bring coord/tasks/ up to date
  tools/tasks.py refresh <node>...        the same after an event on these nodes: for them, the nodes that use them, and
                                          every node whose reachability from a target the event changed
  tools/tasks.py add <id> <stage> <instructions> [--node N] [--module M] [--files F,...]
                                          a task of the main agent's own: what code does not produce (a review of the
                                          target statements, Challenge.lean); --files lists the
                                          files outside the library the worker may deliver, relative to the project
  tools/tasks.py settle <id> <code> [reason]  what happens to a task after its worker ended (tools/dispatch.py):
                                          the code is tools/accept.py's, or 4 when the worker left no delivery
  tools/tasks.py mark <event> <id> [note] record an event: delivered, done, landed, rework, failed, released
  tools/tasks.py claim <id> <who>         claim a listed task (atomic); exit 1 if someone holds it
  tools/tasks.py release <id> [note]      give a claim back
  tools/tasks.py list [--open]            the listed tasks in order: id, stage, kind, state, holder
  tools/tasks.py show <id>                the task file, its events and its notes
  tools/tasks.py summary                  counts per stage and state
  tools/tasks.py report                   write coord/queue.md, the readable view

A task is the file coord/tasks/<id>.json. It names the item and its stage, says why the item is open and what the
worker may change, and lists the neighbouring nodes a worker may continue into; the worker needs nothing else
(roles/worker.md). The id is `s<stage>-<node id>`, or `s3-<module>` for a module no node names. The file is written
when the item opens and is not rewritten while the task is claimed.

What is open follows from each node's own state, never from a calendar, so the three stages run at once:

  stage 1  a node a target reaches that is not split yet; nearest to a target first.
  stage 2  a node stage 1 is finished with, that is not in Mathlib, has no landed Lean declaration, and every node
           its statement uses is in Mathlib or has a landed declaration; nearest to Mathlib first. With
           SHEAF_EARLY_REVIEW=1 and no coord/targets-confirmed, only the nodes needed to state the targets, and no
           stage 3 (stages/2-statements.md §2).
  stage 3  a module with `sorry` that a target reaches, through the DAG or through the imports of
           lean/TargetsCheck.lean, and every node its proof uses is stated; repairs and disputed statements first,
           then nearest to a target.

Besides the items of the three stages, the code opens tasks for the work around them, before all others:

  target-review  review-<target>: a target's statement is in the library and has no review for its present version,
                 the target module and the modules of every node its statement uses (stages/2-statements.md §4);
  target-fix     fix-<target>: the review of the present version found a defect;
  challenge      challenge: every target is reviewed without defect, and lean/Challenge.lean was not written for
                 these versions; lean/TargetsCheck.lean, which imports the target modules, is written by the code;
  dispute        dispute-<task>: a worker delivered `disputed`; the disputed task is withdrawn until it is done;
  diagnose       diagnose-<task>-<n>: a task failed n = 5, 10, 20, 40 times.
The first three follow from the state like the stage items; the last two are opened by the event and stay until
done. Tasks the main agent adds (`add`, kind `custom`) also stay until done.

A node is stated when the DAG records its module and the module's file exists in the library: a node that records a
module that was never landed is still an item of stage 2.

Computing and writing the tasks, and marking an event, each hold coord/tasks/.lock, so that two acceptances
refreshing at once never write back a task that the other has just finished.

State is kept apart from the task file:
  coord/tasks/events.tsv        one line per event (time, event, id, who, note); the last event is the state
  coord/tasks/claims/<id>.lock  who works on the task now
  coord/tasks/notes/<id>.md     what earlier attempts left: errors of a failed acceptance, the report of a give-up
  coord/tasks/done/             tasks that are finished; withdrawn/: tasks whose item closed without being done
Every listed task that nobody holds is handed out: no check refuses it (tools/dispatch.py).
"""
from __future__ import annotations
import collections, contextlib, fcntl, hashlib, json, os, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402
import dag_queue as dq  # noqa: E402

COORD = li.ROOT / "coord"
TD = COORD / "tasks"
DONE, WITHDRAWN, CLAIMS, NOTES = TD / "done", TD / "withdrawn", TD / "claims", TD / "notes"
EVENTS = TD / "events.tsv"
CACHE = li.ROOT / "local" / "tasks-imports.json"   # import distances of the last full gen
REACH = li.ROOT / "local" / "tasks-reach.json"     # the nodes a target reached at the last computation
STAGE_NAMES = {1: "stages/1-dag.md", 2: "stages/2-statements.md", 3: "stages/3-proving-and-pruning.md"}
FAIL_ALERTS = (5, 10, 20, 40)
PERSISTENT = {"custom", "dispute", "diagnose"}          # opened by an event or by the main agent; stay until done
SPECIAL = {"target-review", "target-fix", "challenge"}  # follow from the state, recomputed on every refresh
REVIEWS = COORD / "targets-review"


def now() -> str:
    return time.strftime("%FT%TZ", time.gmtime())


def safe(s: str) -> str:
    """A file name for an id, the same on every system: letters, digits, `.`, `-`, `_` are kept, `/` becomes `__`,
    anything else `~xx` by its UTF-8 bytes; a name longer than 150 characters is cut and ends with a hash of the id."""
    out = []
    for ch in s.replace("/", "__"):
        if ch.isascii() and (ch.isalnum() or ch in "._-"):
            out.append(ch)
        else:
            out.append("".join(f"~{b:02x}" for b in ch.encode("utf-8")))
    name = "".join(out)
    if name.startswith("."):
        name = "~2e" + name[1:]
    if len(name) > 150:
        name = name[:133] + "~" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
    return name


def dirs():
    for d in (TD, DONE, WITHDRAWN, CLAIMS, NOTES):
        d.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def tasks_lock():
    """Computing what is open and writing it, and marking an event, are one step each: an acceptance that refreshes
    from an older reading of the DAG must not write back a task another one has just finished."""
    dirs()
    with open(TD / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_json(p: pathlib.Path, d: dict):
    tmp = p.with_name(f".{p.name}.{os.getpid()}")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, p)


def read_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def task_path(tid: str) -> pathlib.Path:
    return TD / f"{safe(tid)}.json"


def listed() -> dict[str, dict]:
    out = {}
    for p in TD.glob("*.json"):
        d = read_json(p)
        if d and "id" in d:
            out[d["id"]] = d
    return out


# ---------------------------------------------------------------- events and claims

def event(ev: str, tid: str, who: str = "-", note: str = ""):
    dirs()
    line = "\t".join((now(), ev, tid, who, " ".join(note.split()))) + "\n"
    with open(EVENTS, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)


def history() -> dict[str, list[tuple[str, str, str, str]]]:
    h = collections.defaultdict(list)
    if EVENTS.exists():
        for l in EVENTS.read_text().splitlines():
            p = l.split("\t")
            if len(p) >= 4:
                h[p[2]].append((p[0], p[1], p[3], p[4] if len(p) > 4 else ""))
    return h


FAILS = TD / "fails"


def fail_count(tid: str, add: int = 0, reset: bool = False) -> int:
    """failed and rework events since the last done, kept per task so that nothing reads the whole event log."""
    FAILS.mkdir(parents=True, exist_ok=True)
    p = FAILS / safe(tid)
    try:
        n = int(p.read_text())
    except (FileNotFoundError, ValueError):
        n = 0
    n = 0 if reset else n + add
    p.write_text(str(n))
    return n


def failures(evs) -> int:
    """failed and rework events since the last done."""
    n = 0
    for _, e, _, _ in evs:
        if e == "done":
            n = 0
        elif e in ("failed", "rework"):
            n += 1
    return n


def lock(tid): return CLAIMS / f"{safe(tid)}.lock"


def holder(tid):
    d = read_json(lock(tid))
    return d.get("who") if d else None


def claim(tid: str, who: str) -> bool:
    """Any listed task that nobody holds is granted; nothing else is checked."""
    dirs()
    if not task_path(tid).exists():
        return False
    try:
        fd = os.open(lock(tid), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"who": who, "since": now(), "t": time.time()}))
    event("claimed", tid, who)
    return True


def release(tid: str, note: str = ""):
    who = holder(tid) or "-"
    lock(tid).unlink(missing_ok=True)
    event("released", tid, who, note)


def add_note(tid: str, text: str):
    dirs()
    with open(NOTES / f"{safe(tid)}.md", "a") as f:
        f.write(f"\n## {now()}\n\n{text.rstrip()}\n")


def alert(text: str):
    """A line for the main agent: coord/attention.md is what code cannot decide."""
    with open(COORD / "attention.md", "a") as f:
        f.write(f"- {now()} {text}\n")


def mark(ev: str, tid: str, note: str = "", who: str = "-"):
    """Mark the task at the event. done moves the task file to done/; rework and failed keep it listed, so it is
    handed out again, with the note for the next worker; landed (stage 3, `sorry` left) keeps it listed."""
    with tasks_lock():
        _mark(ev, tid, note, who)


def _mark(ev: str, tid: str, note: str, who: str):
    event(ev, tid, who, note)
    p = task_path(tid)
    if ev == "done" and p.exists():
        os.replace(p, DONE / p.name)
    if ev in ("rework", "failed") and note:
        add_note(tid, f"{ev}: {note}")
    if ev == "done":
        fail_count(tid, reset=True)
    if ev in ("rework", "failed"):
        n = fail_count(tid, add=1)
        t = read_json(p)
        if n in FAIL_ALERTS and t and t.get("kind") not in ("diagnose",):
            open_event_task(f"diagnose-{tid}-{n}", "diagnose", t.get("stage", 1), t, (
                f"Task {tid} has failed {n} times. Read its task file and its notes, coord/tasks/notes/{safe(tid)}.md, "
                f"and find why. If the cause is in the DAG, a statement or the Lean code (a node too large to split in "
                f"one step, a statement that is false or too weak for its users, a definition that is hard to use), "
                f"repair it as the stage documents say and deliver the repair. If the cause is outside, in the "
                f"worker command, the agents' API limits, a login, the tools or the machine, change nothing and say "
                f"what you found in the report: it goes to the main agent."))


SETTLE = {0: "accepted", 1: "refused", 2: "gave up", 3: "disputed", 4: "no delivery"}


def open_event_task(tid: str, kind: str, stage: int, about: dict, text: str):
    """A task opened by an event (a dispute, repeated failures); it stays listed until done."""
    if task_path(tid).exists() or (DONE / task_path(tid).name).exists():
        return
    t = {"id": tid, "stage": stage, "kind": kind, "node": about.get("node"), "module": about.get("module"),
         "about": about.get("id"), "priority": [0, 1, 0], "stage_document": STAGE_NAMES[stage], "instructions": text,
         "files": [], "neighbours": about.get("neighbours", {"uses": [], "used_by": []}), "inputs_hash": "",
         "generated": now(), "may_change": ["what the instructions name"]}
    write_json(task_path(tid), t)
    event("opened", tid, "-", f"{kind} of {about.get('id')}")


def settle(tid: str, code: int, reason: str = "", who: str = "-"):
    """The queue after a worker ended, from the result alone: accepted is done, or landed in stage 3 while `sorry` is
    left; anything else returns the task, with the reason in its notes for the next worker. The claim is released,
    and what the result may have opened or closed is computed again: the item, the nodes and modules delivered, and
    every node whose reachability changed."""
    with tasks_lock():
        t = read_json(task_path(tid)) or {}
        dv = read_json(COORD / "deliveries" / f"{safe(tid)}.json") or {}
        touched = {x for x in (t.get("node"), t.get("module")) if x}
        if code == 0:
            for rel in dv.get("nodes", []):
                d = read_json(dq.nodes_dir() / rel)
                if d and dq.field(d, "id"):
                    touched.add(str(dq.field(d, "id")))
            touched |= {f[:-5].replace("/", ".") for f in dv.get("lean", []) if f.endswith(".lean")}
            left = 0
            if t.get("kind") in ("prove", "repair", "disputed") and t.get("module") and li.file_of(t["module"]).is_file():
                left = li.sorry_count(li.file_of(t["module"]).read_text(errors="ignore"))
            if t.get("kind") == "target-review":
                record_review(t, dv)
            if t.get("kind") == "challenge":
                write_json(REVIEWS / "challenge.json", {"hash": t.get("inputs_hash"), "at": now()})
            if t.get("kind") == "diagnose":
                alert(f"diagnosis of {t.get('about')} ({tid}): {str(dv.get('report', ''))[:600]}")
            if t.get("kind") == "dispute" and t.get("about"):
                touched.add(t.get("about"))
            _mark("landed" if left else "done", tid, f"{left} sorry left" if left else "", who)
        elif code == 1:
            _mark("rework", tid, reason, who)
        else:
            _mark("failed", tid, f"{SETTLE.get(code, f'acceptance error {code}')}: {reason}", who)
            if code == 3 and t:
                add_note(tid, f"report of the worker (disputed):\n\n{dv.get('report', '')}")
                open_event_task(f"dispute-{tid}", "dispute", 3, t, (
                    f"A worker on task {tid} found its statement false or not provable as stated; its report is in "
                    f"coord/tasks/notes/{safe(tid)}.md. Look for a counterexample, find the correct statement, and "
                    f"change it as stages/3-proving-and-pruning.md §3 says, with every module adapted to it. If the "
                    f"statement is right after all, change nothing and say why in the report. Task {tid} waits "
                    f"until this one is done."))
        if holder(tid):
            lock(tid).unlink(missing_ok=True)
            event("released", tid, who, f"after {SETTLE.get(code, code)}")
        return _refresh(sorted(touched)) if touched else (0, 0, 0)


# ---------------------------------------------------------------- what is open

class Dag(dq.Dag):
    """The DAG with `stated` meaning: in Mathlib, or the recorded module exists in the library."""

    def stated(self, i: str) -> bool:
        d = self.live.get(i)
        if d is None or dq.is_leaf(d):
            return True
        m = dq.module_of(d)
        return bool(m) and li.file_of(m).is_file()

    def users(self) -> dict[str, set[str]]:
        u = collections.defaultdict(set)
        for j in self.live:
            for c in self.deps(j, "all"):
                u[c].add(j)
        return u


def node_hash(d: dict, module: str | None) -> str:
    h = hashlib.sha256(json.dumps(d, sort_keys=True).encode())
    if module and li.file_of(module).is_file():
        h.update(li.file_of(module).read_bytes())
    return h.hexdigest()[:16]


def dep_state(g: Dag, c: str) -> dict:
    d = g.live.get(c)
    if d is None:
        return {"node": c, "state": "missing"}
    if dq.is_leaf(d):
        return {"node": c, "state": "mathlib", "mathlib": dq.field(d, "mathlib")}
    m = dq.module_of(d)
    lean = dq.field(d, "lean")
    decl = lean.get("declaration") if isinstance(lean, dict) else None
    return {"node": c, "state": "stated" if g.stated(c) else "not stated", "module": m, "declaration": decl}


def import_distances(full: bool) -> dict[str, int]:
    """Import distance from lean/TargetsCheck.lean of every module it reaches; cached by the last full gen."""
    if not full:
        try:
            return json.loads(CACHE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    if not li.LEAN.is_dir():
        return {}
    _, imports = li.scan()
    dist, q = {}, collections.deque()
    for r in sorted(imports.get("TargetsCheck", set())):
        dist[r] = 0; q.append(r)
    while q:
        x = q.popleft()
        for i in imports.get(x, ()):
            if i in imports and i not in dist:
                dist[i] = dist[x] + 1; q.append(i)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(dist))
    return dist


def repairs() -> set[str]:
    rp = COORD / "repairs.txt"
    if not rp.exists():
        return set()
    return {l.split()[0] for l in rp.read_text().splitlines() if l.strip() and not l.startswith("#")}


def compute(g: Dag, idist: dict[str, int], only: set[str] | None = None) -> dict[str, dict]:
    """The open tasks; with `only`, those of these nodes (and their modules) alone."""
    out = {}
    users = g.users()
    by_module = {dq.module_of(d): i for i, d in g.live.items() if dq.module_of(d)}
    early = li.config().get("SHEAF_EARLY_REVIEW", "") not in ("", "0", "no")
    tsc = g.target_statement_closure() if early else set()
    hold = early and not (COORD / "targets-confirmed").exists()   # stages/2-statements.md §2

    def nb(i):
        return {"uses": sorted(set(g.deps(i, "all"))), "used_by": sorted(users.get(i, ()))}

    def base(stage, i, kind, prio, module=None):
        d = g.live.get(i, {}) if i else {}
        tid = f"s{stage}-{i}" if i else f"s3-{module}"
        return tid, {
            "id": tid, "stage": stage, "kind": kind, "node": i, "module": module,
            "node_file": str(d.get("_path", "")) or None,
            "priority": prio, "stage_document": STAGE_NAMES[stage],
            "neighbours": nb(i) if i else {"uses": [], "used_by": []},
            "inputs_hash": node_hash(d, module),
        }

    waiting = {t.get("about") for t in listed().values() if t.get("kind") == "dispute"}

    for i, d in g.live.items():
        if only is not None and i not in only:
            continue
        if i not in g.dist or dq.is_leaf(d):
            continue
        if not dq.unfolded(d):
            tid, t = base(1, i, "split", [1, g.dist[i]])
            if tid in waiting:
                continue
            t["may_change"] = ["this node", "new nodes it needs"]
            out[tid] = t
            continue
        if not g.stated(i):
            sd = g.deps(i, "stmt")
            if all(g.stated(c) for c in sd) and not (hold and i not in tsc):
                kind = "target-statement" if i in tsc else "state"
                tid, t = base(2, i, kind, [0 if kind == "target-statement" else 2, g.h(i)])
                if tid in waiting:
                    continue
                t["opened_because"] = {"statement_deps": [dep_state(g, c) for c in sd]}
                t["may_change"] = ["this node", "a new module for this node", "new nodes and modules for lemmas"]
                out[tid] = t
            continue

    # stage 3: modules with sorry that a target reaches
    if hold:
        return out
    rp = repairs()
    cand: dict[str, int] = {}
    for i in g.dist:
        d = g.live.get(i)
        m = dq.module_of(d) if d else None
        if m and g.stated(i):
            cand[m] = g.dist[i]
    for m, k in idist.items():
        cand[m] = min(k, cand.get(m, k))
    for m, k in cand.items():
        i = by_module.get(m)
        if only is not None and i not in only and m not in only:
            continue
        p = li.file_of(m)
        if not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        n = li.sorry_count(text)
        if n == 0:
            continue
        kind = "repair" if m in rp else "disputed" if "STATEMENT-DISPUTED" in text else "prove"
        pd = g.deps(i, "proof") if i else []
        if kind == "prove" and not all(g.stated(c) for c in pd):
            continue
        tid, t = base(3, i, kind, [3, ("repair", "disputed", "prove").index(kind), k], module=m)
        if tid in waiting:
            continue
        t["sorry"] = n
        t["opened_because"] = {"proof_deps": [dep_state(g, c) for c in pd]}
        t["may_change"] = [f"module {m}", "this node", "new nodes and modules for lemmas",
                           "a statement or definition others use, with every module adapted to it (stages/3 §3)"]
        out[tid] = t
    return out


def statement_hash(g: Dag, t: str) -> str:
    """The version of a target's statement: what its module and the module of every node its statement uses show to
    others (leanindex.interface: statements and definitions, not proofs, comments or imports)."""
    seen, st = set(), [t]
    while st:
        i = st.pop()
        if i in seen or i not in g.live:
            continue
        seen.add(i); st += g.deps(i, "stmt")
    h = hashlib.sha256()
    for i in sorted(seen):
        m = dq.module_of(g.live[i])
        if m and li.file_of(m).is_file():
            itf = li.interface(li.file_of(m).read_text(errors="ignore"))
            itf.pop("#imports", None); itf.pop("#public", None)
            h.update(i.encode() + b"\0" + json.dumps(itf, sort_keys=True).encode())
    return h.hexdigest()[:16]


def review_of(t: str) -> dict:
    return read_json(REVIEWS / f"{safe(t)}.json") or {}


def record_review(task: dict, dv: dict):
    """The verdict of an accepted review, for the version of the statement it was opened for."""
    t = task.get("node")
    text = (li.ROOT / "coord" / "targets-review" / f"{safe(t)}.md").read_text(errors="ignore") \
        if (REVIEWS / f"{safe(t)}.md").exists() else ""
    verdict = "defect" if "Verdict: defect" in text else "locked" if "Verdict: locked" in text else "missing"
    write_json(REVIEWS / f"{safe(t)}.json", {"hash": task.get("inputs_hash"), "verdict": verdict, "at": now()})


def special(g: Dag) -> dict[str, dict]:
    """The tasks around the stage items that follow from the state: reviews of the target statements, their fixes,
    Challenge.lean. Also writes lean/TargetsCheck.lean when the stated targets change."""
    out = {}
    stated = [t for t in sorted(g.targets) if not dq.is_leaf(g.live[t]) and g.stated(t)]
    mods = sorted({dq.module_of(g.live[t]) for t in stated})
    if mods and li.LEAN.is_dir():
        tc = li.LEAN / "TargetsCheck.lean"
        text = "".join(f"import {m}\n" for m in mods)
        if not tc.exists() or tc.read_text() != text:
            tc.write_text(text)
    REVIEWS.mkdir(parents=True, exist_ok=True)

    def task(tid, kind, stage, node, text, files, h):
        d = g.live.get(node, {}) if node else {}
        return {"id": tid, "stage": stage, "kind": kind, "node": node,
                "module": dq.module_of(d) if d else None, "priority": [0, 0, 0],
                "stage_document": STAGE_NAMES[stage], "instructions": text, "files": files,
                "neighbours": {"uses": sorted(set(g.deps(node, "stmt"))) if node else [], "used_by": []},
                "inputs_hash": h, "may_change": ["what the instructions name"]}

    locked = []
    for t in stated:
        h = statement_hash(g, t)
        r = review_of(t)
        if r.get("hash") != h or r.get("verdict") == "missing":
            out[f"review-{t}"] = task(
                f"review-{t}", "target-review", 2, t,
                f"Review the Lean statement of target {t} against the paper, as stages/2-statements.md §4 says, "
                f"and write the review to coord/targets-review/{safe(t)}.md. Its last line is `Verdict: locked` if "
                f"you find no defect, `Verdict: defect` otherwise. You did not write this statement; change nothing "
                f"else.", [f"coord/targets-review/{safe(t)}.md"], h)
        elif r.get("verdict") == "defect":
            out[f"fix-{t}"] = task(
                f"fix-{t}", "target-fix", 3, t,
                f"The review in coord/targets-review/{safe(t)}.md found a defect in the statement of target {t} or in "
                f"a definition it uses. Repair it as stages/3-proving-and-pruning.md §3 says, so that the statement "
                f"says exactly what the paper says; never weaken it. The repaired statement is reviewed again.",
                [], h)
        else:
            locked.append((t, h))
    if stated and len(locked) == len(g.targets):
        h = hashlib.sha256("".join(f"{t}:{x}" for t, x in locked).encode()).hexdigest()[:16]
        if (read_json(REVIEWS / "challenge.json") or {}).get("hash") != h:
            out["challenge"] = task(
                "challenge", "challenge", 2, None,
                "Write lean/Challenge.lean as stages/2-statements.md §4 says: the reviewed target statements, "
                "verbatim, with `sorry` proofs, importing only the modules that define what they use.",
                ["lean/Challenge.lean"], h)
    return out


def load_dag() -> Dag:
    nodes = {}
    base = dq.nodes_dir()
    for p in sorted(base.rglob("*.json")):
        d = read_json(p)
        if isinstance(d, dict) and dq.field(d, "id"):
            i = str(dq.field(d, "id"))
            if any(c in i for c in "\t\n\r"):
                alert(f"node {p.relative_to(base)} has an id with a tab or a line break; it is left out until renamed")
                continue
            d["_path"] = str(p.relative_to(base))
            nodes[i] = d
    return Dag(nodes)


def sync(open_now: dict[str, dict], scope: set[str] | None):
    """Write new tasks, rewrite unclaimed ones whose inputs changed, withdraw unclaimed ones that closed.
    With a scope, only tasks of those nodes/modules are withdrawn."""
    dirs()
    have = listed()
    new = changed = gone = 0
    for tid, t in open_now.items():
        old = have.get(tid)
        if old is None:
            t["generated"] = now(); write_json(task_path(tid), t); event("opened", tid); new += 1
        elif holder(tid) is None and old.get("inputs_hash") != t["inputs_hash"]:
            t["generated"] = now(); write_json(task_path(tid), t); changed += 1
    for tid, t in have.items():
        if tid in open_now or holder(tid) is not None or t.get("kind") in PERSISTENT:
            continue
        if scope is not None and t.get("kind") not in SPECIAL and t.get("node") not in scope \
                and t.get("module") not in scope and tid not in scope:
            continue
        os.replace(task_path(tid), WITHDRAWN / task_path(tid).name)
        event("withdrawn", tid, "-", "no longer open"); gone += 1
    return new, changed, gone


def gen():
    with tasks_lock():
        g = load_dag()
        t = compute(g, import_distances(full=True))
        t.update(special(g))
        new, changed, gone = sync(t, None)
        save_reach(g)
    report(g)
    print(f"{len(t)} open tasks: {new} new, {changed} rewritten, {gone} withdrawn")


def refresh(nodes: list[str]):
    """After an event on these nodes: they and the nodes that use them are the only ones whose state can change."""
    with tasks_lock():
        return _refresh(nodes)


def save_reach(g: Dag):
    REACH.parent.mkdir(exist_ok=True)
    tmp = REACH.with_name(f".{REACH.name}.{os.getpid()}")
    tmp.write_text(json.dumps(sorted(g.dist)))
    os.replace(tmp, REACH)


def _refresh(nodes: list[str]):
    g = load_dag()
    users = g.users()
    scope = set()
    for i in nodes:
        i = g.resolve(i)
        scope.add(i)
        scope |= users.get(i, set())
    # a delivery that drops a dependency can cut off a whole subtree, one that adds one can bring a subtree back:
    # every node whose reachability from a target changed is in scope as well
    try:
        before = set(json.loads(REACH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        before = None
    if before is None:
        scope |= set(g.live)
    else:
        scope |= before ^ set(g.dist)
    save_reach(g)
    scope |= {dq.module_of(g.live[i]) for i in list(scope) if i in g.live and dq.module_of(g.live[i])}
    t = compute(g, import_distances(full=False), only=scope)
    t.update(special(g))
    return sync(t, scope)


def ordered() -> list[dict]:
    return sorted(listed().values(), key=lambda t: (t["priority"], t["id"]))


def state_of(tid: str, h) -> str:
    if holder(tid):
        return "claimed"
    evs = h.get(tid, [])
    return evs[-1][1] if evs else "opened"


def report(g: Dag | None = None):
    h = history()
    ts = ordered()
    by = collections.Counter((t["stage"], state_of(t["id"], h)) for t in ts)
    with open(COORD / "queue.md", "w") as f:
        f.write(f"# Tasks\n\nWritten by `tools/tasks.py` at {now()}. {len(ts)} listed.\n\n")
        f.write("| stage | open | claimed | rework/failed |\n|---|---|---|---|\n")
        for s in (1, 2, 3):
            f.write(f"| {s} | {sum(v for (st, k), v in by.items() if st == s and k not in ('claimed', 'rework', 'failed'))} "
                    f"| {by[(s, 'claimed')]} | {by[(s, 'rework')] + by[(s, 'failed')]} |\n")
        f.write("\n| task | kind | state | holder | failures |\n|---|---|---|---|---|\n")
        for t in ts:
            f.write(f"| `{t['id']}` | {t['kind']} | {state_of(t['id'], h)} | {holder(t['id']) or ''} | {failures(h.get(t['id'], []))} |\n")


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    li.ensure_utf8()
    cmd = a[0]
    if cmd == "gen":
        gen()
    elif cmd == "refresh":
        new, changed, gone = refresh(a[1:])
        print(f"refresh of {len(a) - 1} node(s): {new} new, {changed} rewritten, {gone} withdrawn")
    elif cmd == "add":
        dirs()
        tid, stage, text = a[1], int(a[2]), a[3]
        opt = lambda k: a[a.index(k) + 1] if k in a else None
        if task_path(tid).exists():
            print(f"{tid} is listed already"); return 1
        t = {"id": tid, "stage": stage, "kind": "custom", "node": opt("--node"), "module": opt("--module"),
             "priority": [0, 0, 0], "stage_document": STAGE_NAMES[stage], "instructions": text,
             "files": [f for f in (opt("--files") or "").split(",") if f],
             "neighbours": {"uses": [], "used_by": []}, "inputs_hash": "", "generated": now(),
             "may_change": ["what the instructions name"]}
        write_json(task_path(tid), t); event("opened", tid, "main", text[:200]); print(tid)
    elif cmd == "settle":
        print(settle(a[1], int(a[2]), " ".join(a[3:])))
    elif cmd == "mark":
        mark(a[1], a[2], " ".join(a[3:]))
    elif cmd == "claim":
        if not claim(a[1], a[2]):
            print(f"not granted: {'not listed' if not task_path(a[1]).exists() else 'held by ' + str(holder(a[1]))}")
            return 1
        print(a[1])
    elif cmd == "release":
        release(a[1], " ".join(a[2:]))
    elif cmd == "list":
        h = history()
        for t in ordered():
            s = state_of(t["id"], h)
            if "--open" in a and s == "claimed":
                continue
            print(f"{t['id']}\t{t['stage']}\t{t['kind']}\t{s}\t{holder(t['id']) or '-'}")
    elif cmd == "show":
        p = task_path(a[1])
        for q in (p, DONE / p.name, WITHDRAWN / p.name):
            if q.exists():
                print(q.read_text()); break
        for e in history().get(a[1], []):
            print("\t".join(e))
        n = NOTES / f"{safe(a[1])}.md"
        if n.exists():
            print(n.read_text())
    elif cmd == "summary":
        h = history()
        c = collections.Counter((t["stage"], state_of(t["id"], h)) for t in listed().values())
        for s in (1, 2, 3):
            print(f"stage {s}: " + ", ".join(f"{k} {v}" for (st, k), v in sorted(c.items()) if st == s))
        print(f"done {len(list(DONE.glob('*.json')))}, withdrawn {len(list(WITHDRAWN.glob('*.json')))}")
    elif cmd == "report":
        report()
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
