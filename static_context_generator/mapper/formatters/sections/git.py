"""
formatters/sections/git.py — Compact TXT formatter for git section.
"""
from __future__ import annotations


def format_git_txt(section: dict, meta: dict) -> str:
    """Compact git info optimized for AI context."""
    lines = []
    
    available = section.get('available', False)
    if not available:
        return "GIT: not a git repository\n"
    
    # Basic info
    branch = section.get('branch', 'unknown')
    total_commits = section.get('total_commits', 0)
    last_commit = section.get('last_commit', 'none')
    lines.append(f"GIT: branch:{branch} | commits:{total_commits} | last:{last_commit}")
    
    # Recent activity
    recent_activity = section.get('recent_activity', {})
    if recent_activity:
        days_7 = recent_activity.get('commits_last_7_days', 0)
        days_30 = recent_activity.get('commits_last_30_days', 0)
        lines.append(f"ACTIVITY: {days_7}commits/7days | {days_30}commits/30days")
    
    # Active contributors
    contributors = section.get('contributors', [])
    if contributors:
        top_contributors = contributors[:3]  # Top 3
        contrib_stats = [f"{c['name']}({c['commits']})" for c in top_contributors]
        lines.append(f"CONTRIBUTORS: {' '.join(contrib_stats)}{'...' if len(contributors) > 3 else ''}")
    
    # Hot files (most changed)
    hot_files = section.get('hot_files', [])
    if hot_files:
        top_hot = hot_files[:5]  # Top 5
        hot_stats = [f"{f['file']}({f['changes']})" for f in top_hot]
        lines.append(f"HOT_FILES: {' '.join(hot_stats)}")
    
    # Recent changes
    recent_files = section.get('recent_files', [])
    if recent_files:
        recent_stats = recent_files[:3]  # Most recent 3
        recent_names = [f['file'].split('/')[-1] for f in recent_stats]  # Just filenames
        lines.append(f"RECENT_CHANGES: {', '.join(recent_names)}")
    
    return "\n".join(lines) + "\n"