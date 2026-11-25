"""
One-click release & installer builder for PathNote · 路径备注:
1. Renders sculpted Windows 11 Fluent multi-size `assets/app_icon.ico` & `docs/icon.png`
2. Packages `dist/PathNote/PathNote.exe` via PyInstaller and strips ~25MB of unused Qt bloat (`opengl32sw.dll`, etc.)
3. Creates green portable archive `release/PathNote_Portable_v1.1.0_x64.zip`
4. Compiles native single-file graphical Windows Setup Installer `release/PathNote_Setup_v1.1.0.exe` using `csc.exe`
"""

from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
VERSION = "1.1.0"
APP_NAME = "PathNote"


def generate_icons() -> Path:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication
    from file_alias.ui.theme import render_fluent_icon_pixmap

    _app = QApplication.instance() or QApplication([])
    assets_dir = ROOT / "assets"
    docs_dir = ROOT / "docs"
    assets_dir.mkdir(exist_ok=True)
    docs_dir.mkdir(exist_ok=True)

    ico_path = assets_dir / "app_icon.ico"
    pix512 = render_fluent_icon_pixmap(512, muted=False)
    pix256 = render_fluent_icon_pixmap(256, muted=False)
    pix256.save(str(docs_dir / "icon.png"), "PNG")

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix512.save(buf, "PNG")
    im = Image.open(io.BytesIO(bytes(buf.data())))
    im.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    print(f"[1/5] Generated Fluent icon: {ico_path}")
    return ico_path


def warm_comtypes_cache() -> None:
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    print("[2/5] Verified comtypes UIAutomationCore bindings")


def build_pyinstaller_and_slim(ico_path: Path) -> Path:
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
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
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
        APP_NAME,
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

    print("[3/5] Running PyInstaller & slimming unused Qt binaries ...")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    dist_dir = ROOT / "dist" / APP_NAME

    # Strip unneeded software OpenGL & translation bloat (~25+ MB savings!)
    pyside_internal = dist_dir / "_internal" / "PySide6"
    for bloat_file in ("opengl32sw.dll", "d3dcompiler_47.dll", "Qt6OpenGL.dll", "Qt6Svg.dll", "Qt6Pdf.dll"):
        p = pyside_internal / bloat_file
        if p.exists():
            p.unlink()
    trans_dir = pyside_internal / "translations"
    if trans_dir.exists():
        shutil.rmtree(trans_dir, ignore_errors=True)

    shutil.copy2(ROOT / "README.md", dist_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", dist_dir / "LICENSE.txt")
    return dist_dir


def create_portable_zip(dist_dir: Path) -> Path:
    rel_dir = ROOT / "release"
    rel_dir.mkdir(exist_ok=True)
    # Clean old zips/installers
    for old in rel_dir.glob("*"):
        old.unlink(missing_ok=True)

    zip_path = rel_dir / f"{APP_NAME}_Portable_v{VERSION}_x64.zip"
    print(f"[4/5] Creating slimmed portable archive: {zip_path} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                arcname = Path(APP_NAME) / file_path.relative_to(dist_dir)
                zf.write(file_path, str(arcname))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"      Portable ZIP ready: {size_mb:.2f} MB")
    return zip_path


def build_native_setup_exe(zip_path: Path, ico_path: Path) -> Path:
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.exists():
        raise FileNotFoundError(f"csc.exe not found at {csc}")

    setup_exe = ROOT / "release" / f"{APP_NAME}_Setup_v{VERSION}.exe"
    cs_file = ROOT / "installer_stub.cs"

    cmd = [
        str(csc),
        "/nologo",
        "/optimize+",
        "/target:winexe",
        f"/out:{setup_exe}",
        f"/win32icon:{ico_path}",
        f"/resource:{zip_path},payload.zip",
        "/r:System.dll",
        "/r:System.Core.dll",
        "/r:System.Drawing.dll",
        "/r:System.Windows.Forms.dll",
        "/r:System.IO.Compression.dll",
        "/r:System.IO.Compression.FileSystem.dll",
        "/r:Microsoft.CSharp.dll",
        str(cs_file),
    ]
    print(f"[5/5] Compiling single-file Windows installer: {setup_exe} ...")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    size_mb = setup_exe.stat().st_size / (1024 * 1024)
    print(f"SUCCESS! Single-file Setup Installer ready: {setup_exe} ({size_mb:.2f} MB)")
    return setup_exe


if __name__ == "__main__":
    ico = generate_icons()
    warm_comtypes_cache()
    dist = build_pyinstaller_and_slim(ico)
    zpath = create_portable_zip(dist)
    build_native_setup_exe(zpath, ico)
