#!/usr/bin/env python3
"""
Standalone entry point for the mapper package.
Run: python3 scripts/run_mapper.py [args...]
"""
import sys
from pathlib import Path

# Add scripts dir to path so we can import mapper
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

try:
    from mapper.cli import main
    main()
except Exception as e:
    print(f"[ERROR] Failed to run mapper: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)