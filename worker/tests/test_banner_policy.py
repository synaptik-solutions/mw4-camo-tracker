"""Run the real entrypoint/policy hooks without starting OCR or network refreshes."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BannerPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core = load('isolated_core','detector.py')
        class Matcher:
            ready = False
            def start_async(self): pass
            def match_frame(self,image): return None
        backend = types.SimpleNamespace(mss=type('Capture',(),{}))
        references = types.SimpleNamespace(CamoReferenceMatcher=Matcher)
        with patch.dict(sys.modules,{'detector':core,'capture_backend':backend,'camo_reference':references}):
            cls.entry = load('isolated_entry','detector_entry.py')
        with patch.dict(sys.modules,{'detector_entry':cls.entry}):
            cls.policy = load('isolated_policy','recognition_policy.py')
        cls.core = core

    def setUp(self):
        self.entry._prepare_frame(None,'upper-right',.95,'fake')

    def test_other_banner_types_never_become_camos(self):
        for label in ['WEAPON LEVEL 15','LEVEL UP','RANK UP','BATTLE PASS',
                      'ATTACHMENT','XP TOKEN','NEW UNLOCK','KILL STREAK','BEST PLAY']:
            with self.subTest(label=label):
                self.assertIsNone(self.core.parse_candidate(['UNLOCKED','M4',label,'GOLD CAMO']))

    def test_actual_camos_still_parse(self):
        for title in ['MILITARY CAMO 1','GOLD CAMO','PLATINUM CAMO','HARMONIC BREAK CAMO']:
            with self.subTest(title=title):
                candidate = self.core.parse_candidate(['UNLOCKED','M4',title])
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate['weapon'],'M4')

    def test_image_similarity_without_camo_text_cannot_create_unlock(self):
        import time
        self.entry._state['matches']['upper-right'] = {'name':'Gold','score':.99}
        self.entry._state['match_times']['upper-right'] = time.monotonic()
        self.assertIsNone(self.core.parse_candidate(['UNLOCKED','M4','RED DOT OPTIC']))

    def test_preparing_next_card_clears_previous_image_vote(self):
        self.entry._state['matches']['upper-right'] = {'name':'Gold','score':.99}
        self.entry._prepare_frame(None,'upper-right',.95,'fake')
        self.assertIsNone(self.entry._fresh_match('upper-right'))

    def test_capture_api_is_not_wrapped_with_image_matching(self):
        self.assertNotIn('grab',self.entry.capture_mss.mss.__dict__)


if __name__ == '__main__':
    unittest.main()
