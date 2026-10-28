"""Recognition regressions reproduced from an unlock recording; no game capture needed."""
import ast
from collections import Counter
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detector


class RecognitionTests(unittest.TestCase):
    def test_missing_digit_is_not_a_named_camo(self):
        self.assertIsNone(detector.parse_candidate([
            'UNLOCKED', '.50GS', 'MILITARY CAMO', 'HULHIARY CAMO']))

    def test_split_focused_text_retains_digit_and_weapon(self):
        candidate = detector.parse_candidate([
            'UNLOCKED', '55', 'GS', 'MILITARY', 'CAMO', '1', '.50GS', 'MILITARY CAMO'])
        self.assertEqual((candidate['weapon'], candidate['family'], candidate['number']),
                         ('.50 GS', 'MILITARY CAMO', 1))

    def test_family_letter_confusion(self):
        candidate = detector.parse_candidate(['UNLOCKED', '.50GS', 'MILIIARY CAMO1'])
        self.assertEqual(candidate['number'], 1)

    def test_invalid_digit_does_not_mask_later_valid_read(self):
        self.assertIsNone(detector.parse_candidate(['MILITARY CAMO 55']))
        candidate = detector.parse_candidate(['MILITARY CAMO 55', '.50GS', 'MILITARY CAMO 1'])
        self.assertEqual(candidate['number'], 1)

    def test_other_named_camos_still_parse(self):
        self.assertEqual(detector.parse_candidate(['GOLD CAMO', '.50GS'])['camo'], 'GOLD')

    def test_motion_rearms_exhausted_bursts(self):
        # Execute the production trigger block with deterministic time. Under the old
        # trigger, scans stop after the quota and a later three-second popup is missed.
        tree = ast.parse(inspect.getsource(detector.main))
        trigger = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                       and ast.unparse(n.test) == 'visual_change or activity_spike or popup_match')
        code = compile(ast.Module(body=[trigger], type_ignores=[]), '<trigger>', 'exec')
        zone = dict(burst_until=0., burst_attempts=0, next_burst_ocr=0., last_ocr=-5.)
        reads = []
        for tick in range(240):
            now = tick / 4
            popup = now < 6 or 14 <= now <= 17
            exec(code, dict(zone=zone, now=now, visual_change=True,
                            activity_spike=False, popup_match=popup, Counter=Counter))
            due = (now <= zone['burst_until'] and zone['burst_attempts'] < (12 if popup else 9)
                   and now >= zone['next_burst_ocr'])
            if due or now-zone['last_ocr'] >= 5:
                reads.append(now)
                zone['last_ocr'] = now
                if due:
                    zone['burst_attempts'] += 1
                    zone['next_burst_ocr'] = now + (.16 if popup else .20)
        self.assertTrue(any(14 <= now <= 17 for now in reads))
        self.assertLessEqual(max(b-a for a,b in zip(reads, reads[1:])), .25)


if __name__ == '__main__':
    unittest.main()
