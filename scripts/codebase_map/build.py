"""Join the parsed repository with the surveyed geography, check it, and render the map.

    python scripts/codebase_map/build.py

Writes docs/codebase-map.html. Prints a verification report: anything the geography
claims that the source does not support is listed, and marked unverified on the map
rather than silently drawn.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import extract  # noqa: E402
import geography as geo  # noqa: E402

ROOT = extract.ROOT
TEMPLATE = Path(__file__).parent / "template.html"
OUT = ROOT / "docs" / "codebase-map.html"

problems: list[str] = []
unverified: list[dict] = []


def text_of(rel: str) -> str:
    p = ROOT / rel
    if p.is_dir():
        return "\n".join(f.read_text(encoding="utf-8") for f in sorted(p.glob("*.tf")))
    return p.read_text(encoding="utf-8") if p.exists() else ""


def text_has(rel: str, pattern: str) -> bool:
    return re.search(pattern, text_of(rel)) is not None


# --------------------------------------------------------------------------- terrain
DISTRICTS = [
    {"id": d[0], "name": d[1], "gx0": d[2], "gx1": d[3], "gy0": d[4], "gy1": d[5], "z": d[6],
     "terrain": d[7], "blurb": d[8], "folders": d[9],
     "labelAt": list(geo.DISTRICT_LABEL_AT.get(d[0], ((d[2] + d[3]) / 2, (d[4] + d[5]) / 2)))}
    for d in geo.DISTRICTS
]


def district_at(gx: float, gy: float) -> dict | None:
    for d in DISTRICTS:
        if d["gx0"] <= gx <= d["gx1"] and d["gy0"] <= gy <= d["gy1"]:
            return d
    return None


def z_at(gx: float, gy: float) -> float:
    d = district_at(gx, gy)
    return d["z"] if d else 0


# --------------------------------------------------------------------------- code
mods = extract.extract()
dbt = extract.extract_dbt()
tables = extract.extract_tables()
beat = extract.extract_beat()
tests = extract.extract_tests()

path_to_mod = {m.path: m for m in mods.values()}
all_funcs = {f"{m.mod}:{q}": (m, f) for m in mods.values() for q, f in m.funcs.items()}


def mod_of_fid(fid: str) -> str:
    return fid.split(":")[0]


def canonical(fid: str) -> str | None:
    """Resolve a call target to a known function id; classes resolve to __init__/class."""
    if fid in all_funcs:
        return fid
    mod, _, q = fid.partition(":")
    if f"{mod}:{q}.__init__" in all_funcs:
        return f"{mod}:{q}.__init__"
    return None


# Dispatch edges (verified by the literal call text in the caller's file)
dispatch_edges: list[tuple[str, str, int]] = []
for caller, callee, rx in geo.DISPATCH:
    cm = mods.get(mod_of_fid(caller))
    if caller not in all_funcs or callee not in all_funcs:
        problems.append(f"dispatch refers to unknown function: {caller} -> {callee}")
        continue
    _, f = all_funcs[caller]
    src_lines = (ROOT / cm.path).read_text(encoding="utf-8").splitlines()[f.line - 1:f.end]
    text = "\n".join(src_lines)
    hit = re.search(rx, text)
    if hit:
        dispatch_edges.append((caller, callee, f.line + text[:hit.start()].count("\n")))
    else:
        problems.append(f"dispatch evidence not found in {caller}: /{rx}/")


def kind_of(path: str) -> str:
    if path == "app/celery_app.py":
        return "scheduler"
    if path.startswith("migrations/"):
        return "blueprint"
    if path.startswith(("infra/", "scripts/")) or path in {"Dockerfile", "docker-compose.yml",
                                                          "docker-compose.prod.yml", "aws.ps1"}:
        return "infra"
    return "module"


def loc_of(rel: str) -> int:
    p = ROOT / rel
    if p.is_dir():
        return sum(len(f.read_text(encoding="utf-8").splitlines()) for f in p.glob("*.tf"))
    return len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0


buildings: list[dict] = []
by_id: dict[str, dict] = {}


def place(bid, path, gx, gy, w, d, kind, purpose, extra=None):
    cx, cy = gx + w / 2, gy + d / 2
    dist = district_at(cx, cy)
    if dist is None:
        problems.append(f"{bid} sits outside every district at ({cx}, {cy})")
    b = {"id": bid, "path": path, "name": path.rsplit("/", 1)[-1] if path else bid,
         "district": dist["id"] if dist else None, "kind": kind,
         "gx": gx, "gy": gy, "w": w, "d": d, "z0": dist["z"] if dist else 0,
         "purpose": purpose, "funcs": [], "notes": [], "unverified": False}
    if extra:
        b.update(extra)
    buildings.append(b)
    by_id[bid] = b
    return b


# Python modules and other files
for path, (gx, gy, w, d, purpose) in geo.BUILDINGS.items():
    if not extract.exists(path):
        problems.append(f"building path does not exist: {path}")
        continue
    kind = kind_of(path)
    loc = loc_of(path)
    b = place(path, path, gx, gy, w, d, kind, purpose, {"loc": loc})
    m = path_to_mod.get(path)
    if m:
        b["mod"] = m.mod
        b["doc"] = m.doc
        for q, f in m.funcs.items():
            fid = f"{m.mod}:{q}"
            b["funcs"].append({
                "id": fid, "q": q, "line": f.line, "end": f.end, "kind": f.kind, "doc": f.doc,
                "entry": f.entry, "touches": f.touches, "reads": f.reads, "writes": f.writes,
            })

# Every app module must be on the map
placed = {b["path"] for b in buildings}
for m in mods.values():
    if m.path not in placed:
        problems.append(f"module not placed on the map: {m.path}")

# Phantoms
for path, (gx, gy, w, d, purpose, (ref_file, rx)) in geo.PHANTOMS.items():
    if extract.exists(path):
        problems.append(f"phantom actually exists (draw it as a building): {path}")
    ok = text_has(ref_file, rx)
    b = place(path, path, gx, gy, w, d, "phantom", purpose, {"loc": 0})
    b["notes"].append(f"Referenced in {ref_file}" if ok else "Reference not found either")
    unverified.append({"what": path, "why": "referenced in " + ref_file + " but the file does not exist"})

# dbt nodes
for name, (gx, gy, w, d) in geo.DBT.items():
    if name not in dbt:
        problems.append(f"dbt node not found: {name}")
        continue
    info = dbt[name]
    place(f"dbt:{name}", info["path"], gx, gy, w, d, "seed" if info["layer"] == "seed" else "dbt",
          geo.DBT_PURPOSE.get(name, info["doc"]),
          {"loc": info["loc"], "layer": info["layer"], "refs": info["refs"], "sources": info["sources"]})
for name in dbt:
    if name not in geo.DBT:
        problems.append(f"dbt node not placed: {name}")

# Landmarks
for lid, (name, gx, gy, w, d, shape, note, (ev_file, rx)) in geo.LANDMARKS.items():
    ok = text_has(ev_file, rx)
    b = place(lid, "", gx, gy, w, d, "external" if lid.startswith("ext:") else "datastore", note,
              {"name": name, "shape": shape, "evidence": f"{ev_file} /{rx}/", "loc": 0})
    if not ok:
        b["unverified"] = True
        problems.append(f"landmark evidence not found: {lid} in {ev_file}")
    if lid == "ext:metabase":
        b["unverified"] = True
        unverified.append({"what": "Metabase", "why": "its dashboards and queries live inside Metabase, not in this repository"})
    if lid == "lm:postgres":
        b["tables"] = tables

# Tests: arranged in geographic order of what they test
district_order = [d["id"] for d in DISTRICTS]
mod_district = {b.get("mod"): b["district"] for b in buildings if b.get("mod")}


def test_rank(t):
    ds = [mod_district.get(x) for x in t["targets"] if mod_district.get(x)]
    return min((district_order.index(x) for x in ds), default=99), t["path"]


cols = [51.5, 54.5, 57.5, 60.5, 63.5]
rows = [32, 35, 38, 41]
for i, t in enumerate(sorted(tests, key=test_rank)):
    gx, gy = cols[i % 5], rows[i // 5]
    target_ids = sorted({b["id"] for b in buildings if b.get("mod") in t["targets"]})
    place(t["path"], t["path"], gx, gy, 1.4, 1.4, "test",
          f"{t['tests']} tests ({t['suite']}), checking {', '.join(by_id[x]['name'] for x in target_ids) or 'shared settings'}.",
          {"loc": loc_of(t["path"]), "proves": target_ids, "ntests": t["tests"]})

# Overlap check within a district
for i, a in enumerate(buildings):
    for b2 in buildings[i + 1:]:
        if a["district"] != b2["district"]:
            continue
        if (a["gx"] < b2["gx"] + b2["w"] and b2["gx"] < a["gx"] + a["w"]
                and a["gy"] < b2["gy"] + b2["d"] and b2["gy"] < a["gy"] + a["d"]):
            problems.append(f"overlap: {a['id']} and {b2['id']}")

# Heights: lines of code for code, fixed for landmarks
for b in buildings:
    loc = b.get("loc", 0)
    b["h"] = {
        "module": 1.2 + math.sqrt(loc) * 0.42,
        "scheduler": 9.5,
        "blueprint": 1.2,
        "infra": 1.6 + math.sqrt(loc) * 0.12,
        "dbt": 0.7 + math.sqrt(loc) * 0.1,
        "seed": 0.8,
        "test": 1.2 + math.sqrt(b.get("ntests", 1)) * 0.5,
        "phantom": 0,
        "external": 3.2,
        "datastore": {"lm:postgres": 5.5, "lm:raw": 6.5, "lm:redis": 3.5, "lm:dlq": 2.6}.get(b["id"], 3),
    }[b["kind"]]
    b["h"] = round(b["h"], 2)

# --------------------------------------------------------------------------- call graph
calls: dict[str, dict[str, int]] = {}  # callee -> line of the call
for fid, (_, f) in all_funcs.items():
    for c in f.calls:
        cc = canonical(c)
        if cc and cc != fid:
            calls.setdefault(fid, {}).setdefault(cc, f.call_lines[c])
for a, b2, line in dispatch_edges:
    calls.setdefault(a, {})[b2] = line

called_by: dict[str, set[str]] = {}
for a, bs in calls.items():
    for b2 in bs:
        called_by.setdefault(b2, set()).add(a)

mod_to_bid = {b["mod"]: b["id"] for b in buildings if b.get("mod")}


def io_targets(fid: str, f) -> list[str]:
    mod = mod_of_fid(fid)
    out = []
    for t in f.touches:
        override = geo.IO_TARGETS.get(fid, {}).get(t) or geo.IO_TARGETS.get(mod, {}).get(t)
        if override:
            out.append(override)
        elif t == "db":
            out.append("lm:postgres")
        elif t == "redis":
            out.append("lm:redis")
        elif t == "raw":
            out.append("lm:raw")
    if (f.reads or f.writes) and "lm:postgres" not in out:
        out.append("lm:postgres")
    return sorted(set(out))


for b in buildings:
    for fn in b["funcs"]:
        fid = fn["id"]
        m, f = all_funcs[fid]
        got = calls.get(fid, {})
        fn["calls"] = sorted(got, key=got.get)
        fn["calledBy"] = sorted(called_by.get(fid, ()))
        fn["io"] = io_targets(fid, f)
        fn["out"] = any(mod_of_fid(c) != m.mod for c in fn["calls"]) or bool(fn["io"])

# Building-level links: non-core cross-module calls
links = set()
for a, bs in calls.items():
    for b2 in bs:
        ma, mb = mod_of_fid(a), mod_of_fid(b2)
        if ma != mb and not mb.startswith("app.core") and ma in mod_to_bid and mb in mod_to_bid:
            links.add((mod_to_bid[ma], mod_to_bid[mb]))
core_edges = sum(
    1 for m in mods.values() for i in m.imports if i.startswith("app.core") and m.mod in mod_to_bid
)

for b in buildings:
    if b.get("mod"):
        b["importsCore"] = sorted(i for i in mods[b["mod"]].imports if i.startswith("app.core"))

# Findings worth drawing
if "app/ingestion/cdc.py" in by_id and not called_by.get("app.ingestion.cdc:apply_record"):
    by_id["app/ingestion/cdc.py"]["notes"].append(
        "apply_record() has no callers in app/: live ingestion uses bulk.py. Only the parity test runs it.")
if "lm:dlq" in by_id:
    readers = [fid for fid, (m, f) in all_funcs.items()
               if "get_deadletter_store" in "".join(f.calls) and "dead_letter" not in fid]
    if not readers:
        by_id["lm:dlq"]["notes"].append("Written by dead_letter(); no code in app/ reads it back. A dead end by design.")
if "app/ai/matching.py" in by_id:
    by_id["app/ai/matching.py"]["notes"].append("Reads products and product_versions directly, not a dbt mart.")

# --------------------------------------------------------------------------- routes
anchors: dict[str, tuple[float, float, float]] = {}
for b in buildings:
    anchors[b["id"]] = (b["gx"] + b["w"] / 2, b["gy"] + b["d"] / 2, b["z0"])
anchors[geo.FORK["id"]] = (geo.FORK["gx"], geo.FORK["gy"], geo.FORK["z"])
anchors[geo.TERMINUS["id"]] = (geo.TERMINUS["gx"], geo.TERMINUS["gy"], geo.TERMINUS["z"])


def has_call(a: str, b2: str) -> bool:
    return b2 in calls.get(a, {}) or canonical(b2) in calls.get(a, {})


def check(ev) -> bool:
    kind = ev[0]
    if kind == "call":
        return has_call(ev[1], ev[2])
    if kind in {"reads", "writes"}:
        if ev[1] not in all_funcs:
            return False
        return ev[2] in getattr(all_funcs[ev[1]][1], kind)
    if kind == "touch":
        return ev[1] in all_funcs and ev[2] in all_funcs[ev[1]][1].touches
    if kind == "text":
        return text_has(ev[1], ev[2])
    return False


def point(p) -> list[float]:
    gx, gy = p[0], p[1]
    return [gx, gy, p[2] if len(p) > 2 else z_at(gx, gy)]


routes = []
for r in geo.ROUTES:
    a, b2 = r["from"], r["to"]
    if a not in anchors or b2 not in anchors:
        problems.append(f"route {r['id']} has an unknown end: {a} -> {b2}")
        continue
    failed = [" ".join(map(str, e)) for e in r["evidence"] if not check(e)]
    pts = [list(anchors[a])] + [point(v) for v in r["via"]] + [list(anchors[b2])]
    if a == b2 and not r["via"]:
        problems.append(f"route {r['id']} is a loop with no waypoints")
    rr = dict(r, points=[[round(x, 2) for x in p] for p in pts], verified=not failed, failed=failed)
    if r["label_at"]:
        rr["label_at"] = point(r["label_at"])
    rr["evidence"] = [" ".join(map(str, e)) for e in r["evidence"]]
    del rr["via"]
    routes.append(rr)
    if failed:
        problems.append(f"route {r['id']} evidence failed: {failed}")
        unverified.append({"what": f"route {r['name']} ({r['id']})", "why": "; ".join(failed)})

# dbt lineage edges
lineage = []
for name, info in dbt.items():
    for parent in info["refs"]:
        if f"dbt:{parent}" in by_id and f"dbt:{name}" in by_id:
            lineage.append({"from": f"dbt:{parent}", "to": f"dbt:{name}"})
        else:
            problems.append(f"dbt ref not placed: {parent} -> {name}")
    for src in info["sources"]:
        lineage.append({"from": "lm:postgres", "to": f"dbt:{name}", "table": src})

# Journey references
route_ids = {r["id"] for r in routes}
for nid, n in geo.JOURNEY["nodes"].items():
    if n["at"] not in anchors:
        problems.append(f"journey node {nid} at unknown anchor {n['at']}")
    for ref in n.get("chain", []):
        if ref not in anchors:
            problems.append(f"journey node {nid} chain has unknown anchor {ref}")
    for rid in n.get("visit", []):
        if rid not in route_ids:
            problems.append(f"journey node {nid} visits unknown route {rid}")
    for e in n.get("next", []):
        if e["to"] not in geo.JOURNEY["nodes"]:
            problems.append(f"journey edge {nid} -> {e['to']} goes nowhere")
        for rid, _ in e["legs"]:
            if rid not in route_ids:
                problems.append(f"journey edge {nid} -> {e['to']} uses unknown route {rid}")
    if "split" in n and n["split"][0] not in route_ids:
        problems.append(f"journey split uses unknown route {n['split'][0]}")

fork_ok = text_has(*geo.FORK["evidence"])
if not fork_ok:
    problems.append("THE FORK evidence not found: raw put() before normalize()")

# --------------------------------------------------------------------------- assemble
try:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
except OSError:
    commit = ""

counts = {
    "modules": sum(1 for b in buildings if b.get("mod")),
    "dbt": sum(1 for b in buildings if b["kind"] in {"dbt", "seed"}),
    "tests": sum(1 for b in buildings if b["kind"] == "test"),
    "infra": sum(1 for b in buildings if b["kind"] in {"infra", "blueprint"}),
    "landmarks": sum(1 for b in buildings if b["kind"] in {"external", "datastore"}),
    "functions": sum(len(b["funcs"]) for b in buildings),
    "routes": len(routes),
    "links": len(links),
    "lineage": len(lineage),
    "coreEdges": core_edges,
    "tables": len(tables),
    "beat": len(beat),
}

MAP = {
    "meta": {"generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "commit": commit,
             "counts": counts, "unverified": unverified, "problems": problems},
    "districts": DISTRICTS,
    "buildings": buildings,
    "routes": routes,
    "links": sorted([list(x) for x in links]),
    "lineage": lineage,
    "fork": geo.FORK | {"evidence": " ".join(geo.FORK["evidence"]), "verified": fork_ok},
    "terminus": geo.TERMINUS | {"evidence": " ".join(geo.TERMINUS["evidence"])},
    "journey": geo.JOURNEY,
    "beat": beat,
    "tables": tables,
    "glossary": geo.GLOSSARY,
}

html = TEMPLATE.read_text(encoding="utf-8")
payload = json.dumps(MAP, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
html = html.replace("/*__MAP__*/null", payload)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")

print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)")
print("counts:", json.dumps(counts))
print(f"unverified ({len(unverified)}):")
for u in unverified:
    print("  -", u["what"], "--", u["why"])
print(f"problems ({len(problems)}):")
for p in problems:
    print("  !", p)
