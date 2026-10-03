from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from subtitle_tool import web
from subtitle_tool.job_store import JobStore


class RetainedInputTests(unittest.TestCase):
    def test_cleanup_preserves_references_from_old_and_resumed_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / '.inputs' / 'original' / 'video.mp4'
            orphan = root / '.inputs' / 'orphan' / 'video.mp4'
            for file in (original, orphan):
                file.parent.mkdir(parents=True)
                file.write_bytes(b'video')
            store = JobStore(root / 'jobs.sqlite3')
            store.save({'id': 'resumed', 'status': 'failed', 'payload': {'input': str(original)}})
            with patch.object(web, 'JOB_STORE', store), patch.dict(web.JOBS, {}, clear=True):
                summary = web.cache_summary(root)['retainedInputs']
                self.assertEqual(summary['bytes'], 10)
                self.assertEqual(summary['reclaimableBytes'], 5)
                result = web.clear_retained_inputs(root)
                self.assertEqual(result['removedFiles'], 1)
                self.assertTrue(original.exists())
                self.assertFalse(orphan.exists())
                store.clear_finished()
                web.clear_retained_inputs(root)
                self.assertFalse(original.exists())

    def test_cleanup_refuses_active_jobs_and_symlink_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(web, 'JOB_STORE', None), patch.dict(web.JOBS, {'active': web.JobState('active')}, clear=True):
                with self.assertRaises(web.RequestError):
                    web.clear_retained_inputs(root)
            outside = root / 'outside'
            outside.mkdir()
            important = outside / 'video.mp4'
            important.write_bytes(b'keep')
            (root / '.inputs').symlink_to(outside, target_is_directory=True)
            with patch.object(web, 'JOB_STORE', None), patch.dict(web.JOBS, {}, clear=True):
                with self.assertRaises(web.RequestError):
                    web.clear_retained_inputs(root)
            self.assertEqual(important.read_bytes(), b'keep')

    def test_cleanup_does_not_follow_nested_symlinks_and_protects_render_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keep = root / '.inputs' / 'job' / 'video.mp4'
            keep.parent.mkdir(parents=True)
            keep.write_bytes(b'keep')
            outside = root / 'outside'
            outside.mkdir()
            private = outside / 'private.mp4'
            private.write_bytes(b'private')
            (keep.parent / 'link.mp4').symlink_to(private)
            (root / '.inputs' / 'linked').symlink_to(outside, target_is_directory=True)
            job = web.JobState('render', status='succeeded', payload={'videoPath': str(keep)})
            with patch.object(web, 'JOB_STORE', None), patch.dict(web.JOBS, {'render': job}, clear=True):
                result = web.clear_retained_inputs(root)
                self.assertEqual(result['removedFiles'], 0)
            self.assertTrue(keep.exists())
            self.assertEqual(private.read_bytes(), b'private')
