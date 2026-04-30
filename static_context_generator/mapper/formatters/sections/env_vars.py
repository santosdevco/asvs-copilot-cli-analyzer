"""
formatters/sections/env_vars.py — Compact TXT formatter for environment variables section.
"""
from __future__ import annotations


def format_env_vars_txt(section: dict, meta: dict) -> str:
    """Compact env vars info optimized for AI context."""
    lines = []
    
    total = section.get('total_unique_vars', 0)
    refs = section.get('total_references', 0)
    
    if total == 0:
        return "ENV_VARS: none detected\n"
    
    lines.append(f"ENV_VARS: {total} unique variables, {refs} total references")
    
    # Classification
    classified = section.get('classified', {})
    if classified:
        class_stats = []
        for category, vars_list in classified.items():
            if vars_list:
                class_stats.append(f"{category.lower()}:{len(vars_list)}")
        if class_stats:
            lines.append(f"CATEGORIES: {'/'.join(class_stats)}")
    
    # Show some examples from each category
    for category, vars_list in classified.items():
        if vars_list and category in ['SECRET', 'CREDENTIAL']:
            examples = vars_list[:3]  # First 3 examples
            lines.append(f"{category}: {', '.join(examples)}{'...' if len(vars_list) > 3 else ''}")
    
    # Files using env vars - top 5
    files_using = section.get('files_using_env', {})
    if files_using:
        sorted_files = sorted(files_using.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        file_stats = [f"{file}({len(vars)})" for file, vars in sorted_files]
        lines.append(f"TOP_FILES: {' '.join(file_stats)}")
    
    # Most referenced variables
    vars_data = section.get('vars', {})
    if vars_data:
        sorted_vars = sorted(
            [(name, data['references']) for name, data in vars_data.items()],
            key=lambda x: x[1], reverse=True
        )[:5]
        top_refs = [f"{name}({refs}refs)" for name, refs in sorted_vars]
        lines.append(f"TOP_REFS: {' '.join(top_refs)}")

    # Full file→variable mapping so the auditor sees exact usage per file.
    files_using = section.get('files_using_env', {})
    if files_using:
        lines.append("FILE_VAR_MAP:")
        for file, var_list in sorted(files_using.items()):
            lines.append(f"  {file}: {', '.join(sorted(var_list))}")

    return "\n".join(lines) + "\n"