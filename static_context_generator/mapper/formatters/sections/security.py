"""
formatters/sections/security.py — Compact TXT formatter for security section.
"""
from __future__ import annotations


def format_security_txt(section: dict, meta: dict) -> str:
    """Compact security info optimized for AI context."""
    lines = []
    
    available = section.get('available', False)
    if not available:
        return "SECURITY: scanning not available\n"
    
    total = section.get('total_findings', 0)
    lines.append(f"SECURITY: {total} total findings")
    
    # Exposed environment files
    exposed = section.get('exposed_env_files', [])
    if exposed:
        lines.append(f"EXPOSED_ENV: {', '.join(exposed)}")
    
    # Potential secrets breakdown
    secrets = section.get('potential_secrets', [])
    if secrets:
        # Group by type
        by_type = {}
        for secret in secrets:
            secret_type = secret.get('type', 'unknown')
            if secret_type not in by_type:
                by_type[secret_type] = []
            by_type[secret_type].append(secret)
        
        type_counts = [f"{stype}:{len(items)}" for stype, items in by_type.items()]
        lines.append(f"SECRET_TYPES: {'/'.join(type_counts)}")
        
        # Show examples of high-risk findings
        high_risk_types = ['hardcoded_password', 'hardcoded_api_key', 'private_key_in_code', 'aws_access_key']
        for risk_type in high_risk_types:
            if risk_type in by_type:
                examples = by_type[risk_type][:2]  # First 2 examples
                file_lines = [f"{item['file']}:{item['line']}" for item in examples]
                lines.append(f"{risk_type.upper()}: {', '.join(file_lines)}{'...' if len(by_type[risk_type]) > 2 else ''}")
        
        # Files with most findings
        files_with_issues = {}
        for secret in secrets:
            file_path = secret.get('file', '')
            if file_path not in files_with_issues:
                files_with_issues[file_path] = 0
            files_with_issues[file_path] += 1
        
        if files_with_issues:
            sorted_files = sorted(files_with_issues.items(), key=lambda x: x[1], reverse=True)[:3]
            file_stats = [f"{file}({count})" for file, count in sorted_files]
            lines.append(f"HOTSPOT_FILES: {' '.join(file_stats)}")
    
    return "\n".join(lines) + "\n"