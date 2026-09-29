#!/usr/bin/env python3
"""Who depends on a module, and who uses a declaration. Reads sources only; no Lean is run.

Usage:
  tools/downstream.py <Module> [<Module> ...]                modules that import any of them, transitively
  tools/downstream.py <Module> ... --uses <name> [<name> ...]  also: which of those modules mention each name
Options: --direct (direct importers only), --count (only the number), --names (bare list, one line),
         --allow-missing (accept modules that no longer exist).
Use it before changing a statement or definition, to see what must be adapted.
Name matches are textual and whole-word on the last segment of the name, so they over-approximate: read the hits.
"""
from __future__ import annotations
import argparse, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import leanindex as li  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("modules", nargs="+")
    ap.add_argument("--uses", nargs="*", default=[])
    ap.add_argument("--direct", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--allow-missing", action="store_true")
    a = ap.parse_args()
    _, imports = li.scan()
    missing = [m for m in a.modules if m not in imports]
    if missing and not a.allow_missing:
        print("unknown module(s): " + ", ".join(missing), file=sys.stderr)
        return 2
    down = sorted(li.downstream(set(a.modules), imports, a.direct))
    if a.names:
        print(" ".join(down)); return 0
    if a.count:
        print(len(down)); return 0
    print(f"{len(down)} module(s) downstream of {', '.join(a.modules)}" + (" (direct importers)" if a.direct else ""))
    for m in down:
        print("  " + m)
    for name in a.uses:
        pat = re.compile(r"(?<![\w'])" + re.escape(name.split(".")[-1]) + r"(?![\w'])")
        hits = []
        for m in sorted(set(down) | set(a.modules)):
            p = li.file_of(m)
            if p.is_file():
                n = len(pat.findall(li.strip(p.read_text(errors="ignore"))))
                if n:
                    hits.append((m, n))
        print(f"uses of {name}: {len(hits)} module(s)")
        for m, n in hits:
            print(f"  {m} ({n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
