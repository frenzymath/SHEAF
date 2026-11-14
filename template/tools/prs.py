#!/usr/bin/env python3
"""Pull requests to a repository kept by a managing agent (skills/compiling/SKILL.md, the first and the third layout).
A sketch, written quickly: change it to fit the project, as long as the skill's rules hold.

Usage:
  tools/prs.py open <group> <sandbox lean dir> <file under lean/>...   queue the files as one pull request; prints its id
  tools/prs.py wait <id>                         wait until it is closed; exit 0 merged, 1 returned (the reason printed)
  tools/prs.py list                              the open pull requests: files, what they change for other modules,
                                                 and files the library changed since the pull request was opened
  tools/prs.py apply <lean dir> <id>...          write the files of these pull requests into a Lean tree (the
                                                 managing agent's copy); a file whose first line is `-- DELETE` deletes it
  tools/prs.py close <id> merged|returned [reason]

A pull request is local/prs/open/<id>/: meta.json and files/<path under lean/>. Closing moves meta.json, with the
result, to local/prs/closed/<id>.json. The managing agent decides which pull requests form a batch, builds the batch
in its own copy, brings the result into the repository the workers compile against, and only then closes them.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, shutil, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402

D = li.ROOT / "local" / "prs"
OPEN, CLOSED = D / "open", D / "closed"


def digest(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def open_pr(group: str, src: str, files: list[str]) -> int:
    pid = f"{time.strftime('%Y%m%dT%H%M%S')}-{group}-{os.getpid()}"
    d = OPEN / pid
    for f in files:
        (d / "files" / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pathlib.Path(src) / f, d / "files" / f)
    meta = {"id": pid, "group": group, "opened": time.time(),
            "files": {f: digest(li.LEAN / f) for f in files}}  # the library's version when it was opened
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    print(pid)
    return 0


def wait(pid: str) -> int:
    while not (CLOSED / f"{pid}.json").exists():
        time.sleep(10)
    r = json.loads((CLOSED / f"{pid}.json").read_text())
    print(f"{r['result']}: {r.get('reason', '')}")
    return 0 if r["result"] == "merged" else 1


def listing() -> int:
    for d in sorted(OPEN.glob("*/meta.json")):
        m = json.loads(d.read_text())
        print(f"{m['id']}  {m['group']}")
        for f, was in m["files"].items():
            new = (d.parent / "files" / f).read_text(errors="ignore")
            lib = li.LEAN / f
            old = lib.read_text(errors="ignore") if lib.is_file() else ""
            ch = "new file" if not lib.is_file() else ", ".join(li.interface_changes(old, new)) or "proofs only"
            moved = "  (the library changed since)" if digest(lib) != was else ""
            print(f"  {f}: {ch}{moved}")
    return 0


def apply(tree: str, pids: list[str]) -> int:
    for pid in pids:
        src = OPEN / pid / "files"
        for p in sorted(src.rglob("*.lean")):
            dst = pathlib.Path(tree) / p.relative_to(src)
            if p.read_text(errors="ignore").startswith("-- DELETE"):
                dst.unlink(missing_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dst)
        print(f"applied {pid}")
    return 0


def close(pid: str, result: str, reason: str) -> int:
    if result not in ("merged", "returned"):
        print("result is merged or returned"); return 2
    m = json.loads((OPEN / pid / "meta.json").read_text())
    m.update(result=result, reason=reason, closed=time.time())
    CLOSED.mkdir(parents=True, exist_ok=True)
    (CLOSED / f"{pid}.json").write_text(json.dumps(m, indent=1))
    shutil.rmtree(OPEN / pid)
    return 0


def main() -> int:
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "open":
        return open_pr(a[1], a[2], a[3:])
    if len(a) == 2 and a[0] == "wait":
        return wait(a[1])
    if a == ["list"]:
        return listing()
    if len(a) >= 3 and a[0] == "apply":
        return apply(a[1], a[2:])
    if len(a) >= 3 and a[0] == "close":
        return close(a[1], a[2], " ".join(a[3:]))
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main())
