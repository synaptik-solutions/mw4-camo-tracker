"""Header matching must reject blank frames, HUD text and ordinary motion."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import popup_signature as signature


class HeaderTests(unittest.TestCase):
    def test_blank_and_nearly_blank_frames(self):
        for value in (0, 1, 127, 255):
            self.assertIsNone(signature.find_popup_header(np.full((288, 512, 3), value, np.uint8)))

    def test_white_hud_text_is_not_an_unlock(self):
        image = np.zeros((288, 512, 3), np.uint8)
        cv2.putText(image, 'LOCKED', (300, 150), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,255,255), 1)
        self.assertIsNone(signature.find_popup_header(image))

    def test_detail_without_header_is_not_an_unlock(self):
        image = np.random.default_rng(123).integers(0, 256, (288, 512, 3), np.uint8)
        self.assertIsNone(signature.find_popup_header(image))

    def test_lettering_with_yellow_green_backing_at_multiple_sizes(self):
        gray = signature._template
        header = np.stack((gray*.65, gray, gray*.85), axis=2).astype(np.uint8)
        image = np.zeros((288, 512, 3), np.uint8)
        image[120:136, 420:492] = header
        for scale in (1., 1.5, 2., 3.):
            with self.subTest(scale=scale):
                enlarged = cv2.resize(image, None, fx=scale, fy=scale)
                self.assertIsNotNone(signature.find_popup_header(enlarged))


if __name__ == '__main__':
    unittest.main()
