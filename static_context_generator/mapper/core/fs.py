"""
core/fs.py — File-system helpers: walking, filtering, reading, language detection.
No business logic — pure I/O utilities.
"""
import os
import re
from pathlib import Path
from typing import Optional

from .config import (
    EXCLUDED_DIRS, EXCLUDED_EXTENSIONS, LOCK_FILES,
    EXT_TO_LANG, FILENAME_TO_LANG,
)


def is_excluded_dir(name: str) -> bool:
    return name.lower() in {d.lower() for d in EXCLUDED_DIRS}


def is_excluded_file(path: Path, exclude_locks: bool) -> bool:
    name_lower = path.name.lower()
    if exclude_locks and name_lower in {f.lower() for f in LOCK_FILES}:
        return True
    for ext in EXCLUDED_EXTENSIONS:
        if name_lower.endswith(ext):
            return True
    if re.search(r"\.min\.[a-z]+$", name_lower):
        return True
    return False


def detect_language(path: Path) -> Optional[str]:
    if path.name in FILENAME_TO_LANG:
        return FILENAME_TO_LANG[path.name]
    return EXT_TO_LANG.get(path.suffix.lower())


def read_text(path: Path, max_bytes: int = 2_000_000) -> Optional[str]:
    """Read file as UTF-8. Returns None if binary or unreadable."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(max_bytes)
        if raw.count(b"\x00") > len(raw) * 0.05:
            return None
        return raw.decode("utf-8", errors="replace")
    except (PermissionError, OSError):
        return None


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (1 if not text.endswith("\n") else 0)


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def collect_files(root: Path, exclude_locks: bool) -> list[Path]:
    result: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if not is_excluded_dir(d) and not Path(dirpath, d).is_symlink()
        )
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if not fpath.is_symlink() and not is_excluded_file(fpath, exclude_locks):
                result.append(fpath)
    return result
