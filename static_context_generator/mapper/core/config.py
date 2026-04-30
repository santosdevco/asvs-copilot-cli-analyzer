"""
core/config.py — All global constants, lookup tables, and regex patterns
that are pure data (no I/O, no logic).
"""
import re

# ── Version ───────────────────────────────────────────────────────────────────
SCRIPT_VERSION = "3.0.0"

# ── Excluded directories ──────────────────────────────────────────────────────
EXCLUDED_DIRS: set[str] = {
    "node_modules", ".npm", ".yarn", "bower_components", "jspm_packages", "packages",
    "__pycache__", ".venv", "venv", "env", ".env",
    "site-packages", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pypackages__",
    "dist", "build", "out", "output", "target", "bin", "obj", "release", "debug",
    ".next", ".nuxt", ".svelte-kit", ".parcel-cache", ".cache", ".turbo",
    ".vercel", ".netlify",
    "assets", "static", "public", "media", "images", "img", "fonts", "icons", "videos", "audio",
    ".git", ".svn", ".hg",
    ".idea", ".vscode", ".vs", ".eclipse",
    "coverage", ".nyc_output", "htmlcov", "reports",
    ".terraform", ".docker",
    "Pods", "DerivedData", ".gradle",
    "generated", "gen", "auto-generated", "stubs", "typings", ".docusaurus", ".expo",
}

EXCLUDED_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".pyd",
    ".class", ".jar", ".war", ".ear",
    ".o", ".obj", ".a", ".so", ".dll", ".exe", ".lib", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".tif", ".heic", ".raw",
    ".mp4", ".avi", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".ogg", ".flac", ".aac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
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
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".cs": "C#",
    ".cpp": "C++", ".cxx": "C++", ".cc": "C++", ".c": "C",
    ".h": "C/C++ Header", ".hpp": "C/C++ Header",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".r": "R",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".ps1": "PowerShell",
    ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".toml": "TOML",
    ".xml": "XML", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".sql": "SQL", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".proto": "Protobuf", ".md": "Markdown", ".mdx": "Markdown",
    ".tf": "Terraform", ".hcl": "HCL",
    ".vue": "Vue", ".svelte": "Svelte",
    ".ex": "Elixir", ".exs": "Elixir",
    ".hs": "Haskell", ".clj": "Clojure", ".cljs": "Clojure",
    ".dart": "Dart", ".lua": "Lua", ".nim": "Nim", ".zig": "Zig",
}

FILENAME_TO_LANG: dict[str, str] = {
    "Dockerfile": "Dockerfile", "Makefile": "Makefile",
    "Rakefile": "Ruby", "Gemfile": "Ruby", "Jenkinsfile": "Groovy",
}

NON_CODE_LANGS: set[str] = {
    "JSON", "YAML", "TOML", "XML", "Markdown",
    "Dockerfile", "Makefile", "HCL", "Terraform",
}

# ── Framework signatures ──────────────────────────────────────────────────────
FRAMEWORK_SIGNATURES: list[tuple[str, set, str]] = [
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
    ("go_deps", {"github.com/gin-gonic/gin"}, "Gin"),
    ("go_deps", {"github.com/labstack/echo"}, "Echo"),
    ("go_deps", {"github.com/gofiber/fiber"}, "Fiber"),
    ("go_deps", {"github.com/go-chi/chi"}, "Chi"),
    ("go_deps", {"gorm.io/gorm"}, "GORM"),
    ("rust_deps", {"actix-web"}, "Actix Web"),
    ("rust_deps", {"axum"}, "Axum"),
    ("rust_deps", {"warp"}, "Warp"),
    ("rust_deps", {"tokio"}, "Tokio"),
    ("rust_deps", {"serde"}, "Serde"),
    ("ruby_deps", {"rails"}, "Ruby on Rails"),
    ("ruby_deps", {"sinatra"}, "Sinatra"),
    ("php_deps", {"laravel/framework"}, "Laravel"),
    ("php_deps", {"symfony/symfony"}, "Symfony"),
]

SEMANTIC_FOLDERS: set[str] = {
    "routes", "route", "routing", "controllers", "controller",
    "handlers", "handler", "models", "model", "entities", "entity",
    "services", "service", "repositories", "repository", "repos",
    "middleware", "middlewares", "views", "templates", "partials",
    "schemas", "schema", "migrations", "tests", "test", "__tests__", "spec", "specs",
    "utils", "helpers", "lib", "config", "configs", "settings",
    "api", "v1", "v2", "v3", "auth", "authentication", "authorization",
    "db", "database", "jobs", "tasks", "workers", "queues",
    "events", "listeners", "subscribers", "hooks", "plugins", "extensions",
    "interfaces", "types", "dto", "dtos", "validators", "validation",
    "errors", "exceptions", "graphql", "grpc", "proto",
    "infra", "infrastructure", "domain", "application", "core", "common", "shared",
}

ENTRY_POINT_NAMES: set[str] = {
    "main.py", "app.py", "server.py", "run.py", "manage.py",
    "wsgi.py", "asgi.py", "__main__.py",
    "index.js", "app.js", "server.js", "main.js",
    "index.ts", "app.ts", "server.ts", "main.ts",
    "main.go", "main.rs", "main.rb", "app.rb",
    "index.php", "Program.cs", "Startup.cs", "Application.java",
}

INFRA_FILE_PATTERNS: list[str] = [
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore",
    "Makefile", "Procfile", ".github/workflows", ".gitlab-ci.yml",
    ".circleci/config.yml", "Jenkinsfile", "azure-pipelines.yml", ".travis.yml",
    "nginx.conf", "k8s", "kubernetes", "helm",
    ".env.example", ".env.sample", ".env.template",
    "fly.toml", "vercel.json", "netlify.toml", "render.yaml",
    "railway.json", "serverless.yml", "serverless.yaml",
    "cloudbuild.yaml", "appspec.yml",
]

TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|OPTIMIZE|REFACTOR)\b")

# ── Import patterns per language ──────────────────────────────────────────────
_JS_IMPORT_RE = re.compile(
    r'(?:import\s+[^"\';\n]*?from\s+|import\s*\(\s*)["\']([^"\']+)["\']', re.M,
)
_JS_REQUIRE_RE = re.compile(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', re.M)

IMPORT_PATTERNS: dict[str, list[tuple]] = {
    "Python": [
        (re.compile(r"^\s*import\s+([\w.]+)", re.M), False),
        (re.compile(r"^\s*from\s+(\.[\w.]*|[\w][\w.]*)\s+import", re.M), "detect"),
    ],
    "JavaScript": [(_JS_IMPORT_RE, "detect"), (_JS_REQUIRE_RE, "detect")],
    "TypeScript": [(_JS_IMPORT_RE, "detect"), (_JS_REQUIRE_RE, "detect")],
    "Go":   [(re.compile(r'^\s*"([^"]+)"', re.M), False)],
    "Java": [(re.compile(r"^\s*import\s+([\w.]+);", re.M), False)],
    "Ruby": [
        (re.compile(r"^\s*require\s+['\"]([^'\"]+)['\"]", re.M), "detect"),
        (re.compile(r"^\s*require_relative\s+['\"]([^'\"]+)['\"]", re.M), True),
    ],
    "PHP": [(re.compile(r"(?:require|include)(?:_once)?\s*['\"]([^'\"]+)['\"]", re.M), "detect")],
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
        r"(?:\w+\s+)+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{", re.M,
    ),
    "Rust":   re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+", re.M),
    "Ruby":   re.compile(r"^\s*def\s+\w+", re.M),
    "PHP":    re.compile(
        r"^\s*(?:public|private|protected|static|abstract|final)?\s*function\s+\w+", re.M,
    ),
    "C#":     re.compile(
        r"(?:public|private|protected|internal|static|virtual|override|abstract)\s+"
        r"(?:\w+\s+)+\w+\s*\([^)]*\)", re.M,
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
        r"(?:class|interface|enum|record)\s+\w+", re.M,
    ),
    "Rust":   re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+\w+", re.M),
    "Ruby":   re.compile(r"^\s*(?:class|module)\s+\w+", re.M),
    "PHP":    re.compile(r"^\s*(?:abstract|final)?\s*(?:class|interface|trait)\s+\w+", re.M),
    "C#":     re.compile(
        r"(?:public|private|protected|internal|abstract|sealed|static)?\s*"
        r"(?:class|interface|struct|enum|record)\s+\w+", re.M,
    ),
    "Kotlin": re.compile(
        r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)?class\s+\w+|"
        r"^\s*(?:interface|object)\s+\w+", re.M,
    ),
    "Swift":  re.compile(r"^\s*(?:class|struct|enum|protocol|actor)\s+\w+", re.M),
    "Dart":   re.compile(r"^\s*(?:abstract\s+)?class\s+\w+|^\s*mixin\s+\w+", re.M),
}

# ── Hardcoded-secret detection patterns ──────────────────────────────────────
SECURITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*["\'][^"\']{{4,}}["\']', re.I), "hardcoded_password"),
    (re.compile(r'(?:api_key|apikey|api_secret|secret_key)\s*[=:]\s*["\'][^"\']{{8,}}["\']', re.I), "hardcoded_api_key"),
    (re.compile(r'(?:secret(?:_key)?|private_key|encryption_key)\s*[=:]\s*["\'][^"\']{{8,}}["\']', re.I), "hardcoded_secret"),
    (re.compile(r'(?:access_token|auth_token|bearer_token|refresh_token|jwt_token)\s*[=:]\s*["\'][^"\']{{8,}}["\']', re.I), "hardcoded_token"),
    (re.compile(r'(?:database_url|db_url|connection_string)\s*[=:]\s*["\'][^"\']{{10,}}["\']', re.I), "hardcoded_db_url"),
    (re.compile(r'-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----', re.I), "private_key_in_code"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "aws_access_key"),
    (re.compile(r'(?:mysql|postgresql|postgres|mongodb|redis|sqlite)\+?://[^@\s"\']+:[^@\s"\']+@', re.I), "database_url_with_credentials"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "github_personal_token"),
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "openai_api_key"),
    # Additional patterns for common credentials
    (re.compile(r'xoxb-[0-9]{11,}-[0-9]{11,}-[a-zA-Z0-9]{24}'), "slack_bot_token"),
    (re.compile(r'xoxp-[0-9]{11,}-[0-9]{11,}-[0-9]{11,}-[a-zA-Z0-9]{32}'), "slack_user_token"),
    (re.compile(r'AIza[0-9A-Za-z\\-_]{35}'), "google_api_key"),
    (re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'), "uuid_as_secret"),
    (re.compile(r'(?:client_secret|consumer_secret|webhook_secret)\s*[=:]\s*["\'][^"\']{{12,}}["\']', re.I), "oauth_secret"),
    # Environment variable references in code (may indicate hardcoding)
    (re.compile(r'process\.env\.[A-Z_]+\s*\|\|\s*["\'][^"\']{{8,}}["\']', re.I), "fallback_secret"),
    (re.compile(r'os\.environ\.get\(["\'][A-Z_]+["\'],\s*["\'][^"\']{{8,}}["\']\)', re.I), "fallback_secret"),
]
