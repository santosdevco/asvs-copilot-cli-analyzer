"""
formatters/sections/imports.py — TXT formatter for the imports section.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

from ..base import _txt_header


def format_imports_txt(section: dict, meta: dict) -> str:
    imp  = section
    SEP  = "─" * 68
    lines: list[str] = _txt_header("IMPORT GRAPH", meta)

    graph    = imp.get("graph", {})
    rev      = imp.get("reverse_graph", {})
    paths    = imp.get("data_flow_paths", [])
    ext_pkgs = imp.get("all_external_packages", [])
    total_ie = imp.get("total_internal_edges", 0)
    total_ep = imp.get("unique_external_packages", 0)

    lines += [
        f"Files: {len(graph)}   Internal edges: {total_ie}   External packages: {total_ep}",
        "",
    ]

    _ROLE_SEGS = [
        ("controllers/", "CTRL"),
        ("services/",    "SVC"),
        ("logic/",       "LGC"),
        ("middlewares/", "MW"),
        ("helpers/",     "HLP"),
        ("cron/",        "CRN"),
        ("routes/",      "RT"),
    ]

    def _role(path: str) -> str:
        p = path.replace("\\", "/")
        for seg, tag in _ROLE_SEGS:
            if seg in p:
                return tag
        return "ROOT"

    def _short(path: str) -> str:
        name = re.sub(r"\.js$", "", os.path.basename(path))
        name = re.sub(r"Controller$", "Ctrl", name)
        return name

    def _tag(path: str) -> str:
        r = _role(path)
        s = _short(path)
        return f"{r}:{s}" if r != "ROOT" else s

    # Blast radius
    lines += [SEP, "[BLAST RADIUS — fan-in sorted, top 14]", SEP]
    
    # Debug: check if we have data
    if not rev:
        lines.append("  No reverse dependencies found.")
        lines.append("")
    else:
        # Sort by blast radius (descending) and filter out empty ones
        sorted_rev = sorted(
            [(key, info) for key, info in rev.items() if info.get("blast_radius", 0) > 0],
            key=lambda x: x[1]["blast_radius"],
            reverse=True
        )
        
        if not sorted_rev:
            lines.append("  No files with incoming dependencies found.")
            lines.append("")
        else:
            lines.append(f"  {'FILE':<34} {'BR':>4}  IMPORTED BY (grouped by role)")
            lines.append("  " + "─" * 92)
            
            for key, info in sorted_rev[:14]:
                br  = info["blast_radius"]
                iby = info["imported_by"]
                by_role: dict[str, list[str]] = {}
                for f in iby:
                    by_role.setdefault(_role(f), []).append(_short(f))
                parts = []
                for role in ["CTRL", "SVC", "LGC", "MW", "HLP", "CRN", "RT", "ROOT"]:
                    if role in by_role:
                        parts.append(f"{role}:{','.join(sorted(by_role[role]))}")
                summary = "  ".join(parts)
                if len(summary) > 88:
                    summary = summary[:85] + "…"
                lines.append(f"  {_tag(key):<34} {br:>4}  {summary}")
            lines.append("")

    # Adjacency list
    lines += [SEP, "[ADJACENCY LIST — MACHINE READABLE]", SEP]
    for fpath in sorted(graph):
        fdata    = graph[fpath]
        internal = sorted(set(fdata.get("internal_resolved", [])))
        external = sorted(set(fdata.get("external", [])))
        internal_str = ", ".join(internal) if internal else "none"
        external_str = ", ".join(external) if external else "none"
        lines.append(
            f"EDGE | FILE: {fpath} | INTERNAL_TO: {internal_str} | EXTERNAL: {external_str}"
        )
    lines.append("")

    # Data flow paths
    lines += [SEP, "[DATA FLOW PATHS — controller → … → service  (≥3 nodes)]", SEP]
    lines.append("  Notation: {A|B|C} = parallel middle nodes  ×N = N merged paths")
    lines.append("")

    by_hops: dict[int, list[list[str]]] = defaultdict(list)
    for p in paths:
        by_hops[p["hops"]].append(p["path"])

    if not by_hops:
        lines.append("  No controller/router→service/repository paths found (≥3 nodes).")
        lines.append("")

    for hop_count in sorted(by_hops.keys(), reverse=True):
        group   = by_hops[hop_count]
        n_edges = hop_count - 1
        lines.append(f"  [{hop_count} nodes / {n_edges} edges]")
        var_idx = hop_count - 2
        merged: dict[tuple, list[str]] = {}
        for path in group:
            short = [_short(n) for n in path]
            key   = tuple(short[:var_idx] + short[var_idx + 1:])
            merged.setdefault(key, []).append(short[var_idx])
        for key, variants in sorted(merged.items(), key=lambda x: (-len(x[1]), x[0])):
            prefix = list(key[:-1])
            suffix = key[-1]
            if len(variants) == 1:
                full = prefix + variants + [suffix]
                lines.append("    " + " → ".join(full))
            else:
                var_str = "{" + "|".join(sorted(variants)) + "}"
                full    = prefix + [var_str] + [suffix]
                lines.append("    " + " → ".join(full) + f"   ×{len(variants)}")
        lines.append("")

    # External packages
    lines += [SEP, "[EXTERNAL PACKAGES]", SEP]
    _STDLIB = {
        "__future__", "abc", "argparse", "ast", "asyncio", "base64", "binascii",
        "calendar", "cgi", "chunk", "cmath", "cmd", "code", "codecs", "collections",
        "colorsys", "compileall", "concurrent", "configparser", "contextlib",
        "contextvars", "copy", "copyreg", "csv", "ctypes", "dataclasses", "datetime",
        "dbm", "decimal", "difflib", "dis", "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
        "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
        "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib", "importlib",
        "inspect", "io", "ipaddress", "itertools", "json", "keyword", "linecache",
        "locale", "logging", "lzma", "mailbox", "math", "mimetypes", "mmap",
        "multiprocessing", "numbers", "operator", "os", "pathlib", "pdb",
        "pickle", "pkgutil", "platform", "plistlib", "pprint", "profile",
        "queue", "random", "re", "readline", "runpy", "sched", "secrets",
        "select", "selectors", "shelve", "shlex", "shutil", "signal", "site",
        "smtplib", "socket", "socketserver", "sqlite3", "ssl", "stat",
        "statistics", "string", "struct", "subprocess", "sys", "sysconfig",
        "tarfile", "tempfile", "test", "textwrap", "threading", "time", "timeit",
        "tkinter", "token", "tokenize", "tomllib", "trace", "traceback",
        "tracemalloc", "types", "typing", "unicodedata", "unittest", "urllib",
        "uuid", "warnings", "wave", "weakref", "webbrowser", "wsgiref",
        "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    }
    _SEC  = {
        "bcryptjs", "jsonwebtoken", "crypto-js", "otplib", "qrcode",
        "express-validator", "helmet", "cors",
        "jose", "passlib", "cryptography", "pyjwt", "jwt", "itsdangerous", "authlib",
    }
    _HTTP = {
        "axios", "ibm-watson", "ibm-cos-sdk", "web-push",
        "httpx", "requests", "aiohttp", "httplib2",
    }
    stdlib = [p for p in ext_pkgs if p in _STDLIB]
    sec    = [p for p in ext_pkgs if p in _SEC and p not in _STDLIB]
    http   = [p for p in ext_pkgs if p in _HTTP and p not in _STDLIB and p not in _SEC]
    infra  = [p for p in ext_pkgs if p not in _STDLIB and p not in _SEC and p not in _HTTP]
    if stdlib:
        lines.append(f"  STDLIB   : {', '.join(stdlib)}")
    if sec:
        lines.append(f"  SECURITY : {', '.join(sec)}")
    if http:
        lines.append(f"  HTTP/EXT : {', '.join(http)}")
    if infra:
        lines.append(f"  INFRA    : {', '.join(infra)}")
    lines.append("")

    return "\n".join(lines)
