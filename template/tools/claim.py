#!/usr/bin/env python3
"""Claims: which group is working on which module, so that no two agents work on the same one.

Usage:
  tools/claim.py next <group> [--count N]      claim up to N items from the head of coord/queue.tsv; prints one module per line
  tools/claim.py take <group> <module>         claim a given module (also before changing someone else's statement)
  tools/claim.py renew <group> <module>        keep a claim alive during long work
  tools/claim.py done <group> <module> <note>  delivered; if the module still has `sorry`, it goes back to the queue
  tools/claim.py release <group> <module> <reason>   give the item back, stuck or abandoned
  tools/claim.py mine <group> | list           the group's claims | all claims with their age
  tools/claim.py expire                        release every claim not renewed for SHEAF_CLAIM_TTL hours (the maintainer)

A claim is the file coord/claims/<module>.lock, created atomically, so two agents can never both obtain it.
A group holds at most SHEAF_CLAIMS_PER_GROUP claims (default 10). A claim not renewed for SHEAF_CLAIM_TTL hours
(default 6) may be taken over by anyone; the takeover is serialized so only one agent gets it.
Every `done` and `release` is recorded in coord/deliveries.log.
"""
from __future__ import annotations
import fcntl, json, os, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402

WORK = li.ROOT / "coord"
C = WORK / "claims"
CFG = li.config()
LIMIT = int(CFG.get("SHEAF_CLAIMS_PER_GROUP", "10"))
TTL = float(CFG.get("SHEAF_CLAIM_TTL", "6")) * 3600


def lock(m): return C / (m.replace("/", "__") + ".lock")


def read(m):
    try:
        return json.loads(lock(m).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def expired(r) -> bool:
    return r is not None and time.time() - r.get("t", 0) > TTL


def create(m, who):
    fd = os.open(lock(m), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"who": who, "t": time.time(), "since": time.strftime("%FT%TZ", time.gmtime())}))


def held_by(who):
    return [p.stem.replace("__", "/") for p in sorted(C.glob("*.lock")) if (read(p.stem.replace("__", "/")) or {}).get("who") == who and not expired(read(p.stem.replace("__", "/")))]


def log(line):
    with open(WORK / "deliveries.log", "a") as f:
        f.write(time.strftime("%FT%TZ", time.gmtime()) + " " + line + "\n")


def sorries(m):
    p = li.file_of(m)
    return li.sorry_count(p.read_text(errors="ignore")) if p.is_file() else None


def take(who, m, quiet=False) -> bool:
    if len(held_by(who)) >= LIMIT:
        if not quiet:
            print(f"{who} already holds {LIMIT} claims; deliver or release one first")
        return False
    try:
        create(m, who); print(m); return True
    except FileExistsError:
        pass
    with open(C / ".takeover", "w") as g:
        fcntl.flock(g, fcntl.LOCK_EX)
        r = read(m)
        if expired(r):
            lock(m).unlink(missing_ok=True)
            log(f"{who} took over the expired claim of {r.get('who')} on {m}")
            try:
                create(m, who); print(m); return True
            except FileExistsError:
                pass
    if not quiet:
        r = read(m) or {}
        print(f"taken by {r.get('who', '?')} since {r.get('since', '?')}")
    return False


def queue():
    q = WORK / "queue.tsv"
    if not q.exists():
        raise SystemExit("no coord/queue.tsv yet; the maintainer writes it after each build")
    rows = [l.split("\t") for l in q.read_text().splitlines() if l and not l.startswith("#")]
    return [r[0] for r in rows]


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    C.mkdir(parents=True, exist_ok=True)
    cmd = a[0]
    if cmd == "next":
        who = a[1]; n = int(a[a.index("--count") + 1]) if "--count" in a else 1
        n = min(n, LIMIT - len(held_by(who)))
        got = 0
        for m in queue():
            if got >= n:
                break
            if sorries(m) == 0:  # finished since the queue was written
                continue
            r = read(m)
            if (r is None or expired(r)) and take(who, m, quiet=True):
                got += 1
        if got == 0:
            print("nothing to claim" if n > 0 else f"{who} already holds {LIMIT} claims")
    elif cmd == "take":
        return 0 if take(a[1], a[2]) else 1
    elif cmd == "renew":
        r = read(a[2])
        if r and r["who"] == a[1]:
            r["t"] = time.time(); tmp = C / f".{a[2]}.{os.getpid()}"
            tmp.write_text(json.dumps(r)); os.replace(tmp, lock(a[2])); print("renewed")
        else:
            print("not your claim"); return 1
    elif cmd in ("done", "release"):
        who, m, note = a[1], a[2], " ".join(a[3:])
        r = read(m)
        if not r or r["who"] != who:
            print("not your claim"); return 1
        left = sorries(m)
        lock(m).unlink(missing_ok=True)
        if cmd == "done":
            log(f"{who} done {m} (sorry left: {left}) {note}")
            print("done" + (f"; {left} sorry left, so the module returns to the queue" if left else ""))
        else:
            log(f"{who} released {m}: {note}")
            print("released")
    elif cmd == "mine":
        print("\n".join(held_by(a[1])))
    elif cmd == "list":
        for p in sorted(C.glob("*.lock")):
            r = read(p.stem.replace("__", "/")) or {}
            age = (time.time() - r.get("t", 0)) / 3600
            print(f"{p.stem.replace("__", "/")}\t{r.get('who')}\t{r.get('since')}\t{age:.1f} h" + ("\texpired" if expired(r) else ""))
    elif cmd == "expire":
        for p in sorted(C.glob("*.lock")):
            r = read(p.stem.replace("__", "/"))
            if expired(r):
                p.unlink(missing_ok=True); log(f"expired the claim of {r.get('who')} on {p.stem.replace("__", "/")}"); print(p.stem.replace("__", "/"))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
