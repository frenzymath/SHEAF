#!/usr/bin/env python3
"""The items of stages 1 and 2, read from the DAG, and the modules that stage 3 must still wait for.

Usage:
  tools/dag_queue.py summary      how many nodes each stage has open, and why the others are not open
  tools/dag_queue.py items        the open items, one per line: stage, item, distance (to a target in stage 1, to Mathlib in stage 2), kind
  tools/dag_queue.py waiting      modules whose proof uses a node that has no Lean declaration yet, one per line

`queue.py write` calls this and puts the items into coord/queue.tsv; run this by hand only to look.

What is open follows the stage documents. A node is open for

  stage 1  when it is a statement that is not a Mathlib leaf and has no proof in steps yet
           (it is still to be split); nearest to a target first;
  stage 2  when stage 1 is finished with it (it is a definition, or a statement with its proof in steps),
           it has no Lean declaration yet, and every node its statement needs has one or is a Mathlib leaf;
           nearest to Mathlib first (the fewest dependency steps down to a Mathlib leaf), so that the
           statements climb from Mathlib upward. With SHEAF_EARLY_REVIEW=1 in coord/sheaf.env the nodes
           needed to state the targets come first instead.

A module of stage 3 is held back ("waiting") while a node that its proof uses has no Lean declaration: its
proof cannot be written yet. The order of the dependencies is never overridden: no node is stated before the
nodes its statement needs, so stage 2 climbs from Mathlib upward whatever order stage 1 or stage 3 keep.

The DAG layout is the project's own (`stages/1-dag.md` §1 fixes the content, not the field names). The FIELDS
table below lists the names this script accepts for each piece of content; the maintainer adapts it to the
project's layout, as `tools/README.md` says. `SHEAF_DAG` in coord/sheaf.env names the node directory when it is
not `dag/nodes`.
"""
from __future__ import annotations
import collections, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402

# content -> field names tried in order; the first present wins
FIELDS = {
    "id": ("id",),
    "kind": ("kind", "role"),                       # definition / statement / target
    "target": ("target",),                          # true for a target
    "status": ("status",),                          # 'mathlib' (a leaf), 'split', 'merged', ...
    "mathlib": ("mathlib_match", "mathlib"),        # the Mathlib match of a leaf, if any
    "merged": ("merged_into",),                     # the node this one was merged into
    "stmt_deps": ("stmt_deps", "statement_deps", "deps"),
    "proof_deps": ("proof_deps",),
    "proof": ("proof", "steps"),                    # the proof in steps; each step may list what it uses
    "module": ("module", "lean_module"),            # set when the node has a Lean declaration
    "lean": ("lean",),                              # or a record {module, declaration, ...}
}
DEF_KINDS = {"def", "definition", "stmt", "notion", "structure"}
LEAF_STATUS = {"mathlib", "exact", "adapt"}


def field(d: dict, name: str):
    for f in FIELDS[name]:
        if f in d and d[f] not in (None, "", [], {}):
            return d[f]
    return None


def nodes_dir() -> pathlib.Path:
    p = li.config().get("SHEAF_DAG", "dag/nodes")
    return pathlib.Path(p) if pathlib.Path(p).is_absolute() else li.ROOT / p


def load() -> dict[str, dict]:
    out = {}
    for p in sorted(nodes_dir().rglob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and field(d, "id"):
            out[str(field(d, "id"))] = d
    return out


def is_leaf(d) -> bool:
    st = field(d, "status")
    return str(st).lower() in LEAF_STATUS if st else bool(field(d, "mathlib"))


def is_def(d) -> bool:
    return str(field(d, "kind") or "").lower() in DEF_KINDS


def has_decl(d) -> bool:
    if field(d, "module"):
        return True
    l = field(d, "lean")
    return bool(l.get("module") if isinstance(l, dict) else l)


def module_of(d):
    m = field(d, "module")
    if m:
        return str(m)
    l = field(d, "lean")
    return str(l.get("module")) if isinstance(l, dict) and l.get("module") else None


def unfolded(d) -> bool:
    """Stage 1 is finished with the node: a leaf, a definition, or a statement whose proof is written in steps."""
    if is_leaf(d) or is_def(d):
        return True
    pf = field(d, "proof")
    return bool(pf) and (not isinstance(pf, list) or len(pf) > 0)


def deps_of(d, which: str) -> list[str]:
    out = []
    if which in ("stmt", "all"):
        out += [str(x) for x in (field(d, "stmt_deps") or [])]
    if which in ("proof", "all"):
        out += [str(x) for x in (field(d, "proof_deps") or [])]
        pf = field(d, "proof")
        if isinstance(pf, list):
            for step in pf:
                if isinstance(step, dict):
                    out += [str(x) for x in (step.get("uses") or [])]
    return out


class Dag:
    def __init__(self, nodes: dict[str, dict]):
        self.n = nodes
        self.merged = {i: str(field(d, "merged")) for i, d in nodes.items()
                       if field(d, "merged") or str(field(d, "status") or "").lower() == "merged"}
        self.live = {i: d for i, d in nodes.items() if i not in self.merged}
        self.targets = [i for i, d in self.live.items() if field(d, "target") or str(field(d, "kind") or "").lower() == "target"]
        self.dist = {}
        self.height = {}   # fewest dependency steps down to a Mathlib leaf
        dq = collections.deque((t, 0) for t in self.targets)
        while dq:
            i, k = dq.popleft()
            if i in self.dist:
                continue
            self.dist[i] = k
            for c in deps_of(self.live[i], "all"):
                c = self.resolve(c)
                if c in self.live and c not in self.dist:
                    dq.append((c, k + 1))

    def h(self, i: str, stack=()) -> int:
        if i in self.height:
            return self.height[i]
        d = self.live.get(i)
        if d is None or is_leaf(d):
            return 0
        if i in stack:
            return 10**6
        below = [self.h(c, stack + (i,)) for c in self.deps(i, "all")]
        self.height[i] = 1 + (min(below) if below else 0)
        return self.height[i]

    def resolve(self, i: str) -> str:
        seen = set()
        while i in self.merged and i not in seen:
            seen.add(i); i = self.merged[i]
        return i

    def deps(self, i: str, which: str) -> list[str]:
        return [self.resolve(c) for c in deps_of(self.live[i], which)]

    def stated(self, i: str) -> bool:
        d = self.live.get(i)
        return d is None or is_leaf(d) or has_decl(d)   # a dependency on a missing node is reported by the DAG check, not here

    def stage1(self) -> list[tuple[int, str]]:
        return sorted((self.dist.get(i, 10**6), i) for i, d in self.live.items() if not unfolded(d))

    def target_statement_closure(self) -> set[str]:
        out, st = set(), list(self.targets)
        while st:
            i = st.pop()
            if i in out or i not in self.live:
                continue
            out.add(i); st += self.deps(i, "stmt")
        return out

    def stage2(self) -> tuple[list[tuple[int, int, str]], collections.Counter]:
        """(priority, height, node): nearest to Mathlib first; the targets' statement closure first when the early review is on."""
        why = collections.Counter(); items = []; tsc = self.target_statement_closure()
        early = li.config().get("SHEAF_EARLY_REVIEW", "") not in ("", "0", "no")
        for i, d in self.live.items():
            if is_leaf(d) or has_decl(d):
                continue
            if not unfolded(d):
                why["waits for stage 1"] += 1; continue
            if not all(self.stated(c) for c in self.deps(i, "stmt")):
                why["waits for a statement dependency"] += 1; continue
            items.append((0 if early and i in tsc else 1, self.h(i), i))
        return sorted(items), why

    def waiting(self) -> list[tuple[str, str]]:
        """(module, node it waits for) for every stated node whose proof uses an unstated node."""
        out = []
        for i, d in self.live.items():
            if is_leaf(d) or not has_decl(d) or not module_of(d):
                continue
            for c in self.deps(i, "proof"):
                if not self.stated(c):
                    out.append((module_of(d), c)); break
        return sorted(out)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if not nodes_dir().is_dir():
        raise SystemExit(f"no DAG at {nodes_dir()}")
    g = Dag(load())
    s1 = g.stage1(); s2, why = g.stage2(); w = g.waiting()
    if cmd == "summary":
        print(f"nodes: {len(g.n)} ({len(g.merged)} merged, {sum(1 for d in g.live.values() if is_leaf(d))} Mathlib leaves, "
              f"{len(g.targets)} targets, {sum(1 for i in g.live if i not in g.dist)} not reached from a target)")
        print(f"stage 1 open: {len(s1)} nodes to split")
        print(f"stage 2 open: {len(s2)} nodes to state; not open: " + ", ".join(f"{v} {k}" for k, v in why.items()) if why else f"stage 2 open: {len(s2)} nodes to state")
        print(f"stage 3 waiting: {len(w)} stated modules whose proof uses a node without a declaration")
    elif cmd == "items":
        for dist, i in s1:
            print(f"1\t{i}\t{dist if dist < 10**6 else '-'}\tsplit")
        for pri, hgt, i in s2:
            print(f"2\t{i}\t{hgt}\t{'target-statement' if pri == 0 else 'state'}")
    elif cmd == "waiting":
        for m, c in w:
            print(f"{m}\t{c}")
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
