"""
formatters/sections/database.py — TXT formatter for the database section.
"""
from __future__ import annotations

from pathlib import Path
from ..base import _txt_header, _file_list


def format_database_txt(section: dict, meta: dict) -> str:
    db = section
    lines: list[str] = _txt_header("DATABASE CONTEXT", meta)
    SEP = "─" * 68

    lines += [
        f"Schema files used as map : {', '.join(db.get('sql_files_used_as_map', ['—']))}",
        f"Declared tables          : {db.get('total_schema_tables', 0)}",
        f"Tables referenced in code: {db.get('total_tables_used', 0)}",
        f"Undeclared tables        : {len(db.get('undeclared_tables', {}))}",
        f"ORM/ODM detected         : {', '.join(db.get('orm_odm', {}).get('detected', [])) or 'none'}",
        "",
    ]

    # Declared tables
    lines += ["[DECLARED TABLES]", SEP]
    for tbl in db.get("schema_tables", []):
        name      = tbl["table"]
        def_file  = tbl.get("definition_file", "?")
        def_lines = tbl.get("definition_lines", [])
        ops       = tbl.get("operations_seen", [])
        used_in   = tbl.get("used_in_files", [])

        def_lines_str = ", ".join(str(n) for n in def_lines)
        ops_str       = ", ".join(ops) if ops else "none detected"
        files_str     = _file_list(used_in)

        lines.append(f"Table: {name}")
        lines.append(f"  Defined in  : {def_file}  (lines: {def_lines_str})")
        lines.append(f"  Operations  : {ops_str}")
        if used_in:
            lines.append(f"  Used in ({len(used_in):>2}): {files_str}")
        else:
            lines.append("  Used in     : not referenced in code")
        lines.append("")

    # Undeclared tables
    undeclared = db.get("undeclared_tables", {})
    if undeclared:
        lines += [SEP, "[UNDECLARED / DYNAMIC TABLES]", SEP]
        lines.append("  (Referenced in queries but not found in any CREATE TABLE)")
        lines.append("")
        for tname, info in undeclared.items():
            ops = ", ".join(info.get("operations", []))
            fls = _file_list(info.get("files", []))
            lines.append(f"  {tname}")
            lines.append(f"    Operations : {ops}")
            lines.append(f"    Files      : {fls}")
        lines.append("")

    # ORM/ODM
    orm_section = db.get("orm_odm", {})
    details     = orm_section.get("details", {})
    if details:
        lines += [SEP, "[ORM / ODM DETECTED]", SEP]
        for orm_name, orm_info in details.items():
            models = orm_info.get("models", [])
            ops    = ", ".join(orm_info.get("operations", []))
            files  = orm_info.get("files", [])
            if len(models) > 12:
                model_str = ", ".join(models[:12]) + f" … (+{len(models)-12} more)"
            else:
                model_str = ", ".join(models) if models else "—"
            lines.append(f"ORM: {orm_name}")
            lines.append(f"  Operations : {ops}")
            lines.append(f"  Models     : {model_str}")
            lines.append(f"  Files ({len(files):>2}) : {_file_list(files)}")
            lines.append("")

    # File → table index
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
