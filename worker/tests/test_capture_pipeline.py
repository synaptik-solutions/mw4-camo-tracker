import threading
import time
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_pipeline import CapturePump, FrameQueue, PopupFrame, MIN_CAPTURE_FPS
import detector


class PipelineTests(unittest.TestCase):
    def test_queue_is_bounded_and_keeps_recent_frames(self):
        queue = FrameQueue(4)
        for i in range(20):
            queue.put(PopupFrame('upper-right', i, (.9, ()), float(i), '', 'fake'))
        self.assertEqual(len(queue), 4)
        self.assertEqual(queue.dropped, 16)
        self.assertEqual([queue.get().frame for _ in range(4)], [16,17,18,19])

    def test_different_banners_in_same_time_slot_are_both_kept(self):
        queue = FrameQueue(4)
        queue.put(PopupFrame('upper-right',1,(.9,()),.1,'','fake'))
        queue.put(PopupFrame('upper-right',2,(.9,()),.2,'','fake'))
        self.assertEqual([queue.get().frame,queue.get().frame],[1,2])

    def test_default_buffer_retains_short_popup_amid_following_frames(self):
        queue = FrameQueue()
        for i in range(100):
            queue.put(PopupFrame('upper-right', i, (.9, ()), i / 10., '', 'fake'))
        self.assertEqual(queue.dropped, 0)
        self.assertEqual(queue.get().frame, 0)
        self.assertEqual(len(queue), 99)

    def test_queue_memory_budget_and_byte_accounting(self):
        frame = np.zeros((10,10,3), np.uint8)
        queue = FrameQueue(capacity=100, max_bytes=650)
        for i in range(3):
            queue.put(PopupFrame('upper-right', frame+i, (.9, ()), i, '', 'fake'))
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue.pending_bytes, 600)
        self.assertEqual(queue.dropped, 1)
        self.assertEqual(int(queue.get().frame[0,0,0]), 1)
        self.assertEqual(queue.pending_bytes, 300)
        queue.get()
        self.assertEqual(queue.pending_bytes, 0)
        queue.put(PopupFrame('upper-right', np.zeros((20,20,3), np.uint8), (.9,()), 4, '', 'fake'))
        self.assertEqual(len(queue), 0)
        self.assertEqual(queue.dropped, 2)

    def test_identical_pending_cards_coalesce_across_time_slots(self):
        queue = FrameQueue()
        for i in range(20):
            queue.put(PopupFrame('upper-right', np.zeros((10,10,3),np.uint8), (.9,()), float(i), '', 'fake'))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.get().captured_at, 0.)

    def test_capture_rate_is_independent_of_slow_ocr_setting(self):
        pump = CapturePump(None, None, None, fps=2)
        self.assertEqual(1. / pump.interval, MIN_CAPTURE_FPS)

    def test_closed_queue_wakes_waiting_reader(self):
        queue = FrameQueue()
        results = []
        thread = threading.Thread(target=lambda: results.append(queue.get(5)))
        thread.start()
        queue.close()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])

    def test_capture_continues_while_ocr_is_busy_and_different_banners_stay_separate(self):
        first_read = threading.Event()
        second_captured = threading.Event()
        later_frames_captured = threading.Event()
        calls, instances, events = [], [], []

        class FakeCapture:
            monitors = [dict(left=0,top=0,width=40,height=30)] * 2
            backend = 'fake'
            def __init__(self):
                self.owner = threading.get_ident()
                self.count = 0
                self.closed = False
                instances.append(self)
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.closed = True
                calls.append(threading.get_ident())
            def grab(self, region):
                calls.append(threading.get_ident())
                self.count += 1
                if self.count == 1:
                    value = 1
                elif self.count == 2:
                    if not first_read.wait(2):
                        raise RuntimeError('Consumer never began OCR')
                    value = 99  # unrelated rank/weapon-level banner
                elif self.count == 3:
                    value = 2
                    second_captured.set()
                elif self.count <= 10:
                    value = 90 + self.count
                    if self.count == 10:
                        later_frames_captured.set()
                else:
                    value = 0
                return np.full((30,40,3), value, np.uint8)

        def inspect_frame(frame, zone):
            value = int(frame[0,0,0])
            header = (.9,(10,2,10,4)) if value in (1,2) or value >= 90 else None
            return header, dict(mean=value,stddev=2.,activity=0.,popupScore=.9 if header else 0.)

        def read_frame(ocr, frame, aggressive=False):
            value = int(frame[0,0,0])
            if value == 1:
                first_read.set()
                self.assertTrue(second_captured.wait(2), 'Capture paused during slow OCR')
                self.assertTrue(later_frames_captured.wait(3), 'Capture did not retain a disappeared popup')
            self.assertTrue(value in (1,2) or value >= 90)
            self.assertLess(frame.shape[1], 40, 'Queue should hold the cropped popup card')
            if value >= 90:
                return ['UNLOCKED','M4','WEAPON LEVEL 15'], .95
            return ['UNLOCKED','M4',f'MILITARY CAMO {value}'], .95

        def emit(payload):
            events.append(payload)
            if payload.get('type') == 'unlock' and payload.get('number') == 2:
                raise KeyboardInterrupt

        argv = ['detector','--fps','6','--zones','[{"name":"upper-right","x":0,"y":0,"width":1,"height":1}]']
        with patch.object(sys,'argv',argv), patch.object(detector.mss,'mss',FakeCapture), \
             patch.object(detector,'RapidOCR',return_value=object()), \
             patch.object(detector,'inspect_capture_frame',side_effect=inspect_frame), \
             patch.object(detector,'read_frame_variants',side_effect=read_frame), \
             patch.object(detector,'emit',side_effect=emit):
            with self.assertRaises(KeyboardInterrupt):
                detector.main()
        unlocks = [event for event in events if event.get('type') == 'unlock']
        self.assertEqual([(e['weapon'],e['number']) for e in unlocks], [('M4',1),('M4',2)])
        self.assertTrue(instances[0].closed)
        self.assertTrue(all(owner == instances[0].owner for owner in calls))
        self.assertNotEqual(instances[0].owner, threading.get_ident())
        self.assertFalse(any(t.name == 'popup-capture' for t in threading.enumerate()))

    def test_saved_popup_is_read_after_old_fifteen_second_expiry(self):
        queue = FrameQueue()
        captured = '2026-10-28T10:00:00Z'
        queue.put(PopupFrame('upper-right', np.ones((30,40,3),np.uint8),
                             (.9,(10,2,10,4)), time.monotonic()-30., captured, 'fake'))
        class SavedPump:
            monitors = [dict(left=0,top=0,width=40,height=30)] * 2
            interval = .1
            def __init__(self,*args): self.queue=queue
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def check_error(self): pass
            def configure(self,zones): pass
            def snapshot(self):
                raise AssertionError('An already-captured popup expired without OCR')
        events=[]
        def emit(payload):
            events.append(payload)
            if payload.get('type')=='unlock': raise KeyboardInterrupt
        argv=['detector','--zones','[{"name":"upper-right","x":0,"y":0,"width":1,"height":1}]']
        with patch.object(sys,'argv',argv), patch.object(detector,'CapturePump',SavedPump), \
             patch.object(detector,'RapidOCR',return_value=object()), \
             patch.object(detector,'read_frame_variants',return_value=(['UNLOCKED','M4','MILITARY CAMO 1'],.95)), \
             patch.object(detector,'emit',side_effect=emit):
            with self.assertRaises(KeyboardInterrupt): detector.main()
        unlock=next(e for e in events if e.get('type')=='unlock')
        self.assertEqual(unlock['timestamp'],captured)
        self.assertEqual(unlock['number'],1)

    def test_capture_failure_is_reported_and_owner_closes(self):
        closed = threading.Event()
        class Broken:
            monitors = [{}]
            def __enter__(self): return self
            def __exit__(self,*_): closed.set()
            def grab(self,region): raise ValueError('camera failed')
        with CapturePump(Broken, lambda *a:None, lambda:'', fps=4) as pump:
            pump.configure([{'name':'upper-right','region':{}}])
            self.assertTrue(closed.wait(1))
            with self.assertRaisesRegex(RuntimeError,'camera failed'):
                pump.check_error()


if __name__ == '__main__':
    unittest.main()
