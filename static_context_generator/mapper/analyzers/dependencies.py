"""
analyzers/dependencies.py — Dependency file parsers and framework detector.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.config import FRAMEWORK_SIGNATURES
from ..core.fs import read_text


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_requirements_txt(path: Path) -> list[dict]:
    text = read_text(path)
    if not text:
        return []
    deps = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r", "-c", "--")):
            continue
        m = re.match(r"^([A-Za-z0-9_\-\[\].]+)\s*([><=!~^]{1,3}\s*[\d.*,]+)?", line)
        if m:
            deps.append({"name": m.group(1).lower(), "version": (m.group(2) or "").strip()})
    return deps


def _parse_pyproject_toml(path: Path) -> tuple[list[dict], list[dict]]:
    text = read_text(path)
    if not text:
        return [], []
    prod: list[dict] = []
    dev: list[dict] = []

    in_list = None
    for line in text.splitlines():
        s = line.strip()
        if s in ("dependencies = [", "dependencies=["):
            in_list = prod
            continue
        if s.startswith("[tool.poetry.dev-dependencies]") or \
           s.startswith("[tool.poetry.group.dev.dependencies]"):
            in_list = dev
            continue
        if s.startswith("[tool.poetry.dependencies]"):
            in_list = prod
            continue
        if s.startswith("[") and in_list is not None:
            in_list = None
            continue
        if in_list is not None and s.endswith("]") and s != "]":
            in_list = None
            continue
        if in_list is not None:
            pkg = re.match(r'^"?([A-Za-z0-9_\-\[\].]+)', s.strip('"').strip("'"))
            if pkg and pkg.group(1).lower() != "python":
                in_list.append({"name": pkg.group(1).lower(), "version": ""})
    return prod, dev


def _parse_package_json(path: Path) -> tuple[list[dict], list[dict], list[str]]:
    text = read_text(path)
    if not text:
        return [], [], []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], [], []
    prod = [{"name": k, "version": v} for k, v in data.get("dependencies", {}).items()]
    dev  = [{"name": k, "version": v} for k, v in data.get("devDependencies", {}).items()]
    scripts = list(data.get("scripts", {}).keys())
    return prod, dev, scripts


def _parse_go_mod(path: Path) -> list[dict]:
    text = read_text(path)
    if not text:
        return []
    deps = []
    in_require = False
    for line in text.splitlines():
        s = line.strip()
        if s == "require (":
            in_require = True
            continue
        if in_require and s == ")":
            in_require = False
            continue
        if in_require or s.startswith("require "):
            parts = s.lstrip("require ").split()
            if len(parts) >= 1 and "/" in parts[0]:
                deps.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else ""})
    return deps


def _parse_cargo_toml(path: Path) -> tuple[list[dict], list[dict]]:
    text = read_text(path)
    if not text:
        return [], []
    prod, dev = [], []
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s == "[dependencies]":
            section = "prod"
            continue
        if s == "[dev-dependencies]":
            section = "dev"
            continue
        if s.startswith("["):
            section = None
            continue
        if section:
            m = re.match(r"^([\w\-]+)\s*=", s)
            if m:
                (prod if section == "prod" else dev).append({"name": m.group(1), "version": ""})
    return prod, dev


def _parse_gemfile(path: Path) -> tuple[list[dict], list[dict]]:
    text = read_text(path)
    if not text:
        return [], []
    prod, dev = [], []
    in_dev = False
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"group\s+.*:test|:development", s):
            in_dev = True
        if s == "end" and in_dev:
            in_dev = False
        m = re.match(r"gem\s+['\"]([^'\"]+)['\"]", s)
        if m:
            (dev if in_dev else prod).append({"name": m.group(1), "version": ""})
    return prod, dev


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def find_dependencies(root: Path) -> dict:
    result: dict = {
        "source_files": [],
        "python_deps": set(),
        "js_deps": set(),
        "go_deps": set(),
        "rust_deps": set(),
        "ruby_deps": set(),
        "production": [],
        "development": [],
        "npm_scripts": [],
    }

    def _add(src: str, prod: list, dev: list, dep_set_key: str) -> None:
        if prod or dev:
            if src not in result["source_files"]:
                result["source_files"].append(src)
            result["production"].extend(prod)
            result["development"].extend(dev)
            for d in prod + dev:
                result[dep_set_key].add(d["name"])

    for name in ["requirements.txt", "requirements/base.txt", "requirements/common.txt"]:
        p = root / name
        if p.exists():
            _add(name, _parse_requirements_txt(p), [], "python_deps")
    for name in ["requirements-dev.txt", "requirements/dev.txt", "requirements/test.txt"]:
        p = root / name
        if p.exists():
            _add(name, [], _parse_requirements_txt(p), "python_deps")
    p = root / "pyproject.toml"
    if p.exists():
        pr, dv = _parse_pyproject_toml(p)
        _add("pyproject.toml", pr, dv, "python_deps")

    p = root / "package.json"
    if p.exists():
        pr, dv, scripts = _parse_package_json(p)
        _add("package.json", pr, dv, "js_deps")
        result["npm_scripts"] = scripts

    p = root / "go.mod"
    if p.exists():
        _add("go.mod", _parse_go_mod(p), [], "go_deps")

    p = root / "Cargo.toml"
    if p.exists():
        pr, dv = _parse_cargo_toml(p)
        _add("Cargo.toml", pr, dv, "rust_deps")

    p = root / "Gemfile"
    if p.exists():
        pr, dv = _parse_gemfile(p)
        _add("Gemfile", pr, dv, "ruby_deps")

    return result


def detect_frameworks(deps: dict) -> list[str]:
    found = set()
    for field, required, name in FRAMEWORK_SIGNATURES:
        if required & deps.get(field, set()):
            found.add(name)
    return sorted(found)
