"""Reading Lean sources without running Lean: a lexer, declarations, imports and closures.

Used by the other Python tools. The lexer knows nested block comments, string and character literals,
so comment handling is exact; declaration names are recovered from `namespace`/`section`/`end` and are
right for ordinary code but not for names produced by macros.
"""
from __future__ import annotations
import collections, os, pathlib, re, shlex, unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEAN = (ROOT / "lean").resolve()
COMMENT_KINDS = ("line", "block", "doc", "moddoc")


def config() -> dict[str, str]:
    cfg = {}
    import socket
    for p in (ROOT / "coord" / "sheaf.env", ROOT / "coord" / "machines" / f"{socket.gethostname()}.env"):
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = " ".join(shlex.split(v))
    cfg.update({k: v for k, v in os.environ.items() if k.startswith("SHEAF_")})
    return cfg


def library_dirs() -> list[str]:
    lib = config().get("SHEAF_LIB", "")
    if not lib:
        raise SystemExit("set SHEAF_LIB in coord/sheaf.env")
    return lib.split()


# ---------------------------------------------------------------- lexer

class LexError(Exception):
    pass


def _ident_cont(c: str) -> bool:
    return c in "_'!?" or unicodedata.category(c)[0] in "LN"


_CHAR = re.compile(r"'(\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|[\\\"'ntr0])|[^\\'\n])'")


def lex(s: str) -> list[tuple[str, int, int]]:
    """Split source into segments (kind, start, end); kinds: code, ws, string, char, line, block, doc, moddoc."""
    segs, i, n, start = [], 0, len(s), None

    def flush(upto):
        nonlocal start
        if start is not None and start < upto:
            segs.append(("code", start, upto))
        start = None

    while i < n:
        c = s[i]
        if c in " \t\r\n":
            flush(i); j = i
            while j < n and s[j] in " \t\r\n":
                j += 1
            segs.append(("ws", i, j)); i = j; continue
        if s.startswith("--", i):
            flush(i); j = s.find("\n", i); j = n if j == -1 else j
            segs.append(("line", i, j)); i = j; continue
        if s.startswith("/-", i):
            flush(i)
            kind = "doc" if s.startswith("/--", i) else "moddoc" if s.startswith("/-!", i) else "block"
            depth, j = 1, i + (2 if kind == "block" else 3)
            while depth:
                if j >= n:
                    raise LexError(f"unterminated comment at {i}")
                if s.startswith("/-", j):
                    depth += 1; j += 2
                elif s.startswith("-/", j):
                    depth -= 1; j += 2
                else:
                    j += 1
            segs.append((kind, i, j)); i = j; continue
        if c == '"':
            flush(i); j = i + 1
            while True:
                if j >= n:
                    raise LexError(f"unterminated string at {i}")
                if s[j] == "\\":
                    j += 2
                elif s[j] == '"':
                    j += 1; break
                else:
                    j += 1
            segs.append(("string", i, j)); i = j; continue
        if c == "'" and not (i > 0 and _ident_cont(s[i - 1])):
            m = _CHAR.match(s, i)
            if m:
                flush(i); segs.append(("char", i, m.end())); i = m.end(); continue
        if c == "«":
            flush(i); j = s.find("»", i)
            if j == -1:
                raise LexError(f"unterminated « at {i}")
            segs.append(("code", i, j + 1)); i = j + 1; continue
        if start is None:
            start = i
        i += 1
    flush(n)
    return segs


def strip(s: str) -> str:
    """The source with every comment replaced by a space."""
    return "".join(" " if k in COMMENT_KINDS else s[a:b] for k, a, b in lex(s))


def tokens(s: str) -> list[str]:
    """Code tokens: comments and whitespace removed, comments acting as separators."""
    out, cur = [], []
    for k, a, b in lex(s):
        if k == "ws" or k in COMMENT_KINDS:
            if cur:
                out.append("".join(cur)); cur = []
        else:
            cur.append(s[a:b])
    if cur:
        out.append("".join(cur))
    return out


def sorry_count(s: str) -> int:
    code = strip(s)
    code = "".join(" " if k in ("string", "char") else code[a:b] for k, a, b in lex(code))
    return len(re.findall(r"(?<![\w.'])(?:sorry|admit)(?![\w'])", code))


# ---------------------------------------------------------------- declarations and imports

_DECL = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?!.*\bprivate\b)(?:protected\s+|noncomputable\s+|local\s+|scoped\s+|unsafe\s+|partial\s+)*"
    r"(?:def|theorem|lemma|instance|abbrev|structure|class|inductive|opaque)\s+([^\s({\[:⦃]+)", re.M)
_IMPORT = re.compile(r"^import\s+([\w.']+)", re.M)


def imports_of(text: str) -> set[str]:
    return set(_IMPORT.findall(strip(text)))


def decls_in_text(text: str) -> set[str]:
    """Namespace-qualified names of the non-private declarations in one source text."""
    out, stack = set(), []
    for line in strip(text).split("\n"):
        m = re.match(r"\s*namespace\s+([^\s]+)", line)
        if m:
            stack.append(("ns", m.group(1))); continue
        if re.match(r"\s*(?:noncomputable\s+)?section\b", line):
            stack.append(("sec", None)); continue
        if re.match(r"\s*end\b", line):
            if stack:
                stack.pop()
            continue
        mm = _DECL.match(line)
        if mm:
            name = mm.group(1).removeprefix("_root_.")
            ns = [n for k, n in stack if k == "ns"]
            out.add(".".join(ns + [name]) if ns and not mm.group(1).startswith("_root_.") else name)
    return out


_KW = r"(?:def|theorem|lemma|instance|abbrev|structure|class|inductive|opaque|axiom|example)"
_MODS = r"(?:private|protected|noncomputable|nonrec|unsafe|partial|local|scoped|public)"
_HEAD = re.compile(rf"^((?:@\[[^\]]*\]\s*)*)((?:{_MODS}\s+)*)({_KW})\b\s*(.*)$")
_CONT = re.compile(r"^(?:\||where\b|termination_by\b|decreasing_by\b|deriving\b|with\b|[)}\]⟩])")


def commands(text: str) -> list[dict]:
    """The top-level commands of a source text, in order. Each is a dict with
    kind: a declaration keyword, or 'other' (`variable`, `open`, `notation`, `attribute`, `set_option`, …);
    name: the qualified name ('' for an anonymous instance and for 'other'); private: bool;
    head: attributes, modifiers and a preceding `open … in`; text: the whole command, whitespace collapsed;
    statement: for a declaration, the binders and type between the name and `:=`.
    `namespace`, `section` and `end` only set the names."""
    out, stack, cur, pending = [], [], None, []

    def close():
        nonlocal cur
        if cur is not None:
            body = " ".join(" ".join(cur.pop("lines")).split())
            cur["text"] = body
            if cur["kind"] != "other":
                cut = re.search(r"\s:=|\swhere\b|\s\|\s|:=\s*$", " " + body)
                cur["statement"] = (body[: cut.start() - 1] if cut else body).strip()
            out.append(cur)
        cur = None

    for line in strip(text).split("\n"):
        if not line.strip():
            continue
        if line[0].isspace():
            if cur is not None:
                cur["lines"].append(line)
            continue
        m = re.match(r"namespace\s+(\S+)", line)
        if m:
            close(); stack.append(("ns", m.group(1))); continue
        if re.match(r"(?:noncomputable\s+)?section\b", line):
            close(); stack.append(("sec", None)); continue
        if re.match(r"end\b", line):
            close()
            if stack:
                stack.pop()
            continue
        if re.match(r"@\[[^\]]*\]\s*$", line) or re.match(r"open\b.*\sin\s*$", line):
            close(); pending.append(line.strip()); continue
        if re.match(r"set_option\b.*\sin\s*$", line):
            close(); continue  # affects only how the next declaration is checked
        h = _HEAD.match(line)
        if h:
            close()
            attrs, mods, kind, rest = h.groups()
            name = ""
            n = re.match(r"([^\s({\[:⦃]+)(.*)$", rest)
            if n and not (kind == "instance" and rest[:1] in ":([{⦃"):
                name, rest = n.group(1), n.group(2)
                ns = [x for k, x in stack if k == "ns"]
                name = name.removeprefix("_root_.") if name.startswith("_root_.") or not ns else ".".join(ns + [name])
            cur = {"kind": kind, "name": name, "private": "private" in mods.split(),
                   "head": " ".join(pending + [attrs.strip(), mods.strip()]).strip(), "lines": [rest]}
            pending = []
            continue
        if cur is not None and cur["kind"] != "other" and _CONT.match(line):
            cur["lines"].append(line); continue
        close()
        cur = {"kind": "other", "name": "", "private": False, "head": "", "lines": [line]}
    close()
    return out


def statements_in_text(text: str) -> dict[str, str]:
    """Theorems and lemmas of one source text, private ones included: qualified name -> statement."""
    return {c["name"]: c["statement"] for c in commands(text) if c["kind"] in ("theorem", "lemma") and c["name"]}


def interface(text: str) -> dict[str, str]:
    """What the modules importing this one can see: for a theorem its head and statement, for any other declaration
    its whole text, plus the imports and the other commands. Proof bodies, private declarations and comments are not
    part of it."""
    out, other = {"#imports": " ".join(sorted(imports_of(text)))}, []
    for c in commands(text):
        if c["kind"] == "other":
            if not c["text"].startswith("import "):
                other.append(c["text"])
        elif c["private"] or c["kind"] == "example":
            continue
        elif c["kind"] in ("theorem", "lemma"):
            out[c["name"]] = c["head"] + " | " + c["statement"]
        else:
            key = c["name"] or f"instance {c['statement']}"
            out[key] = c["head"] + " | " + c["kind"] + " " + c["text"]
    out["#commands"] = "\n".join(other)
    return out


def interface_changes(old: str, new: str) -> list[str]:
    """What a change to a module changes for the modules importing it; empty when only proofs changed or plain
    declarations were added. Listed: a declaration removed or changed in what `interface` records, a declaration
    added with an attribute or as an instance (it changes elaboration downstream), a removed import, and a change
    in the other commands."""
    a, b = interface(old), interface(new)
    out = [k for k in a if not k.startswith("#") and (k not in b or a[k] != b[k])]
    out += [k for k in b if not k.startswith("#") and k not in a
            and (b[k].split(" | ")[0].strip() or b[k].split(" | ")[1].startswith("instance"))]
    if set(a["#imports"].split()) - set(b["#imports"].split()):
        out.append("(imports removed)")
    if a["#commands"] != b["#commands"]:
        out.append("(commands such as variable, open, notation or attribute)")
    return out


def library_statements() -> dict[str, set[tuple[str, str]]]:
    """statement -> {(qualified name, module)} over the whole library, for finding a fact proved twice."""
    out = collections.defaultdict(set)
    for p in library_files():
        mod = module_of(p)
        if mod in ("Challenge", "TargetsCheck"):
            continue
        try:
            text = p.read_text(errors="ignore")
        except FileNotFoundError:
            continue
        for q, s in statements_in_text(text).items():
            if s:
                out[s].add((q, mod))
    return out


def module_of(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(LEAN).with_suffix("").parts)


def file_of(mod: str) -> pathlib.Path:
    return LEAN / pathlib.Path(*mod.split(".")).with_suffix(".lean")


def library_files():
    for d in library_dirs():
        base = LEAN / d
        if base.is_dir():
            yield from sorted(base.rglob("*.lean"))
        if (LEAN / f"{d}.lean").is_file():
            yield LEAN / f"{d}.lean"
    for root in ("Challenge", "TargetsCheck"):
        if (LEAN / f"{root}.lean").is_file():
            yield LEAN / f"{root}.lean"


def scan():
    """decls: qualified name -> {modules declaring it}; imports: module -> {imported modules}."""
    decls, imports = collections.defaultdict(set), {}
    for p in library_files():
        try:
            text = p.read_text(errors="ignore")
        except FileNotFoundError:
            continue
        mod = module_of(p)
        if mod != "Challenge":  # it restates the targets under their own names on purpose
            for q in decls_in_text(text):
                decls[q].add(mod)
        imports[mod] = imports_of(text)
    return decls, imports


def closure(mod: str, imports: dict, memo: dict) -> set[str]:
    """Modules imported by `mod`, transitively (not including `mod`)."""
    if mod in memo:
        return memo[mod]
    memo[mod] = set()
    out = set()
    for i in imports.get(mod, ()):
        out.add(i); out |= closure(i, imports, memo)
    memo[mod] = out
    return out


def downstream(mods: set[str], imports: dict, direct: bool = False) -> set[str]:
    """Modules that import any of `mods` (transitively unless `direct`)."""
    users = collections.defaultdict(set)
    for m, imps in imports.items():
        for i in imps:
            users[i].add(m)
    out, stack = set(), list(mods)
    while stack:
        for u in users.get(stack.pop(), ()):
            if u not in out:
                out.add(u)
                if not direct:
                    stack.append(u)
    return out - set(mods)
