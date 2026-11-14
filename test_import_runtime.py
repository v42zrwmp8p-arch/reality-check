"""Reproduce stale imported helpers in an existing Python process."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tiktok_ui import import_report

ROOT = Path(__file__).resolve().parent


class RuntimeChecks(unittest.TestCase):
    def test_mixed_release_reloads_helpers_once_and_preserves_shared_queue(self):
        script = '''
from unittest.mock import patch
import analysis_core, market_data, case_analysis, charts, asset_resolution, target_extraction, tracker_core, tracker_ui, tiktok_import, photo_import, video_pipeline, tiktok_ui
from import_runtime import import_flow
modules = [analysis_core, market_data, case_analysis, charts, asset_resolution, target_extraction, tracker_core, tracker_ui, tiktok_import, photo_import, video_pipeline, tiktok_ui]
pool, slots, tasks, lock = (video_pipeline._POOL, video_pipeline._SLOTS,
                          video_pipeline._TASKS, video_pipeline._LOCK)
old = lambda *args: 'No supported stock or crypto detected'
tiktok_ui.tiktok_mode = old
tiktok_ui.IMPORT_VERSION = 'old-loaded-ui'
video_pipeline.ENGINE_VERSION = 'groq-whisper-ocr-v1'
flow = import_flow('2026-11-14.13')
assert flow is not old
assert flow is tiktok_ui.tiktok_mode
assert all(module.IMPORT_VERSION == '2026-11-14.13' for module in modules)
assert video_pipeline.ENGINE_VERSION == 'groq-whisper-ocr-v8'
assert video_pipeline._POOL is pool
assert video_pipeline._SLOTS is slots
assert video_pipeline._TASKS is tasks
assert video_pipeline._LOCK is lock
assert tiktok_ui.ENGINE_VERSION == video_pipeline.ENGINE_VERSION
assert tiktok_ui.ImportProblem is tiktok_import.ImportProblem
assert video_pipeline.GroqClient is tiktok_import.GroqClient
assert video_pipeline.read_photo_post is photo_import.read_photo_post
assert photo_import.ImportProblem is tiktok_import.ImportProblem
assert tracker_ui.prediction_record is tracker_core.prediction_record
assert tracker_core.provider_symbol is market_data.provider_symbol
assert market_data.validated_split_review is analysis_core.validated_split_review
assert tracker_core.validated_split_review is analysis_core.validated_split_review
assert tracker_core.analyse_comparisons is case_analysis.analyse_comparisons
assert tiktok_ui.analyse_comparisons is case_analysis.analyse_comparisons
assert tiktok_import.provider_symbol is market_data.provider_symbol
assert tiktok_import.recover_multiple is target_extraction.recover_multiple
with patch('import_runtime.importlib.reload', side_effect=AssertionError('ordinary rerun must not reload')):
    assert import_flow('2026-11-14.13') is flow
print('mixed-release regression passed')
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mixed-release regression passed", result.stdout)

    def test_incomplete_deployment_does_not_silently_use_incompatible_helpers(self):
        script = '''
from import_runtime import import_flow
try:
    import_flow('future-not-deployed')
except RuntimeError as error:
    assert 'update is still loading' in str(error)
else:
    raise AssertionError('incompatible helpers must not run')
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostic_report_excludes_credentials_tasks_and_private_edits(self):
        report = import_report({"url": "https://www.tiktok.com/@fixture/video/123456",
                                "engine": "groq-whisper-ocr-v8", "transcript": "public source",
                                "drafts": [{"claim": "private edited claim"}], "raw_drafts": [],
                                "api_key": "fixture-secret-key", "task": object(),
                                "extraction_checks": [{"detected_assets": []}]})
        text = json.dumps(report)
        self.assertNotIn("fixture-secret-key", text)
        self.assertNotIn("private edited claim", text)
        self.assertNotIn('"task"', text)
        self.assertEqual(report["extraction_result_count"], 0)
        self.assertEqual(report["review_list_count"], 1)


if __name__ == "__main__":
    unittest.main()
