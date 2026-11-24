"""
One-click release builder for FileAlias (影名):
1. Generates multi-resolution Windows icon `assets/app_icon.ico`
2. Ensures `UIAutomationCore.dll` COM bindings are pre-generated in `comtypes.gen`
3. Packages lightweight standalone `dist/FileAlias/FileAlias.exe` via PyInstaller
4. Creates ready-to-share `release/FileAlias_v1.0.0_Windows_x64.zip`
"""

from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
VERSION = "1.0.0"


def generate_ico() -> Path:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication
    from file_alias.ui.theme import create_app_icon

    _app = QApplication.instance() or QApplication([])
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(exist_ok=True)
    ico_path = assets_dir / "app_icon.ico"

    pix = create_app_icon(True, 256).pixmap(256, 256)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    im = Image.open(io.BytesIO(bytes(buf.data())))
    im.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"[1/4] Generated icon: {ico_path}")
    return ico_path


def warm_comtypes_cache() -> None:
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    print("[2/4] Verified comtypes UIAutomationCore bindings")


def run_pyinstaller(ico_path: Path) -> Path:
    excludes = [
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "cv2",
        "numpy",
        "PIL",
        "playwright",
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter",
    ]
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "FileAlias",
        "--icon",
        str(ico_path),
        "--contents-directory",
        "_internal",
        "--collect-submodules",
        "comtypes.gen",
    ]
    for mod in excludes:
        cmd.extend(["--exclude-module", mod])
    cmd.append(str(ROOT / "main.py"))

    print("[3/4] Running PyInstaller ...")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    dist_dir = ROOT / "dist" / "FileAlias"
    shutil.copy2(ROOT / "README.md", dist_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", dist_dir / "LICENSE.txt")
    return dist_dir


def create_release_zip(dist_dir: Path) -> Path:
    rel_dir = ROOT / "release"
    rel_dir.mkdir(exist_ok=True)
    zip_path = rel_dir / f"FileAlias_v{VERSION}_Windows_x64.zip"
    if zip_path.exists():
        zip_path.unlink()

    print(f"[4/4] Creating archive: {zip_path} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                arcname = Path("FileAlias") / file_path.relative_to(dist_dir)
                zf.write(file_path, str(arcname))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"SUCCESS! Release package ready: {zip_path} ({size_mb:.2f} MB)")
    return zip_path


if __name__ == "__main__":
    ico = generate_ico()
    warm_comtypes_cache()
    dist = run_pyinstaller(ico)
    create_release_zip(dist)
