"""Configuration persistence for FileAlias."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import sys
import threading


def _resolve_default_data_dir() -> Path:
    """
    Resolve persistent data directory:
    - Source mode: `<repo>/data`
    - Packaged .exe mode (`sys.frozen`): `<exe_dir>/data` if writable (portable mode),
      falling back to `%LOCALAPPDATA%/FileAlias/data` if installed in read-only Program Files.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        portable_dir = exe_dir / "data"
        try:
            portable_dir.mkdir(parents=True, exist_ok=True)
            probe = portable_dir / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return portable_dir
        except OSError:
            appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            fallback = appdata / "FileAlias" / "data"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
    return Path(__file__).resolve().parent.parent / "data"


DEFAULT_DATA_DIR = _resolve_default_data_dir()


@dataclass
class AppConfig:
    """User-configurable settings."""

    alias_enabled: bool = True
    hotkey_toggle: str = "Alt+A"
    hotkey_search: str = "Alt+Q"
    hotkey_quick_add: str = "Alt+S"

    # Primary in-place inline '(别名或用途)' suffix right after filenames
    show_inline_suffix: bool = True
    inline_include_note: bool = True
    inline_pill_style: bool = False
    inline_text_color: str = "#0F6CBD"

    # Optional auxiliary surfaces (off by default to keep Explorer clean)
    show_companion_panel: bool = False
    show_hover_bubble: bool = False

    show_unaliased_in_panel: bool = True
    companion_dock_side: str = "right"   # "right" | "left"
    companion_width: int = 320
    theme: str = "light"                 # "light" | "dark"
    ascii_warning_banner: bool = True


class ConfigManager:
    """Thread-safe JSON configuration manager."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.path = config_path or (DEFAULT_DATA_DIR / "config.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config = AppConfig()
        self.load()

    def load(self) -> AppConfig:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    valid_fields = AppConfig.__dataclass_fields__.keys()
                    filtered = {k: v for k, v in raw.items() if k in valid_fields}
                    self.config = AppConfig(**filtered)
                except Exception:
                    self.config = AppConfig()
            else:
                self.save()
            return self.config

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(asdict(self.config), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self.path)

    def update(self, **kwargs) -> AppConfig:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self.config, k):
                    setattr(self.config, k, v)
            self.save()
            return self.config
