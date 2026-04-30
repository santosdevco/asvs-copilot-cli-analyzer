"""
analyzers/imports.py — Import graph with blast-radius and critical data-flow paths.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path, PurePosixPath

from ..core.config import IMPORT_PATTERNS
from ..core.fs import detect_language, read_text


def build_import_graph(files: list[Path], root: Path) -> dict:
    # ── Detect internal package roots (top-level dirs + root-level module stems)
    internal_roots: set[str] = set()
    for f in files:
        try:
            rel_f = str(f.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        parts = PurePosixPath(rel_f).parts
        if not parts:
            continue
        if len(parts) == 1:
            stem = os.path.splitext(parts[0])[0]
            if stem and stem not in ("__init__", "__main__"):
                internal_roots.add(stem)
        else:
            internal_roots.add(parts[0])

    graph: dict[str, dict] = {}

    for f in files:
        lang = detect_language(f)
        if lang not in IMPORT_PATTERNS:
            continue
        text = read_text(f)
        if not text:
            continue

        rel = str(f.relative_to(root))
        internal: list[str] = []
        external: set[str] = set()

        for pattern, is_rel in IMPORT_PATTERNS[lang]:
            for m in pattern.finditer(text):
                module = m.group(1).strip()
                if not module:
                    continue
                if is_rel is True:
                    internal.append(module)
                elif is_rel is False:
                    # Python `import X` — check whether X is a local package
                    root_pkg = module.split(".")[0].split("/")[0]
                    if root_pkg in internal_roots:
                        internal.append(module)
                    else:
                        external.add(root_pkg)
                else:  # "detect"
                    if module.startswith(".") or module.startswith("/"):
                        internal.append(module)
                    else:
                        # Absolute import: internal if root package lives in the project
                        root_pkg = module.split("/")[0].split(".")[0]
                        if root_pkg in internal_roots:
                            internal.append(module)
                        else:
                            external.add(module.split("/")[0])

        if internal or external:
            graph[rel] = {
                "internal": sorted(set(internal)),
                "external": sorted(external),
            }

    # ── Most-imported modules ─────────────────────────────────────────────
    importee_count: Counter = Counter()
    for data in graph.values():
        for imp in data["internal"]:
            importee_count[imp] += 1

    most_imported = [
        {"module": mod, "imported_by": cnt}
        for mod, cnt in importee_count.most_common(15)
    ]

    all_external: set[str] = set()
    for v in graph.values():
        all_external.update(v["external"])

    # ── Stem → key lookup for resolving relative imports ──────────────────
    stem_to_key: dict[str, str] = {}
    for key in graph:
        stem = os.path.splitext(key)[0]
        stem_to_key[stem] = key
        if PurePosixPath(key).stem == "index":
            parent = str(PurePosixPath(key).parent)
            stem_to_key.setdefault(parent, key)

    def _resolve(importer: str, imp: str) -> str | None:
        base = os.path.dirname(importer)

        if imp.startswith(".") and not imp.startswith("./") and not imp.startswith("../"):
            # Python dot-notation relative import: .models, ..schemas, .base.pipeline_builder
            n_dots = len(imp) - len(imp.lstrip("."))
            module_path = imp.lstrip(".")          # e.g. "models", "base.pipeline_builder"

            cur = base if base else "."
            for _ in range(n_dots - 1):
                parent = os.path.dirname(cur)
                cur = parent if parent else "."

            if module_path:
                if cur == ".":
                    raw = module_path.replace(".", "/")
                else:
                    raw = cur + "/" + module_path.replace(".", "/")
            else:
                raw = "" if cur == "." else cur

        elif imp.startswith("./") or imp.startswith("../"):
            # JS/TS style relative: ./utils, ../services
            raw = os.path.normpath(os.path.join(base, imp)).replace("\\", "/")

        elif imp.startswith("/"):
            raw = imp.lstrip("/")

        else:
            # Python absolute internal import: core.security → core/security
            raw = imp.replace(".", "/").strip("/")

        if not raw:
            return None

        if raw in stem_to_key:
            return stem_to_key[raw]
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            if (raw + ext) in stem_to_key:
                return stem_to_key[raw + ext]
        index_key = stem_to_key.get(raw + "/index")
        if index_key:
            return index_key
        return None

    # ── Resolved adjacency list ───────────────────────────────────────────
    adj: dict[str, list[str]] = {k: [] for k in graph}
    for importer, data in graph.items():
        for rel in data["internal"]:
            target = _resolve(importer, rel)
            if target:
                adj[importer].append(target)

    # Preserve full project-relative resolved targets for machine-readable formatters.
    for importer in graph:
        graph[importer]["internal_resolved"] = sorted(set(adj.get(importer, [])))

    # ── 1. Reverse graph (blast radius) ──────────────────────────────────
    rev: dict[str, list[str]] = {}
    for importer, targets in adj.items():
        for target in targets:
            rev.setdefault(target, []).append(importer)

    reverse_graph: dict[str, dict] = {
        key: {
            "imported_by": sorted(rev.get(key, [])),
            "blast_radius": len(rev.get(key, [])),
        }
        for key in sorted(graph, key=lambda k: -len(rev.get(k, [])))
        if rev.get(key)
    }

    # ── 2. Data-flow paths (controller → service, ≥ 3 hops) ─────────────
    def _is_role(path: str, role: str) -> bool:
        return role in path.lower().replace("\\", "/")

    controllers = [k for k in graph if _is_role(k, "controller") or _is_role(k, "router")]
    services    = {k for k in graph if _is_role(k, "service") or _is_role(k, "repository")}

    found_paths: list[list[str]] = []

    def _dfs(node: str, path: list[str], visited: set[str]) -> None:
        if len(path) > 7:
            return
        if node in services and len(path) >= 3:
            found_paths.append(list(path))
            return
        for nxt in adj.get(node, []):
            if nxt not in visited:
                visited.add(nxt)
                path.append(nxt)
                _dfs(nxt, path, visited)
                path.pop()
                visited.remove(nxt)

    for ctrl in controllers:
        _dfs(ctrl, [ctrl], {ctrl})

    found_paths.sort(key=lambda p: -len(p))
    seen_sigs: set[tuple] = set()
    unique_paths: list[dict] = []
    for p in found_paths:
        sig = tuple(p)
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            unique_paths.append({
                "hops": len(p),
                "path": p,
                "flow": " → ".join(os.path.basename(n) for n in p),
            })
        if len(unique_paths) >= 60:
            break

    # ── 3. Unreferenced files (dead-code candidates) ──────────────────────
    _ENTRY_POINTS = frozenset({
        "index.js", "main.js", "server.js", "app.js",
        "manage.py", "wsgi.py", "asgi.py",
    })
    imported_set = set(rev.keys())
    unreferenced = [
        {"file": k, "external_deps": graph[k]["external"]}
        for k in sorted(graph)
        if k not in imported_set
        and os.path.basename(k) not in _ENTRY_POINTS
        and "test" not in k.lower()
        and "spec" not in k.lower()
        and "seed" not in k.lower()
        and "migration" not in k.lower()
    ]

    return {
        "graph": graph,
        "most_imported_modules": most_imported,
        "total_internal_edges": sum(len(v["internal"]) for v in graph.values()),
        "unique_external_packages": len(all_external),
        "all_external_packages": sorted(all_external),
        "reverse_graph": reverse_graph,
        "data_flow_paths": unique_paths,
        "unreferenced_files": unreferenced,
    }
