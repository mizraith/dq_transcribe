"""Tests for dq_transcribe.server (real server on an OS-chosen port, fake speech engine).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.server import DqTranscribeServer, build_audio_path, render_script
from dq_transcribe.worker import RefineWorker, TranscriptionWorker
from helpers import FakeTranscriber, build_wav_bytes

LOOPBACK_HOST = "127.0.0.1"
EXAMPLE_TIMESTAMP = datetime(2026, 10, 16, 19, 5, 0)
TWO_TURN_PATTERN = [("tone", 2.0), ("silence", 1.5), ("tone", 2.0)]
WAIT_SECONDS = 15.0


class BuildAudioPathTests(unittest.TestCase):
    """Clips are grouped into per-day folders."""

    def test_path_is_inside_day_directory(self) -> None:
        path = build_audio_path("clip", "audio/wav", Path("recordings"), EXAMPLE_TIMESTAMP)
        self.assertEqual(path.parent, Path("recordings") / "2026-10-16")
        self.assertEqual(path.suffix, ".wav")

    def test_unknown_media_type_gets_fallback_extension(self) -> None:
        path = build_audio_path("clip", "application/x-weird", Path("r"), EXAMPLE_TIMESTAMP)
        self.assertEqual(path.suffix, constants.UNKNOWN_AUDIO_EXTENSION)


class ServerTests(unittest.TestCase):
    """End-to-end tests."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.recordings = self.root / "recordings"
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        self.transcriber = FakeTranscriber()
        self.refine_worker = RefineWorker(
            self.database, FakeTranscriber(prefix="refined"), self.recordings, self.root / "scratch", idle_poll_seconds=0.1
        )
        self.worker = TranscriptionWorker(
            self.database,
            self.transcriber,
            self.recordings,
            self.root / "scratch",
            idle_poll_seconds=0.1,
            refine_worker=self.refine_worker,
        )
        self.refine_worker.start()
        self.server = DqTranscribeServer((LOOPBACK_HOST, 0), self.recordings, self.database, self.worker)
        self.worker.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.worker.stop()
        self.refine_worker.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        return connection.getresponse()

    def _upload_clip(self, info: dict | None = None, pattern=TWO_TURN_PATTERN) -> dict:
        headers = {constants.CONTENT_TYPE_HEADER: constants.WAV_UPLOAD_MEDIA_TYPE}
        if info is not None:
            headers[constants.CAPTURE_INFO_HEADER] = json.dumps(info)
        response = self._request("POST", constants.ROUTE_CLIPS, build_wav_bytes(pattern), headers)
        self.assertEqual(response.status, 200)
        return json.loads(response.read())

    def _wait_until_done(self, expected_clips: int) -> list[dict]:
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            clips = json.loads(self._request("GET", constants.ROUTE_CLIPS).read())[constants.RESPONSE_KEY_CLIPS]
            finished = all(
                c["status"] == constants.CLIP_STATUS_DONE and c["refine_status"] == constants.CLIP_STATUS_DONE
                for c in clips
            )
            if len(clips) == expected_clips and finished:
                return clips
            time.sleep(0.1)
        self.fail("clips were not transcribed in time")

    def test_pages_have_no_unfilled_placeholders(self) -> None:
        for route in (constants.ROUTE_HOME, constants.ROUTE_MIC_TEST, constants.ROUTE_APP_SCRIPT,
                      constants.ROUTE_CAPTURE_WORKLET):
            response = self._request("GET", route)
            self.assertEqual(response.status, 200, route)
            self.assertNotIn("${", response.read().decode("utf-8"), route)

    def test_scripts_are_valid_javascript(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.skipTest("node not installed")
        for name in (constants.APP_SCRIPT_FILENAME, constants.CAPTURE_WORKLET_FILENAME):
            path = self.root / name
            path.write_bytes(render_script(name))
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_upload_is_stored_in_day_folder_and_transcribed(self) -> None:
        info = {constants.CAPTURE_INFO_KEY_STARTED_AT: "2026-10-16T10:00:00.000Z",
                constants.CAPTURE_INFO_KEY_ENDED_AT: "2026-10-16T10:00:05.500Z"}
        result = self._upload_clip(info)
        saved = result[constants.RESPONSE_KEY_SAVED_AS]
        self.assertRegex(saved, r"^\d{4}-\d{2}-\d{2}/clip_.*\.wav$")
        self.assertTrue((self.recordings / saved).is_file())
        clips = self._wait_until_done(1)
        self.assertEqual([u["original_text"] for u in clips[0]["utterances"]], ["turn 1", "turn 2"])
        self.assertEqual([u["text"] for u in clips[0]["utterances"]], ["refined 1", "refined 2"])
        self.assertTrue(clips[0]["started_at"].startswith("2026-10-16T10:00:00"))

    def test_close_clips_share_a_group(self) -> None:
        for start, end in (("10:00:00", "10:00:05"), ("10:00:07", "10:00:12"), ("10:01:00", "10:01:05")):
            self._upload_clip({constants.CAPTURE_INFO_KEY_STARTED_AT: f"2026-10-16T{start}.000Z",
                               constants.CAPTURE_INFO_KEY_ENDED_AT: f"2026-10-16T{end}.000Z"})
        clips = sorted(self._wait_until_done(3), key=lambda clip: clip["id"])
        self.assertEqual(clips[0]["group_id"], clips[1]["group_id"])
        self.assertNotEqual(clips[1]["group_id"], clips[2]["group_id"])

    def test_audio_transcript_export_edit_and_reprocess(self) -> None:
        clip_id = self._upload_clip()[constants.RESPONSE_KEY_CLIP_ID]
        clips = self._wait_until_done(1)
        audio = self._request("GET", f"{constants.ROUTE_CLIPS}/{clip_id}{constants.CLIP_AUDIO_SUFFIX}")
        self.assertEqual(audio.status, 200)
        self.assertEqual(audio.read()[:4], b"RIFF")

        utterance_id = clips[0]["utterances"][0]["id"]
        edit = self._request("POST", f"{constants.ROUTE_UTTERANCES}/{utterance_id}",
                             json.dumps({constants.REQUEST_KEY_TEXT: "edited"}).encode())
        self.assertEqual(edit.status, 200)
        bad = self._request("POST", f"{constants.ROUTE_UTTERANCES}/{utterance_id}", b"not json")
        self.assertEqual(bad.status, 400)

        transcript = self._request("GET", constants.ROUTE_TRANSCRIPT_TEXT).read().decode()
        self.assertIn("edited", transcript)
        export = json.loads(self._request("GET", constants.ROUTE_EXPORT).read())
        self.assertTrue(export)

        reprocess = self._request("POST", f"{constants.ROUTE_CLIPS}/{clip_id}{constants.CLIP_REPROCESS_SUFFIX}", b"x")
        self.assertEqual(reprocess.status, 200)
        self._wait_until_done(1)

    def test_trash_restore_and_delete_clip(self) -> None:
        result = self._upload_clip()
        clip_id = result[constants.RESPONSE_KEY_CLIP_ID]
        audio_file = self.recordings / result[constants.RESPONSE_KEY_SAVED_AS]
        self._wait_until_done(1)
        base = f"{constants.ROUTE_CLIPS}/{clip_id}"
        trash_list = f"{constants.ROUTE_CLIPS}?{constants.QUERY_KEY_VIEW}={constants.VIEW_TRASH}"

        self.assertEqual(self._request("POST", base + constants.CLIP_DELETE_SUFFIX, b"x").status, 404)
        self.assertEqual(self._request("POST", base + constants.CLIP_TRASH_SUFFIX, b"x").status, 200)
        listed = json.loads(self._request("GET", constants.ROUTE_CLIPS).read())[constants.RESPONSE_KEY_CLIPS]
        trashed = json.loads(self._request("GET", trash_list).read())[constants.RESPONSE_KEY_CLIPS]
        self.assertEqual((listed, [c["id"] for c in trashed]), ([], [clip_id]))

        self.assertEqual(self._request("POST", base + constants.CLIP_RESTORE_SUFFIX, b"x").status, 200)
        self.assertEqual(self._request("POST", base + constants.CLIP_TRASH_SUFFIX, b"x").status, 200)
        self.assertEqual(self._request("POST", base + constants.CLIP_DELETE_SUFFIX, b"x").status, 200)
        self.assertFalse(audio_file.exists())
        self.assertEqual(self._request("GET", base + constants.CLIP_AUDIO_SUFFIX).status, 404)

    def _post_json(self, path: str, payload: dict):
        return self._request("POST", path, json.dumps(payload).encode(), {constants.CONTENT_TYPE_HEADER: constants.JSON_CONTENT_TYPE})

    def test_meets_file_new_clips_and_filter_the_list(self) -> None:
        early_clip = self._upload_clip()[constants.RESPONSE_KEY_CLIP_ID]  # before any meet exists
        response = self._post_json(constants.ROUTE_MEETS, {constants.REQUEST_KEY_MEET_NAME: "Candy Meet",
                                                           constants.REQUEST_KEY_MEET_START_DATE: "2026-10-16"})
        meet_id = json.loads(response.read())[constants.RESPONSE_KEY_MEET_ID]
        meets = json.loads(self._request("GET", constants.ROUTE_MEETS).read())
        self.assertEqual(meets[constants.RESPONSE_KEY_ACTIVE_MEET_ID], meet_id)

        saved = self._upload_clip()[constants.RESPONSE_KEY_SAVED_AS]
        self.assertTrue(saved.startswith("2026-10-16_candy-meet/"), saved)
        listed = json.loads(self._request("GET", constants.ROUTE_CLIPS).read())[constants.RESPONSE_KEY_CLIPS]
        self.assertEqual(len(listed), 1)  # only the active meet's clip

        assigned = self._post_json(f"{constants.ROUTE_MEETS}/{meet_id}{constants.MEET_ASSIGN_SUFFIX}",
                                   {constants.REQUEST_KEY_CLIP_IDS: [early_clip]})
        self.assertEqual(json.loads(assigned.read())[constants.RESPONSE_KEY_COUNT], 1)
        listed = json.loads(self._request("GET", constants.ROUTE_CLIPS).read())[constants.RESPONSE_KEY_CLIPS]
        self.assertEqual(len(listed), 2)

        self._request("POST", f"{constants.ROUTE_MEETS}/{constants.NO_MEET_ID}{constants.MEET_ACTIVATE_SUFFIX}", b"x").read()
        self.assertIsNone(json.loads(self._request("GET", constants.ROUTE_MEETS).read())[constants.RESPONSE_KEY_ACTIVE_MEET_ID])
        self.assertEqual(self._upload_clip()[constants.RESPONSE_KEY_SAVED_AS].count("/"), 1)  # day folder only

    def test_meet_validation(self) -> None:
        bad_date = self._post_json(constants.ROUTE_MEETS, {constants.REQUEST_KEY_MEET_NAME: "X",
                                                           constants.REQUEST_KEY_MEET_START_DATE: "Friday"})
        self.assertEqual(bad_date.status, 400)
        no_name = self._post_json(constants.ROUTE_MEETS, {constants.REQUEST_KEY_MEET_NAME: " ",
                                                          constants.REQUEST_KEY_MEET_START_DATE: "2026-10-16"})
        self.assertEqual(no_name.status, 400)
        missing = self._request("POST", f"{constants.ROUTE_MEETS}/999{constants.MEET_ACTIVATE_SUFFIX}", b"x")
        self.assertEqual(missing.status, 404)

    def test_non_wav_upload_is_rejected(self) -> None:
        response = self._request("POST", constants.ROUTE_CLIPS, b"abc",
                                 {constants.CONTENT_TYPE_HEADER: "audio/webm"})
        self.assertEqual(response.status, 415)
        response = self._request("POST", constants.ROUTE_CLIPS, b"not a wav",
                                 {constants.CONTENT_TYPE_HEADER: constants.WAV_UPLOAD_MEDIA_TYPE})
        self.assertEqual(response.status, 400)

    def test_legacy_mic_test_upload_saves_file(self) -> None:
        response = self._request("POST", constants.ROUTE_UPLOAD_RECORDING, b"fake",
                                 {constants.CONTENT_TYPE_HEADER: "audio/webm;codecs=opus"})
        result = json.loads(response.read())
        self.assertEqual((self.recordings / result[constants.RESPONSE_KEY_SAVED_AS]).read_bytes(), b"fake")

    def test_unknown_route_is_404(self) -> None:
        self.assertEqual(self._request("GET", "/nope").status, 404)
        self.assertEqual(self._request("POST", "/nope", b"x").status, 404)


if __name__ == "__main__":
    unittest.main()
