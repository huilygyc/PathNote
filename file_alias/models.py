"""Core data models for FileAlias."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


def normalize_path(raw_path: str | Path) -> str:
    """Normalize a Windows path for consistent, case-insensitive lookup while preserving casing for display."""
    p = str(raw_path).strip().strip('"')
    if not p:
        return ""
    # Expand environment vars and user home
    p = os.path.expandvars(os.path.expanduser(p))
    # Handle file:/// URIs if returned by COM Explorer LocationURL
    if p.lower().startswith("file:///"):
        from urllib.parse import unquote
        p = unquote(p[8:]).replace("/", "\\")
    elif p.lower().startswith("file://"):
        from urllib.parse import unquote
        p = "\\\\" + unquote(p[7:]).replace("/", "\\")
    p = os.path.normpath(p)
    # Keep drive root trailing backslash (e.g. D:\), strip trailing backslash on normal dirs
    if len(p) > 3 and p.endswith("\\"):
        p = p.rstrip("\\")
    return p


def normalize_key(raw_path: str | Path) -> str:
    """Lowercase canonical key for Windows case-insensitive filesystem matching."""
    norm = normalize_path(raw_path)
    return norm.lower() if norm else ""


def is_ascii_safe_path(raw_path: str | Path) -> bool:
    """Return True if every character in the path is pure ASCII (safe for strict English-path tools)."""
    norm = normalize_path(raw_path)
    if not norm:
        return True
    try:
        norm.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


DEFAULT_CATEGORY = "默认分类"


def normalize_category(raw_category: str | None) -> str:
    """Normalize category name; empty or whitespace falls back to '默认分类'."""
    if not raw_category:
        return DEFAULT_CATEGORY
    cleaned = str(raw_category).strip()
    return cleaned if cleaned else DEFAULT_CATEGORY


@dataclass
class AliasEntry:
    """Represents an alias & metadata record bound to a file or directory path."""

    path: str                          # Display-cased normalized path, e.g. D:\Projects\exp_01
    path_key: str                      # Lowercase canonical lookup key
    alias: str                         # Primary Chinese/human-readable alias, e.g. "缺陷检测基线实验"
    note: str = ""                     # Detailed purpose / description
    category: str = DEFAULT_CATEGORY   # Category name, defaults to "默认分类"
    tags: list[str] = field(default_factory=list)
    color: str = "#3B82F6"             # Badge accent color hex
    is_dir: bool = False               # Cached directory indicator
    pinned: bool = False               # Pin to top in companion & search
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def name(self) -> str:
        """File or folder basename."""
        p = Path(self.path)
        return p.name if p.name else self.path

    @property
    def parent_key(self) -> str:
        """Canonical key of the parent directory."""
        p = Path(self.path)
        parent = str(p.parent)
        if parent == self.path:
            return ""
        return normalize_key(parent)

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)

    @property
    def ascii_safe(self) -> bool:
        return is_ascii_safe_path(self.path)


@dataclass
class WindowContext:
    """Snapshot of the active/tracked Explorer or File Open/Save Dialog window."""

    hwnd: int
    kind: str                          # "explorer" | "file_dialog"
    title: str
    current_dir: str                   # Normalized current directory path ("" if virtual/unknown)
    rect: tuple[int, int, int, int]    # (left, top, right, bottom) screen coordinates
    selected_paths: list[str] = field(default_factory=list)
    filename_text: str = ""            # Current text in Save/Open filename input box (if file_dialog)
    is_minimized: bool = False
    is_maximized: bool = False


@dataclass
class HoverTarget:
    """Information about the file/folder item currently hovered or selected in Explorer / File Dialog."""

    path: str                          # Full resolved path
    item_name: str                     # Displayed item text
    item_rect: tuple[int, int, int, int]  # Bounding rectangle of item on screen
    cursor_pos: tuple[int, int]        # Cursor (x, y)
    source: str = "hover"              # "hover" | "selection"
