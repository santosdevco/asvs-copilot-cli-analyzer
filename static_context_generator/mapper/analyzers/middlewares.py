"""
analyzers/middlewares.py — Middleware chain extraction from route declarations.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from ..core.fs import detect_language, read_text
from .endpoints import _ROUTE_LINE_RE, _parse_handlers   # reuse compiled regexes


_HANDLER_HINTS = re.compile(r"Controller\.|\.handler|\.action|ctrl\.", re.I)


def analyze_middlewares(files: list[Path], root: Path) -> dict:
    routes_with_mw: list[dict] = []
    mw_counter: Counter = Counter()
    mw_files: dict[str, set] = defaultdict(set)
    middleware_source_files: list[str] = []
    fastapi_global_middleware: list[dict] = []  # New: track global middlewares

    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript", "Python"}:  # Added Python support
            continue
        rel = str(f.relative_to(root))
        parts = Path(rel).parts
        if any(p.lower() in {"middlewares", "middleware"} for p in parts):
            middleware_source_files.append(rel)

    # FastAPI middleware patterns
    _FASTAPI_MIDDLEWARE_RE = re.compile(r"app\.add_middleware\s*\(\s*([^,)]+)", re.I)
    _FASTAPI_MIDDLEWARE_DECORATOR_RE = re.compile(r"@app\.middleware\s*\(['\"]([^'\"]+)['\"]\)", re.I)
    _FASTAPI_DEPENDS_RE = re.compile(r"Depends\s*\(\s*([^)]+)\)", re.I)
    _FASTAPI_ROUTE_WITH_DEPS_RE = re.compile(
        r"@app\.(get|post|put|delete|patch|options|head)\s*\(\s*['\"]([^'\"]+)['\"].*?dependencies\s*=\s*\[([^\]]+)\]", 
        re.I | re.DOTALL
    )

    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript", "Python"}:
            continue
        text = read_text(f)
        if not text:
            continue
        rel = str(f.relative_to(root))

        # Handle JavaScript/TypeScript (existing logic)
        if lang in {"JavaScript", "TypeScript"}:
            for m in _ROUTE_LINE_RE.finditer(text):
                method   = m.group(1).upper()
                path     = m.group(2)
                raw_args = m.group(3) or ""
                middlewares, handler = _parse_handlers(raw_args)

                if not middlewares:
                    continue

                clean_mw = [mw for mw in middlewares if not _HANDLER_HINTS.search(mw)]

                if clean_mw:
                    routes_with_mw.append({
                        "method":      method,
                        "path":        path,
                        "file":        rel,
                        "line":        text[: m.start()].count("\n") + 1,
                        "middlewares": clean_mw,
                        "handler":     handler,
                    })
                    for mw in clean_mw:
                        base = re.split(r"[\s(.]", mw)[0]
                        mw_counter[base] += 1
                        mw_files[base].add(rel)
        
        # Handle Python FastAPI (new logic)
        elif lang == "Python":
            # 1. Detect global middleware (app.add_middleware)
            for m in _FASTAPI_MIDDLEWARE_RE.finditer(text):
                middleware_class = m.group(1).strip()
                line_no = text[:m.start()].count("\n") + 1
                fastapi_global_middleware.append({
                    "middleware": middleware_class,
                    "file": rel,
                    "line": line_no,
                    "scope": "global"
                })
                mw_counter[middleware_class] += 1
                mw_files[middleware_class].add(rel)
            
            # 2. Detect middleware decorators (@app.middleware)
            for m in _FASTAPI_MIDDLEWARE_DECORATOR_RE.finditer(text):
                middleware_type = m.group(1)  # 'http' or 'https'
                line_no = text[:m.start()].count("\n") + 1
                fastapi_global_middleware.append({
                    "middleware": f"custom_{middleware_type}_middleware",
                    "file": rel,
                    "line": line_no,
                    "scope": "global"
                })
                mw_counter[f"custom_{middleware_type}_middleware"] += 1
                mw_files[f"custom_{middleware_type}_middleware"].add(rel)
            
            # 3. Detect route-specific dependencies
            for m in _FASTAPI_ROUTE_WITH_DEPS_RE.finditer(text):
                method = m.group(1).upper()
                path = m.group(2)
                dependencies_str = m.group(3)
                line_no = text[:m.start()].count("\n") + 1
                
                # Parse dependencies
                deps = []
                for dep_match in _FASTAPI_DEPENDS_RE.finditer(dependencies_str):
                    dep_name = dep_match.group(1).strip()
                    deps.append(dep_name)
                
                if deps:
                    routes_with_mw.append({
                        "method": method,
                        "path": path,
                        "file": rel,
                        "line": line_no,
                        "middlewares": deps,
                        "handler": "fastapi_route",
                    })
                    for dep in deps:
                        mw_counter[dep] += 1
                        mw_files[dep].add(rel)
            
            # 4. Also detect individual Depends() usage in route functions
            # Look for @app.{method} followed by function with Depends in signature
            route_pattern = re.compile(
                r"@app\.(get|post|put|delete|patch|options|head)\s*\([^)]*['\"]([^'\"]+)['\"][^)]*\)\s*\n"
                r"(?:async\s+)?def\s+\w+\([^)]*Depends\s*\([^)]+\).*?\):",
                re.I | re.DOTALL
            )
            
            for route_m in route_pattern.finditer(text):
                method = route_m.group(1).upper()
                path = route_m.group(2)
                line_no = text[:route_m.start()].count("\n") + 1
                
                # Extract all Depends() calls from the function signature
                func_signature = route_m.group(0)
                deps = []
                for dep_match in _FASTAPI_DEPENDS_RE.finditer(func_signature):
                    dep_name = dep_match.group(1).strip()
                    deps.append(dep_name)
                
                if deps:
                    routes_with_mw.append({
                        "method": method,
                        "path": path,
                        "file": rel,
                        "line": line_no,
                        "middlewares": deps,
                        "handler": "fastapi_function",
                    })
                    for dep in deps:
                        mw_counter[dep] += 1
                        mw_files[dep].add(rel)

    middleware_usage = {
        name: {
            "route_count": count,
            "files":       sorted(mw_files[name]),
        }
        for name, count in mw_counter.most_common()
    }

    return {
        "middleware_source_files":  sorted(middleware_source_files),
        "routes_with_middleware":   routes_with_mw,
        "middleware_usage":         middleware_usage,
        "total_middlewares_detected": len(middleware_usage),
        "fastapi_global_middleware": fastapi_global_middleware,  # New: include global middleware info
    }
