"""Read the repository and describe what is actually in it.

Everything the map says about code -- files, functions, who calls whom, what each
function touches, which tables it reads and writes -- comes from here, parsed out of the
source. Nothing in this module is typed in by hand. The hand-drawn part (where things
sit, what the routes are called) lives in geography.py, and build.py refuses to render
any of it that this module cannot find.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Matched against a function's own source. Direct I/O only: a function that *calls*
# something which reads the database is not itself marked as reading it -- that shows up
# as a call instead.
TOUCHES = {
    "db": re.compile(
        r"session\.execute|session_scope\(|\bdb\.execute|conn\.execute|Depends\(get_db\)"
        r"|session\.add|session\.commit|SessionLocal\(\)"
    ),
    "http": re.compile(
        r"_get_json\(|httpx\.(get|post|Client)|self\._http\.|smtplib\.SMTP|send_email\("
        r"|\bllm\.call\(|\.kickoff\("
    ),
    "redis": re.compile(
        r"self\._redis|redis\.Redis|_client\(s?\)\.|self\._bucket\(|register_script"
    ),
    "raw": re.compile(
        r"store\.put\(|\.put_object\(|\.get_object\(|write_bytes\(|read_bytes\("
        r"|get_bronze_store\(\)\.put|store\.iter_payloads\("
    ),
    "process": re.compile(r"subprocess\.run"),
}

_WRITE_RX = re.compile(r"(?:insert\s+into|update|delete\s+from)\s+([a-z_][a-z_.]*)", re.I)
_READ_RX = re.compile(r"(?:from|join)\s+([a-z_][a-z_.]*)", re.I)


@dataclass
class Func:
    name: str
    qual: str
    line: int
    end: int
    kind: str  # fn | method | class
    doc: str
    entry: str | None = None
    touches: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # "module:qual", in source order
    call_lines: dict[str, int] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)


@dataclass
class Module:
    path: str
    mod: str
    loc: int
    doc: str
    funcs: dict[str, Func] = field(default_factory=dict)
    imports: set[str] = field(default_factory=set)


def _first_line(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(doc.strip().split("\n\n")[0].split())


def _entry_reason(node: ast.AST, mod: str) -> str | None:
    for dec in getattr(node, "decorator_list", []):
        src = ast.unparse(dec)
        if "shared_task" in src:
            m = re.search(r"name=['\"]([^'\"]+)", src)
            return f"Celery task {m.group(1).rsplit('.', 1)[-1]}" if m else "Celery task"
        m = re.match(r"(app|router)\.(get|post)\(['\"]([^'\"]*)", src)
        if m:
            prefix = "/showcase" if mod.endswith("showcase.routes") else ""
            return f"HTTP {m.group(2).upper()} {prefix}{m.group(3)}"
    name = getattr(node, "name", "")
    if mod == "app.cli" and name.startswith("cmd_"):
        return f"CLI: cpi {name[4:]}"
    if name == "main" and mod in {"app.cli", "app.ui.review"}:
        return "program entry"
    return None


def _resolve_imports(tree: ast.Module, modules: set[str]) -> dict[str, str]:
    """Local name -> 'module:symbol', or 'module:' when the name is a module."""
    names: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
            for a in n.names:
                sub = f"{n.module}.{a.name}"
                names[a.asname or a.name] = f"{sub}:" if sub in modules else f"{n.module}:{a.name}"
    return names


def _tables(text: str, known: set[str]) -> tuple[list[str], list[str]]:
    def clean(name: str) -> str | None:
        name = name.lower().split(".")[-1]
        return name if name in known else None

    writes = {clean(m) for m in _WRITE_RX.findall(text)} - {None}
    reads = {clean(m) for m in _READ_RX.findall(text)} - {None}
    return sorted(reads), sorted(writes)


def extract_tables() -> list[str]:
    tables: set[str] = set()
    for p in (ROOT / "migrations" / "versions").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        tables |= set(re.findall(r"create table (?:if not exists )?([a-z_]+)", text, re.I))
    return sorted(tables)


def extract_dbt() -> dict[str, dict]:
    """dbt models and seeds, their layer, and their ref()/source() edges.

    dbt/dbt_packages is vendored third-party code and is deliberately not read.
    """
    models: dict[str, dict] = {}
    for p in sorted((ROOT / "dbt" / "models").rglob("*.sql")):
        sql = p.read_text(encoding="utf-8")
        comment = next(
            (
                ln.strip().lstrip("-").strip()
                for ln in sql.splitlines()
                if ln.strip().startswith("--")
            ),
            "",
        )
        models[p.stem] = {
            "path": p.relative_to(ROOT).as_posix(),
            "layer": p.parent.name,
            "loc": len(sql.splitlines()),
            "refs": sorted(set(re.findall(r"ref\('([a-z_]+)'\)", sql))),
            "sources": sorted(set(re.findall(r"source\('[a-z_]+',\s*'([a-z_]+)'\)", sql))),
            "doc": comment,
        }
    for p in sorted((ROOT / "dbt" / "seeds").glob("*.csv")):
        models[p.stem] = {
            "path": p.relative_to(ROOT).as_posix(),
            "layer": "seed",
            "loc": len(p.read_text(encoding="utf-8").splitlines()),
            "refs": [],
            "sources": [],
            "doc": "",
        }
    return models


def extract() -> dict[str, Module]:
    paths = sorted(
        p
        for p in (ROOT / "app").rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )
    modules = {".".join(p.relative_to(ROOT).with_suffix("").parts) for p in paths}
    known = set(extract_tables()) | set(extract_dbt())
    out: dict[str, Module] = {}
    for p in paths:
        m = _read_module(p, modules, known)
        out[m.mod] = m
    return out


def _read_module(p: Path, modules: set[str], known: set[str]) -> Module:
    rel = p.relative_to(ROOT).as_posix()
    mod = ".".join(p.relative_to(ROOT).with_suffix("").parts)
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    m = Module(rel, mod, len(src.splitlines()), _first_line(ast.get_docstring(tree)))
    imported = _resolve_imports(tree, modules)
    m.imports = {v.split(":")[0] for v in imported.values()} - {mod}
    top_names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    # Module-level SQL constants, so a function that runs CANDIDATES_SQL is credited
    # with the tables CANDIDATES_SQL reads.
    consts = {
        t.id: ast.get_source_segment(src, n.value) or ""
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id.isupper()
    }

    def add(node, qual, kind, cls_methods=()):
        seg = ast.get_source_segment(src, node) or ""
        f = Func(
            name=node.name,
            qual=qual,
            line=node.lineno,
            end=node.end_lineno or node.lineno,
            kind=kind,
            doc=_first_line(ast.get_docstring(node)),
            entry=_entry_reason(node, mod),
        )
        if kind != "class":
            f.touches = [k for k, rx in TOUCHES.items() if rx.search(seg)]
            found: dict[str, tuple[int, int]] = {}
            for c in ast.walk(node):
                if not isinstance(c, ast.Call):
                    continue
                fn = c.func
                if isinstance(fn, ast.Attribute) and fn.attr in {"delay", "apply_async", "s"}:
                    fn = fn.value
                target = None
                if isinstance(fn, ast.Name):
                    if fn.id in imported and not imported[fn.id].endswith(":"):
                        target = imported[fn.id]
                    elif fn.id in top_names and fn.id != node.name:
                        target = f"{mod}:{fn.id}"
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    base = fn.value.id
                    if base in imported and imported[base].endswith(":"):
                        target = f"{imported[base][:-1]}:{fn.attr}"
                    elif base == "self" and fn.attr in cls_methods:
                        target = f"{mod}:{qual.split('.')[0]}.{fn.attr}"
                if target is None:
                    continue
                pos = (c.lineno, c.col_offset)
                if target not in found or pos < found[target]:
                    found[target] = pos
            # Source order, not alphabetical: a trace is a sequence.
            f.calls = sorted(found, key=found.get)
            f.call_lines = {t: pos[0] for t, pos in found.items()}
            used = "".join(v for k, v in consts.items() if re.search(rf"\b{k}\b", seg))
            f.reads, f.writes = _tables(seg + used, known)
        m.funcs[qual] = f

    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(n, n.name, "fn")
        elif isinstance(n, ast.ClassDef):
            methods = [
                x.name for x in n.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            add(n, n.name, "class")
            for x in n.body:
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    not x.name.startswith("__") or x.name == "__init__"
                ):
                    add(x, f"{n.name}.{x.name}", "method", methods)
    return m


def extract_beat() -> list[dict]:
    src = (ROOT / "app" / "celery_app.py").read_text(encoding="utf-8")
    block = src[src.index("beat_schedule") :]
    rx = r'"([a-z0-9-]+)":\s*\{\s*"task":\s*"([^"]+)",\s*"schedule":\s*(crontab\([^)]*\))'
    return [{"name": a, "task": b, "schedule": c} for a, b, c in re.findall(rx, block)]


def extract_tests() -> list[dict]:
    out = []
    for p in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        targets: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app"):
                targets.add(n.module)
                for a in n.names:
                    targets.add(f"{n.module}.{a.name}")
        count = sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        )
        out.append(
            {
                "path": p.relative_to(ROOT).as_posix(),
                "suite": p.parent.name,
                "targets": sorted(targets),
                "tests": count,
            }
        )
    return out


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


if __name__ == "__main__":
    for m in extract().values():
        for f in m.funcs.values():
            if f.touches or f.reads or f.writes:
                print(
                    f"{m.path:30} {f.qual:30} {','.join(f.touches):14} "
                    f"R:{','.join(f.reads)[:55]:55} W:{','.join(f.writes)}"
                )
