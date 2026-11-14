#!/usr/bin/env python3
"""Accept one delivery: check it, and if it passes, put it in. It answers only whether the delivery passed; what
then happens to the task is decided by tools/dispatch.py through tools/tasks.py settle.

Usage:
  tools/accept.py <task id> <group>

Exit code, also printed as the last line `RESULT <code>`, with the reason above it:
  0  accepted: the nodes are in dag/nodes/, the Lean files went through the submit command
  1  refused: the reason says what does not pass; no node is written (the Lean files stay where the submit command
     put them if the nodes are refused only afterwards, at step 4)
  2  the worker gave up, 3 the worker disputes the statement; the report is printed
  9  the acceptance itself failed

The worker of the task delivers by writing coord/deliveries/<task id>.json (roles/worker.md §3):

  {"task": "<task id>", "result": "delivered" | "gave-up" | "disputed",
   "nodes": ["<path under dag/nodes/>", ...],   the node files, written in <sandbox>/nodes/<path>
   "lean":  ["<path under lean/>", ...],        the Lean files, written in <sandbox>/lean/<path>
   "files": ["<path under the project>", ...],  only the files its task lists under "files";
                                                written in <sandbox>/files/<path>
   "report": "<the report of roles/worker.md §3>"}

The sandbox is lean/.sandbox/<group>/<task file name without .json>/. Nothing is judged here, only checked:

  1. The nodes: every file is JSON with an id; every node it uses exists, in the DAG or in the delivery; no new cycle;
     an id that exists already is delivered at the path it has; no node that is not the item was changed by another
     delivery after this task was claimed (the worker wrote it from an older version). For the item: in stage 1 the
     node is split afterwards (stages/1-dag.md §2); in stage 2 it records a module that the delivery or the library
     has.
  2. Other files are only those the task lists. A target review ends with a line `Verdict: locked` or
     `Verdict: defect`.
  3. The Lean files are submitted: the command `submit_cmd` of coord/dispatch.json is run with the group, the
     sandbox's lean/ directory and the files; exit 0 means they are in the library. How it compiles them is chosen
     in skills/compiling/SKILL.md, by the main agent with the human. Until they have chosen, the default is the safest
     layout, one frozen repository: tools/submit_frozen.py.
  4. Under a lock, the checks of 1 are run again, and the nodes and other files are written.
"""
from __future__ import annotations
import fcntl, json, os, pathlib, re, shutil, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402
import dag_queue as dq  # noqa: E402
import tasks  # noqa: E402

T = pathlib.Path(__file__).resolve().parent
ACCEPTED, REFUSED, GAVE_UP, DISPUTED, ERROR = 0, 1, 2, 3, 9
DELIV = li.ROOT / "coord" / "deliveries"


def sandbox(tid: str, group: str) -> pathlib.Path:
    return li.LEAN / ".sandbox" / group / tasks.task_path(tid).stem


def check_nodes(task: dict, sb: pathlib.Path, files: list[str], lean_files: list[str]) -> tuple[list[str], dict]:
    """Errors, and the delivered nodes by path."""
    errs, got = [], {}
    base = dq.nodes_dir()
    for rel in files:
        p = sb / "nodes" / rel
        d = tasks.read_json(p)
        if not isinstance(d, dict) or not dq.field(d, "id"):
            errs.append(f"{rel}: not a JSON node with an id"); continue
        if pathlib.PurePath(rel).is_absolute() or ".." in pathlib.PurePath(rel).parts:
            errs.append(f"{rel}: path outside dag/nodes"); continue
        got[rel] = d
    g = tasks.load_dag()
    path_of = {i: d.get("_path") for i, d in g.n.items()}
    merged = dict(g.n)
    for rel, d in got.items():
        i = str(dq.field(d, "id"))
        if i in path_of and path_of[i] != rel:
            errs.append(f"node {i} exists at dag/nodes/{path_of[i]}; deliver it at that path, not at {rel}")
        d = dict(d); d["_path"] = rel
        merged[i] = d
    h = tasks.Dag(merged)
    for rel, d in got.items():
        i = str(dq.field(d, "id"))
        if i in h.merged:
            continue
        for c in h.deps(i, "all"):
            if c not in h.live:
                errs.append(f"node {i} uses {c}, which is neither in the DAG nor in the delivery")
    # cycles through a delivered node
    colour = {}

    def visit(i, stack):
        colour[i] = 1
        for c in h.deps(i, "all") if i in h.live else []:
            if colour.get(c) == 1:
                errs.append("cycle: " + " -> ".join(stack + [i, c])); return
            if c not in colour:
                visit(c, stack + [i])
        colour[i] = 2

    for rel, d in got.items():
        i = str(dq.field(d, "id"))
        if i in h.live and i not in colour:
            visit(i, [])
    item = task.get("node")
    if item and item in h.live and task.get("kind") != "custom":
        d = h.live[item]
        if task["stage"] == 1 and not (dq.unfolded(d) or item in h.merged):
            errs.append(f"stage 1: node {item} is still not split (stages/1-dag.md §2)")
        if task["stage"] == 2:
            m = dq.module_of(d)
            if not m:
                errs.append(f"stage 2: node {item} records no module")
            elif m.replace(".", "/") + ".lean" not in lean_files and not li.file_of(m).is_file():
                errs.append(f"stage 2: node {item} records module {m}, which is neither delivered nor in the library")
    return errs, got


def submit(group: str, sb: pathlib.Path, lean_files: list[str]) -> tuple[bool, str]:
    for f in lean_files:
        if not (sb / "lean" / f).is_file():
            return False, f"lean/{f} is not in the sandbox at {sb / 'lean' / f}"
    try:
        cmd = json.loads((li.ROOT / "coord" / "dispatch.json").read_text()).get("submit_cmd")
    except (FileNotFoundError, json.JSONDecodeError):
        cmd = None
    cmd = [str(x).replace("{tools}", str(T)) for x in (cmd or ["{tools}/submit_frozen.py"])]
    r = subprocess.run(cmd + [group, str(sb / "lean")] + lean_files, capture_output=True, text=True,
                       cwd=li.ROOT, env=dict(os.environ, SHEAF_GROUP=group))
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def stale(task: dict, files: list[str], since: float) -> list[str]:
    """Delivered nodes that are not the item and that someone else changed after the claim: the worker wrote them
    from an older version, so the version in the DAG is kept (`roles/worker.md` §3)."""
    out, base = [], dq.nodes_dir()
    for rel in files:
        dst = base / rel
        if not dst.exists() or dst.stat().st_mtime <= since:
            continue
        d = tasks.read_json(dst) or {}
        if str(dq.field(d, "id")) != str(task.get("node")):
            out.append(rel)
    return out



def refuse(reason: str) -> int:
    print(reason)
    return REFUSED


def accept(tid: str, group: str) -> int:
    task = tasks.read_json(tasks.task_path(tid))
    if task is None:
        print(f"{tid} is not listed"); return ERROR
    dv = tasks.read_json(DELIV / f"{tasks.safe(tid)}.json")
    if dv is None:
        return refuse("no delivery file, or not JSON")
    report = dv.get("report", "")
    if isinstance(report, (dict, list)):
        report = json.dumps(report, ensure_ascii=False)
    if dv.get("result") == "gave-up":
        print(report); return GAVE_UP
    if dv.get("result") == "disputed":
        print(report); return DISPUTED
    if dv.get("result") != "delivered":
        return refuse(f"unknown result {dv.get('result')!r}")
    sb = sandbox(tid, group)
    since = (tasks.read_json(tasks.lock(tid)) or {}).get("t", 0.0)
    node_files = [str(x) for x in dv.get("nodes", [])]
    lean_files = [str(x) for x in dv.get("lean", [])]
    other = [str(x) for x in dv.get("files", [])]
    old = stale(task, node_files, since)
    if old:
        return refuse("nodes changed by another delivery after this task was claimed; start from their current "
                      "version: " + " ".join(old))
    errs, got = check_nodes(task, sb, node_files, lean_files)
    if errs:
        return refuse("the nodes do not pass:\n" + "\n".join(errs))
    bad = [f for f in other if f not in task.get("files", [])]
    if bad:
        return refuse("files the task does not list: " + " ".join(bad))
    if task.get("kind") == "target-review":
        rv = [f for f in other if f.startswith("coord/targets-review/")]
        text = (sb / "files" / rv[0]).read_text(errors="ignore") if rv and (sb / "files" / rv[0]).is_file() else ""
        if not any(l.strip() in ("Verdict: locked", "Verdict: defect") for l in text.splitlines()[-3:]):
            return refuse("the review must be delivered, ending with `Verdict: locked` or `Verdict: defect`")
    for f in other:
        src = sb / "files" / f
        if not src.is_file():
            return refuse(f"{f} is not in the sandbox at {src}")
    if lean_files:
        ok, out = submit(group, sb, lean_files)
        if not ok:
            return refuse("not accepted into the library:\n" + out[-4000:])
    with open(tasks.TD / ".accept.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        old = stale(task, node_files, since)
        errs, got = check_nodes(task, sb, node_files, lean_files)
        if old or errs:
            return refuse("the nodes conflict with a delivery accepted meanwhile:\n" + "\n".join(errs + old))
        base = dq.nodes_dir()
        for rel in got:
            dst = base / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{os.getpid()}")
            shutil.copyfile(sb / "nodes" / rel, tmp)
            os.replace(tmp, dst)
        for f in other:
            dst = li.ROOT / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{os.getpid()}")
            shutil.copyfile(sb / "files" / f, tmp)
            os.replace(tmp, dst)
    print("accepted")
    return ACCEPTED


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__); return ERROR
    li.ensure_utf8()
    try:
        code = accept(sys.argv[1], sys.argv[2])
    except Exception as e:
        print(f"acceptance error: {type(e).__name__}: {e}"); code = ERROR
    print(f"RESULT {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
