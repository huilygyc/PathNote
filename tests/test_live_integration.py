"""
Live Windows 11 integration tests:
1. Global hotkey parser & formatting
2. Real #32770 Save As dialog detection, inline '(别名或用途)' anchor tracking, and folder navigation
3. Real Windows 11 Explorer (CabinetWClass) inline '(别名或用途)' tracking on folders ('AsusMCenterAppstore', 'coad')
4. Full UI Controller lifecycle verification
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import win32gui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from file_alias.config import ConfigManager
from file_alias.hotkeys import parse_hotkey
from file_alias.inline_sensor import InlineSensorWorker, InlineViewSnapshot
from file_alias.models import normalize_key
from file_alias.storage import AliasStore
from file_alias.ui.inline_overlay import InlineAliasOverlay, format_inline_parenthetical
from file_alias.ui.tray import FileAliasController
from file_alias.win_inspector import WindowInspector


class TestLiveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        cls.app = QApplication.instance() or QApplication([])

    def test_hotkey_and_inline_formatter(self) -> None:
        self.assertIsNotNone(parse_hotkey("Alt+A"))
        self.assertIsNotNone(parse_hotkey("Ctrl+Shift+Space"))
        self.assertIsNone(parse_hotkey("InvalidKey"))

        self.assertEqual(
            format_inline_parenthetical("华硕应用中心", "", include_note=True),
            "(华硕应用中心)",
        )
        self.assertEqual(
            format_inline_parenthetical("代码练习", "C++与算法", include_note=True),
            "(代码练习 · C++与算法)",
        )

    def test_live_save_dialog_inline_and_navigation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fa_eng_") as tmp_str:
            base_dir = Path(tmp_str)
            dir_asus = base_dir / "AsusMCenterAppstore"
            dir_coad = base_dir / "coad"
            dir_asus.mkdir()
            dir_coad.mkdir()
            (base_dir / "weights_v1.pt").write_text("ok", encoding="utf-8")

            store = AliasStore(db_path=base_dir / "test_inline.db")
            store.upsert(dir_asus, alias="华硕控制中心商店")
            store.upsert(dir_coad, alias="代码工程目录", note="日常练习")

            dialog_title = f"FileAliasLiveTest_{int(time.time() * 1000)}"
            initial_file = str(base_dir / "draft_model.pt")

            helper_code = (
                "from PySide6.QtWidgets import QApplication, QFileDialog\n"
                "app = QApplication([])\n"
                f"QFileDialog.getSaveFileName(None, {dialog_title!r}, {initial_file!r})\n"
            )
            proc = subprocess.Popen([sys.executable, "-c", helper_code])
            worker = InlineSensorWorker(store)
            cfg_mgr = ConfigManager(config_path=base_dir / "cfg.json")
            overlay = InlineAliasOverlay(cfg_mgr)
            received_snaps: list[InlineViewSnapshot] = []
            worker.snapshotChanged.connect(
                lambda s: (received_snaps.append(s), overlay.update_snapshot(s)) if s else None
            )

            try:
                hwnd = 0
                for _ in range(50):
                    time.sleep(0.1)
                    h = win32gui.FindWindow("#32770", dialog_title)
                    if h and win32gui.IsWindowVisible(h):
                        hwnd = h
                        break
                self.assertNotEqual(hwnd, 0, "Failed to spawn live #32770 Save As dialog")
                time.sleep(0.55)

                inspector = WindowInspector()
                ctx = inspector.inspect_hwnd(hwnd)
                self.assertIsNotNone(ctx)
                self.assertEqual(ctx.kind, "file_dialog")
                self.assertEqual(normalize_key(ctx.current_dir), normalize_key(base_dir))

                # Verify real-time InlineSensorWorker + InlineAliasOverlay detects both folders!
                worker.set_context(ctx)
                worker.start()
                for _ in range(25):
                    time.sleep(0.08)
                    self.app.processEvents()
                    if received_snaps:
                        break

                self.assertTrue(len(received_snaps) > 0, "InlineSensorWorker did not emit snapshot for #32770")
                snap = received_snaps[-1]
                found_names = {a.display_name: a.alias for a in snap.items}
                self.assertIn("AsusMCenterAppstore", found_names)
                self.assertIn("coad", found_names)
                self.assertEqual(found_names["AsusMCenterAppstore"], "华硕控制中心商店")
                self.assertTrue(overlay.isVisible())

                # Test live directory navigation inside #32770 Save As dialog
                ok = inspector.navigate_to_directory(ctx, str(dir_coad))
                self.assertTrue(ok)

                navigated_ctx = None
                for _ in range(25):
                    time.sleep(0.12)
                    self.app.processEvents()
                    navigated_ctx = inspector.inspect_hwnd(hwnd)
                    if navigated_ctx and normalize_key(navigated_ctx.current_dir) == normalize_key(dir_coad):
                        break

                self.assertIsNotNone(navigated_ctx)
                self.assertEqual(normalize_key(navigated_ctx.current_dir), normalize_key(dir_coad))

                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
            finally:
                worker.stop_worker()
                overlay.close()
                store.close()
                proc.terminate()
                proc.wait(timeout=5)

    def test_live_win11_explorer_inline_tracking(self) -> None:
        """Verify live Windows 11 CabinetWClass Explorer directory detection and inline item matching."""
        import ctypes
        from ctypes import wintypes

        with tempfile.TemporaryDirectory(prefix="fa_exp_") as tmp_str:
            base_dir = Path(tmp_str)
            (base_dir / "AsusMCenterAppstore").mkdir()
            (base_dir / "coad").mkdir()
            (base_dir / "main.py").write_text("print(1)", encoding="utf-8")

            store = AliasStore(db_path=base_dir / "exp.db")
            store.upsert(base_dir / "AsusMCenterAppstore", alias="华硕控制中心")
            store.upsert(base_dir / "coad", alias="代码练习目录")
            store.upsert(base_dir / "main.py", alias="主入口脚本")

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            before: set[int] = set()
            ctypes.windll.user32.EnumWindows(
                WNDENUMPROC(
                    lambda h, _: (before.add(int(h)) if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "CabinetWClass" else None) or True
                ),
                0,
            )

            subprocess.Popen(["explorer.exe", str(base_dir)])
            hwnd = 0
            for _ in range(40):
                time.sleep(0.15)
                now_set: set[int] = set()
                ctypes.windll.user32.EnumWindows(
                    WNDENUMPROC(
                        lambda h, _: (now_set.add(int(h)) if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "CabinetWClass" else None) or True
                    ),
                    0,
                )
                diff = now_set - before
                if diff:
                    hwnd = next(iter(diff))
                    break

            worker = InlineSensorWorker(store)
            snaps: list[InlineViewSnapshot] = []
            worker.snapshotChanged.connect(lambda s: snaps.append(s) if s else None)
            try:
                self.assertNotEqual(hwnd, 0, "Failed to open Windows 11 Explorer window")
                inspector = WindowInspector()
                ctx = None
                for _ in range(25):
                    time.sleep(0.18)
                    ctx = inspector.inspect_hwnd(hwnd)
                    if ctx and normalize_key(ctx.current_dir) == normalize_key(base_dir):
                        break
                self.assertIsNotNone(ctx)
                self.assertEqual(normalize_key(ctx.current_dir), normalize_key(base_dir))

                worker.set_context(ctx)
                worker.start()
                for _ in range(25):
                    time.sleep(0.08)
                    self.app.processEvents()
                    if snaps:
                        break

                # Live rename test inside open Windows 11 Explorer: rename 'coad' -> 'code_renamed' on disk!
                import os
                os.rename(base_dir / "coad", base_dir / "code_renamed")
                snaps.clear()
                worker.request_refresh(1.8, force_reconcile=True)
                renamed_matched = {}
                for _ in range(35):
                    time.sleep(0.08)
                    self.app.processEvents()
                    if snaps:
                        renamed_matched = {a.display_name: a.alias for a in snaps[-1].items}
                        if "code_renamed" in renamed_matched:
                            break
                self.assertEqual(
                    renamed_matched.get("code_renamed"),
                    "代码练习目录",
                    f"Expected renamed folder 'code_renamed' to auto-follow alias, got {renamed_matched}",
                )

                # Trigger live Win11 right-click context menu and verify Z-order occlusion clipping!
                from file_alias.inline_sensor import _find_visible_file_view_hwnds
                import win32con
                _, vw = _find_visible_file_view_hwnds(hwnd)
                if vw:
                    l, t, r, b = win32gui.GetWindowRect(vw)
                    cx, cy = (l + r) // 2, (t + b) // 2
                    snaps.clear()
                    win32gui.PostMessage(vw, win32con.WM_CONTEXTMENU, vw, ((cy & 0xFFFF) << 16) | (cx & 0xFFFF))
                    occluded_snap = None
                    for _ in range(20):
                        time.sleep(0.06)
                        self.app.processEvents()
                        if snaps and snaps[-1].occluding_rects:
                            occluded_snap = snaps[-1]
                            break
                    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                    self.assertIsNotNone(occluded_snap, "Expected right-click menu occluding_rects to be captured!")
                    self.assertGreater(len(occluded_snap.occluding_rects), 0)
            finally:
                worker.stop_worker()
                store.close()
                if hwnd:
                    win32gui.PostMessage(hwnd, 0x0010, 0, 0)

    def test_zero_lag_window_drag_and_winevent_hook(self) -> None:
        from file_alias.inline_sensor import InlineItemAnchor
        from file_alias.win_events import WinEventMonitor

        mon = WinEventMonitor()
        mon.start()
        try:
            self.assertGreater(len(mon._hooks), 0)
        finally:
            mon.stop()
            self.assertEqual(len(mon._hooks), 0)

        with tempfile.TemporaryDirectory(prefix="fa_drag_") as tmp_str:
            cfg_mgr = ConfigManager(config_path=Path(tmp_str) / "cfg.json")
            ov = InlineAliasOverlay(cfg_mgr)
            try:
                snap = InlineViewSnapshot(
                    hwnd=9999,
                    host_rect=(300, 300, 1200, 900),
                    viewport_rect=(330, 360, 1170, 870),
                    is_dark_bg=False,
                    items=(
                        InlineItemAnchor("d:\\a\\f.py", "f.py", "测试脚本", "", "#0F6CBD", (360, 390, 700, 420)),
                    ),
                )
                ov.update_snapshot(snap)
                self.app.processEvents()
                orig_pos = ov.pos()

                # Translate host window by (+150, +90) physical pixels -> pure translation returns True
                ok = ov.sync_host_window_move((450, 390, 1350, 990))
                self.assertTrue(ok)
                self.assertGreater(ov.pos().x(), orig_pos.x())
                self.assertGreater(ov.pos().y(), orig_pos.y())

                # Resize host window -> returns False so UIA layout refreshes
                resized = ov.sync_host_window_move((450, 390, 1600, 1100))
                self.assertFalse(resized)
            finally:
                ov.close()

    def test_controller_and_inline_overlay_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fa_ui_") as tmp_str:
            tmp = Path(tmp_str)
            cfg_mgr = ConfigManager(config_path=tmp / "config.json")
            cfg_mgr.update(
                hotkey_toggle="Ctrl+Alt+F9",
                hotkey_search="Ctrl+Alt+F10",
                hotkey_quick_add="Ctrl+Alt+F11",
            )
            store = AliasStore(db_path=tmp / "aliases.db")
            sample_dir = tmp / "pcb_rev_c"
            sample_dir.mkdir()
            sample_file = sample_dir / "gerber_top.gbr"
            sample_file.write_text("gbr", encoding="utf-8")
            store.upsert(sample_dir, alias="主控板 C版 PCB 生产文件")
            store.upsert(sample_file, alias="顶层线路光绘文件", note="发板前必查线宽")

            ctrl = FileAliasController(self.app, store=store, config_mgr=cfg_mgr)
            try:
                # Default config: inline suffix ON, companion panel OFF
                self.assertTrue(ctrl.config_mgr.config.alias_enabled)
                self.assertTrue(ctrl.config_mgr.config.show_inline_suffix)
                self.assertFalse(ctrl.config_mgr.config.show_companion_panel)

                ctrl.toggle_alias_mode()
                self.assertFalse(ctrl.config_mgr.config.alias_enabled)
                ctrl.toggle_alias_mode()
                self.assertTrue(ctrl.config_mgr.config.alias_enabled)
            finally:
                ctrl.win_events.stop()
                ctrl.inspector.stop()
                ctrl.inline_worker.stop_worker()
                ctrl.hover_worker.stop_worker()
                ctrl.hotkeys.unregister_all()
                ctrl.inline_overlay.close()
                ctrl.companion.close()
                ctrl.hover_bubble.close()
                ctrl.quick_search.close()
                ctrl.toast.close()
                ctrl.tray.hide()
                store.close()


if __name__ == "__main__":
    unittest.main()
