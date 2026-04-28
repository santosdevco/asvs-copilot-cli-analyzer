#!/usr/bin/env python3
"""
project_mapper.py - Comprehensive static analysis context map for AI agents.

Generates a multi-file project map under an output directory:
  00_index.json        Always load first: manifest + when to use each file
  01_identity.json     Language, framework, dependencies
  02_structure.json    Directory tree, entry points, architecture
  03_endpoints.json    HTTP routes detected (method, path, middlewares, handler)
  04_env_vars.json     process.env / os.environ usage per variable and file
  05_database.json     SQL tables (CREATE TABLE) + DML usage per table/file
  06_middlewares.json  Middleware chains extracted from route declarations
  07_imports.json      Internal import graph + external packages
  08_code_signals.json Functions, classes, complexity, TODOs
  09_security.json     Exposed .env files, hardcoded secrets patterns
  10_git.json          Branch, hot files, recent touches, contributors

Usage:
    python project_mapper.py [path] [options]

Examples:
    python project_mapper.py .
    python project_mapper.py /my/project --out-dir ./map
    python project_mapper.py /my/project --no-git --no-security
    python project_mapper.py /my/project --exclude-dir migrations --max-depth 5
    # Single-file fallback:
    python project_mapper.py /my/project --single-file --output json --out map.json
"""

import os
import sys
import re
import json
import argparse
import subprocess
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from typing import Optional

SCRIPT_VERSION = "2.0.0"

# ── Excluded directories ──────────────────────────────────────────────────────

EXCLUDED_DIRS: set[str] = {
    # JS / Node
    "node_modules", ".npm", ".yarn", "bower_components",
    "jspm_packages", "packages",
    # Python
    "__pycache__", ".venv", "venv", "env", ".env",
    "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "__pypackages__",
    # Build / output
    "dist", "build", "out", "output", "target",
    "bin", "obj", "release", "debug",
    ".next", ".nuxt", ".svelte-kit", ".parcel-cache",
    ".cache", ".turbo", ".vercel", ".netlify",
    # Assets / media
    "assets", "static", "public", "media",
    "images", "img", "fonts", "icons", "videos", "audio",
    # VCS
    ".git", ".svn", ".hg",
    # IDEs
    ".idea", ".vscode", ".vs", ".eclipse",
    # Coverage / reports
    "coverage", ".nyc_output", "htmlcov", "reports",
    # Infra / cloud
    ".terraform", ".docker",
    # Mobile
    "Pods", "DerivedData", ".gradle",
    # Generated
    "generated", "gen", "auto-generated",
    "stubs", "typings", ".docusaurus", ".expo",
}

EXCLUDED_EXTENSIONS: set[str] = {
    # Compiled
    ".pyc", ".pyo", ".pyd",
    ".class", ".jar", ".war", ".ear",
    ".o", ".obj", ".a", ".so", ".dll", ".exe", ".lib", ".bin",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".bmp", ".tiff", ".tif", ".heic", ".raw",
    # Video / audio
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac", ".aac",
    # Fonts
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # Archives
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    # DB
    ".db", ".sqlite", ".sqlite3",
    # Docs
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Source maps
    ".map",
}

LOCK_FILES: set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "composer.lock", "Gemfile.lock",
    "cargo.lock", "go.sum", "Podfile.lock",
}

# ── Extension → Language ──────────────────────────────────────────────────────

EXT_TO_LANG: dict[str, str] = {
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".cpp": "C++", ".cxx": "C++", ".cc": "C++",
    ".c": "C",
    ".h": "C/C++ Header", ".hpp": "C/C++ Header",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".r": "R",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".ps1": "PowerShell",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS", ".sass": "Sass",
    ".less": "Less",
    ".sql": "SQL",
    ".graphql": "GraphQL", ".gql": "GraphQL",
    ".proto": "Protobuf",
    ".md": "Markdown", ".mdx": "Markdown",
    ".tf": "Terraform", ".hcl": "HCL",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".ex": "Elixir", ".exs": "Elixir",
    ".hs": "Haskell",
    ".clj": "Clojure", ".cljs": "Clojure",
    ".dart": "Dart",
    ".lua": "Lua",
    ".nim": "Nim",
    ".zig": "Zig",
}

FILENAME_TO_LANG: dict[str, str] = {
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
    "Rakefile": "Ruby",
    "Gemfile": "Ruby",
    "Jenkinsfile": "Groovy",
}

# Languages that are "config/data", not counted for primary language
NON_CODE_LANGS: set[str] = {
    "JSON", "YAML", "TOML", "XML", "Markdown",
    "Dockerfile", "Makefile", "HCL", "Terraform",
}

# ── Framework signatures ──────────────────────────────────────────────────────
# (dep_set_key, required_deps_subset, framework_name)

FRAMEWORK_SIGNATURES: list[tuple[str, set, str]] = [
    # Python
    ("python_deps", {"django"}, "Django"),
    ("python_deps", {"flask"}, "Flask"),
    ("python_deps", {"fastapi"}, "FastAPI"),
    ("python_deps", {"tornado"}, "Tornado"),
    ("python_deps", {"starlette"}, "Starlette"),
    ("python_deps", {"aiohttp"}, "aiohttp"),
    ("python_deps", {"sanic"}, "Sanic"),
    ("python_deps", {"celery"}, "Celery"),
    ("python_deps", {"sqlalchemy"}, "SQLAlchemy"),
    ("python_deps", {"alembic"}, "Alembic"),
    ("python_deps", {"pydantic"}, "Pydantic"),
    ("python_deps", {"pytest"}, "pytest"),
    ("python_deps", {"langchain"}, "LangChain"),
    ("python_deps", {"openai"}, "OpenAI SDK"),
    ("python_deps", {"anthropic"}, "Anthropic SDK"),
    # JS / Node
    ("js_deps", {"react"}, "React"),
    ("js_deps", {"vue"}, "Vue"),
    ("js_deps", {"@angular/core"}, "Angular"),
    ("js_deps", {"svelte"}, "Svelte"),
    ("js_deps", {"next"}, "Next.js"),
    ("js_deps", {"nuxt"}, "Nuxt"),
    ("js_deps", {"gatsby"}, "Gatsby"),
    ("js_deps", {"@remix-run/react"}, "Remix"),
    ("js_deps", {"express"}, "Express"),
    ("js_deps", {"fastify"}, "Fastify"),
    ("js_deps", {"@nestjs/core"}, "NestJS"),
    ("js_deps", {"koa"}, "Koa"),
    ("js_deps", {"hapi"}, "Hapi"),
    ("js_deps", {"vite"}, "Vite"),
    ("js_deps", {"webpack"}, "Webpack"),
    ("js_deps", {"prisma"}, "Prisma"),
    ("js_deps", {"typeorm"}, "TypeORM"),
    ("js_deps", {"graphql"}, "GraphQL"),
    ("js_deps", {"jest"}, "Jest"),
    ("js_deps", {"vitest"}, "Vitest"),
    ("js_deps", {"playwright"}, "Playwright"),
    ("js_deps", {"cypress"}, "Cypress"),
    ("js_deps", {"langchain"}, "LangChain"),
    # Go
    ("go_deps", {"github.com/gin-gonic/gin"}, "Gin"),
    ("go_deps", {"github.com/labstack/echo"}, "Echo"),
    ("go_deps", {"github.com/gofiber/fiber"}, "Fiber"),
    ("go_deps", {"github.com/go-chi/chi"}, "Chi"),
    ("go_deps", {"gorm.io/gorm"}, "GORM"),
    # Rust
    ("rust_deps", {"actix-web"}, "Actix Web"),
    ("rust_deps", {"axum"}, "Axum"),
    ("rust_deps", {"warp"}, "Warp"),
    ("rust_deps", {"tokio"}, "Tokio"),
    ("rust_deps", {"serde"}, "Serde"),
    # Ruby
    ("ruby_deps", {"rails"}, "Ruby on Rails"),
    ("ruby_deps", {"sinatra"}, "Sinatra"),
    # PHP
    ("php_deps", {"laravel/framework"}, "Laravel"),
    ("php_deps", {"symfony/symfony"}, "Symfony"),
]

# ── Semantic folder names ─────────────────────────────────────────────────────

SEMANTIC_FOLDERS: set[str] = {
    "routes", "route", "routing",
    "controllers", "controller",
    "handlers", "handler",
    "models", "model", "entities", "entity",
    "services", "service",
    "repositories", "repository", "repos",
    "middleware", "middlewares",
    "views", "templates", "partials",
    "schemas", "schema",
    "migrations",
    "tests", "test", "__tests__", "spec", "specs",
    "utils", "helpers", "lib",
    "config", "configs", "settings",
    "api", "v1", "v2", "v3",
    "auth", "authentication", "authorization",
    "db", "database",
    "jobs", "tasks", "workers", "queues",
    "events", "listeners", "subscribers",
    "hooks", "plugins", "extensions",
    "interfaces", "types", "dto", "dtos",
    "validators", "validation",
    "errors", "exceptions",
    "graphql", "grpc", "proto",
    "infra", "infrastructure",
    "domain", "application",
    "core", "common", "shared",
}

# ── Entry point patterns ──────────────────────────────────────────────────────

ENTRY_POINT_NAMES: set[str] = {
    "main.py", "app.py", "server.py", "run.py", "manage.py",
    "wsgi.py", "asgi.py", "__main__.py",
    "index.js", "app.js", "server.js", "main.js",
    "index.ts", "app.ts", "server.ts", "main.ts",
    "main.go",
    "main.rs",
    "main.rb", "app.rb",
    "index.php",
    "Program.cs", "Startup.cs",
    "Application.java",
}

# ── Import patterns per language ──────────────────────────────────────────────
# Each entry: (compiled_regex, is_relative)
# is_relative: True = always internal, False = always external,
#              "detect" = check if starts with . or /

_JS_IMPORT_RE = re.compile(
    r'(?:import\s+[^"\';\n]*?from\s+|import\s*\(\s*)["\']([^"\']+)["\']',
    re.M,
)
_JS_REQUIRE_RE = re.compile(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', re.M)

IMPORT_PATTERNS: dict[str, list[tuple]] = {
    "Python": [
        (re.compile(r"^\s*import\s+([\w.]+)", re.M), False),
        (re.compile(r"^\s*from\s+(\.[\w.]*|[\w][\w.]*)\s+import", re.M), "detect"),
    ],
    "JavaScript": [(_JS_IMPORT_RE, "detect"), (_JS_REQUIRE_RE, "detect")],
    "TypeScript": [(_JS_IMPORT_RE, "detect"), (_JS_REQUIRE_RE, "detect")],
    "Go": [
        (re.compile(r'^\s*"([^"]+)"', re.M), False),
    ],
    "Java": [
        (re.compile(r"^\s*import\s+([\w.]+);", re.M), False),
    ],
    "Ruby": [
        (re.compile(r"^\s*require\s+['\"]([^'\"]+)['\"]", re.M), "detect"),
        (re.compile(r"^\s*require_relative\s+['\"]([^'\"]+)['\"]", re.M), True),
    ],
    "PHP": [
        (re.compile(r"(?:require|include)(?:_once)?\s*['\"]([^'\"]+)['\"]", re.M), "detect"),
    ],
    "Rust": [
        (re.compile(r"^\s*use\s+([\w:]+)", re.M), False),
        (re.compile(r"^\s*extern\s+crate\s+(\w+)", re.M), False),
    ],
}

# ── Function / class detection regex ─────────────────────────────────────────

FUNCTION_PATTERNS: dict[str, re.Pattern] = {
    "Python":     re.compile(r"^\s*(?:async\s+)?def\s+\w+", re.M),
    "JavaScript": re.compile(
        r"(?:^|\b)(?:async\s+)?function\s+\w+|"
        r"(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>|\w+\s*=>)",
        re.M,
    ),
    "TypeScript": re.compile(
        r"(?:^|\b)(?:async\s+)?function\s+\w+|"
        r"(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>|\w+\s*=>)",
        re.M,
    ),
    "Go":     re.compile(r"^\s*func\s+", re.M),
    "Java":   re.compile(
        r"(?:public|private|protected|static|final|synchronized|abstract)\s+"
        r"(?:\w+\s+)+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
        re.M,
    ),
    "Rust":   re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+", re.M),
    "Ruby":   re.compile(r"^\s*def\s+\w+", re.M),
    "PHP":    re.compile(
        r"^\s*(?:public|private|protected|static|abstract|final)?\s*function\s+\w+",
        re.M,
    ),
    "C#":     re.compile(
        r"(?:public|private|protected|internal|static|virtual|override|abstract)\s+"
        r"(?:\w+\s+)+\w+\s*\([^)]*\)",
        re.M,
    ),
    "C++":    re.compile(r"^\w[\w\s*&<>:]+\s+\w+\s*\([^;{]*\)\s*(?:const\s*)?\{", re.M),
    "C":      re.compile(r"^\w[\w\s*]+\s+\w+\s*\([^;]*\)\s*\{", re.M),
    "Kotlin": re.compile(r"^\s*(?:suspend\s+)?fun\s+\w+", re.M),
    "Swift":  re.compile(r"^\s*(?:@\w+\s+)*func\s+\w+", re.M),
    "Shell":  re.compile(r"^\s*\w+\s*\(\s*\)\s*\{", re.M),
    "Dart":   re.compile(r"^\s*(?:\w+\s+)+\w+\s*\(", re.M),
}

CLASS_PATTERNS: dict[str, re.Pattern] = {
    "Python":     re.compile(r"^\s*class\s+\w+", re.M),
    "JavaScript": re.compile(r"^\s*class\s+\w+", re.M),
    "TypeScript": re.compile(
        r"^\s*(?:abstract\s+)?class\s+\w+|^\s*interface\s+\w+|^\s*enum\s+\w+|^\s*type\s+\w+\s*=",
        re.M,
    ),
    "Go":     re.compile(r"^\s*type\s+\w+\s+struct", re.M),
    "Java":   re.compile(
        r"(?:public|private|protected|abstract|final)?\s*"
        r"(?:class|interface|enum|record)\s+\w+",
        re.M,
    ),
    "Rust":   re.compile(
        r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+\w+", re.M
    ),
    "Ruby":   re.compile(r"^\s*(?:class|module)\s+\w+", re.M),
    "PHP":    re.compile(
        r"^\s*(?:abstract|final)?\s*(?:class|interface|trait)\s+\w+", re.M
    ),
    "C#":     re.compile(
        r"(?:public|private|protected|internal|abstract|sealed|static)?\s*"
        r"(?:class|interface|struct|enum|record)\s+\w+",
        re.M,
    ),
    "Kotlin": re.compile(
        r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)?class\s+\w+|"
        r"^\s*(?:interface|object)\s+\w+",
        re.M,
    ),
    "Swift":  re.compile(
        r"^\s*(?:class|struct|enum|protocol|actor)\s+\w+", re.M
    ),
    "Dart":   re.compile(r"^\s*(?:abstract\s+)?class\s+\w+|^\s*mixin\s+\w+", re.M),
}

# ── Security patterns ─────────────────────────────────────────────────────────

SECURITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']', re.I),
     "hardcoded_password"),
    (re.compile(r'(?:api_key|apikey|api_secret)\s*=\s*["\'][^"\']{8,}["\']', re.I),
     "hardcoded_api_key"),
    (re.compile(r'(?:secret(?:_key)?)\s*=\s*["\'][^"\']{8,}["\']', re.I),
     "hardcoded_secret"),
    (re.compile(r'(?:access_token|auth_token|bearer_token)\s*=\s*["\'][^"\']{8,}["\']', re.I),
     "hardcoded_token"),
    (re.compile(r'-----BEGIN\s+(?:RSA\s+|EC\s+)?PRIVATE KEY-----', re.I),
     "private_key_in_code"),
    (re.compile(r'AKIA[0-9A-Z]{16}'),
     "aws_access_key"),
    (re.compile(
        r'(?:mysql|postgresql|postgres|mongodb|redis|sqlite)\+?://[^@\s"\']{3,}:[^@\s"\']{3,}@',
        re.I,
    ), "database_url_with_credentials"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "github_personal_token"),
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "openai_api_key"),
]

# Infrastructure / CI file patterns to detect
INFRA_FILE_PATTERNS: list[str] = [
    "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
    ".dockerignore",
    "Makefile",
    "Procfile",
    ".github/workflows",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    ".travis.yml",
    "nginx.conf",
    "k8s",
    "kubernetes",
    "helm",
    ".env.example", ".env.sample", ".env.template",
    "fly.toml",
    "vercel.json",
    "netlify.toml",
    "render.yaml",
    "railway.json",
    "serverless.yml", "serverless.yaml",
    "cloudbuild.yaml",
    "appspec.yml",
]

TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|OPTIMIZE|REFACTOR)\b")

# ══════════════════════════════════════════════════════════════════════════════
# Low-level helpers
# ══════════════════════════════════════════════════════════════════════════════

def is_excluded_dir(name: str) -> bool:
    return name.lower() in {d.lower() for d in EXCLUDED_DIRS}


def is_excluded_file(path: Path, exclude_locks: bool) -> bool:
    name = path.name
    name_lower = name.lower()
    if exclude_locks and name_lower in {f.lower() for f in LOCK_FILES}:
        return True
    for ext in EXCLUDED_EXTENSIONS:
        if name_lower.endswith(ext):
            return True
    if re.search(r"\.min\.[a-z]+$", name_lower):
        return True
    return False


def detect_language(path: Path) -> Optional[str]:
    if path.name in FILENAME_TO_LANG:
        return FILENAME_TO_LANG[path.name]
    return EXT_TO_LANG.get(path.suffix.lower())


def read_text(path: Path, max_bytes: int = 2_000_000) -> Optional[str]:
    """Read file as text. Returns None if binary/unreadable."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(max_bytes)
        if raw.count(b"\x00") > len(raw) * 0.05:
            return None
        return raw.decode("utf-8", errors="replace")
    except (PermissionError, OSError):
        return None


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (1 if not text.endswith("\n") else 0)


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def collect_files(root: Path, exclude_locks: bool) -> list[Path]:
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if not is_excluded_dir(d) and not Path(dirpath, d).is_symlink()
        )
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if not fpath.is_symlink() and not is_excluded_file(fpath, exclude_locks):
                result.append(fpath)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 1. Directory tree
# ══════════════════════════════════════════════════════════════════════════════

def build_tree(
    root: Path,
    exclude_locks: bool,
    max_depth: Optional[int],
    depth: int = 0,
) -> dict:
    node: dict = {
        "name": root.name or str(root),
        "type": "directory",
        "children": [],
        "summary": {"files": 0, "bytes": 0, "lines": 0},
    }
    if max_depth is not None and depth >= max_depth:
        node["truncated"] = True
        return node
    try:
        entries = sorted(root.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        node["error"] = "permission denied"
        return node

    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if is_excluded_dir(entry.name):
                continue
            child = build_tree(entry, exclude_locks, max_depth, depth + 1)
            node["children"].append(child)
            for k in ("files", "bytes", "lines"):
                node["summary"][k] += child["summary"][k]
        elif entry.is_file():
            if is_excluded_file(entry, exclude_locks):
                continue
            size = entry.stat().st_size
            text = read_text(entry)
            lines = count_lines(text) if text is not None else None
            node["children"].append({
                "name": entry.name,
                "type": "file",
                "lang": detect_language(entry),
                "bytes": size,
                "lines": lines,
            })
            node["summary"]["files"] += 1
            node["summary"]["bytes"] += size
            if lines:
                node["summary"]["lines"] += lines
    return node


# ══════════════════════════════════════════════════════════════════════════════
# 2. Language distribution
# ══════════════════════════════════════════════════════════════════════════════

def analyze_languages(files: list[Path]) -> dict:
    stats: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0, "bytes": 0})
    for f in files:
        lang = detect_language(f) or "Other"
        text = read_text(f)
        stats[lang]["files"] += 1
        stats[lang]["bytes"] += f.stat().st_size
        stats[lang]["lines"] += count_lines(text) if text else 0

    total_lines = sum(v["lines"] for v in stats.values()) or 1
    distribution = {
        lang: {**s, "pct_lines": round(s["lines"] / total_lines * 100, 1)}
        for lang, s in sorted(stats.items(), key=lambda x: -x[1]["lines"])
    }

    code_only = {k: v for k, v in distribution.items() if k not in NON_CODE_LANGS}
    primary = (
        max(code_only, key=lambda k: code_only[k]["lines"])
        if code_only
        else (max(distribution, key=lambda k: distribution[k]["lines"]) if distribution else "Unknown")
    )
    return {"primary": primary, "distribution": distribution}


# ══════════════════════════════════════════════════════════════════════════════
# 3. Dependency parsers
# ══════════════════════════════════════════════════════════════════════════════

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

    # PEP 517 [project] dependencies
    in_list = None
    for line in text.splitlines():
        s = line.strip()
        if s in ('dependencies = [', 'dependencies=['):
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
            m = re.match(r'^([\w\-]+)\s*=', s)
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

    # Python
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

    # JS / Node
    p = root / "package.json"
    if p.exists():
        pr, dv, scripts = _parse_package_json(p)
        _add("package.json", pr, dv, "js_deps")
        result["npm_scripts"] = scripts

    # Go
    p = root / "go.mod"
    if p.exists():
        _add("go.mod", _parse_go_mod(p), [], "go_deps")

    # Rust
    p = root / "Cargo.toml"
    if p.exists():
        pr, dv = _parse_cargo_toml(p)
        _add("Cargo.toml", pr, dv, "rust_deps")

    # Ruby
    p = root / "Gemfile"
    if p.exists():
        pr, dv = _parse_gemfile(p)
        _add("Gemfile", pr, dv, "ruby_deps")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 4. Framework detection
# ══════════════════════════════════════════════════════════════════════════════

def detect_frameworks(deps: dict) -> list[str]:
    found = set()
    for field, required, name in FRAMEWORK_SIGNATURES:
        if required & deps.get(field, set()):
            found.add(name)
    return sorted(found)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Architecture analysis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_architecture(root: Path, files: list[Path]) -> dict:
    rel_files = [f.relative_to(root) for f in files]

    # Entry points
    entry_points = []
    for rf in rel_files:
        if rf.name in ENTRY_POINT_NAMES:
            entry_points.append(str(rf))

    # All directory names (depth 1 and 2)
    all_dir_names: set[str] = set()
    for dp, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        rel_dp = Path(dp).relative_to(root)
        if len(rel_dp.parts) < 2:
            for d in dirnames:
                all_dir_names.add(d.lower())

    semantic = sorted(all_dir_names & SEMANTIC_FOLDERS)

    # Infrastructure files
    infra = []
    for pattern in INFRA_FILE_PATTERNS:
        p = root / pattern
        if p.exists():
            infra.append(pattern)

    # Test files
    test_files = [
        f for f in files
        if re.search(r"(test|spec|_test|\.test\.|\.spec\.)", f.name, re.I)
        or any(
            part.lower() in {"tests", "test", "__tests__", "spec", "specs"}
            for part in f.relative_to(root).parts
        )
    ]
    total = len(files)
    test_count = len(test_files)

    # Project type
    names = {f.name.lower() for f in files}
    proj_type = "unknown"
    if "manage.py" in names or any(f.name == "wsgi.py" for f in files):
        proj_type = "web_api"
    elif "index.js" in names or "index.ts" in names:
        if any(d in semantic for d in ("routes", "controllers", "handlers")):
            proj_type = "web_api"
        else:
            proj_type = "frontend"
    elif "main.go" in names:
        proj_type = "service"
    elif "app.py" in names or "server.py" in names:
        proj_type = "web_api"
    elif any("cli" in str(f).lower() or "commands" in str(f).lower() for f in files):
        proj_type = "cli"

    # Monorepo heuristic
    pkg_jsons = [f for f in files if f.name == "package.json"]
    pyprojects = [f for f in files if f.name == "pyproject.toml"]
    if len(pkg_jsons) > 2 or len(pyprojects) > 2:
        proj_type = "monorepo"

    return {
        "type": proj_type,
        "entry_points": list(dict.fromkeys(entry_points)),
        "semantic_folders": semantic,
        "infrastructure_files": infra,
        "test_files_count": test_count,
        "source_files_count": total - test_count,
        "test_ratio": round(test_count / total, 2) if total else 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. Import graph
# ══════════════════════════════════════════════════════════════════════════════

def build_import_graph(files: list[Path], root: Path) -> dict:
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
                    external.add(module.split(".")[0].split("/")[0])
                else:  # "detect"
                    if module.startswith(".") or module.startswith("/"):
                        internal.append(module)
                    else:
                        external.add(module.split("/")[0])

        if internal or external:
            graph[rel] = {
                "internal": sorted(set(internal)),
                "external": sorted(external),
            }

    # Count how often each internal module is imported
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

    # ── Graph enrichment ──────────────────────────────────────────────────
    # Build a stem → graph-key lookup for resolving relative imports to
    # actual file keys (handles missing extension + index.js shortcuts).
    stem_to_key: dict[str, str] = {}
    for key in graph:
        stem = os.path.splitext(key)[0]
        stem_to_key[stem] = key
        # "require('./services/postgresql')" may map to 'services/postgresql/index.js'
        from pathlib import PurePosixPath as _PPP
        if _PPP(key).stem == "index":
            parent = str(_PPP(key).parent)
            stem_to_key.setdefault(parent, key)

    def _resolve(importer: str, rel: str) -> str | None:
        """Resolve a relative import string to the matching graph key."""
        base = os.path.dirname(importer)
        raw  = os.path.normpath(os.path.join(base, rel)).replace("\\", "/")
        return stem_to_key.get(raw) or stem_to_key.get(raw + "/index")

    # Build resolved adjacency list (internal edges only, keys are graph keys)
    adj: dict[str, list[str]] = {k: [] for k in graph}
    for importer, data in graph.items():
        for rel in data["internal"]:
            target = _resolve(importer, rel)
            if target:
                adj[importer].append(target)

    # ── 1. reverse_graph  (Blast Radius) ─────────────────────────────────
    # Maps each file → list of files that directly import it.
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
        if rev.get(key)  # only files that are actually imported
    }

    # ── 2. data_flow_paths  (Critical Paths ≥ 3 hops) ────────────────────
    # DFS from every controller node; collect paths that reach a service
    # node in at least 3 hops (controller → logic → service = 3 nodes).
    def _is_role(path: str, role: str) -> bool:
        p = path.lower().replace("\\", "/")
        return role in p

    controllers = [k for k in graph if _is_role(k, "controller")]
    services    = {k for k in graph if _is_role(k, "service")}

    found_paths: list[list[str]] = []

    def _dfs(node: str, path: list[str], visited: set[str]) -> None:
        if len(path) > 7:          # guard: max depth 7 hops
            return
        if node in services and len(path) >= 3:
            found_paths.append(list(path))
            return                 # don't descend further past a service
        for nxt in adj.get(node, []):
            if nxt not in visited:
                visited.add(nxt)
                path.append(nxt)
                _dfs(nxt, path, visited)
                path.pop()
                visited.remove(nxt)

    for ctrl in controllers:
        _dfs(ctrl, [ctrl], {ctrl})

    # Sort longest-first, deduplicate, cap at 60 paths
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

    # ── 3. unreferenced_files  (dead-code candidates) ────────────────────
    # Files that appear in the graph but are NEVER imported by anything.
    _KNOWN_ENTRY_POINTS = frozenset({
        "index.js", "main.js", "server.js", "app.js",
        "manage.py", "wsgi.py", "asgi.py",
    })
    imported_set = set(rev.keys())
    unreferenced: list[dict] = [
        {"file": k, "external_deps": graph[k]["external"]}
        for k in sorted(graph)
        if k not in imported_set
        and os.path.basename(k) not in _KNOWN_ENTRY_POINTS
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


# ══════════════════════════════════════════════════════════════════════════════
# 7. Code signals
# ══════════════════════════════════════════════════════════════════════════════


# ── Security-signal regex patterns ────────────────────────────────────────────
# 1. TODO/FIXME — extract the full comment text
_TODO_TEXT_RE = re.compile(
    r"(?:#|//)\s*(TODO|FIXME|HACK|XXX|BUG|NOTE)[:\s]\s*(.{0,120})",
    re.IGNORECASE,
)

# 2. Dangerous sinks (OS / code-execution / file-write APIs)
_SINK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eval",              re.compile(r"\beval\s*\(")),
    ("exec/spawn",        re.compile(r"\b(?:exec|execSync|spawn|spawnSync|execFile)\s*\(")),
    ("fs.write",          re.compile(r"\bfs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)\s*\(")),
    ("fs.unlink/rm",      re.compile(r"\bfs\.(?:unlink|rmdir|rm|rmdirSync|unlinkSync)\s*\(")),
    ("fs.readFile",       re.compile(r"\bfs\.(?:readFile|readFileSync)\s*\(")),
    ("child_process",     re.compile(r"\brequire\(['\"]child_process['\"]\)")),
    ("vm.runInNewContext", re.compile(r"\bvm\.(?:runInNewContext|runInContext|runInThisContext)\s*\(")),
    ("innerHTML",         re.compile(r"\binnerHTML\s*=")),
    ("document.write",    re.compile(r"\bdocument\.write\s*\(")),
    ("open redirect",     re.compile(r"\bres\.redirect\s*\(\s*req\.")),
    ("path traversal hint", re.compile(r"(?:path\.join|path\.resolve)\s*\([^)]*req\.")),
]

# 3. Input sources
_SOURCE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("req.body",    re.compile(r"\breq\.body\b")),
    ("req.query",   re.compile(r"\breq\.query\b")),
    ("req.params",  re.compile(r"\breq\.params\b")),
    ("req.headers", re.compile(r"\breq\.headers\b")),
    ("req.files",   re.compile(r"\breq\.files?\b")),
]

# 4. Crypto usage
_CRYPTO_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("bcrypt.hash",         re.compile(r"\bbcrypt(?:js)?\.hash\s*\(")),
    ("bcrypt.compare",      re.compile(r"\bbcrypt(?:js)?\.compare\s*\(")),
    ("jwt.sign",            re.compile(r"\bjwt\.sign\s*\(")),
    ("jwt.verify",          re.compile(r"\bjwt\.verify\s*\(")),
    ("jwt.decode (unsafe)", re.compile(r"\bjwt\.decode\s*\(")),
    ("crypto.createHash",   re.compile(r"\bcrypto\.createHash\s*\(")),
    ("crypto.createCipher", re.compile(r"\bcrypto\.createCipher(?:iv)?\s*\(")),
    ("Math.random (weak)",  re.compile(r"\bMath\.random\s*\(")),
    ("crypto-js",           re.compile(r"\bCryptoJS\.")),
    ("otplib",              re.compile(r"\bauthenticator\.")),
]

# 5. SQL injection — only flag ACTUAL user-input concatenation
# pg.format('%I', val) and { text, values } are SAFE — excluded deliberately
_SQLI_RE = re.compile(
    r"""(?:db|pool|client|pg|connection|conn|query)\.query\s*\(\s*"""
    r"""(?:`[^`]*\$\{.*?req\.|['"][^'"]*['"\s]*\+\s*(?:req\.|[a-z_]\w*))""",
    re.IGNORECASE | re.DOTALL,
)
# Only flag format() where user input is DIRECTLY concatenated in
_SQLI_CONCAT_RE = re.compile(
    r"""(?:pg\.format|format)\s*\([^)]*\+\s*(?:req\.|params\.|body\.)""",
    re.IGNORECASE,
)

# 5b. Parameterized query detection (positive safety signal)
_PARAM_QUERY_RE = re.compile(
    r"""\.query\s*\(\s*\{[^{}]{0,400}\btext\s*:[^{}]*\bvalues\s*:""",
    re.IGNORECASE | re.DOTALL,
)

# 5c. Sensitive field extraction from req.body/params/query destructuring
_SENSITIVE_NAMES: frozenset = frozenset({
    'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey',
    'private_key', 'signing_key', 'credential', 'otp', 'code', 'pin',
    'mfa', 'totp', 'key', 'jwt', 'refresh_token', 'access_token',
    'card_number', 'cvv', 'ssn', 'account_number', 'auth',
})
_DESTRUCTURE_RE = re.compile(
    r"""const\s*\{([^}]+)\}\s*=\s*req\.(?:body|params|query)\b""",
    re.DOTALL,
)
_SIMPLE_REQ_FIELD_RE = re.compile(r"""req\.(?:body|params|query)\.(\w+)""")

# 5d. JWT — sign without algorithm, verify without algorithms array
_JWT_SIGN_BLOCK_RE   = re.compile(r"""jwt\.sign\s*\(.*?\)""", re.DOTALL)
_JWT_VERIFY_BLOCK_RE = re.compile(r"""jwt\.verify\s*\(.*?\)""", re.DOTALL)

# 5e. Missing input validation: file reads req. but has no check()/validRequest
_INPUT_GUARD_RE = re.compile(
    r"""\bcheck\s*\(|\bvalidRequest\b|\bvalidate\s*\(|\bJoi\.\b|\bbody\(|\bquery\("""
)

# 6. Authorization gaps — req.params.id / req.body.id without nearby auth guard
_AUTHZ_ID_RE    = re.compile(r"\breq\.(?:params|body|query)\s*\.\s*(?:id|userId|user_id|agentId|agent_id)\b")
_AUTHZ_GUARD_RE = re.compile(r"\b(?:validJwt|validPermission|validAgent|checkRole|isAdmin|authorize|authenticate)\b")

# 7. Error / info leakage
_ERR_LEAK_RE = re.compile(
    r"""res\.(?:json|send|status\(\d+\)\.json)\s*\(\s*(?:err|error|e|ex|exception)\b"""
    r"""|console\.(?:log|error)\s*\(\s*(?:err|error|e|ex|exception)\b""",
    re.IGNORECASE,
)


def _scan_security_signals(text: str, lang: str) -> dict:
    """Extract security signal categories from file text."""

    # 1. TODO/FIXME text
    todos: list[dict] = []
    for m in _TODO_TEXT_RE.finditer(text):
        todos.append({"type": m.group(1).upper(), "text": m.group(2).strip()})

    # 2. Dangerous sinks
    sinks: list[str] = []
    for label, pat in _SINK_PATTERNS:
        if pat.search(text):
            sinks.append(label)

    # 3. Input sources — count occurrences
    sources: dict[str, int] = {}
    for label, pat in _SOURCE_PATTERNS:
        n = len(pat.findall(text))
        if n:
            sources[label] = n

    # 4. Crypto
    crypto: list[str] = []
    for label, pat in _CRYPTO_PATTERNS:
        if pat.search(text):
            crypto.append(label)

    # 5. SQL injection — only real user-input concatenation
    sqli_hints: list[str] = []
    for m in _SQLI_RE.finditer(text):
        snippet = m.group(0)[:100].replace("\n", " ").strip()
        sqli_hints.append(snippet)
    for m in _SQLI_CONCAT_RE.finditer(text):
        snippet = m.group(0)[:100].replace("\n", " ").strip()
        if snippet not in sqli_hints:
            sqli_hints.append(snippet)

    # 5b. Parameterized queries (positive safety signal)
    param_query_count = len(_PARAM_QUERY_RE.findall(text))

    # 5c. Sensitive field names handled by this file
    sensitive_fields: list[str] = []
    seen_fields: set[str] = set()
    for m in _DESTRUCTURE_RE.finditer(text):
        for field in re.split(r"[,\s]+", m.group(1)):
            field = field.strip().rstrip(",:")
            if field and field.lower() in _SENSITIVE_NAMES and field.lower() not in seen_fields:
                sensitive_fields.append(field)
                seen_fields.add(field.lower())
    for m in _SIMPLE_REQ_FIELD_RE.finditer(text):
        field = m.group(1)
        if field.lower() in _SENSITIVE_NAMES and field.lower() not in seen_fields:
            sensitive_fields.append(field)
            seen_fields.add(field.lower())

    # 5d. JWT options check
    jwt_issues: list[str] = []
    for m in _JWT_SIGN_BLOCK_RE.finditer(text):
        if "algorithm" not in m.group(0).lower():
            jwt_issues.append("jwt.sign: no algorithm specified (algorithm confusion risk)")
            break
    for m in _JWT_VERIFY_BLOCK_RE.finditer(text):
        if "algorithms" not in m.group(0).lower():
            jwt_issues.append("jwt.verify: no algorithms array (algorithm confusion risk)")
            break

    # 5e. Missing input validation (reads req. but no guard)
    has_sources = bool(sources)
    has_validation = bool(_INPUT_GUARD_RE.search(text))
    missing_input_validation = has_sources and not has_validation

    # 6. Authorization gap — user-controlled ID without auth guard
    has_id_access  = bool(_AUTHZ_ID_RE.search(text))
    has_auth_guard = bool(_AUTHZ_GUARD_RE.search(text))
    authz_gap = has_id_access and not has_auth_guard

    # 7. Error leakage
    err_leaks: list[str] = []
    for m in _ERR_LEAK_RE.finditer(text):
        snippet = m.group(0)[:80].replace("\n", " ").strip()
        if snippet not in err_leaks:
            err_leaks.append(snippet)

    result: dict = {}
    if todos:                     result["todos"]                    = todos
    if sinks:                     result["sinks"]                    = sinks
    if sources:                   result["sources"]                  = sources
    if crypto:                    result["crypto"]                   = crypto
    if sqli_hints:                result["sqli_hints"]               = sqli_hints[:5]
    if param_query_count:         result["parameterized_queries"]    = param_query_count
    if sensitive_fields:          result["sensitive_fields"]         = sensitive_fields
    if jwt_issues:                result["jwt_issues"]               = jwt_issues
    if missing_input_validation:  result["missing_input_validation"] = True
    if authz_gap:                 result["authz_gap"]                = True
    if err_leaks:                 result["error_leaks"]              = err_leaks[:5]

    return result


def analyze_code_signals(files: list[Path], root: Path) -> dict:
    per_file = []
    totals: Counter = Counter()

    for f in files:
        lang = detect_language(f)
        text = read_text(f)
        if not text:
            continue

        lines      = count_lines(text)
        size       = f.stat().st_size
        todo_hits  = Counter(TODO_PATTERN.findall(text))  # keep original count

        func_count = 0
        class_count = 0
        if lang in FUNCTION_PATTERNS:
            func_count = len(FUNCTION_PATTERNS[lang].findall(text))
        if lang in CLASS_PATTERNS:
            class_count = len(CLASS_PATTERNS[lang].findall(text))

        complexity_keywords = len(re.findall(
            r"\b(if|else|elif|for|while|case|catch|except|and|or|&&|\|\|)\b",
            text,
        ))

        # Security signals (only for code files)
        sec_signals: dict = {}
        if lang in {"JavaScript", "TypeScript", "Python", "Java", "PHP", "Ruby"}:
            sec_signals = _scan_security_signals(text, lang)

        entry: dict = {
            "path":                str(f.relative_to(root)),
            "lang":                lang,
            "lines":               lines,
            "bytes":               size,
            "functions":           func_count,
            "classes":             class_count,
            "complexity_keywords": complexity_keywords,
            "todos":               dict(todo_hits),
        }
        if sec_signals:
            entry["security_signals"] = sec_signals

        per_file.append(entry)

        totals["functions"] += func_count
        totals["classes"]   += class_count
        for k, v in todo_hits.items():
            totals[k] += v

    # Largest source files
    source_files = [f for f in per_file if f["lang"] not in {*NON_CODE_LANGS, None}]
    largest      = sorted(source_files, key=lambda x: x["lines"], reverse=True)[:10]
    most_complex = sorted(
        [f for f in source_files if f["functions"] > 0],
        key=lambda x: x["functions"], reverse=True,
    )[:10]
    todo_heavy = sorted(
        [f for f in per_file if f["todos"]],
        key=lambda x: sum(x["todos"].values()), reverse=True,
    )[:10]

    # Security heatmap — files with any signal, sorted by risk weight
    def _sig_weight(entry: dict) -> int:
        sig = entry.get("security_signals", {})
        score = 0
        score += len(sig.get("sinks", [])) * 3
        score += len(sig.get("sqli_hints", [])) * 5       # confirmed concat = high risk
        score += 3 if sig.get("authz_gap") else 0
        score += 3 if sig.get("missing_input_validation") else 0
        score += len(sig.get("jwt_issues", [])) * 2
        score += len(sig.get("error_leaks", [])) * 2
        score += len(sig.get("sensitive_fields", [])) * 2
        score += sum(sig.get("sources", {}).values())
        score += len(sig.get("crypto", []))
        score += len(sig.get("todos", []))
        # parameterized_queries is a POSITIVE signal — not penalised
        return score

    security_heatmap = sorted(
        [f for f in per_file if f.get("security_signals")],
        key=_sig_weight, reverse=True,
    )[:20]

    return {
        "totals":          dict(totals),
        "per_file":        per_file,
        "largest_files":   [
            {"path": f["path"], "lines": f["lines"], "lang": f["lang"]}
            for f in largest
        ],
        "most_complex_files": [
            {"path": f["path"], "functions": f["functions"],
             "classes": f["classes"], "complexity_keywords": f["complexity_keywords"]}
            for f in most_complex
        ],
        "todo_heavy_files": [{"path": f["path"], "todos": f["todos"]} for f in todo_heavy],
        "security_heatmap": [
            {"path": f["path"], "score": _sig_weight(f),
             "signals": list(f.get("security_signals", {}).keys())}
            for f in security_heatmap
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. Security scan
# ══════════════════════════════════════════════════════════════════════════════

def scan_security(files: list[Path], root: Path) -> dict:
    findings = []
    exposed_env = []
    SKIP_COMMENTS = re.compile(r"^\s*(?:#|//|\*|--|<!--|;)")

    for f in files:
        name = f.name
        # Detect real .env files (not templates/examples)
        if name == ".env" or re.match(r"^\.env\.[a-z]+$", name, re.I):
            if not any(w in name.lower() for w in ("example", "sample", "template", "test")):
                exposed_env.append(str(f.relative_to(root)))

        lang = detect_language(f)
        # Scan code and config files (YAML may embed credentials)
        if lang in {"Markdown"}:
            continue

        text = read_text(f, max_bytes=500_000)
        if not text:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            if SKIP_COMMENTS.match(line):
                continue
            for pattern, ptype in SECURITY_PATTERNS:
                if pattern.search(line):
                    masked = re.sub(r'["\'][^"\']{4,}["\']', '"[REDACTED]"', line.strip())
                    findings.append({
                        "file": str(f.relative_to(root)),
                        "line": line_no,
                        "type": ptype,
                        "snippet": masked[:150],
                    })
                    break  # one finding per line max

    return {
        "exposed_env_files": exposed_env,
        "potential_secrets": findings,
        "total_findings": len(findings) + len(exposed_env),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 9. Git analysis
# ══════════════════════════════════════════════════════════════════════════════

def _git(args: list[str], cwd: Path) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def analyze_git(root: Path) -> dict:
    if not (root / ".git").exists():
        return {"available": False}

    branch      = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    last_commit = _git(["log", "-1", "--format=%H %s %ad", "--date=short"], root)
    remote      = _git(["remote", "get-url", "origin"], root)
    total_raw   = _git(["rev-list", "--count", "HEAD"], root)

    # Hot files (by commit frequency, last 1000 commits)
    raw_files = _git(
        ["log", "--pretty=format:", "--name-only", "--diff-filter=ACDM", "-n", "1000"],
        root,
    )
    file_activity: Counter = Counter()
    if raw_files:
        for line in raw_files.splitlines():
            if line.strip():
                file_activity[line.strip()] += 1

    most_active = [
        {"file": f, "commits": c}
        for f, c in file_activity.most_common(15)
    ]

    # Recently modified (last 14 days)
    recent_raw = _git(
        ["log", "--since=14.days", "--pretty=format:", "--name-only", "--diff-filter=ACDM"],
        root,
    )
    recently_modified: list[str] = []
    if recent_raw:
        seen: set[str] = set()
        for line in recent_raw.splitlines():
            if line.strip() and line.strip() not in seen:
                seen.add(line.strip())
                recently_modified.append(line.strip())

    # Contributors
    contrib_raw = _git(["shortlog", "-s", "-n", "--no-merges"], root)
    contributors = []
    if contrib_raw:
        for line in contrib_raw.splitlines()[:10]:
            m = re.match(r"\s*(\d+)\s+(.+)", line)
            if m:
                contributors.append({"commits": int(m.group(1)), "author": m.group(2).strip()})

    # First commit date
    first_commit_date = _git(["log", "--reverse", "--format=%ad", "--date=short", "-1"], root)

    return {
        "available": True,
        "branch": branch,
        "last_commit": last_commit,
        "first_commit_date": first_commit_date,
        "remote": remote,
        "total_commits": int(total_raw) if total_raw and total_raw.isdigit() else None,
        "most_active_files": most_active,
        "recently_modified_files": recently_modified[:20],
        "top_contributors": contributors,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10. API Endpoint detection
# ══════════════════════════════════════════════════════════════════════════════
#
# Detects:  router.METHOD('path', ...handlers)  /  app.METHOD('path', ...)
# Works for Express (JS/TS) and also detects Flask/FastAPI-style decorators
# (@app.route, @router.get) for Python.
# ─────────────────────────────────────────────────────────────────────────────

# Express / Koa / Fastify (JS/TS)
_ROUTE_LINE_RE = re.compile(
    r"""
    (?:router|app|Route|server|v\w+)\s*         # receiver (router / app / v1 …)
    \.\s*
    (get|post|put|patch|delete|head|options|use) # HTTP method
    \s*\(\s*
    ['"`]([^'"`\n]+)['"`]                         # path string
    ((?:\s*,\s*[\w.$\[\]()\s'"`={}:]+)*)          # rest of args (handlers)
    \s*\)
    """,
    re.VERBOSE | re.I,
)

# Python Flask / FastAPI decorator style
_PY_ROUTE_RE = re.compile(
    r"""
    @\s*(?:app|router|blueprint|bp)\s*\.\s*
    (get|post|put|patch|delete|head|route)       # method / route
    \s*\(\s*['"`]([^'"`\n]+)['"`]                # path
    """,
    re.VERBOSE | re.I,
)

_ARG_SPLIT_RE = re.compile(r"[\s,]+")


def _parse_handlers(raw_args: str) -> tuple[list[str], str]:
    """
    Given the raw args string after the path, split into middleware list and
    handler (last token). Returns (middlewares, handler).
    """
    # Remove outer whitespace / commas and split on comma+space
    parts = [
        p.strip()
        for p in re.split(r"\s*,\s*", raw_args.strip().strip(","))
        if p.strip()
    ]
    if not parts:
        return [], ""
    # Last part is typically the controller handler; rest are middlewares
    return parts[:-1], parts[-1]


def analyze_endpoints(files: list[Path], root: Path) -> dict:
    """Extract HTTP route declarations from JS/TS/Python source files."""
    endpoints: list[dict] = []
    routes_per_file: dict[str, int] = {}

    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript", "Python"}:
            continue
        text = read_text(f)
        if not text:
            continue

        rel = str(f.relative_to(root))
        count = 0

        if lang in {"JavaScript", "TypeScript"}:
            for m in _ROUTE_LINE_RE.finditer(text):
                method   = m.group(1).upper()
                path     = m.group(2)
                raw_args = m.group(3) or ""
                middlewares, handler = _parse_handlers(raw_args)
                endpoints.append({
                    "method":      method,
                    "path":        path,
                    "file":        rel,
                    "line":        text[: m.start()].count("\n") + 1,
                    "middlewares": middlewares,
                    "handler":     handler,
                })
                count += 1

        elif lang == "Python":
            for m in _PY_ROUTE_RE.finditer(text):
                method = m.group(1).upper()
                path   = m.group(2)
                endpoints.append({
                    "method":      method,
                    "path":        path,
                    "file":        rel,
                    "line":        text[: m.start()].count("\n") + 1,
                    "middlewares": [],
                    "handler":     "",
                })
                count += 1

        if count:
            routes_per_file[rel] = count

    # Group by path prefix (first segment) for a quick domain map
    domains: dict[str, list[str]] = defaultdict(set)  # type: ignore[assignment]
    for ep in endpoints:
        parts = [p for p in ep["path"].split("/") if p and not p.startswith(":")]
        prefix = parts[0] if parts else "/"
        domains[prefix].add(ep["method"])

    # ── Route parameter extraction (:id, :userId, etc.) ──────────────────
    _ROUTE_PARAM_RE = re.compile(r":(\w+)")
    for ep in endpoints:
        params = _ROUTE_PARAM_RE.findall(ep["path"])
        if params:
            ep["route_params"] = params

    # ── Unprotected routes (no auth middleware visible) ───────────────────
    _AUTH_MW_TOKENS = frozenset({
        "validjwt", "validpermission", "validagent", "authmiddleware",
        "checkrole", "isadmin", "authenticate", "authorize", "requireauth",
        "ensureauth", "jwtauth", "bearerauth",
    })
    unprotected: list[dict] = []
    for ep in endpoints:
        mw_clean = {re.sub(r"[^a-z]", "", t.lower()) for t in ep.get("middlewares", [])}
        if not (mw_clean & _AUTH_MW_TOKENS):
            entry: dict = {"method": ep["method"], "path": ep["path"],
                           "file": ep["file"], "line": ep["line"]}
            if ep.get("route_params"):
                entry["route_params"] = ep["route_params"]
            unprotected.append(entry)

    return {
        "total": len(endpoints),
        "routes_per_file": routes_per_file,
        "domain_map": {k: sorted(v) for k, v in sorted(domains.items())},
        "endpoints": endpoints,
        "unprotected_routes": unprotected,
        "total_unprotected": len(unprotected),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 11. Environment variables
# ══════════════════════════════════════════════════════════════════════════════

# JS/TS: process.env.VAR_NAME
_JS_ENV_RE = re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)")
# Python: os.environ['VAR'] / os.environ.get('VAR') / os.getenv('VAR')
_PY_ENV_RE = re.compile(
    r"""
    (?:os\.environ\s*\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]|
       os\.environ\.get\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]|
       os\.getenv\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\))
    """,
    re.VERBOSE,
)
# Ruby: ENV['VAR'] / ENV["VAR"]
_RB_ENV_RE = re.compile(r'ENV\s*\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]')
# Go: os.Getenv("VAR")
_GO_ENV_RE = re.compile(r'os\.Getenv\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*\)')


def analyze_env_vars(files: list[Path], root: Path) -> dict:
    """
    Find every env variable referenced in the codebase.
    Returns:
      - vars: { VAR_NAME: { files: [...], count: N } }  sorted by count desc
      - summary: total unique vars, total references
      - files_using_env: { file: [VAR1, VAR2, ...] }
    """
    var_files: dict[str, set] = defaultdict(set)
    var_count: Counter = Counter()
    file_vars: dict[str, set] = defaultdict(set)

    for f in files:
        lang = detect_language(f)
        text = read_text(f)
        if not text:
            continue
        rel = str(f.relative_to(root))

        found: list[str] = []
        if lang in {"JavaScript", "TypeScript"}:
            found = _JS_ENV_RE.findall(text)
        elif lang == "Python":
            for m in _PY_ENV_RE.finditer(text):
                name = m.group(1) or m.group(2) or m.group(3)
                if name:
                    found.append(name)
        elif lang == "Ruby":
            found = _RB_ENV_RE.findall(text)
        elif lang == "Go":
            found = _GO_ENV_RE.findall(text)

        for name in found:
            var_files[name].add(rel)
            var_count[name] += 1
            file_vars[rel].add(name)

    # Sort by reference count
    ordered = {
        name: {
            "files": sorted(var_files[name]),
            "references": var_count[name],
        }
        for name, _ in var_count.most_common()
    }

    # ── Sensitivity classification ────────────────────────────────────────
    _SECRET_WORDS = frozenset({"key", "secret", "token", "signing", "private",
                               "hmac", "jwt", "salt", "iam"})
    _CRED_WORDS   = frozenset({"password", "passwd", "pwd", "credential",
                               "username", "user", "login", "auth", "apikey", "api_key"})
    _CONN_WORDS   = frozenset({"host", "port", "url", "uri", "endpoint",
                               "database", "db", "schema", "bucket", "region", "instance"})

    classified: dict[str, list[str]] = {"SECRET": [], "CREDENTIAL": [], "CONNECTIVITY": [], "RUNTIME": []}
    for name in ordered:
        parts = set(re.split(r"[_\-]", name.lower()))
        if parts & _SECRET_WORDS:
            classified["SECRET"].append(name)
        elif parts & _CRED_WORDS:
            classified["CREDENTIAL"].append(name)
        elif parts & _CONN_WORDS:
            classified["CONNECTIVITY"].append(name)
        else:
            classified["RUNTIME"].append(name)

    return {
        "total_unique_vars": len(ordered),
        "total_references": sum(var_count.values()),
        "vars": ordered,
        "files_using_env": {f: sorted(v) for f, v in sorted(file_vars.items())},
        "classified": {k: sorted(v) for k, v in classified.items() if v},
    }


# ══════════════════════════════════════════════════════════════════════════════
# 12. Database / SQL + ORM/ODM analysis
# ══════════════════════════════════════════════════════════════════════════════

# Schema-qualified CREATE TABLE: matches both `schema.table` and plain `table`.
# Group 1 = optional schema prefix, Group 2 = actual table name.
_SQL_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
    re.I,
)

# DML patterns — work on plain SQL or extracted SQL strings.
# Regex captures the first identifier after the keyword (schema.table → table).
_SQL_DML_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("SELECT", re.compile(
        r"\bSELECT\b.{1,300}?\bFROM\b\s+(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
        re.I | re.S,
    )),
    ("INSERT", re.compile(
        r"\bINSERT\s+INTO\s+(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
        re.I,
    )),
    ("UPDATE", re.compile(
        r"\bUPDATE\s+(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?\s+SET\b",
        re.I,
    )),
    ("DELETE", re.compile(
        r"\bDELETE\s+FROM\s+(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
        re.I,
    )),
    ("JOIN", re.compile(
        r"\b(?:INNER|LEFT|RIGHT|FULL|CROSS)?\s*JOIN\s+"
        r"(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
        re.I,
    )),
]

# Words that look like table names but are SQL keywords / false positives.
_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "null", "true", "false",
    "case", "when", "then", "else", "end", "as", "on", "in", "is", "like",
    "between", "exists", "all", "any", "some", "having", "group", "order",
    "by", "limit", "offset", "distinct", "union", "except", "intersect",
    "with", "returning", "set", "values", "into", "table", "view", "index",
    "the", "public", "schema", "lateral", "current_timestamp", "now",
    "coalesce", "nullif", "cast", "convert", "count", "sum", "min",
    "max", "avg", "row_number", "rank", "over", "partition", "window",
    "primary", "foreign", "key", "constraint", "unique", "default",
    "references", "cascade", "restrict", "action", "no",
}

# ── ORM / ODM signatures ──────────────────────────────────────────────────────
#
# Each entry: (orm_name, language_family, list_of_patterns)
# A pattern is a compiled regex that matches a meaningful ORM call.
# We extract one capture group = model / collection / table name when possible.

_ORM_PATTERNS: list[tuple[str, set[str], list[re.Pattern]]] = [
    # ── JavaScript / TypeScript ───────────────────────────────────────────────
    ("Sequelize", {"JavaScript", "TypeScript"}, [
        re.compile(r"(\w+)\.findAll\s*\(", re.I),
        re.compile(r"(\w+)\.findOne\s*\(", re.I),
        re.compile(r"(\w+)\.findByPk\s*\(", re.I),
        re.compile(r"(\w+)\.create\s*\(", re.I),
        re.compile(r"(\w+)\.update\s*\(", re.I),
        re.compile(r"(\w+)\.destroy\s*\(", re.I),
        re.compile(r"(\w+)\.bulkCreate\s*\(", re.I),
        re.compile(r"sequelize\.define\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"DataTypes\.", re.I),
    ]),
    ("TypeORM", {"JavaScript", "TypeScript"}, [
        re.compile(r"@Entity\s*\((?:['\"](\w+)['\"])?\)", re.I),
        re.compile(r"@Table\s*\((?:.*?name\s*:\s*['\"](\w+)['\"])?", re.I),
        re.compile(r"getRepository\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"\.getRepository\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"createQueryBuilder\s*\(\s*['\"]?(\w+)['\"]?\s*\)", re.I),
        re.compile(r"\.find\s*\(\s*\{", re.I),
        re.compile(r"\.findOne\s*\(\s*\{", re.I),
        re.compile(r"\.save\s*\(\s*\w+\s*\)", re.I),
        re.compile(r"\.delete\s*\(\s*\w+\s*,", re.I),
        re.compile(r"InjectRepository\s*\(\s*(\w+)\s*\)", re.I),
    ]),
    ("Prisma", {"JavaScript", "TypeScript"}, [
        re.compile(r"prisma\.(\w+)\.findMany\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.findFirst\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.findUnique\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.create\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.update\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.upsert\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.delete\s*\(", re.I),
        re.compile(r"prisma\.(\w+)\.count\s*\(", re.I),
        re.compile(r"model\s+(\w+)\s*\{", re.I),  # in schema.prisma
    ]),
    ("Mongoose", {"JavaScript", "TypeScript"}, [
        re.compile(r"mongoose\.model\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"new\s+Schema\s*\(", re.I),
        re.compile(r"(\w+)\.find\s*\(", re.I),
        re.compile(r"(\w+)\.findById\s*\(", re.I),
        re.compile(r"(\w+)\.findByIdAndUpdate\s*\(", re.I),
        re.compile(r"(\w+)\.findByIdAndDelete\s*\(", re.I),
        re.compile(r"(\w+)\.aggregate\s*\(", re.I),
        re.compile(r"new\s+(\w+)\s*\(", re.I),
    ]),
    ("Knex", {"JavaScript", "TypeScript"}, [
        re.compile(r"knex\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"\.table\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"knex\.schema\.createTable\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"knex\.schema\.alterTable\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"trx\s*\(\s*['\"](\w+)['\"]", re.I),
    ]),
    ("Drizzle", {"JavaScript", "TypeScript"}, [
        re.compile(r"pgTable\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"mysqlTable\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"sqliteTable\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"db\.select\(\)\.from\s*\((\w+)\)", re.I),
        re.compile(r"db\.insert\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"db\.update\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"db\.delete\s*\(\s*(\w+)\s*\)", re.I),
    ]),
    # ── Python ────────────────────────────────────────────────────────────────
    ("SQLAlchemy", {"Python"}, [
        re.compile(r"class\s+(\w+)\s*\(.*(?:Base|Model|DeclarativeBase)", re.I),
        re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]", re.I),
        re.compile(r"Table\s*\(\s*['\"](\w+)['\"]", re.I),
        re.compile(r"session\.query\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"db\.session\.(add|delete|query)\s*\(", re.I),
        re.compile(r"select\s*\(\s*(\w+)\s*\)", re.I),
    ]),
    ("Django ORM", {"Python"}, [
        re.compile(r"class\s+(\w+)\s*\(.*models\.Model\s*\)", re.I),
        re.compile(r"(\w+)\.objects\.(filter|get|create|update|delete|all|exclude|annotate|aggregate)\s*\(", re.I),
        re.compile(r"db_table\s*=\s*['\"](\w+)['\"]", re.I),
    ]),
    ("Tortoise ORM", {"Python"}, [
        re.compile(r"class\s+(\w+)\s*\(.*Model\s*\):", re.I),
        re.compile(r"(\w+)\.filter\s*\(", re.I),
        re.compile(r"(\w+)\.create\s*\(", re.I),
        re.compile(r"await\s+(\w+)\.get_or_create\s*\(", re.I),
    ]),
    ("Peewee", {"Python"}, [
        re.compile(r"class\s+(\w+)\s*\(.*Model\s*\):", re.I),
        re.compile(r"(\w+)\.select\s*\(", re.I),
        re.compile(r"(\w+)\.insert\s*\(", re.I),
        re.compile(r"db_table\s*=\s*['\"](\w+)['\"]", re.I),
    ]),
    # ── Go ────────────────────────────────────────────────────────────────────
    ("GORM", {"Go"}, [
        re.compile(r'db\.Where\s*\(', re.I),
        re.compile(r'db\.Find\s*\(', re.I),
        re.compile(r'db\.First\s*\(', re.I),
        re.compile(r'db\.Create\s*\(', re.I),
        re.compile(r'db\.Save\s*\(', re.I),
        re.compile(r'db\.Delete\s*\(', re.I),
        re.compile(r'db\.Model\s*\(', re.I),
        re.compile(r'`gorm:"[^"]*"', re.I),
        re.compile(r'AutoMigrate\s*\(', re.I),
    ]),
    ("Ent (entgo)", {"Go"}, [
        re.compile(r'\.From\s*\(\s*(\w+)\s*\)', re.I),
        re.compile(r'client\.(\w+)\.Create\s*\(\)', re.I),
        re.compile(r'client\.(\w+)\.Query\s*\(\)', re.I),
        re.compile(r'client\.(\w+)\.Delete\s*\(\)', re.I),
    ]),
    # ── Java / Kotlin ─────────────────────────────────────────────────────────
    ("JPA / Hibernate", {"Java", "Kotlin"}, [
        re.compile(r"@Entity\b", re.I),
        re.compile(r'@Table\s*\(\s*name\s*=\s*"(\w+)"', re.I),
        re.compile(r"em\.persist\s*\(", re.I),
        re.compile(r"em\.merge\s*\(", re.I),
        re.compile(r"em\.remove\s*\(", re.I),
        re.compile(r"session\.save\s*\(", re.I),
        re.compile(r"session\.get\s*\(", re.I),
        re.compile(r"\.createQuery\s*\(", re.I),
        re.compile(r"@NamedQuery\b", re.I),
    ]),
    ("Spring Data JPA", {"Java", "Kotlin"}, [
        re.compile(r"extends\s+(?:JpaRepository|CrudRepository|PagingAndSortingRepository)", re.I),
        re.compile(r"@Repository\b", re.I),
        re.compile(r"@Query\s*\(", re.I),
    ]),
    # ── Ruby ──────────────────────────────────────────────────────────────────
    ("ActiveRecord", {"Ruby"}, [
        re.compile(r"class\s+(\w+)\s*<\s*(?:ApplicationRecord|ActiveRecord::Base)", re.I),
        re.compile(r"(\w+)\.where\s*\(", re.I),
        re.compile(r"(\w+)\.find\s*\(", re.I),
        re.compile(r"(\w+)\.create\s*\(", re.I),
        re.compile(r"(\w+)\.update\s*\(", re.I),
        re.compile(r"(\w+)\.destroy\s*\(", re.I),
        re.compile(r"has_many\s+:", re.I),
        re.compile(r"belongs_to\s+:", re.I),
    ]),
    # ── PHP ───────────────────────────────────────────────────────────────────
    ("Eloquent (Laravel)", {"PHP"}, [
        re.compile(r"class\s+(\w+)\s+extends\s+Model\b", re.I),
        re.compile(r"(\w+)::where\s*\(", re.I),
        re.compile(r"(\w+)::find\s*\(", re.I),
        re.compile(r"(\w+)::create\s*\(", re.I),
        re.compile(r"\$table\s*=\s*['\"](\w+)['\"]", re.I),
        re.compile(r"DB::table\s*\(\s*['\"](\w+)['\"]", re.I),
    ]),
    ("Doctrine", {"PHP"}, [
        re.compile(r"@ORM\\Entity\b", re.I),
        re.compile(r'@ORM\\Table\s*\(\s*name\s*=\s*"(\w+)"', re.I),
        re.compile(r"\$em->persist\s*\(", re.I),
        re.compile(r"\$em->remove\s*\(", re.I),
        re.compile(r"->createQueryBuilder\s*\(", re.I),
    ]),
    # ── Rust ──────────────────────────────────────────────────────────────────
    ("Diesel", {"Rust"}, [
        re.compile(r"diesel::insert_into\s*\((\w+)", re.I),
        re.compile(r"diesel::update\s*\((\w+)", re.I),
        re.compile(r"diesel::delete\s*\((\w+)", re.I),
        re.compile(r"\.filter\s*\(", re.I),
        re.compile(r"table!\s*\{", re.I),
        re.compile(r"#\[derive\(Queryable\)\]", re.I),
        re.compile(r"#\[derive\(Insertable\)\]", re.I),
    ]),
    ("SQLx", {"Rust"}, [
        re.compile(r"sqlx::query!\s*\(", re.I),
        re.compile(r"sqlx::query_as!\s*\(", re.I),
        re.compile(r"query\s*\(\s*r?\"[^\"]*\"", re.I),
    ]),
    # ── C# ────────────────────────────────────────────────────────────────────
    ("Entity Framework", {"C#"}, [
        re.compile(r"DbContext\b", re.I),
        re.compile(r"DbSet\s*<(\w+)>", re.I),
        re.compile(r"\[Table\s*\(\s*\"(\w+)\"\s*\)\]", re.I),
        re.compile(r"\.SaveChanges\s*\(", re.I),
        re.compile(r"\.SaveChangesAsync\s*\(", re.I),
        re.compile(r"\.Add\s*\(\s*\w+\s*\)", re.I),
        re.compile(r"\.Remove\s*\(\s*\w+\s*\)", re.I),
        re.compile(r"\.Include\s*\(", re.I),
    ]),
    # ── Swift ──────────────────────────────────────────────────────────────────
    ("CoreData", {"Swift"}, [
        re.compile(r"NSManagedObject\b", re.I),
        re.compile(r"NSFetchRequest\b", re.I),
        re.compile(r"viewContext\.save\s*\(", re.I),
        re.compile(r"@NSManaged\b", re.I),
    ]),
    # ── Dart / Flutter ────────────────────────────────────────────────────────
    ("Drift (Moor)", {"Dart"}, [
        re.compile(r"@DataClassName\s*\(", re.I),
        re.compile(r"extends\s+Table\b", re.I),
        re.compile(r"\.watch\s*\(", re.I),
    ]),
]

# ORM operation labels for canonical method → SQL operation mapping
_ORM_OP_MAP: dict[str, str] = {
    "findAll": "SELECT", "findMany": "SELECT", "find": "SELECT",
    "findOne": "SELECT", "findFirst": "SELECT", "findUnique": "SELECT",
    "findByPk": "SELECT", "findById": "SELECT",
    "get": "SELECT", "query": "SELECT", "select": "SELECT",
    "filter": "SELECT", "where": "SELECT", "all": "SELECT",
    "first": "SELECT", "last": "SELECT",
    "create": "INSERT", "insert": "INSERT", "save": "INSERT/UPDATE",
    "bulkCreate": "INSERT", "bulkInsert": "INSERT",
    "update": "UPDATE", "upsert": "INSERT/UPDATE",
    "delete": "DELETE", "destroy": "DELETE", "remove": "DELETE",
    "persist": "INSERT/UPDATE", "merge": "UPDATE",
    "aggregate": "SELECT", "count": "SELECT",
}

_ORM_METHOD_RE = re.compile(
    r"\.(" + "|".join(re.escape(k) for k in _ORM_OP_MAP) + r")\s*\(",
    re.I,
)


def _extract_sql_from_code(text: str, lang: str) -> str:
    """Pull SQL strings out of template literals, quoted strings and f-strings."""
    if lang in {"JavaScript", "TypeScript"}:
        tl = re.findall(r"`([^`]*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^`]*)`", text, re.I)
        qs = re.findall(
            r"""["']([^"']*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"']*)["']""",
            text, re.I,
        )
        return "\n".join(tl + qs)
    if lang == "Python":
        tl = re.findall(r'"""([^"]*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"]*)"""', text, re.I | re.S)
        qs = re.findall(
            r"""["']([^"']*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"']*)["']""",
            text, re.I,
        )
        return "\n".join(tl + qs)
    return text  # SQL / plain text — use as-is


def analyze_database(files: list[Path], root: Path) -> dict:
    """
    1. Parse every .sql file to build the definitive table schema map (deduplicated).
    2. Cross-reference each table name across ALL code files to discover DML usage.
    3. Detect ORM/ODM usage patterns per file.
    """

    # ── Pass 1: collect table definitions from SQL files ─────────────────────
    # schema_map: { table_lower → { canonical_name, definition_file, definition_lines } }
    schema_map: dict[str, dict] = {}
    sql_files: list[tuple[Path, str]] = []   # (path, text) for reuse in pass 2

    for f in files:
        if detect_language(f) != "SQL":
            continue
        text = read_text(f) or ""
        rel  = str(f.relative_to(root))
        sql_files.append((f, text))

        for m in _SQL_CREATE_TABLE_RE.finditer(text):
            tname = m.group(1)
            if not tname or tname.lower() in _SQL_KEYWORDS:
                continue
            key = tname.lower()
            line_no = text[: m.start()].count("\n") + 1
            if key not in schema_map:
                schema_map[key] = {
                    "table": tname,
                    "definition_file": rel,
                    "definition_lines": [line_no],
                }
            else:
                if line_no not in schema_map[key]["definition_lines"]:
                    schema_map[key]["definition_lines"].append(line_no)

    # ── Pass 2: DML usage scan — SQL files + code files ──────────────────────
    # table_usage: { table_lower → { ops: set, files: set } }
    table_usage: dict[str, dict] = defaultdict(lambda: {"operations": set(), "files": set()})

    # Also scan SQL files themselves for DML (stored procedures, etc.)
    code_langs = {"JavaScript", "TypeScript", "Python", "Java", "Go", "Ruby", "PHP", "C#", "Kotlin", "Swift", "Rust", "Dart"}

    for f in files:
        lang = detect_language(f)
        rel  = str(f.relative_to(root))

        if lang == "SQL":
            sql_text = read_text(f) or ""
        elif lang in code_langs:
            raw = read_text(f) or ""
            if not re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|JOIN)\b", raw, re.I):
                # No raw SQL keywords — still run ORM scan later but skip SQL
                continue
            sql_text = _extract_sql_from_code(raw, lang)
        else:
            continue

        for op, pattern in _SQL_DML_PATTERNS:
            for m in pattern.finditer(sql_text):
                tname = m.group(1)
                if not tname or tname.lower() in _SQL_KEYWORDS or len(tname) < 2:
                    continue
                key = tname.lower()
                table_usage[key]["operations"].add(op)
                table_usage[key]["files"].add(rel)

    # ── Pass 3: cross-reference — search each known table name in code files ─
    # For each table defined in the schema, scan every code file for its name.
    # This catches cases where the ORM or raw string doesn't match DML patterns.
    known_tables = set(schema_map.keys())

    # Build an index: file_rel → text (only for code files, cached)
    code_cache: dict[str, str] = {}
    for f in files:
        lang = detect_language(f)
        if lang in code_langs:
            rel = str(f.relative_to(root))
            code_cache[rel] = read_text(f) or ""

    for key in known_tables:
        canonical = schema_map[key]["table"]
        pat = re.compile(r"\b" + re.escape(canonical) + r"\b", re.I)
        op_pat = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|JOIN|UPSERT)\b", re.I)
        for rel, text in code_cache.items():
            if not pat.search(text):
                continue
            table_usage[key]["files"].add(rel)
            # Check each line that mentions the table for SQL operation keywords
            for line in text.splitlines():
                if pat.search(line) and op_pat.search(line):
                    for op_m in op_pat.finditer(line):
                        table_usage[key]["operations"].add(op_m.group(1).upper())

    # ── Pass 4: ORM / ODM scan ───────────────────────────────────────────────
    orm_usage: dict[str, dict] = {}  # { orm_name: { files: set, models: set, operations: set } }

    for f in files:
        lang = detect_language(f)
        if not lang:
            continue
        rel  = str(f.relative_to(root))
        # Also check schema.prisma as TypeScript-like
        effective_lang = "TypeScript" if f.name.endswith(".prisma") else lang

        text = code_cache.get(rel) or read_text(f) or ""
        if not text:
            continue

        for orm_name, supported_langs, patterns in _ORM_PATTERNS:
            if effective_lang not in supported_langs:
                continue
            matched_any = False
            models_found: set[str] = set()
            ops_found: set[str] = set()

            for pat in patterns:
                for m in pat.finditer(text):
                    matched_any = True
                    if m.lastindex and m.group(1):
                        models_found.add(m.group(1))

            if matched_any:
                # Detect ORM operation types on the same lines
                for m in _ORM_METHOD_RE.finditer(text):
                    method = m.group(1).lower()
                    op = _ORM_OP_MAP.get(method)
                    if op:
                        ops_found.add(op)

                if orm_name not in orm_usage:
                    orm_usage[orm_name] = {"files": set(), "models": set(), "operations": set()}
                orm_usage[orm_name]["files"].add(rel)
                orm_usage[orm_name]["models"].update(models_found - {"", "undefined"})
                orm_usage[orm_name]["operations"].update(ops_found)

    # ── Serialize ─────────────────────────────────────────────────────────────
    schema_list = []
    for key, entry in sorted(schema_map.items()):
        tname = entry["table"]
        usage = table_usage.get(key, {})
        schema_list.append({
            "table":            tname,
            "definition_file":  entry["definition_file"],
            "definition_lines": sorted(entry["definition_lines"]),
            "operations_seen":  sorted(usage.get("operations", set())),
            "used_in_files":    sorted(usage.get("files", set())),
        })

    all_usage_serialized = {
        tname: {
            "operations": sorted(info["operations"]),
            "files":      sorted(info["files"]),
        }
        for tname, info in sorted(table_usage.items())
    }

    defined_lowers = set(schema_map.keys())
    undeclared = {
        tname: info
        for tname, info in all_usage_serialized.items()
        if tname not in defined_lowers and tname not in _SQL_KEYWORDS
    }

    orm_serialized = {
        name: {
            "files":      sorted(info["files"]),
            "models":     sorted(info["models"]),
            "operations": sorted(info["operations"]),
        }
        for name, info in sorted(orm_usage.items())
    }

    detected_orms = sorted(orm_usage.keys())

    return {
        "schema_tables":      schema_list,
        "all_table_usage":    all_usage_serialized,
        "undeclared_tables":  undeclared,
        "orm_odm": {
            "detected": detected_orms,
            "details":  orm_serialized,
        },
        "total_schema_tables": len(schema_list),
        "total_tables_used":   len(all_usage_serialized),
        "sql_files_used_as_map": [str(f.relative_to(root)) for f, _ in sql_files],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 13. Middleware chains in routes
# ══════════════════════════════════════════════════════════════════════════════
#
# For each route declaration, extract the middleware functions listed before
# the final controller handler.  Also produces a global middleware usage table.
# ─────────────────────────────────────────────────────────────────────────────

# Names that look like controller handlers rather than middlewares
_HANDLER_HINTS = re.compile(r"Controller\.|\.handler|\.action|ctrl\.", re.I)

# Known middleware file-stem prefixes
_MW_PREFIXES = re.compile(
    r"^(?:valid|check|ensure|verify|auth|permission|role|guard|protect|rate|"
    r"cors|logger|morgan|helmet|compress|parse|body|session|jwt|mfa|cache)",
    re.I,
)


def analyze_middlewares(files: list[Path], root: Path) -> dict:
    """
    Analyse route files and extract:
    - per_route: [ { method, path, file, line, middlewares, handler } ]
    - middleware_usage: { mw_name: { routes: N, files: [...] } }
    - middleware_files: list of files that export middleware functions
    """
    routes_with_mw: list[dict] = []
    mw_counter: Counter = Counter()
    mw_files: dict[str, set] = defaultdict(set)
    middleware_source_files: list[str] = []

    # Detect which files are middleware files
    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript"}:
            continue
        rel = str(f.relative_to(root))
        parts = Path(rel).parts
        # If file lives under a 'middlewares' / 'middleware' folder
        if any(p.lower() in {"middlewares", "middleware"} for p in parts):
            middleware_source_files.append(rel)

    # Parse route files
    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript", "Python"}:
            continue
        text = read_text(f)
        if not text:
            continue
        rel = str(f.relative_to(root))

        if lang in {"JavaScript", "TypeScript"}:
            for m in _ROUTE_LINE_RE.finditer(text):
                method   = m.group(1).upper()
                path     = m.group(2)
                raw_args = m.group(3) or ""
                middlewares, handler = _parse_handlers(raw_args)

                if not middlewares:
                    continue   # skip routes with no middleware (noise)

                # Remove anything that looks like a plain controller call
                clean_mw = [
                    mw for mw in middlewares
                    if not _HANDLER_HINTS.search(mw)
                ]

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
                        # Normalise: strip call-expression suffixes  valid-jwt → valid-jwt
                        base = re.split(r"[\s(.]", mw)[0]
                        mw_counter[base] += 1
                        mw_files[base].add(rel)

    middleware_usage = {
        name: {
            "route_count": count,
            "files": sorted(mw_files[name]),
        }
        for name, count in mw_counter.most_common()
    }

    return {
        "middleware_source_files": sorted(middleware_source_files),
        "routes_with_middleware": routes_with_mw,
        "middleware_usage": middleware_usage,
        "total_middlewares_detected": len(middleware_usage),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 14. Main assembler
# ══════════════════════════════════════════════════════════════════════════════

def generate_map(
    root: Path,
    exclude_locks: bool = False,
    max_depth: Optional[int] = None,
    no_git: bool = False,
    no_security: bool = False,
    no_imports: bool = False,
) -> dict:
    total_steps = 11 - int(no_git) - int(no_security) - int(no_imports)
    step = 0

    def log(msg: str) -> None:
        nonlocal step
        step += 1
        print(f"  [{step}/{total_steps}] {msg}", file=sys.stderr)

    print(f"Scanning {root} ...", file=sys.stderr)
    files = collect_files(root, exclude_locks)
    print(f"  Found {len(files)} files.", file=sys.stderr)

    log("Building directory tree ...")
    tree = build_tree(root, exclude_locks, max_depth)
    tree["path"] = str(root)

    log("Analyzing languages ...")
    lang_info = analyze_languages(files)

    log("Parsing dependencies and detecting frameworks ...")
    deps = find_dependencies(root)
    frameworks = detect_frameworks(deps)

    log("Analyzing architecture ...")
    arch = analyze_architecture(root, files)

    log("Detecting API endpoints ...")
    endpoints = analyze_endpoints(files, root)

    log("Extracting environment variables ...")
    env_vars = analyze_env_vars(files, root)

    log("Analyzing database / SQL usage ...")
    database = analyze_database(files, root)

    log("Mapping middleware chains ...")
    middlewares = analyze_middlewares(files, root)

    import_data: dict = {"available": False}
    if not no_imports:
        log("Building import graph ...")
        import_data = build_import_graph(files, root)
        import_data["available"] = True

    log("Analyzing code signals ...")
    code_signals = analyze_code_signals(files, root)

    security: dict = {"available": False}
    if not no_security:
        log("Scanning security hints ...")
        security = scan_security(files, root)
        security["available"] = True

    git: dict = {"available": False}
    if not no_git:
        log("Reading git history ...")
        git = analyze_git(root)

    meta = {
        "generated_at": datetime.now().isoformat(),
        "root": str(root),
        "scanner_version": SCRIPT_VERSION,
    }

    return {
        "meta": meta,
        "identity": {
            "name": root.name,
            "type": arch["type"],
            "primary_language": lang_info["primary"],
            "language_distribution": lang_info["distribution"],
            "frameworks": frameworks,
            "dependencies": {
                "source_files": deps["source_files"],
                "npm_scripts": deps.get("npm_scripts", []),
                "production": deps["production"][:150],
                "development": deps["development"][:150],
            },
        },
        "structure": {
            "tree": tree,
            "entry_points": arch["entry_points"],
            "semantic_folders": arch["semantic_folders"],
            "infrastructure_files": arch["infrastructure_files"],
            "total_files": len(files),
            "test_files_count": arch["test_files_count"],
            "source_files_count": arch["source_files_count"],
            "test_ratio": arch["test_ratio"],
        },
        "endpoints":   endpoints,
        "env_vars":    env_vars,
        "database":    database,
        "middlewares": middlewares,
        "imports":     import_data,
        "code_signals": code_signals,
        "security":    security,
        "git":         git,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 15. Tree rendering helper (shared by formatters)
# ══════════════════════════════════════════════════════════════════════════════

def _render_tree_lines(node: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    connector = "└── " if is_last else "├── "
    extender  = "    " if is_last else "│   "
    out = []
    if node["type"] == "directory":
        s = node["summary"]
        out.append(
            f"{prefix}{connector}{node['name']}/ "
            f"[{s['files']} files | {fmt_bytes(s['bytes'])} | {s['lines']:,} lines]"
        )
        children = node.get("children", [])
        for i, child in enumerate(children):
            out.extend(_render_tree_lines(child, prefix + extender, i == len(children) - 1))
        if node.get("truncated"):
            out.append(f"{prefix}{extender}... (max-depth reached)")
    else:
        ln = f"{node['lines']:,} lines" if node.get("lines") is not None else "binary"
        out.append(f"{prefix}{connector}{node['name']} [{fmt_bytes(node['bytes'])} | {ln}]")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 12. Formatters
# ══════════════════════════════════════════════════════════════════════════════

def format_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def format_json_compact(data: dict) -> str:
    """Compact JSON: strips per-file details and full tree children for LLM injection."""
    import copy
    compact = copy.deepcopy(data)
    compact["code_signals"].pop("per_file", None)

    def strip_tree_children(node: dict, depth: int = 0) -> None:
        if depth >= 2 and node["type"] == "directory":
            node.pop("children", None)
            return
        for child in node.get("children", []):
            strip_tree_children(child, depth + 1)

    strip_tree_children(compact["structure"].get("tree", {}))
    compact["imports"].pop("graph", None)
    return json.dumps(compact, indent=2, ensure_ascii=False, default=str)


def format_md(data: dict) -> str:
    identity  = data["identity"]
    structure = data["structure"]
    signals   = data["code_signals"]
    security  = data["security"]
    git       = data["git"]
    meta      = data["meta"]
    imports   = data["imports"]

    lines = [
        f"# Project Map: `{identity['name']}`",
        "",
        f"> **Generated:** {meta['generated_at']}  ",
        f"> **Root:** `{meta['root']}`  ",
        f"> **Scanner:** v{meta['scanner_version']}",
        "",
        "---",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Name | `{identity['name']}` |",
        f"| Type | `{identity['type']}` |",
        f"| Primary language | `{identity['primary_language']}` |",
        f"| Detected frameworks | {', '.join(f'`{f}`' for f in identity['frameworks']) or '—'} |",
        f"| Total files | {structure['total_files']:,} |",
        f"| Test ratio | {structure['test_ratio'] * 100:.0f}% ({structure['test_files_count']} test files) |",
        "",
        "## Language Distribution",
        "",
        "| Language | Files | Lines | % of lines |",
        "|----------|------:|------:|-----------:|",
    ]

    for lang, s in list(identity["language_distribution"].items())[:20]:
        bar = "█" * max(1, int(s["pct_lines"] / 4))
        lines.append(f"| {lang} | {s['files']} | {s['lines']:,} | {s['pct_lines']}% {bar} |")

    # Dependencies
    deps = identity["dependencies"]
    if deps["source_files"]:
        lines += [
            "",
            "## Dependencies",
            "",
            f"**Manifest files:** {', '.join(f'`{f}`' for f in deps['source_files'])}",
        ]
        if deps["production"]:
            prod_names = ", ".join(f"`{d['name']}`" for d in deps["production"][:25])
            suffix = "…" if len(deps["production"]) > 25 else ""
            lines.append(f"\n**Production ({len(deps['production'])}):** {prod_names}{suffix}")
        if deps["development"]:
            dev_names = ", ".join(f"`{d['name']}`" for d in deps["development"][:25])
            suffix = "…" if len(deps["development"]) > 25 else ""
            lines.append(f"\n**Development ({len(deps['development'])}):** {dev_names}{suffix}")
        if deps.get("npm_scripts"):
            lines.append(f"\n**npm scripts:** {', '.join(f'`{s}`' for s in deps['npm_scripts'])}")

    # Architecture
    lines += ["", "## Architecture", ""]
    if structure["entry_points"]:
        lines.append("**Entry points:** " + ", ".join(f"`{e}`" for e in structure["entry_points"]))
    if structure["semantic_folders"]:
        lines.append("\n**Semantic folders detected:** " +
                     ", ".join(f"`{f}`" for f in structure["semantic_folders"]))
    if structure["infrastructure_files"]:
        lines.append("\n**Infrastructure / CI files:** " +
                     ", ".join(f"`{f}`" for f in structure["infrastructure_files"]))

    # Code signals
    totals = signals.get("totals", {})
    lines += [
        "",
        "## Code Signals",
        "",
        f"| Metric | Count |",
        f"|--------|------:|",
        f"| Functions | {totals.get('functions', 0):,} |",
        f"| Classes / Structs / Interfaces | {totals.get('classes', 0):,} |",
        f"| TODO | {totals.get('TODO', 0)} |",
        f"| FIXME | {totals.get('FIXME', 0)} |",
        f"| HACK | {totals.get('HACK', 0)} |",
        f"| BUG | {totals.get('BUG', 0)} |",
    ]

    if signals.get("largest_files"):
        lines += ["", "**10 largest source files:**", ""]
        lines.append("| File | Lines | Language |")
        lines.append("|------|------:|----------|")
        for f in signals["largest_files"]:
            lines.append(f"| `{f['path']}` | {f['lines']:,} | {f['lang']} |")

    if signals.get("most_complex_files"):
        lines += ["", "**Most complex files (by function count):**", ""]
        lines.append("| File | Functions | Classes | Complexity keywords |")
        lines.append("|------|----------:|--------:|--------------------:|")
        for f in signals["most_complex_files"]:
            lines.append(
                f"| `{f['path']}` | {f['functions']} | {f['classes']} "
                f"| {f['complexity_keywords']} |"
            )

    if signals.get("todo_heavy_files"):
        lines += ["", "**Files with most TODOs/FIXMEs:**", ""]
        for f in signals["todo_heavy_files"][:5]:
            summary = ", ".join(f"{k}: {v}" for k, v in f["todos"].items())
            lines.append(f"- `{f['path']}` — {summary}")

    # Import graph
    if imports.get("available"):
        lines += [
            "",
            "## Import Graph",
            "",
            f"- Internal dependency edges: **{imports['total_internal_edges']}**",
            f"- Unique external packages used: **{imports['unique_external_packages']}**",
        ]
        if imports.get("all_external_packages"):
            pkgs = ", ".join(f"`{p}`" for p in imports["all_external_packages"][:30])
            suffix = "…" if len(imports["all_external_packages"]) > 30 else ""
            lines.append(f"\n**External packages:** {pkgs}{suffix}")
        if imports.get("most_imported_modules"):
            lines += ["", "**Most imported internal modules:**", ""]
            for item in imports["most_imported_modules"][:10]:
                lines.append(f"- `{item['module']}` — imported {item['imported_by']} time(s)")

    # Security
    if security.get("available"):
        lines += ["", "## Security Hints", ""]
        if security["exposed_env_files"]:
            files_list = ", ".join(f"`{f}`" for f in security["exposed_env_files"])
            lines.append(f"> ⚠️ **Real `.env` files found:** {files_list}")
        findings = security.get("potential_secrets", [])
        if findings:
            lines.append(f"\n**Potential hardcoded secrets — {len(findings)} finding(s):**\n")
            lines.append("| File | Line | Type | Snippet |")
            lines.append("|------|-----:|------|---------|")
            for f in findings[:20]:
                snippet = f["snippet"].replace("|", "\\|")
                lines.append(f"| `{f['file']}` | {f['line']} | `{f['type']}` | `{snippet}` |")
            if len(findings) > 20:
                lines.append(f"\n*… and {len(findings) - 20} more findings in the JSON output.*")
        else:
            lines.append("No hardcoded secret patterns detected.")

    # Git
    if git.get("available"):
        lines += ["", "## Git Activity", ""]
        lines.append(f"- **Branch:** `{git['branch']}`")
        if git.get("first_commit_date"):
            lines.append(f"- **First commit:** {git['first_commit_date']}")
        if git.get("total_commits"):
            lines.append(f"- **Total commits:** {git['total_commits']:,}")
        if git.get("last_commit"):
            lines.append(f"- **Last commit:** `{git['last_commit']}`")
        if git.get("remote"):
            lines.append(f"- **Remote:** `{git['remote']}`")
        if git.get("top_contributors"):
            lines += ["", "**Top contributors:**", ""]
            for c in git["top_contributors"][:5]:
                lines.append(f"- {c['author']} — {c['commits']} commits")
        if git.get("most_active_files"):
            lines += ["", "**Most active files (by commit count):**", ""]
            for f in git["most_active_files"][:10]:
                lines.append(f"- `{f['file']}` — {f['commits']} commits")
        if git.get("recently_modified_files"):
            lines += ["", "**Recently modified (last 14 days):**", ""]
            for f in git["recently_modified_files"][:10]:
                lines.append(f"- `{f}`")

    # Directory tree
    tree = structure["tree"]
    lines += ["", "## Directory Tree", "", "```"]
    s = tree["summary"]
    lines.append(
        f"{tree['name']}/ [{s['files']} files | {fmt_bytes(s['bytes'])} | {s['lines']:,} lines]"
    )
    children = tree.get("children", [])
    for i, child in enumerate(children):
        lines.extend(_render_tree_lines(child, "", i == len(children) - 1))
    lines.append("```")

    return "\n".join(lines) + "\n"


def format_txt(data: dict) -> str:
    identity  = data["identity"]
    structure = data["structure"]
    signals   = data["code_signals"]
    security  = data["security"]
    git       = data["git"]
    imports   = data["imports"]
    meta      = data["meta"]

    sep = "─" * 60
    lines = [
        "=" * 60,
        f"  PROJECT MAP: {identity['name']}",
        "=" * 60,
        f"  Generated  : {meta['generated_at']}",
        f"  Root       : {meta['root']}",
        f"  Type       : {identity['type']}",
        f"  Language   : {identity['primary_language']}",
        f"  Frameworks : {', '.join(identity['frameworks']) or 'none detected'}",
        f"  Files      : {structure['total_files']:,}",
        f"  Test ratio : {structure['test_ratio'] * 100:.0f}% ({structure['test_files_count']} test files)",
        "",
        sep,
        "  LANGUAGE DISTRIBUTION",
        sep,
    ]

    for lang, s in list(identity["language_distribution"].items())[:15]:
        bar = "█" * max(1, int(s["pct_lines"] / 5))
        lines.append(f"  {lang:<22} {s['files']:>4} files  {s['lines']:>8,} lines  {s['pct_lines']:>5.1f}%  {bar}")

    deps = identity["dependencies"]
    if deps["source_files"]:
        lines += [
            "",
            sep,
            "  DEPENDENCIES",
            sep,
            f"  Manifests    : {', '.join(deps['source_files'])}",
            f"  Production   : {len(deps['production'])} packages",
            f"  Development  : {len(deps['development'])} packages",
        ]
        if deps.get("npm_scripts"):
            lines.append(f"  npm scripts  : {', '.join(deps['npm_scripts'][:10])}")

    if structure["entry_points"]:
        lines += ["", sep, "  ENTRY POINTS", sep]
        for ep in structure["entry_points"]:
            lines.append(f"  {ep}")

    if structure["semantic_folders"]:
        lines += ["", sep, "  SEMANTIC FOLDERS", sep]
        lines.append("  " + ", ".join(structure["semantic_folders"]))

    if structure["infrastructure_files"]:
        lines += ["", sep, "  INFRASTRUCTURE / CI", sep]
        lines.append("  " + ", ".join(structure["infrastructure_files"]))

    totals = signals.get("totals", {})
    lines += [
        "",
        sep,
        "  CODE SIGNALS",
        sep,
        f"  Functions           : {totals.get('functions', 0):,}",
        f"  Classes / Structs   : {totals.get('classes', 0):,}",
        f"  TODO                : {totals.get('TODO', 0)}",
        f"  FIXME               : {totals.get('FIXME', 0)}",
        f"  HACK                : {totals.get('HACK', 0)}",
    ]
    if signals.get("largest_files"):
        lines += ["", "  Largest files:"]
        for f in signals["largest_files"][:8]:
            lines.append(f"    {f['lines']:>7,} lines  {f['lang']:<15}  {f['path']}")

    if imports.get("available"):
        lines += [
            "",
            sep,
            "  IMPORT GRAPH",
            sep,
            f"  Internal edges    : {imports['total_internal_edges']}",
            f"  External packages : {imports['unique_external_packages']}",
        ]
        if imports.get("most_imported_modules"):
            lines.append("  Most imported:")
            for item in imports["most_imported_modules"][:8]:
                lines.append(f"    ({item['imported_by']:>3}x)  {item['module']}")

    if security.get("available"):
        lines += ["", sep, "  SECURITY HINTS", sep]
        if security["exposed_env_files"]:
            lines.append(f"  WARNING: real .env files → {security['exposed_env_files']}")
        findings = security.get("potential_secrets", [])
        lines.append(f"  Potential secrets : {len(findings)} finding(s)")
        for f in findings[:5]:
            lines.append(f"    [{f['type']}]  {f['file']}:{f['line']}")
            lines.append(f"    {f['snippet']}")

    if git.get("available"):
        lines += ["", sep, "  GIT", sep]
        lines.append(f"  Branch     : {git['branch']}")
        if git.get("total_commits"):
            lines.append(f"  Commits    : {git['total_commits']:,}")
        if git.get("last_commit"):
            lines.append(f"  Last commit: {git['last_commit']}")
        if git.get("top_contributors"):
            lines.append("  Contributors:")
            for c in git["top_contributors"][:5]:
                lines.append(f"    {c['commits']:>5}  {c['author']}")
        if git.get("most_active_files"):
            lines.append("  Most active files:")
            for f in git["most_active_files"][:8]:
                lines.append(f"    {f['commits']:>5} commits  {f['file']}")

    # Tree
    tree = structure["tree"]
    lines += ["", sep, "  DIRECTORY TREE", sep]
    s = tree["summary"]
    lines.append(
        f"  {tree['name']}/ [{s['files']} files | {fmt_bytes(s['bytes'])} | {s['lines']:,} lines]"
    )
    children = tree.get("children", [])
    for i, child in enumerate(children):
        for tl in _render_tree_lines(child, "  ", i == len(children) - 1):
            lines.append(tl)

    return "\n".join(lines) + "\n"


FORMATTERS = {
    "json":    format_json,
    "compact": format_json_compact,
    "md":      format_md,
    "txt":     format_txt,
}

# ══════════════════════════════════════════════════════════════════════════════
# 15b. Per-section TXT formatters (AI-optimised plain-text context blocks)
# ══════════════════════════════════════════════════════════════════════════════

def _txt_header(title: str, meta: dict) -> list[str]:
    W = 68
    return [
        "=" * W,
        f"  {title}",
        f"  Project : {meta.get('root', '')}",
        f"  Generated: {meta.get('generated_at', '')}",
        "=" * W,
        "",
    ]


def format_database_txt(section: dict, meta: dict) -> str:
    """
    AI-context TXT for the database section.
    Design goals:
      - One table = one block, easy to grep / chunk
      - Long used_in lists are compressed to N files + examples
      - Undeclared / CTE tables grouped separately
      - ORM/ODM summary at the end
      - No redundant JSON punctuation, pure prose-friendly key: value
    """
    db = section
    lines: list[str] = _txt_header("DATABASE CONTEXT", meta)

    # ── Schema summary ────────────────────────────────────────────────────────
    lines += [
        f"Schema files used as map : {', '.join(db.get('sql_files_used_as_map', ['—']))}",
        f"Declared tables          : {db.get('total_schema_tables', 0)}",
        f"Tables referenced in code: {db.get('total_tables_used', 0)}",
        f"Undeclared tables        : {len(db.get('undeclared_tables', {}))}",
        f"ORM/ODM detected         : {', '.join(db.get('orm_odm', {}).get('detected', [])) or 'none'}",
        "",
    ]

    SEP = "─" * 68

    # ── Declared tables ───────────────────────────────────────────────────────
    lines += ["[DECLARED TABLES]", SEP]

    def _file_list(files: list[str], limit: int = 6) -> str:
        """Compact file list: show up to `limit` basenames, suffix with count."""
        if not files:
            return "—"
        names = [Path(f).name for f in files]
        if len(names) <= limit:
            return ", ".join(names)
        shown = ", ".join(names[:limit])
        return f"{shown} … (+{len(names) - limit} more — {len(names)} total)"

    for tbl in db.get("schema_tables", []):
        name       = tbl["table"]
        def_file   = tbl.get("definition_file", "?")
        def_lines  = tbl.get("definition_lines", [])
        ops        = tbl.get("operations_seen", [])
        used_in    = tbl.get("used_in_files", [])

        def_lines_str = ", ".join(str(n) for n in def_lines)
        ops_str   = ", ".join(ops) if ops else "none detected"
        files_str = _file_list(used_in)

        lines.append(f"Table: {name}")
        lines.append(f"  Defined in  : {def_file}  (lines: {def_lines_str})")
        lines.append(f"  Operations  : {ops_str}")
        if used_in:
            lines.append(f"  Used in ({len(used_in):>2}): {files_str}")
        else:
            lines.append( "  Used in     : not referenced in code")
        lines.append("")

    # ── Undeclared / CTE / dynamic tables ────────────────────────────────────
    undeclared = db.get("undeclared_tables", {})
    if undeclared:
        lines += [SEP, "[UNDECLARED / DYNAMIC TABLES]", SEP]
        lines.append("  (Referenced in queries but not found in any CREATE TABLE)")
        lines.append("")
        for tname, info in undeclared.items():
            ops  = ", ".join(info.get("operations", []))
            fls  = _file_list(info.get("files", []))
            lines.append(f"  {tname}")
            lines.append(f"    Operations : {ops}")
            lines.append(f"    Files      : {fls}")
        lines.append("")

    # ── ORM / ODM ─────────────────────────────────────────────────────────────
    orm_section = db.get("orm_odm", {})
    details     = orm_section.get("details", {})
    if details:
        lines += [SEP, "[ORM / ODM DETECTED]", SEP]
        for orm_name, orm_info in details.items():
            models = orm_info.get("models", [])
            ops    = ", ".join(orm_info.get("operations", []))
            files  = orm_info.get("files", [])

            # Show up to 12 model names
            if len(models) > 12:
                model_str = ", ".join(models[:12]) + f" … (+{len(models)-12} more)"
            else:
                model_str = ", ".join(models) if models else "—"

            lines.append(f"ORM: {orm_name}")
            lines.append(f"  Operations : {ops}")
            lines.append(f"  Models     : {model_str}")
            lines.append(f"  Files ({len(files):>2}) : {_file_list(files)}")
            lines.append("")

    # ── Cross-reference index: file → tables it touches ──────────────────────
    file_to_tables: dict[str, set[str]] = {}
    for tbl in db.get("schema_tables", []):
        for f in tbl.get("used_in_files", []):
            file_to_tables.setdefault(f, set()).add(tbl["table"])

    if file_to_tables:
        lines += [SEP, "[FILE → TABLE INDEX]", SEP]
        lines.append("  (Reverse lookup: which tables does each file touch?)")
        lines.append("")
        for fpath in sorted(file_to_tables):
            tables = sorted(file_to_tables[fpath])
            lines.append(f"  {Path(fpath).name:<40} {', '.join(tables)}")
        lines.append("")

    return "\n".join(lines)


def format_code_signals_txt(section: dict, meta: dict) -> str:
    """
    AI-context heatmap TXT for code_signals.
    Groups every file's security signals into one dense block.
    Score = weighted sum of signal severity.
    """
    cs    = section
    lines: list[str] = _txt_header("CODE SIGNALS — SECURITY HEATMAP", meta)
    SEP   = "─" * 68

    tot = cs.get("totals", {})
    hm  = cs.get("security_heatmap", [])
    pf  = {e["path"]: e for e in cs.get("per_file", [])}

    lines += [
        f"Total functions : {tot.get('functions', 0)}  "
        f"classes: {tot.get('classes', 0)}  "
        f"TODOs: {tot.get('TODO', 0) + tot.get('FIXME', 0)}",
        f"Files with signals: {len(hm)}",
        "",
        "Score legend: sinks×3  sqli×4  authz_gap×3  err_leak×2  source×1  crypto×1  todo×1",
        "",
    ]

    # ── Heatmap summary table ─────────────────────────────────────────────
    lines += [SEP, "[SECURITY HEATMAP — top files by risk score]", SEP]
    lines.append(f"  {'SCORE':>5}  {'FILE':<48}  SIGNALS PRESENT")
    lines.append("  " + "─" * 90)
    for item in hm:
        sigs = ", ".join(item.get("signals", []))
        lines.append(f"  {item['score']:>5}  {item['path']:<48}  {sigs}")
    lines.append("")

    # ── Per-file detail blocks (only files with signals) ──────────────────
    lines += [SEP, "[PER-FILE SIGNAL DETAIL]", SEP]

    for item in hm:
        fpath  = item["path"]
        fentry = pf.get(fpath, {})
        sig    = fentry.get("security_signals", {})
        score  = item["score"]
        flines = fentry.get("lines", "?")
        cx     = fentry.get("complexity_keywords", 0)

        lines.append(f"\nFile  : {fpath}")
        lines.append(f"Meta  : {flines} lines  complexity={cx}  score={score}")

        if sig.get("todos"):
            lines.append("  [TODOS/FIXMEs]")
            for t in sig["todos"]:
                lines.append(f"    {t['type']}: {t['text']}")

        if sig.get("sinks"):
            lines.append(f"  [DANGEROUS SINKS]  {', '.join(sig['sinks'])}")

        if sig.get("sources"):
            parts = [f"{k}×{v}" for k, v in sig["sources"].items()]
            lines.append(f"  [INPUT SOURCES]    {', '.join(parts)}")

        if sig.get("crypto"):
            lines.append(f"  [CRYPTO]           {', '.join(sig['crypto'])}")

        if sig.get("sqli_hints"):
            lines.append("  [SQLI HINTS]")
            for s in sig["sqli_hints"]:
                lines.append(f"    → {s}")

        if sig.get("authz_gap"):
            lines.append("  [AUTHZ GAP]        req.params/body.id accessed — no visible auth guard in file")

        if sig.get("error_leaks"):
            lines.append("  [ERROR LEAKAGE]")
            for s in sig["error_leaks"]:
                lines.append(f"    → {s}")

    lines.append("")

    # ── Largest / most complex summary ───────────────────────────────────
    lines += [SEP, "[LARGEST FILES]", SEP]
    for f in cs.get("largest_files", []):
        lines.append(f"  {f['lines']:>5} lines  {f['path']}")
    lines.append("")

    lines += [SEP, "[MOST COMPLEX FILES]", SEP]
    lines.append(f"  {'FNS':>4}  {'CX':>4}  FILE")
    for f in cs.get("most_complex_files", []):
        lines.append(f"  {f['functions']:>4}  {f['complexity_keywords']:>4}  {f['path']}")
    lines.append("")

    return "\n".join(lines)


def format_imports_txt(section: dict, meta: dict) -> str:
    """AI-context TXT for imports — max density, role-tagged, paths compressed."""
    imp = section
    lines: list[str] = _txt_header("IMPORT GRAPH", meta)
    SEP = "─" * 68

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

    # ── Role helpers ──────────────────────────────────────────────────────
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
        return f"{r}:{s}" if r not in ("ROOT",) else s

    # ── Blast radius table ────────────────────────────────────────────────
    lines += [SEP, "[BLAST RADIUS — fan-in sorted, top 14]", SEP]
    lines.append(f"  {'FILE':<34} {'BR':>4}  IMPORTED BY (grouped by role)")
    lines.append("  " + "─" * 92)

    for key, info in list(rev.items())[:14]:
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

    # ── Adjacency list ─────────────────────────────────────────────────────
    lines += [SEP, "[ADJACENCY LIST  (→internal  +external)]", SEP]
    for fpath in sorted(graph):
        fdata    = graph[fpath]
        tag      = _tag(fpath)
        internal = [_short(i) for i in fdata.get("internal", [])]
        external = fdata.get("external", [])

        rhs_parts: list[str] = []
        if internal:
            rhs_parts.append(",".join(internal))
        if external:
            rhs_parts.append("+" + ",".join(external))
        rhs = "  ".join(rhs_parts) if rhs_parts else "—"
        lines.append(f"  {tag:<34} → {rhs}")
    lines.append("")

    # ── Data flow paths — compressed ──────────────────────────────────────
    lines += [SEP, "[DATA FLOW PATHS — controller → … → service  (≥3 nodes)]", SEP]
    lines.append("  Notation: {A|B|C} = parallel middle nodes  ×N = N merged paths")
    lines.append("")

    from collections import defaultdict as _dd
    by_hops: dict[int, list[list[str]]] = _dd(list)
    for p in paths:
        by_hops[p["hops"]].append(p["path"])

    for hop_count in sorted(by_hops.keys(), reverse=True):
        group   = by_hops[hop_count]
        n_edges = hop_count - 1
        lines.append(f"  [{hop_count} nodes / {n_edges} edges]")

        # Merge paths that differ only at (hop_count-2) — the node just before the sink
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

    # ── External packages bucketed ────────────────────────────────────────
    lines += [SEP, "[EXTERNAL PACKAGES]", SEP]
    _SEC  = {"bcryptjs", "jsonwebtoken", "crypto-js", "otplib", "qrcode",
             "express-validator", "helmet", "cors"}
    _HTTP = {"axios", "ibm-watson", "ibm-cos-sdk", "web-push"}

    sec   = [p for p in ext_pkgs if p in _SEC]
    http  = [p for p in ext_pkgs if p in _HTTP]
    infra = [p for p in ext_pkgs if p not in _SEC and p not in _HTTP]

    if sec:
        lines.append(f"  SECURITY : {', '.join(sec)}")
    if http:
        lines.append(f"  HTTP/EXT : {', '.join(http)}")
    if infra:
        lines.append(f"  INFRA    : {', '.join(infra)}")
    lines.append("")

    return "\n".join(lines)


def format_middlewares_txt(section: dict, meta: dict) -> str:
    """AI-context TXT for the middlewares section."""
    mw = section
    lines: list[str] = _txt_header("MIDDLEWARE CONTEXT", meta)
    SEP = "─" * 68

    src_files = mw.get("middleware_source_files", [])
    routes    = mw.get("routes_with_middleware", [])

    lines += [
        f"Middleware source files  : {len(src_files)}",
        f"Routes with middleware   : {len(routes)}",
        "",
    ]

    # ── Middleware source files ─────────────────────────────────────────────
    if src_files:
        lines += [SEP, "[MIDDLEWARE SOURCE FILES]", SEP]
        for f in src_files:
            lines.append(f"  {f}")
        lines.append("")

    # ── Routes with middleware chains ──────────────────────────────────────
    if routes:
        lines += [SEP, "[ROUTE → MIDDLEWARE CHAIN]", SEP]
        lines.append(
            f"  {'METHOD':<7} {'PATH':<45} {'FILE':<30} LINE  HANDLER"
        )
        lines.append("  " + "─" * 120)

        # Group by file for readability
        from collections import defaultdict as _dd
        by_file: dict = _dd(list)
        for r in routes:
            by_file[r.get("file", "?")].append(r)

        for fpath, froutes in sorted(by_file.items()):
            lines.append(f"\n  File: {fpath}")
            for r in froutes:
                method  = r.get("method", "?")
                path    = r.get("path", "?")
                lineno  = r.get("line", "?")
                handler = r.get("handler", "?")
                raw_mw  = r.get("middlewares", [])

                # Clean up raw middleware tokens — strip newlines, collapse noise
                clean: list[str] = []
                for token in raw_mw:
                    t = token.replace("\n", " ").strip()
                    # skip bare punctuation artifacts
                    if t in ("[", "]", "(", ")", ""):
                        continue
                    # truncate long inline validators
                    if len(t) > 60:
                        t = t[:57] + "…"
                    clean.append(t)

                mw_str = " → ".join(clean) if clean else "—"
                lines.append(
                    f"    {method:<7} {path:<45} line {lineno:<5}  {handler}"
                )
                lines.append(f"           middlewares: {mw_str}")
        lines.append("")

    # ── Middleware usage frequency ─────────────────────────────────────────
    from collections import Counter as _Counter
    freq: Counter = _Counter()
    for r in routes:
        for token in r.get("middlewares", []):
            t = token.replace("\n", " ").strip()
            if t and t not in ("[", "]"):
                # extract just the function name (first word/identifier)
                import re as _re
                m = _re.match(r"(\w+)", t)
                if m:
                    freq[m.group(1)] += 1

    if freq:
        lines += [SEP, "[MIDDLEWARE USAGE FREQUENCY]", SEP]
        for name, count in freq.most_common():
            lines.append(f"  {name:<35} {count:>3}x")
        lines.append("")

    return "\n".join(lines)


def format_identity_txt(section: dict, meta: dict) -> str:
    """AI-context TXT for the identity section."""
    idn = section
    lines: list[str] = _txt_header("PROJECT IDENTITY", meta)
    SEP = "─" * 68

    # ── Core facts ─────────────────────────────────────────────────────────
    lines += [
        f"Project name     : {idn.get('name', '—')}",
        f"Project type     : {idn.get('type', '—')}",
        f"Primary language : {idn.get('primary_language', '—')}",
        f"Frameworks       : {', '.join(idn.get('frameworks', [])) or 'none detected'}",
        "",
    ]

    # ── Language distribution ───────────────────────────────────────────────
    lines += [SEP, "[LANGUAGE DISTRIBUTION]", SEP]
    lang_dist = idn.get("language_distribution", {})
    total_lines = sum(v.get("lines", 0) for v in lang_dist.values())
    for lang, stats in lang_dist.items():
        pct   = stats.get("pct_lines", 0.0)
        files = stats.get("files", 0)
        lns   = stats.get("lines", 0)
        kb    = stats.get("bytes", 0) / 1024
        lines.append(
            f"  {lang:<18} {pct:>5.1f}%   {lns:>6} lines   {files:>3} files   {kb:>7.1f} KB"
        )
    lines += [f"  {'TOTAL':<18}        {total_lines:>6} lines", ""]

    # ── Dependencies ───────────────────────────────────────────────────────
    deps = idn.get("dependencies", {})
    src_files = deps.get("source_files", [])
    scripts   = deps.get("npm_scripts", [])
    prod      = deps.get("production", [])
    dev       = deps.get("development", [])

    lines += [SEP, "[DEPENDENCIES]", SEP]
    lines.append(f"  Manifest files : {', '.join(src_files) or '—'}")
    lines.append(f"  Run scripts    : {', '.join(scripts) or '—'}")
    lines.append("")

    if prod:
        lines.append(f"  Production ({len(prod)}):")
        for pkg in prod:
            lines.append(f"    {pkg['name']:<35} {pkg.get('version', '')}")
        lines.append("")

    if dev:
        lines.append(f"  Development ({len(dev)}):")
        for pkg in dev:
            lines.append(f"    {pkg['name']:<35} {pkg.get('version', '')}")
        lines.append("")

    return "\n".join(lines)


# Dispatcher: section key → txt formatter
# Signature: (section_dict, meta_dict) -> str
SECTION_TXT_FORMATTERS: dict[str, "Callable[[dict, dict], str]"] = {
    "identity":     format_identity_txt,
    "imports":      format_imports_txt,
    "middlewares":  format_middlewares_txt,
    "code_signals": format_code_signals_txt,
    "database":     format_database_txt,
}


# ══════════════════════════════════════════════════════════════════════════════
# 16. Multi-file output writer
# ══════════════════════════════════════════════════════════════════════════════

# Manifest of output files: (filename, data_key, title, use_when)
_FILE_MANIFEST: list[tuple[str, str, str, str]] = [
    (
        "01_identity.json",
        "identity",
        "Project identity",
        "Understanding the project stack, language, frameworks and installed packages.",
    ),
    (
        "02_structure.json",
        "structure",
        "Directory structure & architecture",
        "Navigating the codebase, finding files, understanding folder conventions and entry points.",
    ),
    (
        "03_endpoints.json",
        "endpoints",
        "HTTP API endpoints",
        "Working with API routes: adding/modifying endpoints, understanding URL layout.",
    ),
    (
        "04_env_vars.json",
        "env_vars",
        "Environment variables",
        "Working with configuration, deployment, or understanding runtime dependencies.",
    ),
    (
        "05_database.json",
        "database",
        "Database schema and SQL usage",
        "Writing queries, understanding the data model, adding migrations.",
    ),
    (
        "06_middlewares.json",
        "middlewares",
        "Middleware chains in routes",
        "Adding or modifying middleware, understanding auth/permission flows.",
    ),
    (
        "07_imports.json",
        "imports",
        "Internal import graph",
        "Understanding module coupling, refactoring, tracing dependencies.",
    ),
    (
        "08_code_signals.json",
        "code_signals",
        "Code signals (complexity, TODOs)",
        "Code quality review, identifying god-objects, tracking tech debt.",
    ),
    (
        "09_security.json",
        "security",
        "Security findings",
        "Security audit, reviewing credential handling, finding hardcoded secrets.",
    ),
    (
        "10_git.json",
        "git",
        "Git activity",
        "Understanding recent changes, hot files, and contributors.",
    ),
]


def _j(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def write_multi_file(
    data: dict,
    out_dir: Path,
    no_per_file: bool = False,
    fmt: str = "json",
    only_reports: Optional[list[str]] = None,
) -> None:
    """
    Write one file per analysis section plus a master index.

    Parameters
    ----------
    fmt          : "json" (default) or "txt"  — format for section files.
    only_reports : when set, only write the sections whose key appears in the
                   list (e.g. ["database", "security"]).  The index is always
                   written regardless.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if no_per_file:
        data["code_signals"].pop("per_file", None)

    ext = "txt" if fmt == "txt" else "json"

    index_files = []
    for filename_json, key, title, use_when in _FILE_MANIFEST:
        # Apply --reports filter
        if only_reports and key not in only_reports:
            continue

        section = data.get(key, {})

        # ── Choose filename extension ──────────────────────────────────────
        stem = filename_json.replace(".json", "")
        filename = f"{stem}.{ext}"

        # ── Serialise ──────────────────────────────────────────────────────
        if fmt == "txt" and key in SECTION_TXT_FORMATTERS:
            content = SECTION_TXT_FORMATTERS[key](section, data["meta"])
        else:
            # Fall back to JSON for sections without a TXT formatter
            payload = {
                "_meta": {**data["meta"], "section": key},
                key: section,
            }
            content = _j(payload)
            filename = f"{stem}.json"  # always .json when no txt formatter

        (out_dir / filename).write_text(content, encoding="utf-8")

        # Quick stats for index
        stats: dict = {}
        if key == "identity":
            stats = {
                "primary_language": section.get("primary_language"),
                "frameworks":       section.get("frameworks", []),
                "production_deps":  len(section.get("dependencies", {}).get("production", [])),
            }
        elif key == "structure":
            stats = {
                "total_files":  section.get("total_files"),
                "entry_points": section.get("entry_points", []),
            }
        elif key == "endpoints":
            stats = {
                "total_endpoints": section.get("total", 0),
                "domains":         list(section.get("domain_map", {}).keys()),
            }
        elif key == "env_vars":
            stats = {
                "unique_vars":      section.get("total_unique_vars", 0),
                "total_references": section.get("total_references", 0),
            }
        elif key == "database":
            stats = {
                "schema_tables":   section.get("total_schema_tables", 0),
                "tables_used":     section.get("total_tables_used", 0),
                "orm_detected":    section.get("orm_odm", {}).get("detected", []),
            }
        elif key == "middlewares":
            stats = {
                "distinct_middlewares": section.get("total_middlewares_detected", 0),
                "routes_protected":    len(section.get("routes_with_middleware", [])),
            }
        elif key == "imports":
            stats = {
                "internal_edges":      section.get("total_internal_edges", 0),
                "external_packages":   section.get("unique_external_packages", 0),
            }
        elif key == "code_signals":
            t = section.get("totals", {})
            stats = {
                "functions": t.get("functions", 0),
                "classes":   t.get("classes", 0),
                "todos":     t.get("TODO", 0) + t.get("FIXME", 0) + t.get("HACK", 0),
            }
        elif key == "security":
            stats = {
                "total_findings":    section.get("total_findings", 0),
                "exposed_env_files": len(section.get("exposed_env_files", [])),
            }
        elif key == "git":
            stats = {
                "available":     section.get("available", False),
                "branch":        section.get("branch"),
                "total_commits": section.get("total_commits"),
            }

        index_files.append({
            "file":     filename,
            "section":  key,
            "title":    title,
            "use_when": use_when,
            "stats":    stats,
        })

    # Write index
    index = {
        "_meta": data["meta"],
        "project": {
            "name":             data["identity"]["name"],
            "type":             data["identity"]["type"],
            "primary_language": data["identity"]["primary_language"],
            "frameworks":       data["identity"]["frameworks"],
        },
        "instructions": (
            "Load 00_index.json first to understand the project. "
            "Then load only the section files relevant to your task using "
            "the 'use_when' field as guidance. "
            "Avoid loading all files at once unless doing a full audit."
        ),
        "files": index_files,
    }
    (out_dir / "00_index.json").write_text(_j(index), encoding="utf-8")

    total_size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
    print(
        f"\n  Written {len(index_files) + 1} files to {out_dir}  "
        f"(total {fmt_bytes(total_size)})",
        file=sys.stderr,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 17. CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    # Collect valid section keys for --reports choices
    _valid_sections = [key for _, key, _, _ in _FILE_MANIFEST]

    parser = argparse.ArgumentParser(
        description="Comprehensive static analysis context map for AI agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", nargs="?", default=".", help="Root directory (default: .)")

    # ── Multi-file output (default) ──
    parser.add_argument(
        "--out-dir", metavar="DIR", default=None,
        help="Output directory for multi-file map (default: ./project_map)",
    )
    parser.add_argument(
        "--reports", metavar="SECTION", nargs="+",
        choices=_valid_sections,
        default=None,
        help=(
            "Only write these section(s). "
            f"Valid values: {', '.join(_valid_sections)}"
        ),
    )
    parser.add_argument(
        "--format", metavar="FMT", dest="section_format",
        choices=["json", "txt"],
        default="json",
        help="Format for section files written by --out-dir: json (default) or txt",
    )

    # ── Single-file fallback ──
    parser.add_argument("--single-file", action="store_true",
                        help="Write a single file instead of a directory")
    parser.add_argument(
        "--output", "-o",
        choices=list(FORMATTERS.keys()),
        default="json",
        help="Single-file format: json (default), compact, md, txt",
    )
    parser.add_argument("--out", "-f", metavar="FILE",
                        help="Single output file path (implies --single-file if extension given)")

    # ── Common options ──
    parser.add_argument("--max-depth", "-d", type=int, default=None, metavar="N",
                        help="Maximum directory depth for the tree")
    parser.add_argument("--exclude-locks", action="store_true",
                        help="Exclude lock files (package-lock.json, yarn.lock, etc.)")
    parser.add_argument("--exclude-dir", action="append", default=[], metavar="DIR",
                        help="Additional directory to exclude (repeatable)")
    parser.add_argument("--no-git",      action="store_true", help="Skip git analysis")
    parser.add_argument("--no-security", action="store_true", help="Skip security scan")
    parser.add_argument("--no-imports",  action="store_true", help="Skip import graph")
    parser.add_argument("--no-per-file", action="store_true",
                        help="Omit per-file details from code_signals (smaller output)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    for d in args.exclude_dir:
        EXCLUDED_DIRS.add(d)

    root = Path(args.path).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    data = generate_map(
        root,
        exclude_locks=args.exclude_locks,
        max_depth=args.max_depth,
        no_git=args.no_git,
        no_security=args.no_security,
        no_imports=args.no_imports,
    )

    # ── Decide output mode ──────────────────────────────────────────────────
    use_single = args.single_file or bool(args.out)

    if use_single:
        if args.no_per_file:
            data["code_signals"].pop("per_file", None)
        content = FORMATTERS[args.output](data)
        if args.out:
            out_path = Path(args.out)
            out_path.write_text(content, encoding="utf-8")
            print(f"\nMap written to {out_path}", file=sys.stderr)
        else:
            sys.stdout.write(content)
    else:
        out_dir = Path(args.out_dir) if args.out_dir else Path("project_map")
        write_multi_file(
            data,
            out_dir,
            no_per_file=args.no_per_file,
            fmt=args.section_format,
            only_reports=args.reports,
        )
        print(f"  Load {out_dir / '00_index.json'} first.", file=sys.stderr)


if __name__ == "__main__":
    main()
