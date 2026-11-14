#!/usr/bin/env python3
"""The dispatcher: hands every listed task to a worker, whatever its stage, and accepts what comes back.

Usage:
  tools/dispatch.py run        the loop; one per project (it holds local/dispatch/dispatcher.lock), kept alive by
                               tools/keepalive.py
  tools/dispatch.py status     the running workers and acceptances, the high-risk ones marked
  tools/dispatch.py stop <run> stop one worker (its process group), on the decision of the main agent or the human;
                               its task then counts as left without a delivery
  tools/dispatch.py once       one pass of the loop, for testing

Settings, coord/dispatch.json, read again on every pass, so that the main agent changes them while it runs:

  slots             workers at once, over all stages together
  starts_per_min    at most this many worker starts per minute (the agents' API limits)
  accept_slots      acceptances at once (each may compile)
  gen_every         seconds between two full `tasks.py gen`; between them, tasks open at the events
  continue          true: a worker that delivered goes on with an open task next to its item, in the same session
  max_chain         at most this many tasks in one session
  continue_wait     seconds a session that delivered waits for a task next to its item; most such tasks open only
                    when its delivery is accepted
  worker_cmd        the command that starts a worker, a list; {prompt} {root} {group} are replaced
  resume_cmd        the command that gives a running session its next task; adds {session}; empty: never resume
  session_regex     how to find the session id in the worker's output, for resume_cmd
  risk_hours        a worker running longer than this is marked high-risk
  risk_idle_minutes a worker whose log has not grown for this long is marked high-risk

One pass:
  1. Reap. A worker that has exited either wrote coord/deliveries/<id>.json, and the task is marked delivered and
     goes to acceptance (tools/accept.py), or it did not, and tasks.py settle returns the task.
     A worker that delivered and may continue waits, without a slot, for an open task next to its item: one its item
     uses or that uses it, or the next stage of its item, which opens when the delivery is accepted.
  2. Accept, up to accept_slots at once. tools/accept.py answers only accepted or not, by its exit code; when it
     ends, tasks.py settle handles the task from that code: done, or back to the list with the reason, and the
     tasks the result opens or closes.
  3. Start. First the waiting sessions that have a task next to their item, in the same session, so that the worker
     keeps its context; once its own delivery is accepted and nothing next to it is open, a session stops waiting.
     Then every listed task that nobody holds is handed out, in task order, as long as slots and the start limit
     allow: no other check. A task none of whose neighbours is held comes first, since the worker of a held
     neighbour may continue into it.
The stage of a task decides only the documents named in the worker's prompt (tools/worker_prompt.md).

High-risk workers, running very long or with a log that has stopped growing, are marked in `status` and reported
once each in coord/attention.md; the code never stops a worker on its own. Many workers that end right after their
start are most often the agents' API limits (HTTP 429) or an expired login: read their logs in local/dispatch/logs/.
The workers run in their own process groups: stopping the dispatcher does not stop them, and a dispatcher started
again adopts them from local/dispatch/runs/. local/dispatch/STOP: start nothing new; the rest goes on.
"""
from __future__ import annotations
import collections, json, os, pathlib, re, shutil, signal, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402
import tasks  # noqa: E402

T = pathlib.Path(__file__).resolve().parent
ROOT = li.ROOT
D = ROOT / "local" / "dispatch"
RUNS, LOGS = D / "runs", D / "logs"
CONF = ROOT / "coord" / "dispatch.json"
DELIV = ROOT / "coord" / "deliveries"
DEFAULTS = {
    "slots": 4, "starts_per_min": 60, "accept_slots": 2, "gen_every": 600, "poll": 5,
    "continue": True, "max_chain": 20, "continue_wait": 600,
    "worker_cmd": ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox", "-C", "{root}", "{prompt}"],
    "resume_cmd": ["codex", "exec", "resume", "--json", "--dangerously-bypass-approvals-and-sandbox", "{session}", "{prompt}"],
    "session_regex": "\"thread_id\"\\s*:\\s*\"([^\"]+)\"",
    "risk_hours": 3, "risk_idle_minutes": 30,
}


def conf() -> dict:
    c = dict(DEFAULTS)
    try:
        c.update(json.loads(CONF.read_text()))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if not isinstance(e, FileNotFoundError):
            tasks.alert(f"coord/dispatch.json is not valid JSON ({e}); using the defaults")
    return c


def alive(pid: int) -> bool:
    """Whether a process runs. For a child of this dispatcher use running(), which keeps its exit code."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # an exited child not yet waited for is a zombie: it does not run (Linux; elsewhere it counts as running)
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ")[-1][:1] != "Z"
    except OSError:
        return True


PROCS: dict = {}   # run -> its subprocess.Popen, for the runs this dispatcher started


def running(r: dict) -> bool:
    """Whether a run still runs. A run this dispatcher started is asked through its process object, which waits for
    it when it ends and keeps its exit code; a run adopted after a restart is looked up by its pid."""
    pr = PROCS.get(r["run"])
    return pr.poll() is None if pr is not None else alive(r["pid"])


def runs() -> dict[str, dict]:
    RUNS.mkdir(parents=True, exist_ok=True)
    return {p.stem: d for p in RUNS.glob("*.json") if (d := tasks.read_json(p))}


def save(r: dict):
    tasks.write_json(RUNS / f"{r['run']}.json", r)


def drop(r: dict):
    (RUNS / f"{r['run']}.json").unlink(missing_ok=True)


def prompt(task: dict, group: str, first: bool) -> str:
    tpl = (T / "worker_prompt.md").read_text()
    stem = tasks.task_path(task["id"]).stem
    notes = tasks.NOTES / f"{stem}.md"
    part = tpl.split("<!-- next -->")
    text = part[0] if first or len(part) == 1 else part[1]
    vals = dict(
        task_file=f"coord/tasks/{stem}.json", task_id=task["id"], stage=str(task["stage"]),
        stage_document=task["stage_document"], group=group,
        sandbox=f"lean/.sandbox/{group}/{stem}", delivery=f"coord/deliveries/{stem}.json",
        notes=(f"Earlier attempts left notes in coord/tasks/notes/{stem}.md: read them first."
               if notes.exists() else ""))
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text.strip()


def subst(cmd: list[str], **kw) -> list[str]:
    out = []
    for x in cmd:
        for k, v in kw.items():
            x = x.replace("{" + k + "}", str(v))
        out.append(x)
    return out


def start(task: dict, group: str, c: dict, session: str | None = None, chain: int = 1) -> dict | None:
    if not tasks.claim(task["id"], group):
        return None
    stem = tasks.task_path(task["id"]).stem
    DELIV.mkdir(parents=True, exist_ok=True)
    (DELIV / f"{stem}.json").unlink(missing_ok=True)
    (ROOT / "lean" / ".sandbox" / group / stem).mkdir(parents=True, exist_ok=True)
    run = f"{time.strftime('%Y%m%dT%H%M%S')}-{group}-{stem}"[:200]
    p = prompt(task, group, first=session is None)
    cmd = (subst(c["resume_cmd"], prompt=p, root=str(ROOT), group=group, session=session)
           if session else subst(c["worker_cmd"], prompt=p, root=str(ROOT), group=group))
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"{run}.log", "w")
    env = dict(os.environ, SHEAF_GROUP=group, SHEAF_TASK=task["id"])
    pr = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                          env=env, start_new_session=True)
    log.close()
    PROCS[run] = pr
    r = {"run": run, "kind": "worker", "task": task["id"], "group": group, "pid": pr.pid, "t": time.time(),
         "session": session, "chain": chain, "log": str(LOGS / f"{run}.log")}
    save(r)
    tasks.event("started", task["id"], group, f"run {run}" + (f", continuing session {session}" if session else ""))
    return r


def session_of(r: dict, c: dict) -> str | None:
    if r.get("session"):
        return r["session"]
    try:
        m = re.search(c["session_regex"], pathlib.Path(r["log"]).read_text(errors="ignore")[:200000])
    except OSError:
        return None
    return m.group(1) if m else None


def result_of(r: dict, state: dict) -> tuple[int, str]:
    """The exit code of an acceptance, and its output as the reason. A run adopted after a restart has no process
    object: its code is the last line `RESULT <code>` of its log; none means it was interrupted."""
    try:
        out = pathlib.Path(r["log"]).read_text(errors="ignore")
    except OSError:
        out = ""
    pr = PROCS.pop(r["run"], None)
    code = pr.wait() if pr is not None else None
    lines = out.rstrip().splitlines()
    if code is None:
        code = int(lines[-1].split()[1]) if lines and lines[-1].startswith("RESULT ") else 9
    reason = "\n".join(l for l in lines if not l.startswith("RESULT "))
    return code, reason[-4000:]


def risk(r: dict, c: dict) -> str:
    """Why a running worker is high-risk, or ''."""
    why = []
    age = (time.time() - r["t"]) / 3600
    if age > c["risk_hours"]:
        why.append(f"running {age:.1f} h")
    try:
        idle = (time.time() - os.stat(r["log"]).st_mtime) / 60
    except OSError:
        idle = 0
    if idle > c["risk_idle_minutes"]:
        why.append(f"log idle {idle:.0f} min")
    return ", ".join(why)


def next_for(item_task: dict, held: set[str], ordered: list[dict]) -> dict | None:
    """The open task nearest to the item just delivered: one whose node its item uses or that uses it. Never a
    review of a target statement: the session may have written it."""
    nb = set(item_task.get("neighbours", {}).get("uses", [])) | set(item_task.get("neighbours", {}).get("used_by", []))
    if item_task.get("node"):
        nb.add(item_task["node"])
    for t in ordered:
        if t.get("kind") == "target-review":
            continue
        if tasks.task_path(t["id"]).stem not in held and t["id"] != item_task["id"] and t.get("node") in nb:
            return t
    return None


def free_groups(rs: dict, n: int) -> list[str]:
    used = {r["group"] for r in rs.values() if r["kind"] == "worker"}
    return [g for g in (f"w{k:03d}" for k in range(1, n + 1)) if g not in used]


def held_now() -> set[str]:
    return {p.stem for p in tasks.CLAIMS.glob("*.lock")}


def one_pass(c: dict, state: dict):
    rs = runs()
    # 1. reap
    for r in list(rs.values()):
        if running(r):
            if r["kind"] == "worker" and not r.get("risk_reported"):
                why = risk(r, c)
                if why:
                    tasks.alert(f"high-risk worker: run {r['run']}, task {r['task']}, pid {r['pid']}: {why}. "
                                f"To stop it: tools/dispatch.py stop {r['run']}")
                    r["risk_reported"] = why; save(r)
            continue
        drop(r); rs.pop(r["run"])
        tid = r["task"]
        if r["kind"] == "accept":
            code, reason = result_of(r, state)  # reads the exit code, which reaps the process
            tasks.settle(tid, code, reason, who=r["group"])
            continue
        PROCS.pop(r["run"], None)
        stem = tasks.task_path(tid).stem
        task = tasks.read_json(tasks.task_path(tid))
        if (DELIV / f"{stem}.json").exists():
            tasks.event("delivered", tid, r["group"])
            state["accept_queue"].append((tid, r["group"]))
            sess = session_of(r, c)
            if c["continue"] and c.get("resume_cmd") and sess and task and r["chain"] < c["max_chain"]:
                # the session waits for a task next to its item; most open only when this delivery is accepted
                state["idle"].append({"session": sess, "task": task, "chain": r["chain"], "t": time.time()})
        else:
            tail = ""
            try:
                tail = pathlib.Path(r["log"]).read_text(errors="ignore")[-1500:]
            except OSError:
                pass
            tasks.settle(tid, 4, f"the worker exited without a delivery (run {r['run']}); end of its log:\n{tail}",
                         who=r["group"])
    # 2. accept
    running_acc = sum(1 for r in rs.values() if r["kind"] == "accept")
    while state["accept_queue"] and running_acc < c["accept_slots"]:
        tid, g = state["accept_queue"].popleft()
        run = f"accept-{time.strftime('%Y%m%dT%H%M%S')}-{tasks.task_path(tid).stem}"[:200]
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / f"{run}.log", "w") as out:
            pr = subprocess.Popen([sys.executable, str(T / "accept.py"), tid, g], cwd=ROOT, start_new_session=True,
                                  stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        PROCS[run] = pr
        r = {"run": run, "kind": "accept", "task": tid, "group": g, "pid": pr.pid, "t": time.time(),
             "log": str(LOGS / f"{run}.log")}
        save(r); rs[run] = r; running_acc += 1
    # 3. full gen now and then
    if time.time() - state["last_gen"] > c["gen_every"]:
        subprocess.run([sys.executable, str(T / "tasks.py"), "gen"], cwd=ROOT, capture_output=True)
        state["last_gen"] = time.time()
    # 4. start: first the sessions that wait to continue, then fresh workers
    if (D / "STOP").exists():
        return
    missing = [x[0] for x in (c["worker_cmd"], c.get("resume_cmd") or ["true"]) if x and not shutil.which(x[0])]
    if missing:  # every start would fail at once; most often the PATH of cron, see tools/keepalive.py
        msg = f"worker command not found: {' '.join(missing)} (PATH={os.environ.get('PATH', '')}); no worker is started"
        if msg != state.get("last_err"):
            tasks.alert(msg); state["last_err"] = msg
        return
    ordered = tasks.ordered()
    workers = [r for r in rs.values() if r["kind"] == "worker"]
    free = c["slots"] - len(workers)
    accepting = {r["task"] for r in rs.values() if r["kind"] == "accept"} | {tid for tid, _ in state["accept_queue"]}
    waiting = []
    for w in state["idle"]:
        if time.time() - w["t"] > c["continue_wait"]:
            continue
        nxt = next_for(w["task"], held_now(), ordered) if free > 0 and state["bucket"] >= 1 else None
        g = free_groups(rs, c["slots"] + c["accept_slots"] + 64)[0]
        nr = start(nxt, g, c, session=w["session"], chain=w["chain"] + 1) if nxt else None
        if nr:
            free -= 1; state["bucket"] -= 1; rs[nr["run"]] = nr
        elif free <= 0 or state["bucket"] < 1 or nxt is not None or w["task"]["id"] in accepting:
            waiting.append(w)  # its own acceptance may still open the next task
    state["idle"] = waiting
    if free <= 0 or state["bucket"] < 1:
        return
    held = held_now()
    busy_nodes = set()
    for h in held:
        t = tasks.read_json(tasks.TD / f"{h}.json") or {}
        busy_nodes |= set(t.get("neighbours", {}).get("uses", [])) | set(t.get("neighbours", {}).get("used_by", []))
    todo = [t for t in ordered if tasks.task_path(t["id"]).stem not in held]
    quiet = [t for t in todo if t.get("node") not in busy_nodes]
    todo = quiet + [t for t in todo if t.get("node") in busy_nodes]
    groups = free_groups(rs, c["slots"] + c["accept_slots"] + 64)
    for t in todo:
        if free <= 0 or state["bucket"] < 1 or not groups:
            break
        g = groups.pop(0)
        r = start(t, g, c)
        if r:
            free -= 1; state["bucket"] -= 1; rs[r["run"]] = r
        else:
            groups.insert(0, g)


def adopt(state: dict):
    """After a restart: deliveries whose acceptance never ran go to the acceptance queue again."""
    rs = runs()
    acc = {r["task"] for r in rs.values() if r["kind"] == "accept"}
    work = {r["task"] for r in rs.values() if r["kind"] == "worker"}
    h = tasks.history()
    by_stem = {tasks.task_path(t["id"]).stem: t for t in tasks.listed().values()}
    for lk in tasks.CLAIMS.glob("*.lock"):
        d = tasks.read_json(lk) or {}
        t = by_stem.get(lk.stem)
        if t is None or t["id"] in acc or t["id"] in work:
            continue
        evs = h.get(t["id"], [])
        if evs and evs[-1][1] == "delivered":
            state["accept_queue"].append((t["id"], d.get("who", "w000")))
        else:
            tasks.release(t["id"], "no worker after a dispatcher restart")


def main() -> int:
    li.ensure_utf8()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    D.mkdir(parents=True, exist_ok=True); tasks.dirs(); DELIV.mkdir(parents=True, exist_ok=True)
    if cmd == "status":
        c = conf()
        for r in sorted(runs().values(), key=lambda r: r["t"]):
            why = risk(r, c) if r["kind"] == "worker" and running(r) else ""
            print(f"{r['run']}\t{r['kind']}\t{r['task']}\tpid {r['pid']}\t{(time.time() - r['t']) / 60:.0f} min"
                  + ("" if running(r) else "\texited") + (f"\tHIGH RISK: {why}" if why else ""))
        print(("STOP is set; " if (D / "STOP").exists() else "") + f"settings: {json.dumps({k: v for k, v in conf().items() if not k.endswith('cmd')})}")
        return 0
    if cmd == "stop":
        r = runs().get(sys.argv[2]) if len(sys.argv) > 2 else None
        if not r or r["kind"] != "worker":
            print("no such worker run; tools/dispatch.py status lists them"); return 1
        try:
            os.killpg(r["pid"], signal.SIGTERM)  # the worker leads its own process group (start_new_session)
        except (ProcessLookupError, PermissionError):
            pass
        tasks.event("stopped", r["task"], r["group"], f"run {r['run']} stopped by hand")
        print(f"stopped {r['run']}; the dispatcher settles its task as left without a delivery"); return 0
    if cmd not in ("run", "once"):
        print(__doc__); return 2
    pidf = D / "pid"
    if cmd == "run":
        import fcntl
        lockf = open(D / "dispatcher.lock", "a")   # held while this dispatcher runs (tools/keepalive.py)
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("a dispatcher runs already" + (f", pid {pidf.read_text().strip()}" if pidf.exists() else "")); return 1
        pidf.write_text(str(os.getpid()))
    state = {"accept_queue": collections.deque(), "idle": [], "last_gen": 0.0, "bucket": 0.0, "t": time.time()}
    adopt(state)
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    while True:
        c = conf()
        now = time.time()
        state["bucket"] = min(c["starts_per_min"], state["bucket"] + (now - state["t"]) * c["starts_per_min"] / 60)
        state["t"] = now
        if cmd == "once":
            state["bucket"] = c["starts_per_min"]
        try:
            one_pass(c, state)
        except Exception as e:  # a pass that fails is reported once and the loop goes on
            msg = f"dispatcher pass failed: {type(e).__name__}: {e}"
            if msg != state.get("last_err"):
                tasks.alert(msg); state["last_err"] = msg
        if cmd == "once" or stop:
            break
        time.sleep(c["poll"])
    if cmd == "run":
        pidf.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
