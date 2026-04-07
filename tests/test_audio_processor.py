"""Tests for audio_processor module."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from src.audio_processor import (
    concatenate_with_crossfade,
    format_timestamp,
    get_duration,
    normalize_audio,
)


class TestFormatTimestamp(unittest.TestCase):
    """Test format_timestamp() outputs."""

    def test_zero(self) -> None:
        self.assertEqual(format_timestamp(0), "0:00")

    def test_under_minute(self) -> None:
        self.assertEqual(format_timestamp(45), "0:45")

    def test_minutes_and_seconds(self) -> None:
        self.assertEqual(format_timestamp(195), "3:15")

    def test_one_hour(self) -> None:
        self.assertEqual(format_timestamp(3600), "1:00:00")

    def test_over_one_hour(self) -> None:
        self.assertEqual(format_timestamp(3723), "1:02:03")

    def test_fractional_seconds_truncated(self) -> None:
        # Float input — should truncate to int
        self.assertEqual(format_timestamp(60.9), "1:00")


class TestGetDuration(unittest.TestCase):
    """Test get_duration() via mocked subprocess."""

    @patch("src.audio_processor.subprocess.run")
    def test_returns_float(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="182.456\n", stderr="")
        dur = get_duration(Path("fake.mp3"))
        self.assertAlmostEqual(dur, 182.456)

    @patch("src.audio_processor.subprocess.run")
    def test_raises_on_ffprobe_error(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such file")
        with self.assertRaises(RuntimeError):
            get_duration(Path("missing.mp3"))


class TestNormalizeAudio(unittest.TestCase):
    """Test normalize_audio() subprocess invocation."""

    @patch("src.audio_processor.subprocess.run")
    def test_calls_ffmpeg(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        normalize_audio(Path("in.mp3"), Path("out.mp3"))
        cmd = mock_run.call_args[0][0]
        self.assertIn("ffmpeg", cmd)
        self.assertIn("loudnorm", " ".join(cmd))

    @patch("src.audio_processor.subprocess.run")
    def test_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error text")
        with self.assertRaises(RuntimeError):
            normalize_audio(Path("in.mp3"), Path("out.mp3"))


class TestConcatenateWithCrossfade(unittest.TestCase):
    """Test concatenate_with_crossfade() logic with mocked FFmpeg calls."""

    def _make_mock_run(self, duration: float = 200.0) -> MagicMock:
        """Return a mock subprocess.run that handles ffprobe duration queries."""

        def side_effect(cmd, **kwargs):  # type: ignore[no-untyped-def]
            # ffprobe call
            if "ffprobe" in cmd:
                return MagicMock(returncode=0, stdout=f"{duration}\n", stderr="")
            # ffmpeg call
            return MagicMock(returncode=0, stdout="", stderr="")

        mock = MagicMock(side_effect=side_effect)
        return mock

    @patch("src.audio_processor.subprocess.run")
    def test_returns_path_and_timestamps(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = self._make_mock_run(200.0).side_effect

        tracks = [Path(f"track_{i}.mp3") for i in range(3)]
        out = Path("output/temp/mix_test.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)

        result_path, timestamps = concatenate_with_crossfade(
            tracks=tracks,
            output_path=out,
            crossfade_sec=3,
            target_duration=3600,
        )

        self.assertIsInstance(result_path, Path)
        self.assertIsInstance(timestamps, list)
        self.assertGreater(len(timestamps), 0)

    @patch("src.audio_processor.subprocess.run")
    def test_timestamp_format(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = self._make_mock_run(200.0).side_effect

        tracks = [Path(f"track_{i}.mp3") for i in range(2)]
        out = Path("output/temp/mix_fmt_test.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)

        _, timestamps = concatenate_with_crossfade(
            tracks=tracks,
            output_path=out,
            crossfade_sec=3,
            target_duration=500,
        )

        for time_str, label in timestamps:
            # Timestamps should be M:SS or H:MM:SS format
            self.assertRegex(time_str, r"^\d+:\d{2}(:\d{2})?$")
            self.assertTrue(label.startswith("Track"))

    @patch("src.audio_processor.subprocess.run")
    def test_empty_tracks_raises(self, mock_run: MagicMock) -> None:
        with self.assertRaises(ValueError):
            concatenate_with_crossfade(
                tracks=[],
                output_path=Path("out.mp3"),
                crossfade_sec=3,
                target_duration=3600,
            )


if __name__ == "__main__":
    unittest.main()
