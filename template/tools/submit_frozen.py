#!/usr/bin/env python3
"""Submit command of the second and the third layout of skills/compiling/SKILL.md, where the statements in the
library are frozen. A sketch, written quickly: change it to fit the project, as long as the skill's rules hold.

Usage:
  tools/submit_frozen.py [--pr] <group> <sandbox lean directory> <file under lean/>...

- A file that exists in the library may change only its proofs and add declarations (leanindex.interface_changes
  finds nothing); new files may hold anything.
- The files are compiled in the sandbox, in the order of their imports, against the library's compiled files, each
  within SHEAF_FILE_TIMEOUT; the compiled files of the delivery come first on the path, so a new file sees the others.
  The sandbox mirrors the paths under lean/, so each file compiles under the module name it will have.
- Then, under a lock, the sources go into the library and their compiled files into the shared build, unless one of
  the library files changed since the compile (refused: start again from the current version).
- A delivery that changes a statement is refused; with --pr (the third layout) it goes instead, as a whole, to the
  managing agent as a pull request (tools/submit_pr.sh), and the command waits for it.

Exit 0: in the library. 1: does not compile, 3: refused, 2: usage.
"""
from __future__ import annotations
import fcntl, hashlib, os, pathlib, shutil, subprocess, sys, tempfile

T = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(T))
import leanindex as li  # noqa: E402


def module(rel: str) -> str:
    return rel[:-len(".lean")].replace("/", ".")


def ordered(src: pathlib.Path, rels: list[str]) -> list[str]:
    mods = {module(r): r for r in rels}
    imps = {m: li.imports_of((src / r).read_text(errors="ignore")) & mods.keys() for m, r in mods.items()}
    out, seen = [], set()

    def visit(m, path=()):
        if m in path:
            raise SystemExit(f"import cycle through {m}")
        if m not in seen:
            for i in sorted(imps[m]):
                visit(i, path + (m,))
            seen.add(m); out.append(mods[m])
    for m in sorted(mods):
        visit(m)
    return out


def digest(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    a = sys.argv[1:]
    pr = bool(a) and a[0] == "--pr"
    a = a[1:] if pr else a
    if len(a) < 3:
        print(__doc__); return 2
    group, src, rels = a[0], pathlib.Path(a[1]).resolve(), a[2:]
    cfg = li.config()
    frozen = []
    for r in rels:
        lib = li.LEAN / r
        if lib.is_file():
            ch = li.interface_changes(lib.read_text(errors="ignore"), (src / r).read_text(errors="ignore"))
            if ch:
                frozen.append(f"{r}: {', '.join(ch)}")
    if frozen:
        if pr:
            os.execv(str(T / "submit_pr.sh"), [str(T / "submit_pr.sh"), group, str(src)] + rels)
        print("Statements in the library are frozen; write a new declaration instead:\n" + "\n".join(frozen))
        return 3

    build = li.LEAN / ".lake" / "build" / "lib" / "lean"
    lp = subprocess.run(["lake", "env", "printenv", "LEAN_PATH"], cwd=li.LEAN, capture_output=True, text=True)
    if lp.returncode:
        print("lake env failed in", li.LEAN); return 2
    before = {r: digest(li.LEAN / r) for r in rels}
    with tempfile.TemporaryDirectory(dir=li.ROOT / "local") as out:
        env = dict(os.environ, LEAN_PATH=out + os.pathsep + lp.stdout.strip(), LEAN_NUM_THREADS="1")
        for r in ordered(src, rels):
            o = pathlib.Path(out) / r[:-len(".lean")]
            o.parent.mkdir(parents=True, exist_ok=True)
            c = subprocess.run(["timeout", cfg.get("SHEAF_FILE_TIMEOUT", "60"), "nice", "-n", "19", "lean",
                                "-R", str(src), "-o", f"{o}.olean", "-i", f"{o}.ilean", str(src / r)],
                               cwd=li.LEAN, env=env, capture_output=True, text=True)
            if c.returncode:
                print(f"{r} does not compile:\n{(c.stdout + c.stderr)[-3000:]}"); return 1
        (li.ROOT / "local").mkdir(exist_ok=True)
        with open(li.ROOT / "local" / "frozen.lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            moved = [r for r in rels if digest(li.LEAN / r) != before[r]]
            if moved:
                print("Changed in the library since the compile; start from the current version: " + " ".join(moved))
                return 3
            for r in rels:
                (li.LEAN / r).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / r, li.LEAN / r)
                stem = pathlib.Path(out) / r[:-len(".lean")]
                for f in stem.parent.glob(stem.name + ".*"):  # .olean, .ilean, and with the module system .olean.server, .olean.private
                    dst = build / f.relative_to(out)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, str(dst) + ".new"); os.replace(str(dst) + ".new", dst)
    print("In the library: " + " ".join(rels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
