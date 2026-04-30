"""
formatters/sections/structure.py — Compact TXT formatter for structure section.
"""
from __future__ import annotations


def format_structure_txt(section: dict, meta: dict) -> str:
    """Compact structure info optimized for AI context."""
    lines = []
    
    # Entry points
    entry_points = section.get('entry_points', [])
    lines.append(f"ENTRY_POINTS: {', '.join(entry_points) if entry_points else 'none'}")
    
    # Semantic layers
    semantic = section.get('semantic_folders', [])
    lines.append(f"LAYERS: {', '.join(semantic) if semantic else 'none'}")
    
    # File stats
    total = section.get('total_files', 0)
    src = section.get('source_files_count', 0)
    test = section.get('test_files_count', 0)
    ratio = section.get('test_ratio', 0) * 100
    lines.append(f"FILES: {total}total/{src}src/{test}test(ratio:{ratio:.0f}%)")
    
    # Infrastructure files
    infra = section.get('infrastructure_files', [])
    if infra:
        lines.append(f"INFRA: {', '.join(infra[:5])}{'...' if len(infra) > 5 else ''}")
    
    # Tree summary - compact
    tree = section.get('tree', {})
    if tree:
        summary = tree.get('summary', {})
        root_name = tree.get('name', 'root')
        files = summary.get('files', 0)
        size = summary.get('bytes', 0) // 1024  # KB
        loc = summary.get('lines', 0)
        lines.append(f"TREE: {root_name}/ [{files}files|{size}KB|{loc:,}lines]")
        
        # Top-level directories
        children = tree.get('children', [])[:8]  # Top 8 only
        dirs = []
        for child in children:
            if child.get('summary', {}).get('files', 0) > 0:
                child_files = child['summary']['files']
                dirs.append(f"{child['name']}({child_files})")
        if dirs:
            lines.append(f"DIRS: {' '.join(dirs)}")
    
    return "\n".join(lines) + "\n"