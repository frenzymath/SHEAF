#!/usr/bin/env python3
"""The work queue: the open items of every open stage, and what the targets need. Reads sources only; no Lean is run.

Usage:
  tools/queue.py write        write coord/queue.tsv and coord/queue.md (the maintainer, after each build)
  tools/queue.py summary      how many items each stage has open, how many modules the targets need and how many still contain `sorry`
  tools/queue.py outside      modules outside the targets' import closure, one per line

Stages 1 and 2 are read from the DAG by dag_queue.py: the nodes still to split, and the nodes that can be stated
because every node their statement needs is stated. Stage 3 is read from the Lean code: the targets are the
library modules imported by lean/TargetsCheck.lean, the active set is their import closure, and the items are
the active modules that still contain `sorry` or `admit`, in this order:
  1. modules listed in coord/repairs.txt (proofs the maintainer replaced by `sorry` to make a red build green),
  2. modules containing `STATEMENT-DISPUTED`,
  3. the rest, nearest to a target first (distance = fewest import steps from a target module).
A module whose proof would use a node that has no Lean declaration yet is not an item: it is listed as waiting
until stage 2 has stated that node. A module in the closure may still contain declarations nothing uses: the
closure is an upper bound of what the targets need.

coord/queue.tsv lists stage 3 first, then 2, then 1, so that `claim.py next` without `--stage` takes the proof
nearest to a target when there is one.
"""
from __future__ import annotations
import collections, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402
import dag_queue  # noqa: E402

WORK = li.ROOT / "coord"


def analyse():
    """imports, and the distance of every module the targets reach; empty when the targets are not stated yet."""
    if not li.LEAN.is_dir():
        return {}, {}
    _, imports = li.scan()
    roots = sorted(imports.get("TargetsCheck", set()))
    dist, dq = {}, collections.deque()
    for r in roots:
        dist[r] = 0; dq.append(r)
    while dq:
        x = dq.popleft()
        for i in imports.get(x, ()):
            if i in imports and i not in dist:
                dist[i] = dist[x] + 1; dq.append(i)
    return imports, dist


def stage3(imports, dist, waiting: set[str]):
    repairs = set()
    rp = WORK / "repairs.txt"
    if rp.exists():
        repairs = {l.split()[0] for l in rp.read_text().splitlines() if l.strip() and not l.startswith("#")}
    items, held = [], []
    for m in dist:
        p = li.file_of(m)
        if not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        n = li.sorry_count(text)
        if n == 0:
            continue
        kind = "repair" if m in repairs else "disputed" if "STATEMENT-DISPUTED" in text else "proof"
        if m in waiting and kind == "proof":
            held.append((dist[m], m, n)); continue
        items.append((("repair", "disputed", "proof").index(kind), dist[m], m, n, kind))
    items.sort(); held.sort()
    return items, held


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    imports, dist = analyse()
    lib = {m for m in imports if m not in ("Challenge", "TargetsCheck") and m not in li.library_dirs()} if imports else set()
    if cmd == "outside":
        print("\n".join(sorted(lib - set(dist)))); return 0
    s1, s2, waiting, why = [], [], [], collections.Counter()
    if dag_queue.nodes_dir().is_dir():
        g = dag_queue.Dag(dag_queue.load())
        s1 = g.stage1(); s2, why = g.stage2(); waiting = g.waiting()
    items3, held = stage3(imports, dist, {m for m, _ in waiting})
    if cmd == "summary":
        print(f"stage 1: {len(s1)} nodes to split")
        print(f"stage 2: {len(s2)} nodes to state" + (f"; not open: " + ", ".join(f"{v} {k}" for k, v in why.items()) if why else ""))
        if dist:
            print(f"stage 3: library modules {len(lib)}; needed by the targets {len(dist)}; outside {len(lib - set(dist))}")
            print(f"stage 3: {len(items3)} items (" + ", ".join(f"{k} {sum(1 for x in items3 if x[4] == k)}" for k in ("repair", "disputed", "proof")) + f"); {len(held)} modules waiting for a statement")
        else:
            print("stage 3: not open (lean/TargetsCheck.lean imports no target module yet)")
        return 0
    if cmd != "write":
        print(__doc__); return 2
    WORK.mkdir(exist_ok=True)
    rows = [(m, 3, d, n, k) for _, d, m, n, k in items3]
    rows += [(i, 2, d if d < 10**6 else "-", "", "target-statement" if pri == 0 else "state") for pri, d, i in s2]
    rows += [(i, 1, d if d < 10**6 else "-", "", "split") for d, i in s1]
    with open(WORK / "queue.tsv", "w") as f:
        f.write("# item\tstage\tdistance\tsorry\tkind\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    with open(WORK / "queue.md", "w") as f:
        f.write(f"# Work queue\n\n{len(rows)} items; claim with `tools/claim.py next <group> [--stage N]`.\n\n")
        f.write(f"## Stage 3: modules to prove ({len(items3)})\n\n")
        if items3:
            f.write("| module | distance to a target | sorry | kind |\n|---|---|---|---|\n")
            for _, d, m, n, k in items3:
                f.write(f"| `{m}` | {d} | {n} | {k} |\n")
        if held:
            f.write(f"\nWaiting, not claimable: {len(held)} modules whose proof uses a node that has no Lean declaration yet.\n\n")
            f.write("| module | distance to a target | sorry |\n|---|---|---|\n")
            for d, m, n in held:
                f.write(f"| `{m}` | {d} | {n} |\n")
        f.write(f"\n## Stage 2: nodes to state ({len(s2)})\n\n")
        if s2:
            f.write("| node | distance to a target | kind |\n|---|---|---|\n")
            for pri, d, i in s2:
                f.write(f"| `{i}` | {d if d < 10**6 else '-'} | {'target-statement' if pri == 0 else 'state'} |\n")
        if why:
            f.write("\nNot open yet: " + ", ".join(f"{v} nodes that {k.replace('waits', 'wait')}" for k, v in why.items()) + ".\n")
        f.write(f"\n## Stage 1: nodes to split ({len(s1)})\n\n")
        if s1:
            f.write("| node | distance to a target |\n|---|---|\n")
            for d, i in s1:
                f.write(f"| `{i}` | {d if d < 10**6 else '-'} |\n")
    print(f"wrote {len(rows)} items to coord/queue.tsv and coord/queue.md (stage 3: {len(items3)}, waiting {len(held)}; stage 2: {len(s2)}; stage 1: {len(s1)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
