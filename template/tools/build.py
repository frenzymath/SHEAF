#!/usr/bin/env python3
"""The global build. Only the agent holding the building function runs it.

It never builds the tree the groups work in. It builds a copy, local/buildtree/, and brings the compiled files back:

  1. Snapshot, under local/tree.lock (seconds): commit the tree, copy the sources into the copy, and for every landing
     still being checked by its group take the previous version of its files. The commit records exactly what is built.
  2. `lake build` in the copy. Landings go on meanwhile; nothing waits for the build.
  3. While it runs, watch local/builds/requests/. When an interface landing arrives (landing.py) and the running build
     contains none, stop the build and start over from a new snapshot, so that the change most likely to break other
     modules is verified first. A build that contains an interface landing is never stopped: what arrives during it
     waits for the next build. So a build is stopped at most once.
  4. Green: the build succeeded. Then publish: copy the changed compiled files into lean/.lake/build, each one written completely before
     it replaces the old one, and close the landings the snapshot contained as verified.
     Red: publish nothing, so the groups keep compiling against the last green build, and list the landings that may
     have caused each failure, interface landings first.

Usage:
  tools/build.py           build until one build completes; exit 0 green or nothing to build, 1 red, 2 cannot start.
                           When nothing has landed, it waits for the next landing (at most SHEAF_BUILD_WAIT seconds,
                           default 600) and builds as soon as it arrives.
  tools/build.py --retry   after a red build: build the same snapshot again with the maintainer's own landings
                           (group M) and without the landings reverted, taking in nothing else that has landed
  tools/build.py status    the last result and the landings waiting
Results: local/builds/last.json, the log in local/build.log.
Options (coord/sheaf.env): SHEAF_BUILD_THREADS (default 3), SHEAF_BUILD_POLL seconds (10).
The packages in lean/.lake/packages are shared with the copy through a link and must never be rebuilt from it: the
build does not start if Lake would rebuild Mathlib. A dependency given by a relative path is not supported.
"""
from __future__ import annotations
import fcntl, hashlib, json, os, pathlib, re, shutil, signal, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402
import landing as ld  # noqa: E402

CFG = li.config()
CLONE = ld.LOCAL / "buildtree"
LOG = ld.B / "build.log"
THREADS = CFG.get("SHEAF_BUILD_THREADS", "3")
POLL = float(CFG.get("SHEAF_BUILD_POLL", "10"))
TOOLS = pathlib.Path(__file__).resolve().parent


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def commit_tree(inflight: list[dict]):
    """Commit the repository holding the Lean sources, with the previous version of every file of the landings held
    back (newest first, so that the oldest previous version of a file is the one that stays)."""
    top = run(["git", "-C", str(li.LEAN), "rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        return None
    repo = pathlib.Path(top.stdout.strip())
    run(["git", "add", "-A"], cwd=repo)
    for r in inflight:
        for f in r["files"]:
            try:
                rel = str((li.LEAN / f["path"]).relative_to(repo))
            except ValueError:
                continue
            bk = ld.BACKUP / r["id"] / f["path"]
            if f["existed"]:
                h = run(["git", "hash-object", "-w", str(bk)], cwd=repo).stdout.strip()
                run(["git", "update-index", "--add", "--cacheinfo", f"100644,{h},{rel}"], cwd=repo)
            else:
                run(["git", "update-index", "--force-remove", rel], cwd=repo)
    c = run(["git", "commit", "-q", "-m", f"build {ld.now()}"], cwd=repo)
    if c.returncode != 0 and "nothing to commit" not in c.stdout + c.stderr and "nothing added" not in c.stdout + c.stderr:
        print("warning: git commit failed: " + (c.stderr or c.stdout).strip().split("\n")[0])
    return run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip() or None


def seed_copy():
    lake = CLONE / ".lake"
    if lake.exists():
        return
    lake.mkdir(parents=True)
    if (li.LEAN / ".lake" / "packages").is_dir():
        (lake / "packages").symlink_to(li.LEAN / ".lake" / "packages")
    if (li.LEAN / ".lake" / "build").is_dir():
        subprocess.run(["cp", "-a", "--reflink=auto", str(li.LEAN / ".lake" / "build"), str(lake / "build")], check=True)


def snapshot(allowed=None):
    """Returns (commit, the landings contained, whether any source changed since the last snapshot).
    Landings still being checked are held back; with `allowed`, so is every waiting landing whose id is not in it."""
    ld.dirs()
    with ld.tree_lock():
        waiting = ld.records(ld.REQUESTS)
        held = [] if allowed is None else [r for r in waiting if r["id"] not in allowed]
        inflight = sorted(ld.records(ld.INFLIGHT) + held, key=lambda r: r["id"], reverse=True)
        commit = commit_tree(inflight)
        CLONE.mkdir(parents=True, exist_ok=True)
        r = run(["rsync", "-a", "-i", "--delete", "--exclude=/.lake", "--exclude=/.sandbox", "--exclude=/.quarantine",
                 "--exclude=/.git", f"{li.LEAN}/", f"{CLONE}/"])
        if r.returncode != 0:
            raise SystemExit("rsync failed: " + r.stderr.strip())
        changed = any(x and not x.startswith(".d") for x in r.stdout.split("\n"))
        for rec in inflight:
            for f in rec["files"]:
                dst, bk = CLONE / f["path"], ld.BACKUP / rec["id"] / f["path"]
                if f["existed"]:
                    shutil.copy2(bk, dst)
                elif dst.exists():
                    dst.unlink()
        included = [r for r in waiting if allowed is None or r["id"] in allowed]
    seed_copy()
    return commit, included, changed


def packages_ok() -> bool:
    if not (li.LEAN / ".lake" / "packages" / "mathlib").is_dir():
        return True
    h = hashlib.sha256()
    for n in ("lake-manifest.json", "lean-toolchain", "lakefile.toml", "lakefile.lean"):
        if (CLONE / n).is_file():
            h.update((CLONE / n).read_bytes())
    stamp = CLONE / ".lake" / "sheaf_packages_ok"
    if stamp.is_file() and stamp.read_text() == h.hexdigest():
        return True
    r = run(["lake", "build", "--no-build", "Mathlib"], cwd=CLONE)
    if r.returncode != 0:
        print("Lake would rebuild Mathlib from the build copy, inside the packages directory that lean/ shares with it; "
              "the build was not started.\nRun `lake exe cache get` in lean/ and check that lake-manifest.json and "
              "lean-toolchain are the ones Mathlib was fetched for.\n" + (r.stdout + r.stderr)[-600:])
        return False
    stamp.write_text(h.hexdigest())
    return True


def failing_modules(log: str) -> list[str]:
    out = re.findall(r"^✖ \[\d+/\d+\] \w+ (\S+)", log, re.M)
    m = re.search(r"Some required \w+ logged failures:\n((?:- .*\n?)+)", log)
    if m:
        out += [x[2:].strip() for x in m.group(1).split("\n") if x.startswith("- ")]
    return sorted(set(out))


def suspects(failing: list[str], included: list[dict]) -> list[dict]:
    imports = {}
    for d in li.library_dirs():
        for p in (CLONE / d).rglob("*.lean"):
            imports[".".join(p.relative_to(CLONE).with_suffix("").parts)] = li.imports_of(p.read_text(errors="ignore"))
    memo: dict = {}
    out = []
    for r in included:
        mods = {f["module"] for f in r["files"]}
        hit = [m for m in failing if m in mods or mods & li.closure(m, imports, memo)]
        if hit or not failing:
            out.append({"id": r["id"], "group": r["group"], "kind": r["kind"], "modules": sorted(mods)[:8],
                        "fails": hit[:8], "landed": r.get("landed", "")})
    out.sort(key=lambda s: s["landed"], reverse=True)
    return sorted(out, key=lambda s: s["kind"] != "interface")


def publish():
    marker = ld.LOCAL / "PUBLISHING"
    marker.write_text(ld.now())
    try:
        dst = li.LEAN / ".lake" / "build"
        dst.mkdir(parents=True, exist_ok=True)
        r = run(["rsync", "-a", "--delete", "--delay-updates", f"{CLONE / '.lake' / 'build'}/", f"{dst}/"])
        if r.returncode != 0:
            raise SystemExit("publishing failed: " + r.stderr.strip())
        lib = dst / "lib" / "lean"
        if lib.is_dir():
            os.utime(lib)
        (ld.B / "published").write_text(ld.now())
    finally:
        marker.unlink(missing_ok=True)


def close_verified(included: list[dict], commit):
    for r in included:
        r.update(result="verified", commit=commit, closed=ld.now())
        ld.write_json(ld.DONE / f"{r['id']}.json", r)
        (ld.REQUESTS / f"{r['id']}.json").unlink(missing_ok=True)
        shutil.rmtree(ld.BACKUP / r["id"], ignore_errors=True)
    old = time.time() - 7 * 86400
    for p in ld.DONE.glob("*.json"):
        if p.stat().st_mtime < old:
            p.unlink()


def status() -> int:
    return ld.status(None, None)


def main() -> int:
    if sys.argv[1:] == ["status"]:
        return status()
    wait, retry = True, sys.argv[1:] == ["--retry"]
    if sys.argv[1:] and not retry:
        print(__doc__); return 2
    ld.dirs()
    guard = open(ld.B / "build.lock", "w")
    try:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another global build is running."); return 2
    preempted, proc = 0, None

    def stop(*_):
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        sys.exit(2)
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)

    while True:
        last = ld.read_json(ld.B / "last.json")
        allowed = None
        if retry:
            if not last or last["result"] != "red":
                print("--retry follows a red build; the last build was not red."); return 2
            allowed = set(last.get("included", [])) | {r["id"] for r in ld.records(ld.REQUESTS) if r["group"] == "M"}
        commit, included, changed = snapshot(allowed)
        if not included and not changed and last and last["result"] == "green":
            deadline = time.time() + float(CFG.get("SHEAF_BUILD_WAIT", "600"))
            while wait and time.time() < deadline and not ld.records(ld.REQUESTS):
                time.sleep(POLL)
            if wait and ld.records(ld.REQUESTS):
                continue
            print("Nothing landed since the last green build."); return 0
        if not packages_ok():
            return 2
        ids = {r["id"] for r in included}
        has_interface = any(r["kind"] == "interface" for r in included)
        print(f"{ld.now()} building commit {(commit or '-')[:10]}: {len(included)} landing(s), "
              f"{sum(r['kind'] == 'interface' for r in included)} of them interface", flush=True)
        t0 = time.time()
        with open(LOG, "w") as log:
            proc = subprocess.Popen(["nice", "-n", "19", "lake", "build"], cwd=CLONE, stdout=log, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, LEAN_NUM_THREADS=THREADS), start_new_session=True)
            restart = False
            while proc.poll() is None:
                time.sleep(POLL)
                if has_interface or retry:
                    continue
                new = [r for r in ld.records(ld.REQUESTS) if r["id"] not in ids and r["kind"] == "interface"]
                if new:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    preempted += 1; restart = True
                    print(f"{ld.now()} interface landing {new[0]['id']} of {new[0]['group']} arrived: "
                          f"starting over", flush=True)
        if restart:
            continue
        break

    text = LOG.read_text(errors="ignore")
    shutil.copy2(LOG, ld.LOCAL / "build.log")
    errors = [x for x in text.split("\n") if x.startswith("error")]
    built = proc.returncode == 0 and not errors and "Build completed successfully" in text
    result = {"time": ld.now(), "commit": commit, "seconds": round(time.time() - t0), "restarts": preempted}
    if built:
        publish()
        close_verified(included, commit)
        result.update(result="green", verified=sorted(ids))
        ld.write_json(ld.B / "last.json", result)
        print(f"GREEN in {result['seconds']} s; {len(ids)} landing(s) verified; compiled files published.")
        return 0
    failing = failing_modules(text)
    sus = suspects(failing, included)
    result.update(result="red", failing=failing, errors=errors[:30], suspects=sus, included=sorted(ids))
    ld.write_json(ld.B / "last.json", result)
    print(f"RED in {result['seconds']} s; nothing published. Failing: {' '.join(failing[:12]) or '-'}")
    for x in errors[:12]:
        print("  " + x[:300])
    if sus:
        print("Landings that may have caused it, most likely first:")
        for s in sus[:12]:
            print(f"  {s['id']}  {s['kind']:9} {s['group']:6} {' '.join(s['modules'][:4])}"
                  + (f"  -> fails {' '.join(s['fails'][:3])}" if s["fails"] else ""))
    print("Make it green (roles/maintainer.md §2) and run tools/build.py --retry.")
    if sus:
        print("To give a landing back: tools/landing.py revert <id> <reason>.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
