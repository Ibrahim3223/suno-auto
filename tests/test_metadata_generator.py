"""Tests for metadata_generator module."""

import json
import tempfile
import unittest
from pathlib import Path

from src.metadata_generator import _format_timestamps, generate_metadata


class TestFormatTimestamps(unittest.TestCase):
    """Test _format_timestamps() helper."""

    def test_empty_returns_fallback(self) -> None:
        result = _format_timestamps([])
        self.assertIn("0:00", result)

    def test_single_timestamp(self) -> None:
        result = _format_timestamps([("0:00", "Track 1")])
        self.assertIn("0:00", result)
        self.assertIn("Track 1", result)

    def test_multiple_timestamps(self) -> None:
        ts = [("0:00", "Track 1"), ("3:15", "Track 2"), ("6:45", "Track 3")]
        result = _format_timestamps(ts)
        self.assertIn("3:15", result)
        self.assertIn("Track 3", result)


class TestGenerateMetadata(unittest.TestCase):
    """Test generate_metadata() output structure."""

    def setUp(self) -> None:
        self.timestamps = [
            ("0:00", "Track 1"),
            ("3:22", "Track 2"),
            ("6:45", "Track 3"),
        ]

    def test_returns_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        for key in ("title", "description", "tags"):
            self.assertIn(key, meta)

    def test_title_is_nonempty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIsInstance(meta["title"], str)
        self.assertGreater(len(meta["title"]), 0)

    def test_description_contains_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIn("0:00", meta["description"])
        self.assertIn("Track 1", meta["description"])

    def test_tags_is_nonempty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIsInstance(meta["tags"], list)
        self.assertGreater(len(meta["tags"]), 0)

    def test_tags_contain_lofi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIn("lofi", meta["tags"])

    def test_description_contains_channel_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIn("Chill Drift", meta["description"])

    def test_json_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generate_metadata(self.timestamps, output_dir=tmp_path)
            json_files = list(tmp_path.glob("metadata_*.json"))
        self.assertEqual(len(json_files), 1)

    def test_json_file_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generate_metadata(self.timestamps, output_dir=tmp_path)
            json_file = next(tmp_path.glob("metadata_*.json"))
            data = json.loads(json_file.read_text(encoding="utf-8"))
        self.assertIn("title", data)
        self.assertIn("tags", data)

    def test_title_uses_template_placeholders(self) -> None:
        """Title must contain mood/scene text — not raw {placeholders}."""
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertNotIn("{mood}", meta["title"])
        self.assertNotIn("{scene}", meta["title"])

    def test_description_contains_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = generate_metadata(self.timestamps, output_dir=Path(tmp))
        self.assertIn(meta["title"], meta["description"])


if __name__ == "__main__":
    unittest.main()
