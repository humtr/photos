from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from photos.services import PhotoOrganizerService
from photos.store import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


BULK_FOLDER_COUNT = 230


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class FolderScalingTests(unittest.TestCase):
    def test_folder_aggregation_and_paging_are_bounded_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            media = base / "media"
            write_file(media / "root.JPG", b"123")
            write_file(media / "albums" / "parent.PNG", b"12345")
            write_file(media / "albums" / "leaf" / "leaf.JPG", b"1234567")
            for index in range(BULK_FOLDER_COUNT):
                write_file(media / "bulk" / f"folder-{index:03d}" / "item.JPG", b"x")

            with PhotoOrganizerService(base / "photos.sqlite") as service:
                scan = service.scan_inventory(media)
                self.assertTrue(scan["ok"], scan)
                self.assertEqual(scan["data"]["folder_count"], 234)

                store_page = service.store.list_folder_nodes(media, page=1, page_size=7)
                self.assertEqual(store_page["total"], 234)
                self.assertEqual(store_page["page_size"], 7)
                self.assertEqual(len(store_page["rows"]), 7)
                self.assertTrue(store_page["has_next"])

                all_nodes_page = service.folder_tree(media, page=1, page_size=500)
                self.assertTrue(all_nodes_page["ok"], all_nodes_page)
                self.assertEqual(all_nodes_page["data"]["total"], 234)
                self.assertFalse(all_nodes_page["data"]["has_next"])
                nodes = {row["path"]: row for row in all_nodes_page["data"]["rows"]}

                root = nodes[""]
                self.assertEqual(root["direct_file_count"], 1)
                self.assertEqual(root["subtree_file_count"], 233)
                self.assertEqual(root["direct_bytes"], 3)
                self.assertEqual(root["subtree_bytes"], 245)
                self.assertIsNone(root["parent_path"])
                self.assertEqual(root["depth"], 0)

                parent = nodes["albums"]
                self.assertEqual(parent["direct_file_count"], 1)
                self.assertEqual(parent["subtree_file_count"], 2)
                self.assertEqual(parent["direct_bytes"], 5)
                self.assertEqual(parent["subtree_bytes"], 12)
                self.assertEqual(parent["parent_path"], "")
                self.assertEqual(parent["depth"], 1)
                self.assertEqual(json.loads(parent["extension_counts_json"]), {".png": 1})
                self.assertIsNotNone(json.loads(parent["date_ranges_json"])["min_mtime_ns"])

                leaf = nodes["albums/leaf"]
                self.assertEqual(leaf["direct_file_count"], 1)
                self.assertEqual(leaf["subtree_file_count"], 1)
                self.assertEqual(leaf["direct_bytes"], 7)
                self.assertEqual(leaf["subtree_bytes"], 7)
                self.assertEqual(leaf["parent_path"], "albums")
                self.assertEqual(leaf["depth"], 2)

                default_page = service.folder_tree(media)
                self.assertTrue(default_page["ok"], default_page)
                self.assertEqual(default_page["data"]["page_size"], DEFAULT_PAGE_SIZE)
                self.assertEqual(default_page["data"]["total"], 234)
                self.assertEqual(len(default_page["data"]["rows"]), DEFAULT_PAGE_SIZE)
                self.assertTrue(default_page["data"]["has_next"])

                second_page = service.folder_tree(media, page=2)
                self.assertTrue(second_page["ok"], second_page)
                self.assertEqual(len(second_page["data"]["rows"]), 34)
                self.assertFalse(second_page["data"]["has_next"])

                legacy_rows = service.store.folder_nodes(media)
                self.assertEqual(len(legacy_rows), DEFAULT_PAGE_SIZE)

                oversized_page = service.folder_tree(media, page_size=MAX_PAGE_SIZE + 1)
                self.assertTrue(oversized_page["ok"], oversized_page)
                self.assertEqual(oversized_page["data"]["page_size"], MAX_PAGE_SIZE)


if __name__ == "__main__":
    unittest.main()
