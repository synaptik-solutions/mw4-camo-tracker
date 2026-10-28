"""Recognition regressions reproduced from an unlock recording; no game capture needed."""
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

    def test_clear_popup_uses_one_small_ocr_pass(self):
        import numpy as np
        from unittest.mock import Mock, patch
        box = [[0,0],[50,0],[50,20],[0,20]]
        ocr = Mock(return_value=([[box, text, .95] for text in ['UNLOCKED','M4','MILITARY CAMO 1']], None))
        frame = np.zeros((288,512,3), np.uint8)
        with patch.object(detector,'find_popup_header',return_value=(.95,(430,122,72,16))):
            lines, confidence = detector.read_frame_variants(ocr,frame)
        self.assertEqual(ocr.call_count,1)
        image = ocr.call_args.args[0]
        self.assertLess(image.shape[0]*image.shape[1], frame.shape[0]*frame.shape[1])
        self.assertEqual(detector.parse_candidate(lines)['number'],1)

    def test_other_banner_stops_after_first_read_and_is_rejected(self):
        import numpy as np
        from unittest.mock import Mock, patch
        box = [[0,0],[50,0],[50,20],[0,20]]
        ocr = Mock(return_value=([[box,text,.95] for text in ['UNLOCKED','M4','WEAPONLEVEL 15','GOLD CAMO']],None))
        with patch.object(detector,'find_popup_header',return_value=(.95,(430,122,72,16))):
            lines, _ = detector.read_frame_variants(ocr,np.zeros((288,512,3),np.uint8))
        self.assertEqual(ocr.call_count,1)
        self.assertIsNone(detector.parse_candidate(lines))

    def test_no_header_does_not_run_ocr(self):
        import numpy as np
        from unittest.mock import Mock, patch
        ocr = Mock()
        with patch.object(detector,'find_popup_header',return_value=None):
            self.assertEqual(detector.read_frame_variants(ocr,np.zeros((40,60,3),np.uint8)),([],0.))
        ocr.assert_not_called()

    def test_full_zone_fallback_excludes_other_banner_text(self):
        import numpy as np
        from unittest.mock import Mock, patch
        box = [[0,0],[30,0],[30,10],[0,10]]
        inside = [[330,140],[370,140],[370,155],[330,155]]
        title = [[box,'MILITARY CAMO 1',.95]]
        ocr = Mock(side_effect=[(title,None),(title,None),
                   ([[inside,'M4',.95],[box,'MAR-9',.99],[box,'WEAPON LEVEL 55',.99]],None)])
        with patch.object(detector,'find_popup_header',return_value=(.95,(430,122,72,16))):
            lines, _ = detector.read_frame_variants(ocr,np.zeros((288,512,3),np.uint8))
        self.assertEqual(ocr.call_count,3)
        self.assertNotIn('MAR-9',lines)
        self.assertNotIn('WEAPON LEVEL 55',lines)
        self.assertEqual(detector.parse_candidate(lines)['weapon'],'M4')


if __name__ == '__main__':
    unittest.main()

