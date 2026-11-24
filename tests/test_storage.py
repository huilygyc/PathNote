"""Unit tests for AliasStore, path normalization, extension-hidden matching, relocation, and JSON backup."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from file_alias.models import is_ascii_safe_path, normalize_key, normalize_path
from file_alias.storage import AliasStore


class TestAliasStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "test_aliases.db"
        self.store = AliasStore(db_path=self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_path_normalization_and_ascii_check(self) -> None:
        self.assertEqual(normalize_path("D:/AI/exp_01/"), r"D:\AI\exp_01")
        self.assertEqual(normalize_path("file:///D:/AI/exp%2001/best.pt"), r"D:\AI\exp 01\best.pt")
        self.assertEqual(normalize_key(r"D:\AI\Exp_01"), normalize_key(r"d:\ai\exp_01"))
        self.assertTrue(is_ascii_safe_path(r"D:\AI\File_Alias\weights\best_v2.pt"))
        self.assertFalse(is_ascii_safe_path(r"D:\项目存档\best_v2.pt"))

    def test_crud_and_hidden_extension_resolution(self) -> None:
        exp_dir = self.root / "exp_yolo_v8"
        exp_dir.mkdir()
        weight_file = exp_dir / "best_epoch120.pt"
        weight_file.write_bytes(b"weights")

        self.store.upsert(
            exp_dir,
            alias="YOLOv8 产线螺丝漏检实验",
            note="输入分辨率 640",
            tags=["视觉检测", "产线A"],
            pinned=True,
        )
        self.store.upsert(
            weight_file,
            alias="最优收敛权重 (mAP 98.6%)",
            note="2026-11 训练完成",
            tags=["模型权重"],
        )

        # Case-insensitive exact lookup
        fetched = self.store.get(str(weight_file).upper())
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.alias, "最优收敛权重 (mAP 98.6%)")

        # Direct children listing
        in_dir = self.store.list_in_dir(exp_dir)
        self.assertEqual(len(in_dir), 1)
        self.assertEqual(in_dir[0].name, "best_epoch120.pt")

        # Hidden extension stem fallback (e.g. Explorer hiding '.pt')
        stem_resolved = self.store.resolve_item_in_dir(exp_dir, "best_epoch120")
        self.assertIsNotNone(stem_resolved)
        self.assertEqual(stem_resolved.alias, "最优收敛权重 (mAP 98.6%)")

        # Exact filename resolution
        exact_resolved = self.store.resolve_item_in_dir(exp_dir, "best_epoch120.pt")
        self.assertIsNotNone(exact_resolved)
        self.assertEqual(exact_resolved.path_key, stem_resolved.path_key)

    def test_search_and_folder_relocation_cascade(self) -> None:
        old_dir = self.root / "proj_alpha"
        old_sub = old_dir / "ckpt_01.bin"
        self.store.upsert(old_dir, alias="阿尔法主控固件", tags=["STM32", "嵌入式"], is_dir=True)
        self.store.upsert(old_sub, alias="v1.2 稳定版烧录包", note="修复CAN总线丢包", is_dir=False)

        hits = self.store.search("烧录 CAN")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].alias, "v1.2 稳定版烧录包")

        tag_hits = self.store.search("", tag_filter="STM32")
        self.assertEqual(len(tag_hits), 1)

        # Relocate parent folder -> nested child should cascade automatically
        new_dir = self.root / "proj_alpha_v2"
        updated = self.store.relocate_path(old_dir, new_dir)
        self.assertEqual(updated, 2)
        self.assertIsNone(self.store.get(old_dir))
        self.assertIsNotNone(self.store.get(new_dir))
        relocated_child = self.store.get(new_dir / "ckpt_01.bin")
        self.assertIsNotNone(relocated_child)
        self.assertEqual(relocated_child.alias, "v1.2 稳定版烧录包")

    def test_export_and_import_json(self) -> None:
        self.store.upsert(r"D:\EngPath\item_a.cad", alias="机架总装图", tags=["CAD"])
        backup_json = self.root / "backup.json"
        exported = self.store.export_json(backup_json)
        self.assertEqual(exported, 1)

        db2 = self.root / "restored.db"
        store2 = AliasStore(db_path=db2)
        try:
            imported = store2.import_json(backup_json)
            self.assertEqual(imported, 1)
            self.assertEqual(store2.get(r"D:\EngPath\item_a.cad").alias, "机架总装图")
        finally:
            store2.close()


    def test_categories_and_legacy_db_migration(self) -> None:
        import sqlite3
        from file_alias.models import DEFAULT_CATEGORY

        # 1. Omitting category defaults to '默认分类'
        e1 = self.store.upsert(r"D:\Eng\item1.txt", alias="默认项")
        self.assertEqual(e1.category, DEFAULT_CATEGORY)

        # 2. Custom category creation, counts, and filtering
        self.store.add_category("深度学习")
        e2 = self.store.upsert(r"D:\Eng\yolo.pt", alias="检测模型", category="深度学习")
        self.assertEqual(e2.category, "深度学习")
        self.assertIn("深度学习", self.store.list_categories())
        self.assertEqual(self.store.category_counts()["深度学习"], 1)
        self.assertEqual(len(self.store.search("", category_filter="深度学习")), 1)
        self.assertEqual(len(self.store.search("", category_filter=DEFAULT_CATEGORY)), 1)

        # 3. Rename category updates entries
        moved = self.store.rename_category("深度学习", "AI模型库")
        self.assertEqual(moved, 1)
        self.assertEqual(self.store.get(r"D:\Eng\yolo.pt").category, "AI模型库")

        # 4. Delete category safely falls back entries to '默认分类'
        reassigned = self.store.delete_category("AI模型库")
        self.assertEqual(reassigned, 1)
        self.assertEqual(self.store.get(r"D:\Eng\yolo.pt").category, DEFAULT_CATEGORY)

        # 5. Legacy DB without `category` column migrates non-destructively
        legacy_db = self.root / "legacy.db"
        conn = sqlite3.connect(str(legacy_db))
        conn.execute(
            """
            CREATE TABLE aliases (
                path_key TEXT PRIMARY KEY, path TEXT NOT NULL, alias TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                color TEXT NOT NULL DEFAULT '#0F6CBD', is_dir INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO aliases VALUES ('d:\\ai\\file_alias', 'D:\\AI\\File_Alias', '文件别名', '', '[]', '#0F6CBD', 1, 0, 1.0, 1.0);"
        )
        conn.commit()
        conn.close()

        migrated_store = AliasStore(db_path=legacy_db)
        try:
            rec = migrated_store.get(r"D:\AI\File_Alias")
            self.assertIsNotNone(rec)
            self.assertEqual(rec.alias, "文件别名")
            self.assertEqual(rec.category, DEFAULT_CATEGORY)
        finally:
            migrated_store.close()


if __name__ == "__main__":
    unittest.main()
