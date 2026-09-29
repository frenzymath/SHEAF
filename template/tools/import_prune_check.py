#!/usr/bin/env python3
"""Check a change to one module against what other modules rely on. Run by land.sh and land_set.sh.

A single-file compile of the changed module cannot see its effect on other modules: they still load its old .olean.
This static check refuses (exit 3) a change that
  1. removes imports, when some downstream module reached a module only through them and uses a declaration from it;
  2. removes or renames a declaration that a downstream module still uses;
  3. adds a declaration whose global name another module already declares (a module importing both then fails with
     `environment already contains`);
  4. adds an import that closes an import cycle;
  5. adds a theorem whose statement another module already states word for word (whitespace aside; statements of
     at least 40 characters), under whatever name: the same fact would then be proved twice.

Usage: tools/import_prune_check.py <module> <old file> <new file>      (an empty or missing old file: a new module)
Exit 0: nothing found. Exit 3: findings printed. Exit 2: usage error.
Uses are found textually: `h.foo` dot notation and names reached only through `open … in` are not seen, and names
shorter than 6 characters are ignored. It is a safety net, not a proof; the global build is the proof.
"""
from __future__ import annotations
import collections, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402


def uses_name(text: str, seg: str, qnames: set[str]) -> bool:
    """Does `text` use a declaration with final segment `seg` and one of the qualified names `qnames`?
    A qualified use counts when its prefix is a suffix of the namespace; a bare use counts only when the text
    enters or opens that namespace (otherwise a Mathlib lemma of the same short name would be mistaken for it)."""
    namespaces = {q.rsplit(".", 1)[0] if "." in q else "" for q in qnames}
    suffixes = set()
    for q in qnames:
        parts = q.split(".")[:-1]
        for k in range(len(parts)):
            suffixes.add(".".join(parts[k:]))
    entered = re.findall(r"^\s*namespace\s+([\w.']+)", text, re.M)
    opened = set()
    for line in re.findall(r"^\s*open\s+(.*)$", text, re.M):
        for tok in line.replace(" in", " ").split():
            if tok not in ("scoped", "in") and re.match(r"^[\w.']+$", tok):
                opened.add(tok)

    def bare_ok(ns: str) -> bool:
        if ns == "" or any(n == ns or n.startswith(ns + ".") for n in entered):
            return True
        for o in opened:
            if ns == o:
                return True
            if ns.endswith("." + o):
                rest = ns[: -len(o) - 1]
                if any(n == rest or n.startswith(rest + ".") for n in entered):
                    return True
        return False

    bare_allowed = any(bare_ok(ns) for ns in namespaces)
    for m in re.finditer(r"((?:[A-Za-z_][\w']*\.)*)" + re.escape(seg) + r"(?![\w'])", text):
        if m.start() > 0 and re.match(r"[\w.']", text[m.start() - 1]):
            continue
        prefix = m.group(1)
        if prefix == "":
            if bare_allowed:
                return True
        elif prefix[:-1] in suffixes:
            return True
    return False


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__); return 2
    mod, old_f, new_f = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    old_text = old_f.read_text(errors="ignore") if old_f.is_file() else ""
    new_text = new_f.read_text(errors="ignore") if new_f.is_file() else ""
    old_imports, new_imports = li.imports_of(old_text), li.imports_of(new_text)
    removed = old_imports - new_imports
    added_imports = new_imports - old_imports
    old_decls, new_decls = li.decls_in_text(old_text), li.decls_in_text(new_text)
    removed_decls = {q for q in old_decls - new_decls if len(q.rsplit(".", 1)[-1]) >= 6}
    added_decls = new_decls - old_decls
    old_stmts = set(li.statements_in_text(old_text).values())
    new_stmts = {q: s for q, s in li.statements_in_text(new_text).items() if len(s) >= 40 and s not in old_stmts}
    if not (removed or removed_decls or added_decls or added_imports or new_stmts):
        return 0
    decls, imports = li.scan()
    imports[mod] = new_imports

    memo: dict = {}
    cyclic = sorted(d for d in added_imports if d == mod or mod in li.closure(d, imports, memo))
    if cyclic:
        print(f"{mod}: the added import(s) {', '.join(cyclic)} already import {mod}, which makes an import cycle.")
        print("Move the shared declarations into a module both can import, or reverse the dependency.")
        return 3

    latent = sorted((q, sorted(decls[q] - {mod})) for q in added_decls if decls.get(q, set()) - {mod})
    if latent:
        print(f"{mod} declares names that other modules already declare:")
        for q, ms in latent:
            print(f"  {q}: also in {', '.join(ms)}")
        print("Import and reuse the existing declaration. Renaming yours only hides the collision and leaves the same "
              "fact proved twice; rename only when the two declarations say different things.")
        return 3

    if new_stmts:
        lib = li.library_statements()
        twice = sorted((q, sorted(f"{n} in {m}" for n, m in lib.get(s, ()) if m != mod))
                       for q, s in new_stmts.items())
        twice = [(q, o) for q, o in twice if o]
        if twice:
            print(f"{mod} proves statements that the library already states word for word:")
            for q, o in twice:
                print(f"  {q}: same statement as {', '.join(o[:3])}")
            print("Import and use the existing theorem instead of proving it again, or generalize it in place. If the two "
                  "texts mean different things through different `variable`s or `open`s, state those binders explicitly.")
            return 3
    if not (removed or removed_decls):
        return 0

    qnames_by_module = collections.defaultdict(set)
    for q, ms in decls.items():
        if len(q.rsplit(".", 1)[-1]) >= 6:
            for m in ms:
                qnames_by_module[m].add(q)
    new_segs = {q.rsplit(".", 1)[-1] for q in new_decls}
    old_graph = dict(imports); old_graph[mod] = old_imports
    memo_new, memo_old = {}, {}
    dependents = li.downstream({mod}, imports)
    hits, decl_hits = [], []
    for i in sorted(dependents):
        p = li.file_of(i)
        if not p.is_file():
            continue
        text = li.strip(p.read_text(errors="ignore"))
        reach = li.closure(i, imports, memo_new)
        still = set(qnames_by_module.get(i, set()))
        for r in reach:
            still |= qnames_by_module.get(r, set())
        lost = li.closure(i, old_graph, memo_old) - reach
        for lm in sorted(lost):
            for q in sorted(qnames_by_module.get(lm, set())):
                if q not in still and uses_name(text, q.rsplit(".", 1)[-1], {q}):
                    hits.append((i, lm, q))
        for q in sorted(removed_decls):
            seg = q.rsplit(".", 1)[-1]
            others = decls.get(q, set()) - {mod}
            if seg in new_segs or any(o in reach | {i} for o in others):
                continue
            if uses_name(text, seg, {q}):
                decl_hits.append((i, q))
    if not hits and not decl_hits:
        return 0
    if hits:
        print(f"{mod} removes import(s) {', '.join(sorted(removed))}; these modules would lose declarations they use:")
        by = collections.defaultdict(list)
        for i, lm, q in hits:
            by[i].append(f"{q} (from {lm})")
        for i in sorted(by):
            print(f"  {i}: {'; '.join(by[i][:6])}")
        print("Keep the import, or add the direct import to each listed module in the same landing (land_set.sh).")
    if decl_hits:
        print(f"{mod} removes or renames declarations that these modules still use:")
        by2 = collections.defaultdict(set)
        for i, q in decl_hits:
            by2[i].add(q)
        for i in sorted(by2):
            print(f"  {i}: {', '.join(sorted(by2[i])[:6])}")
        print("Keep the old name (an alias `theorem old := new` is enough), or update each listed module in the same landing (land_set.sh).")
    return 3


if __name__ == "__main__":
    sys.exit(main())
