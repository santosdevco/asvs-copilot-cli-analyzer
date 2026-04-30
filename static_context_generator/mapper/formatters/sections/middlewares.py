"""
formatters/sections/middlewares.py — Compact TXT formatter for middlewares section.
"""
from __future__ import annotations


def format_middlewares_txt(section: dict, meta: dict) -> str:
    """Compact middleware info optimized for AI context."""
    lines = []
    
    routes_with_mw = section.get('routes_with_middleware', [])
    middleware_usage = section.get('middleware_usage', {})
    fastapi_global = section.get('fastapi_global_middleware', [])
    total_detected = section.get('total_middlewares_detected', 0)
    
    if total_detected == 0 and not fastapi_global:
        return "MIDDLEWARES: none detected\n"
    
    lines.append(f"MIDDLEWARES: {len(routes_with_mw)} routes with middleware | {total_detected} unique middleware types")
    
    # FastAPI global middleware
    if fastapi_global:
        global_mw = [mw['middleware'] for mw in fastapi_global]
        lines.append(f"GLOBAL_MW: {', '.join(set(global_mw))}")
    
    # Most used middlewares
    if middleware_usage:
        sorted_mw = sorted(middleware_usage.items(), key=lambda x: x[1]['route_count'], reverse=True)[:5]
        mw_stats = [f"{name}({data['route_count']}routes)" for name, data in sorted_mw]
        lines.append(f"TOP_MW: {' '.join(mw_stats)}")
    
    # Route breakdown by method
    if routes_with_mw:
        by_method = {}
        for route in routes_with_mw:
            method = route['method']
            if method not in by_method:
                by_method[method] = 0
            by_method[method] += 1
        
        method_stats = [f"{method}:{count}" for method, count in by_method.items()]
        lines.append(f"METHODS: {'/'.join(method_stats)}")
        
        # Sample protected routes
        sample_routes = routes_with_mw[:3]  # First 3
        route_examples = []
        for route in sample_routes:
            mw_list = ','.join(route['middlewares'][:2])  # First 2 middleware
            route_examples.append(f"{route['method']} {route['path']}[{mw_list}]")
        lines.append(f"EXAMPLES: {' | '.join(route_examples)}")
    
    return "\n".join(lines) + "\n"