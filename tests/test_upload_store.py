from io import BytesIO
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool.upload_store import UploadStore
from subtitle_tool.web_security import RequestError


class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = UploadStore(self.root / "uploads", reserve_bytes=0)

    def test_truncated_upload_is_removed(self):
        with self.assertRaises(RequestError):
            self.store.receive(BytesIO(b"abc"), 5, "video.mp4")
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_upload_is_retained_as_job_input_and_temporary_copy_removed(self):
        upload = self.store.receive(BytesIO(b"video"), 5, "../../video.mp4")
        retained = self.store.retain(upload, self.root / "output" / ".inputs" / "job")
        self.assertEqual(retained.read_bytes(), b"video")
        self.assertFalse(upload.exists())
        self.assertEqual(retained.name, "video.mp4")

    def test_cleanup_preserves_recent_and_claimed_files(self):
        import os
        old = self.store.receive(BytesIO(b"old"), 3, "old.mp4")
        recent = self.store.receive(BytesIO(b"new"), 3, "new.mp4")
        held = self.store.receive(BytesIO(b"held"), 4, "held.mp4")
        old_time = time.time() - 90000
        os.utime(old.parent, (old_time, old_time))
        os.utime(held.parent, (old_time, old_time))
        self.store.claim(held)
        self.store.cleanup()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(held.exists())

    def test_legacy_multipart_streams_video_without_boundary_bytes(self):
        content = b"\x00video\r\n--abc-not-a-boundary\xff"
        body = (b'--abc\r\nContent-Disposition: form-data; name="video"; filename="video.mp4"\r\n'
                b'Content-Type: video/mp4\r\n\r\n' + content + b'\r\n--abc--\r\n')
        result = self.store.receive_multipart(BytesIO(body), len(body), "multipart/form-data; boundary=abc")
        self.assertEqual(result.read_bytes(), content)

    def test_cleanup_never_follows_symlink_to_other_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.mp4").write_bytes(b"keep")
        self.store.root.mkdir()
        (self.store.root / "escape").symlink_to(outside, target_is_directory=True)
        self.store.cleanup(max_age_seconds=-1)
        self.assertTrue((outside / "keep.mp4").exists())


if __name__ == "__main__":
    unittest.main()
