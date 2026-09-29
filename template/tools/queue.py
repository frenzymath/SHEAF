#!/usr/bin/env python3
"""The work queue, and what the targets need. Reads sources only; no Lean is run.

Usage:
  tools/queue.py write        write coord/queue.tsv and coord/queue.md (the maintainer, after each build)
  tools/queue.py summary      how many modules the targets need, and how many of those still contain `sorry`
  tools/queue.py outside      modules outside the targets' import closure, one per line (stage 5 deletes them)

The targets are the library modules imported by lean/TargetsCheck.lean; the active set is their import closure.
The items are the active modules that still contain `sorry` or `admit`, in this order:
  1. modules listed in coord/repairs.txt (proofs the maintainer replaced by `sorry` to make a red build green),
  2. modules containing `STATEMENT-DISPUTED`,
  3. the rest, nearest to a target first (distance = fewest import steps from a target module).
A module in the closure may still contain declarations nothing uses: the closure is an upper bound of what the targets need.
"""
from __future__ import annotations
import collections, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402

WORK = li.ROOT / "coord"


def analyse():
    _, imports = li.scan()
    roots = sorted(imports.get("TargetsCheck", set()))
    if not roots:
        raise SystemExit("lean/TargetsCheck.lean imports no target module yet")
    dist, dq = {}, collections.deque()
    for r in roots:
        dist[r] = 0; dq.append(r)
    while dq:
        x = dq.popleft()
        for i in imports.get(x, ()):
            if i in imports and i not in dist:
                dist[i] = dist[x] + 1; dq.append(i)
    return imports, dist


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    imports, dist = analyse()
    lib = {m for m in imports if m not in ("Challenge", "TargetsCheck") and m not in li.library_dirs()}  # root files are not library modules
    if cmd == "outside":
        print("\n".join(sorted(lib - set(dist)))); return 0
    repairs = set()
    rp = WORK / "repairs.txt"
    if rp.exists():
        repairs = {l.split()[0] for l in rp.read_text().splitlines() if l.strip() and not l.startswith("#")}
    items = []
    for m in dist:
        p = li.file_of(m)
        if not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        n = li.sorry_count(text)
        if n == 0:
            continue
        kind = "repair" if m in repairs else "disputed" if "STATEMENT-DISPUTED" in text else "proof"
        items.append((("repair", "disputed", "proof").index(kind), dist[m], m, n, kind))
    items.sort()
    if cmd == "summary":
        print(f"library modules: {len(lib)}; needed by the targets: {len(dist)}; outside: {len(lib - set(dist))}")
        print(f"items: {len(items)} (" + ", ".join(f"{k} {sum(1 for x in items if x[4] == k)}" for k in ("repair", "disputed", "proof")) + ")")
        return 0
    if cmd != "write":
        print(__doc__); return 2
    WORK.mkdir(exist_ok=True)
    with open(WORK / "queue.tsv", "w") as f:
        f.write("# module\tdistance\tsorry\tkind\n")
        for _, d, m, n, k in items:
            f.write(f"{m}\t{d}\t{n}\t{k}\n")
    with open(WORK / "queue.md", "w") as f:
        f.write(f"# Work queue\n\n{len(items)} items; claim with `tools/claim.py next <group>`.\n\n")
        f.write("| module | distance to a target | sorry | kind |\n|---|---|---|---|\n")
        for _, d, m, n, k in items:
            f.write(f"| `{m}` | {d} | {n} | {k} |\n")
    print(f"wrote {len(items)} items to coord/queue.tsv and coord/queue.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
