#!/usr/bin/env python3
"""Landings, and how they reach the global build. Used by land.sh, land_set.sh and build.py.

Every landing is a record that moves through local/builds/, the way a claim is a file in coord/claims/:

  inflight/<id>.json   the files are written, the group is still checking them (single-file compiles, text checks);
                       a build started now takes the previous version of these files
  requests/<id>.json   the landing is complete and waits for a global build to verify it
  done/<id>.json       verified by a green build, or reverted by the maintainer, with the reason
  backup/<id>/…        the previous version of every file of the landing, kept until it is verified

A landing is of kind `interface` when it changes what other modules see: a statement, a definition, an instance or
an attribute, a removed import, a deleted module, or any set landed with land_set.sh. Otherwise it is of kind `proof`.
An interface landing makes the maintainer's build start over at once (build.py), so that it is verified first.

Usage:
  tools/landing.py status [<id>]            all open landings and the last build, or one landing
  tools/landing.py mine <group>             the group's landings that are open or were reverted
  tools/landing.py revert <id> <reason>     (the maintainer) put back the previous version of every file of a landing
                                            that a build showed to be wrong; refused if a file changed since
Called by the landing scripts, not by hand:
  tools/landing.py begin <group> <file>…    files relative to lean/; prints the id
  tools/landing.py finish <id> [--set]      the group's checks passed; prints the kind
  tools/landing.py abort <id>               the group's checks failed: restore the files
  tools/landing.py order <file>…            the files in the order of their imports of each other
Every step that reads or writes the tree holds local/tree.lock, as the build's snapshot does.
"""
from __future__ import annotations
import contextlib, fcntl, hashlib, json, os, pathlib, shutil, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402

WORK = li.ROOT / "coord"
LOCAL = li.ROOT / "local"
B = LOCAL / "builds"
INFLIGHT, REQUESTS, DONE, BACKUP = B / "inflight", B / "requests", B / "done", B / "backup"


def dirs():
    for d in (INFLIGHT, REQUESTS, DONE, BACKUP):
        d.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def tree_lock():
    LOCAL.mkdir(exist_ok=True)
    with open(LOCAL / "tree.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def now() -> str:
    return time.strftime("%FT%TZ", time.gmtime())


def sha(p: pathlib.Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def module(rel: str) -> str:
    return rel[:-5].replace("/", ".")


def write_json(p: pathlib.Path, d: dict):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def read_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def records(d: pathlib.Path) -> list[dict]:
    return [r for r in (read_json(p) for p in sorted(d.glob("*.json"))) if r]


def log(line: str):
    WORK.mkdir(exist_ok=True)
    with open(WORK / "deliveries.log", "a") as f:
        f.write(now() + " " + line + "\n")


def drop_mirror(group: str, rels: list[str]):
    """Remove from the group's private mirror what it compiled from files that are no longer in the tree."""
    mirror = LOCAL / "build" / group
    shared = li.LEAN / ".lake" / "build" / "lib" / "lean"
    for rel in rels:
        for ext in (".olean", ".ilean"):
            m = mirror / (rel[:-5] + ext)
            if m.exists() or m.is_symlink():
                m.unlink()
            s = shared / (rel[:-5] + ext)
            if s.exists() and m.parent.is_dir():
                m.symlink_to(s)


def restore(r: dict):
    for f in r["files"]:
        dst, bk = li.LEAN / f["path"], BACKUP / r["id"] / f["path"]
        if f["existed"]:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bk, dst)
        elif dst.exists():
            dst.unlink()
    drop_mirror(r["group"], [f["path"] for f in r["files"]])
    shutil.rmtree(BACKUP / r["id"], ignore_errors=True)


def begin(group: str, rels: list[str]) -> int:
    dirs()
    rid = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{group}-{os.getpid()}"
    with tree_lock():
        busy = {f["path"]: r["id"] for r in records(INFLIGHT) for f in r["files"]}
        clash = [f"{rel} (landing {busy[rel]})" for rel in rels if rel in busy]
        if clash:
            print("Another landing of these files is still being checked: " + ", ".join(clash), file=sys.stderr)
            return 3
        files = []
        for rel in rels:
            src = li.LEAN / rel
            if src.is_file():
                (BACKUP / rid / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, BACKUP / rid / rel)
            files.append({"path": rel, "module": module(rel), "existed": src.is_file()})
        write_json(INFLIGHT / f"{rid}.json", {"id": rid, "group": group, "time": now(), "files": files})
    print(rid)
    return 0


def finish(rid: str, is_set: bool) -> int:
    with tree_lock():
        r = read_json(INFLIGHT / f"{rid}.json")
        if not r:
            print(f"no landing in flight with id {rid}", file=sys.stderr); return 2
        changed = []
        for f in r["files"]:
            dst, bk = li.LEAN / f["path"], BACKUP / rid / f["path"]
            f["sha"] = sha(dst)
            f["deleted"] = f["existed"] and not dst.is_file()
            if f["deleted"]:
                changed.append(f"{f['module']} (deleted)")
            elif f["existed"]:
                changed += li.interface_changes(bk.read_text(errors="ignore"), dst.read_text(errors="ignore"))
        r.update(kind="interface" if (is_set or changed) else "proof", set=is_set, changed=changed[:40], landed=now())
        write_json(REQUESTS / f"{rid}.json", r)
        (INFLIGHT / f"{rid}.json").unlink()
    log(f"{r['group']} landed {' '.join(f['module'] for f in r['files'])} ({r['kind']}, landing {rid})")
    print(r["kind"])
    return 0


def abort(rid: str) -> int:
    with tree_lock():
        r = read_json(INFLIGHT / f"{rid}.json")
        if not r:
            return 0
        restore(r)
        (INFLIGHT / f"{rid}.json").unlink()
    return 0


def revert(rid: str, reason: str) -> int:
    dirs()
    with tree_lock():
        r = read_json(REQUESTS / f"{rid}.json")
        if not r:
            print(f"no landing waiting for a build with id {rid}", file=sys.stderr); return 2
        moved = [f["path"] for f in r["files"] if sha(li.LEAN / f["path"]) != f.get("sha")]
        if moved:
            print("Not reverted: these files changed after the landing, so putting back the old version would lose "
                  "that work: " + ", ".join(moved) + ". Repair them through a landing of your own.")
            return 3
        restore(r)
        r.update(result="reverted", reason=reason, closed=now())
        write_json(DONE / f"{rid}.json", r)
        (REQUESTS / f"{rid}.json").unlink()
    log(f"M reverted landing {rid} of {r['group']}: {reason}")
    print(f"Reverted landing {rid} ({len(r['files'])} file(s)) of {r['group']}.")
    return 0


def order(rels: list[str]) -> int:
    mods = {module(r): r for r in rels}
    imps = {}
    for m, r in mods.items():
        p = li.LEAN / r
        imps[m] = li.imports_of(p.read_text(errors="ignore")) & mods.keys() if p.is_file() else set()
    out, seen = [], set()

    def visit(m, path=()):
        if m in seen:
            return
        if m in path:
            raise SystemExit(f"the set has an import cycle through {m}")
        for i in sorted(imps[m]):
            visit(i, path + (m,))
        seen.add(m); out.append(mods[m])
    for m in sorted(mods):
        visit(m)
    print("\n".join(r for r in out if (li.LEAN / r).is_file()))
    return 0


def line(r: dict, state: str) -> str:
    mods = " ".join(f["module"] for f in r["files"][:4]) + (" …" if len(r["files"]) > 4 else "")
    tail = f": {r['reason']}" if r.get("reason") else ""
    return f"{r['id']}  {state:9} {r.get('kind', '-'):9} {r['group']:6} {mods}{tail}"


def status(rid: str | None, group: str | None) -> int:
    dirs()
    rows = [(r, "checking") for r in records(INFLIGHT)] + [(r, "waiting") for r in records(REQUESTS)]
    rows += [(r, r.get("result", "verified")) for r in records(DONE)[-200:]]
    if rid:
        hit = [(r, s) for r, s in rows if r["id"] == rid]
        if not hit:
            print(f"no landing with id {rid}"); return 2
        r, s = hit[0]
        print(line(r, s))
        print(json.dumps({k: r[k] for k in r if k != "files"}, ensure_ascii=False, indent=1))
        return 0
    if group:
        rows = [(r, s) for r, s in rows if r["group"] == group and s != "verified"]
    else:
        rows = [(r, s) for r, s in rows if s in ("checking", "waiting")]
    for r, s in rows:
        print(line(r, s))
    last = read_json(B / "last.json")
    if last and not group:
        print(f"last build: {last['result']} at {last['time']}, commit {last.get('commit') or '-'}, "
              f"{len(last.get('verified', []))} landing(s) verified" +
              (f", failing: {' '.join(last['failing'][:6])}" if last.get("failing") else ""))
    return 0


def main() -> int:
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "begin":
        return begin(a[1], a[2:])
    if len(a) in (2, 3) and a[0] == "finish":
        return finish(a[1], "--set" in a[2:])
    if len(a) == 2 and a[0] == "abort":
        return abort(a[1])
    if len(a) >= 3 and a[0] == "revert":
        return revert(a[1], " ".join(a[2:]))
    if len(a) >= 2 and a[0] == "order":
        return order(a[1:])
    if a and a[0] == "status" and len(a) <= 2:
        return status(a[1] if len(a) == 2 else None, None)
    if len(a) == 2 and a[0] == "mine":
        return status(None, a[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
