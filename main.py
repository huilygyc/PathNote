"""
Entry point for FileAlias (影名) — Windows 英文路径文件与文件夹别名助手.
Provides single-instance IPC wake-up, tray residency, and command-line triggers.
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from file_alias.config import DEFAULT_DATA_DIR
from file_alias.storage import AliasStore
from file_alias.ui.tray import FileAliasController


IPC_SERVER_NAME = "PathNote_SingleInstance_v1"


def seed_first_run_examples(store: AliasStore) -> None:
    """Populate real project-directory aliases on very first launch so the user can test immediately."""
    proj_dir = Path(__file__).resolve().parent
    store.upsert(
        proj_dir,
        alias="PathNote 项目主目录",
        note="Windows 英文路径原位备注助手源码目录",
        tags=["PathNote", "源码"],
        color="#0F6CBD",
        pinned=True,
    )
    samples = [
        (proj_dir / "main.py", "程序主入口脚本", "单实例进程通信与应用启动入口", ["核心代码"], "#10B981"),
        (proj_dir / "run.bat", "一键无黑框启动器", "双击即可在后台托盘运行 FileAlias", ["快捷启动"], "#F59E0B"),
        (proj_dir / "file_alias", "核心业务逻辑与界面包", "包含资源管理器/保存窗口追踪、数据库与Qt界面", ["核心代码"], "#8B5CF6"),
        (proj_dir / "tests", "自动化测试套件", "包含存储层单元测试与真实保存窗口联动集成测试", ["测试"], "#06B6D4"),
    ]
    for path, alias, note, tags, color in samples:
        if path.exists():
            store.upsert(path, alias=alias, note=note, tags=tags, color=color)


def send_ipc_command(cmd: str) -> bool:
    """If another instance is already running, send `cmd` to it and return True."""
    sock = QLocalSocket()
    sock.connectToServer(IPC_SERVER_NAME)
    if sock.waitForConnected(250):
        sock.write(cmd.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="PathNote · 路径备注 - 英文路径原位备注助手")
    parser.add_argument("--minimized", action="store_true", help="启动后仅驻留系统托盘，不弹出主窗口")
    parser.add_argument("--toggle", action="store_true", help="切换已运行实例的备注显示开关")
    parser.add_argument("--search", action="store_true", help="唤起已运行实例的全局快速查询面板")
    parser.add_argument("--edit", type=str, default="", help="为指定路径直接弹出设置备注窗口")
    args = parser.parse_args()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("PathNote")

    if args.edit and send_ipc_command(f"edit|{args.edit}"):
        return 0
    if args.toggle and send_ipc_command("toggle"):
        return 0
    if args.search and send_ipc_command("search"):
        return 0
    if not args.edit and send_ipc_command("show"):
        return 0

    # Clean stale local socket if previous crash occurred
    QLocalServer.removeServer(IPC_SERVER_NAME)
    server = QLocalServer(app)
    server.listen(IPC_SERVER_NAME)

    is_first_run = not (DEFAULT_DATA_DIR / "aliases.db").exists()
    controller = FileAliasController(app)
    if is_first_run and controller.store.count() == 0 and not getattr(sys, "frozen", False):
        seed_first_run_examples(controller.store)
        controller.main_window.refresh_table()
        controller.companion.refresh_all()

    def _on_new_ipc_conn() -> None:
        conn = server.nextPendingConnection()
        if not conn:
            return
        if conn.waitForReadyRead(200):
            msg = bytes(conn.readAll()).decode("utf-8", errors="ignore").strip()
            if msg == "toggle":
                controller.toggle_alias_mode()
            elif msg == "search":
                controller.open_quick_search()
            elif msg.startswith("edit|"):
                target_p = msg.split("|", 1)[1].strip()
                controller.open_edit_dialog(target_p)
            else:
                controller.show_main_window()
        conn.disconnectFromServer()

    server.newConnection.connect(_on_new_ipc_conn)

    if args.edit:
        controller.open_edit_dialog(args.edit)
    elif not args.minimized:
        controller.show_main_window()
    else:
        hk = controller.config_mgr.config.hotkey_toggle
        controller.toast.show_toast(f"PathNote 已在后台就绪 ({hk} 开关显示)", "#2563EB")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
