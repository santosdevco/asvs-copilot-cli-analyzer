"""
formatters/txt_fmt.py — Plain-text report formatter.
"""
from __future__ import annotations

from .base import _txt_header, _render_tree_lines
from ..core.fs import fmt_bytes


def format_txt(data: dict) -> str:
    """Optimized text formatter for AI consumption - compact but complete."""
    meta      = data["meta"]
    identity  = data["identity"]
    structure = data["structure"]
    signals   = data["code_signals"]
    security  = data["security"]
    git       = data["git"]
    imports   = data["imports"]
    env_vars  = data.get("env_vars", {})

    lines: list[str] = []
    lines.append(f"PROJECT: {identity['name']} | TYPE: {identity['type']} | LANG: {identity['primary_language']}")
    
    # Frameworks and languages in one line
    frameworks = ", ".join(identity['frameworks']) or "none"
    lines.append(f"FRAMEWORKS: {frameworks}")
    
    # Compact language distribution
    lang_stats = [f"{lang}({s['pct_lines']:.1f}%/{s['files']}files)" 
                  for lang, s in identity["language_distribution"].items()]
    lines.append(f"LANGUAGES: {' '.join(lang_stats)}")
    
    # Architecture summary
    entry_points = ", ".join(structure['entry_points']) if structure['entry_points'] else "none"
    layers = ", ".join(structure['semantic_folders']) if structure['semantic_folders'] else "none"  
    lines.append(f"ENTRY_POINTS: {entry_points} | LAYERS: {layers}")
    lines.append(f"FILES: {structure['source_files_count']}src/{structure['test_files_count']}test(ratio:{structure['test_ratio']*100:.0f}%)")
    
    # Code signals compact
    totals = signals.get("totals", {})
    lines.append(f"CODE: {totals.get('functions',0)}fn/{totals.get('classes',0)}cls | ISSUES: {totals.get('TODO',0)}todo/{totals.get('FIXME',0)}fixme")
    
    # Security heatmap - top 5 only for AI
    hm = signals.get("security_heatmap", [])
    if hm:
        top_risks = []
        for item in hm[:5]:  # Only top 5 for compactness
            sigs = ",".join(item.get("signals", []))
            top_risks.append(f"{item['path']}(score:{item['score']},{sigs})")
        lines.append(f"SECURITY_HOTSPOTS: {' | '.join(top_risks)}")
    
    # Security findings
    if security.get("available"):
        exposed = ",".join(security['exposed_env_files']) if security['exposed_env_files'] else "none"
        lines.append(f"SECURITY: exposed_env:{exposed} | hardcoded_secrets:{security['total_findings']}")
    
    # Environment variables classification
    if env_vars.get("available"):
        classified = env_vars.get("classified", {})
        env_summary = []
        for category, vars_list in classified.items():
            if vars_list:
                env_summary.append(f"{category.lower()}:{len(vars_list)}")
        if env_summary:
            lines.append(f"ENV_VARS: total:{env_vars['total_unique_vars']} | {'/'.join(env_summary)}")
    
    # Git activity
    if git.get("available"):
        lines.append(f"GIT: branch:{git['branch']} | commits:{git.get('total_commits','?')} | last:{git.get('last_commit','—')}")
    
    # Import analysis  
    if imports.get("available"):
        lines.append(f"IMPORTS: internal_edges:{imports['total_internal_edges']} | external_packages:{imports['unique_external_packages']}")
    
    # Directory tree - simplified for AI
    tree = structure["tree"]
    tree_summary = tree["summary"]
    lines.append(f"TREE_ROOT: {tree['name']}/ [{tree_summary['files']}files|{fmt_bytes(tree_summary['bytes'])}|{tree_summary['lines']:,}lines]")
    
    # Key subdirectories only (not full tree to save space)
    children = tree.get("children", [])
    key_dirs = []
    for child in children[:10]:  # Top 10 dirs only
        if child.get("summary", {}).get("files", 0) > 0:
            child_summary = child["summary"]
            key_dirs.append(f"{child['name']}({child_summary['files']}files)")
    if key_dirs:
        lines.append(f"KEY_DIRS: {' '.join(key_dirs)}")
    
    return "\n".join(lines) + "\n"
