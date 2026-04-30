"""
analyzers/database.py — SQL schema extraction, DML usage scan, ORM/ODM detection.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..core.fs import detect_language, read_text


# ─────────────────────────────────────────────────────────────────────────────
# SQL regexes
# ─────────────────────────────────────────────────────────────────────────────

_SQL_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[]?\w+[`\"\]]?\s*\.\s*)?[`\"\[]?(\w+)[`\"\]]?",
    re.I,
)

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

# ─────────────────────────────────────────────────────────────────────────────
# ORM / ODM patterns
# ─────────────────────────────────────────────────────────────────────────────

_ORM_PATTERNS: list[tuple[str, set[str], list[re.Pattern]]] = [
    # ── JavaScript / TypeScript ──────────────────────────────────────────
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
        re.compile(r"model\s+(\w+)\s*\{", re.I),
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
    # ── Python ───────────────────────────────────────────────────────────
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
    # ── Go ───────────────────────────────────────────────────────────────
    ("GORM", {"Go"}, [
        re.compile(r"db\.Where\s*\(", re.I),
        re.compile(r"db\.Find\s*\(", re.I),
        re.compile(r"db\.First\s*\(", re.I),
        re.compile(r"db\.Create\s*\(", re.I),
        re.compile(r"db\.Save\s*\(", re.I),
        re.compile(r"db\.Delete\s*\(", re.I),
        re.compile(r"db\.Model\s*\(", re.I),
        re.compile(r'`gorm:"[^"]*"', re.I),
        re.compile(r"AutoMigrate\s*\(", re.I),
    ]),
    ("Ent (entgo)", {"Go"}, [
        re.compile(r"\.From\s*\(\s*(\w+)\s*\)", re.I),
        re.compile(r"client\.(\w+)\.Create\s*\(\)", re.I),
        re.compile(r"client\.(\w+)\.Query\s*\(\)", re.I),
        re.compile(r"client\.(\w+)\.Delete\s*\(\)", re.I),
    ]),
    # ── Java / Kotlin ─────────────────────────────────────────────────────
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
    # ── Ruby ──────────────────────────────────────────────────────────────
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
    # ── PHP ───────────────────────────────────────────────────────────────
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
    # ── Rust ──────────────────────────────────────────────────────────────
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
    # ── C# ────────────────────────────────────────────────────────────────
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
    # ── Swift ─────────────────────────────────────────────────────────────
    ("CoreData", {"Swift"}, [
        re.compile(r"NSManagedObject\b", re.I),
        re.compile(r"NSFetchRequest\b", re.I),
        re.compile(r"viewContext\.save\s*\(", re.I),
        re.compile(r"@NSManaged\b", re.I),
    ]),
    # ── Dart / Flutter ────────────────────────────────────────────────────
    ("Drift (Moor)", {"Dart"}, [
        re.compile(r"@DataClassName\s*\(", re.I),
        re.compile(r"extends\s+Table\b", re.I),
        re.compile(r"\.watch\s*\(", re.I),
    ]),
]

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

_CODE_LANGS = {
    "JavaScript", "TypeScript", "Python", "Java", "Go",
    "Ruby", "PHP", "C#", "Kotlin", "Swift", "Rust", "Dart",
}


def _extract_sql_from_code(text: str, lang: str) -> str:
    if lang in {"JavaScript", "TypeScript"}:
        tl = re.findall(r"`([^`]*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^`]*)`", text, re.I)
        qs = re.findall(
            r"""["']([^"']*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"']*)["']""", text, re.I,
        )
        return "\n".join(tl + qs)
    if lang == "Python":
        tl = re.findall(r'"""([^"]*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"]*)"""', text, re.I | re.S)
        qs = re.findall(
            r"""["']([^"']*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)[^"']*)["']""", text, re.I,
        )
        return "\n".join(tl + qs)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_database(files: list[Path], root: Path, is_frontend: bool = False) -> dict:
    # Frontend projects never connect directly to a DB — skip all ORM/SQL scanning
    # to avoid false positives from browser APIs with ORM-like names.
    if is_frontend:
        return {
            "schema_tables": [], "all_table_usage": {}, "undeclared_tables": {},
            "orm_odm": {"detected": [], "details": {}},
            "total_schema_tables": 0, "total_code_tables": 0, "total_undeclared": 0,
            "schema_files": [], "_note": "skipped: frontend project",
        }

    # ── Pass 1: schema tables from SQL files ─────────────────────────────
    schema_map: dict[str, dict] = {}
    sql_files: list[tuple[Path, str]] = []

    for f in files:
        if detect_language(f) != "SQL":
            continue
        text = read_text(f) or ""
        rel = str(f.relative_to(root))
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

    # ── Pass 2: DML usage ─────────────────────────────────────────────────
    table_usage: dict[str, dict] = defaultdict(lambda: {"operations": set(), "files": set()})

    for f in files:
        lang = detect_language(f)
        rel = str(f.relative_to(root))
        if lang == "SQL":
            sql_text = read_text(f) or ""
        elif lang in _CODE_LANGS:
            raw = read_text(f) or ""
            if not re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|JOIN)\b", raw, re.I):
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

    # ── Pass 3: cross-reference known tables in code files ───────────────
    known_tables = set(schema_map.keys())
    code_cache: dict[str, str] = {}
    for f in files:
        if detect_language(f) in _CODE_LANGS:
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
            for line in text.splitlines():
                if pat.search(line) and op_pat.search(line):
                    for op_m in op_pat.finditer(line):
                        table_usage[key]["operations"].add(op_m.group(1).upper())

    # ── Pass 4: ORM / ODM detection ──────────────────────────────────────
    orm_usage: dict[str, dict] = {}

    for f in files:
        lang = detect_language(f)
        if not lang:
            continue
        rel = str(f.relative_to(root))
        effective_lang = "TypeScript" if f.name.endswith(".prisma") else lang
        text = code_cache.get(rel) or read_text(f) or ""
        if not text:
            continue

        # Pre-check: verify ORM imports are present before pattern matching
        has_orm_imports = False
        orm_import_patterns = {
            "SQLAlchemy": [r"from\s+sqlalchemy", r"import\s+sqlalchemy", r"from.*declarative.*import", r"DeclarativeBase", r"declarative_base"],
            "Tortoise ORM": [r"from\s+tortoise", r"import\s+tortoise", r"from.*tortoise.*models.*import"],
            "Peewee": [r"from\s+peewee", r"import\s+peewee", r"from.*peewee.*import"],
            "Django ORM": [r"from\s+django", r"import\s+django", r"django\.db", r"models\.Model"],
            "Beanie": [r"from\s+beanie", r"import\s+beanie", r"from.*beanie.*import.*Document"],
            "MongoEngine": [r"from\s+mongoengine", r"import\s+mongoengine"]
        }

        for orm_name, supported_langs, patterns in _ORM_PATTERNS:
            if effective_lang not in supported_langs:
                continue
            
            # For Python ORMs, verify imports first
            if effective_lang == "Python" and orm_name in orm_import_patterns:
                import_found = False
                for import_pat in orm_import_patterns[orm_name]:
                    if re.search(import_pat, text, re.I):
                        import_found = True
                        break
                if not import_found:
                    continue
            
            matched_any = False
            models_found: set[str] = set()
            ops_found: set[str] = set()

            for pat in patterns:
                for m in pat.finditer(text):
                    matched_any = True
                    if m.lastindex and m.group(1):
                        # For Python, add extra validation to avoid Pydantic models
                        if effective_lang == "Python" and orm_name in ["Tortoise ORM", "Peewee"]:
                            # Check if it's really an ORM model by looking for ORM-specific patterns
                            model_name = m.group(1)
                            model_context = text[max(0, m.start()-200):m.end()+200]
                            
                            # Skip if it looks like Pydantic (has BaseModel, validator decorators, etc)
                            if re.search(r"BaseModel|@validator|@field_validator|pydantic", model_context, re.I):
                                continue
                            
                            # Ensure it has actual ORM characteristics
                            orm_indicators = [
                                r"class.*Meta:",  # Common ORM pattern
                                r"db_table",
                                r"__tablename__",
                                r"\.objects\.",  # Django pattern
                                r"\.select\(\)",  # Peewee pattern
                                r"\.filter\(\)",  # Tortoise pattern
                            ]
                            if not any(re.search(indicator, model_context, re.I) for indicator in orm_indicators):
                                continue
                        
                        models_found.add(m.group(1))

            if matched_any:
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

    # ── Serialize ─────────────────────────────────────────────────────────
    schema_list = []
    for key, entry in sorted(schema_map.items()):
        usage = table_usage.get(key, {})
        schema_list.append({
            "table":            entry["table"],
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

    undeclared = {
        tname: info
        for tname, info in all_usage_serialized.items()
        if tname not in set(schema_map.keys()) and tname not in _SQL_KEYWORDS
    }

    orm_serialized = {
        name: {
            "files":      sorted(info["files"]),
            "models":     sorted(info["models"]),
            "operations": sorted(info["operations"]),
        }
        for name, info in sorted(orm_usage.items())
    }

    return {
        "schema_tables":     schema_list,
        "all_table_usage":   all_usage_serialized,
        "undeclared_tables": undeclared,
        "orm_odm": {
            "detected": sorted(orm_usage.keys()),
            "details":  orm_serialized,
        },
        "total_schema_tables": len(schema_list),
        "total_tables_used":   len(all_usage_serialized),
        "sql_files_used_as_map": [str(f.relative_to(root)) for f, _ in sql_files],
    }
