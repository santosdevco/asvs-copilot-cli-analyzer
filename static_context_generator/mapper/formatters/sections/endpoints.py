"""
formatters/sections/endpoints.py — Compact TXT formatter for endpoints section.
"""
from __future__ import annotations


def format_endpoints_txt(section: dict, meta: dict) -> str:
    """Compact endpoint info optimized for AI context."""
    lines = []
    
    total = section.get('total', 0)
    if total == 0:
        return "ENDPOINTS: none detected\n"
    
    lines.append(f"ENDPOINTS: {total} total")
    
    # Methods breakdown
    methods = section.get('methods', {})
    if methods:
        method_counts = [f"{method}:{count}" for method, count in methods.items()]
        lines.append(f"METHODS: {'/'.join(method_counts)}")
    
    # Domains
    domain_map = section.get('domain_map', {})
    if domain_map:
        domains = list(domain_map.keys())[:5]  # Top 5 domains
        lines.append(f"DOMAINS: {', '.join(domains)}{'...' if len(domain_map) > 5 else ''}")
    
    # Routes by file - top 5 files with most routes
    routes_by_file = section.get('routes_by_file', {})
    if routes_by_file:
        sorted_files = sorted(routes_by_file.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        file_stats = [f"{file}({len(routes)})" for file, routes in sorted_files]
        lines.append(f"ROUTE_FILES: {' '.join(file_stats)}")
    
    # Sample routes - show a few examples
    all_routes = section.get('routes', [])
    if all_routes:
        # Group by method
        route_examples = {}
        for route in all_routes[:10]:  # First 10 routes
            method = route.get('method', 'GET')
            path = route.get('path', '')
            if method not in route_examples:
                route_examples[method] = []
            if len(route_examples[method]) < 3:  # Max 3 per method
                route_examples[method].append(path)
        
        examples = []
        for method, paths in route_examples.items():
            examples.append(f"{method}:{','.join(paths)}")
        lines.append(f"EXAMPLES: {' | '.join(examples)}")
    
    return "\n".join(lines) + "\n"