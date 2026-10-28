import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock,patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from capture_pipeline import FrameQueue,PopupFrame
from capture_health import CaptureHealth
from diagnostic_store import DiagnosticStore
from menu_reconcile import parse_menu_result,status_of
from recognition_session import RecognitionSession
from replay import score_events
import detector


def item(value=1,at=None,zone='upper-right'):
    return PopupFrame(zone,np.full((160,240,3),value,np.uint8),(.9,(160,30,65,15)),
                      time.monotonic() if at is None else at,'2026-01-01T00:00:00Z','test')


class DiagnosticsTests(unittest.TestCase):
    def test_snapshot_is_cropped_and_contains_read_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            store=DiagnosticStore(root)
            identity=store.save(item(),['MILITARY CAMO'],.4,'missing-number')
            record=json.loads((Path(root)/identity/'read.json').read_text())
            import cv2
            crop=cv2.imread(str(Path(root)/identity/'popup.png'))
            self.assertLess(crop.shape[0]*crop.shape[1],160*240)
            self.assertEqual(record['reason'],'missing-number')
            self.assertEqual(record['lines'],['MILITARY CAMO'])

    def test_retention_is_bounded_and_does_not_delete_other_folders(self):
        with tempfile.TemporaryDirectory() as root:
            unrelated=Path(root)/'my-files';unrelated.mkdir();(unrelated/'keep.txt').write_text('keep')
            store=DiagnosticStore(root,max_entries=2)
            for index in range(5):store.save(item(index),[str(index)],.2,'uncertain')
            self.assertEqual(len(list(Path(root).glob('*/read.json'))),2)
            self.assertTrue((unrelated/'keep.txt').exists())

    def test_disabled_store_saves_nothing_and_quota_is_enforced(self):
        self.assertIsNone(DiagnosticStore(None).save(item(),[],0.,'failure'))
        with tempfile.TemporaryDirectory() as root:
            store=DiagnosticStore(root,max_bytes=1)
            self.assertIsNone(store.save(item(),[],0.,'failure'))
            self.assertFalse(list(Path(root).glob('*/popup.png')))


class HealthTests(unittest.TestCase):
    def test_unchanged_and_blank_frames_are_distinguished_from_a_stall(self):
        now=[0.];health=CaptureHealth(4,lambda:now[0]);blank=np.zeros((30,40,3),np.uint8)
        health.observe(blank,'upper-right');now[0]=9.
        stats=health.observe(blank,'upper-right')
        self.assertEqual(stats['unchangedForSec'],9.)
        self.assertEqual(stats['blankForSec'],9.)
        self.assertEqual(health.status(1)['lastFrameAgeSec'],0.)
        now[0]=13.
        self.assertTrue(any('not delivered' in text for text in health.status(1)['issues']))
        moving=blank.copy();moving[:,::2]=255
        self.assertEqual(health.observe(moving,'upper-right')['unchangedForSec'],0.)
        self.assertEqual(health.observe(moving,'upper-right')['blankForSec'],0.)

    def test_backlog_is_reported_without_claiming_unlocks_were_missed(self):
        health=CaptureHealth(4)
        status=health.status(2,pending=4,dropped=3)
        self.assertIn('Text recognition is falling behind capture.',status['issues'])
        self.assertEqual(status['droppedFrames'],3)


class RetryTests(unittest.TestCase):
    def make_session(self,reader,store=None):
        emitted=[]
        def emit_unlock(candidate,confidence,zone):emitted.append(candidate.copy());return True
        session=RecognitionSession(object(),reader,detector.parse_candidate,lambda *a:None,
                                   lambda *a:None,emit_unlock,detector.non_camo_banner,store)
        return session,emitted

    def test_retry_reads_new_card_independently_and_recovers(self):
        at=time.monotonic();queue=FrameQueue()
        queue.put(item(2,at+.3))
        reader=Mock(side_effect=[(['UNLOCKED','M4','MILITARY CAMO'],.95),
                                 (['UNLOCKED','Han 86','MILITARY CAMO 2'],.95)])
        store=Mock()
        session,emitted=self.make_session(reader,store)
        result=session.process(item(1,at),queue)
        self.assertEqual([(e['weapon'],e['number']) for e in emitted],[('Han 86',2)])
        self.assertEqual(result['retryAttempt'],1)
        self.assertEqual(session.recovered,1)
        self.assertEqual(store.save.call_count,1)

    def test_retry_budget_and_other_banner_rejection(self):
        at=time.monotonic();queue=FrameQueue(10)
        for i in range(1,5):
            snapshot=item(i+1,at+i*.2)
            queue.put(PopupFrame(snapshot.zone,snapshot.frame,(1.-i*.01,snapshot.header[1]),snapshot.captured_at,snapshot.captured_utc,snapshot.backend))
        reader=Mock(return_value=(['UNLOCKED','MILITARY CAMO'],.9))
        session,emitted=self.make_session(reader)
        session.process(item(0,at),queue)
        self.assertEqual(reader.call_count,3)
        self.assertFalse(emitted)
        reader=Mock(return_value=(['UNLOCKED','M4','WEAPON LEVEL 15','GOLD CAMO'],.99))
        session,emitted=self.make_session(reader)
        session.process(item(),queue)
        self.assertEqual(reader.call_count,1)
        self.assertFalse(emitted)

    def test_unsupported_camo_never_updates_progress(self):
        session,emitted=self.make_session(Mock(return_value=(['UNLOCKED','M4','HULHIARY CAMO'],.99)))
        self.assertFalse(session.process(item())['emitted'])
        self.assertFalse(emitted)


class MenuTests(unittest.TestCase):
    def row(self,text,x=10,y=10):return [[[x,y],[x+100,y],[x+100,y+15],[x,y+15]],text,.99]
    def test_explicit_completion_and_locked_entries_remain_distinct(self):
        rows=parse_menu_result([self.row('Gold UNLOCKED'),self.row('Platinum LOCKED',150),
                               self.row('Military Camo 1 NOT UNLOCKED',300)],'M4')
        statuses={r['name']:r['status'] for r in rows}
        self.assertEqual(statuses,{'Gold':'unlocked','Platinum':'locked','Military Camo 1':'locked'})

    def test_requirement_prose_does_not_confirm_completion(self):
        self.assertIsNone(status_of('COMPLETE ALL CHALLENGES TO UNLOCK'))
        self.assertIsNone(status_of('1/1'))
        rows=parse_menu_result([self.row('Gold'),self.row('Complete all Military camos',10,30)],'M4')
        self.assertEqual(rows[0]['status'],'unclear')

    def test_standalone_status_attaches_only_to_nearest_camo(self):
        rows=parse_menu_result([self.row('Gold'),self.row('Platinum',180),self.row('UNLOCKED',10,30)],'M4')
        self.assertEqual({r['name']:r['status'] for r in rows},{'Gold':'unlocked','Platinum':'unclear'})

    def test_no_unseen_or_unsupported_camos_are_invented(self):
        self.assertEqual(parse_menu_result([self.row('WEAPON LEVEL 15'),self.row('HULHIARY CAMO')],'M4'),[])
        with self.assertRaises(ValueError):parse_menu_result([], 'UNKNOWN')


class ReplayTests(unittest.TestCase):
    def test_scoring_reports_misses_false_events_and_unscored_runs_honestly(self):
        events=[dict(weapon='M4',family='MILITARY CAMO',number=1,sourceTime=5.),dict(weapon='M4',camo='Gold',sourceTime=8.)]
        expected=[dict(weapon='M4',camo='Military Camo 1',start=4,end=6),dict(weapon='Han 86',camo='Gold',start=4,end=10)]
        result=score_events(events,expected)
        self.assertEqual(result['matched'],1)
        self.assertEqual(len(result['missed']),1)
        self.assertEqual(len(result['falseDetections']),1)
        self.assertIsNone(score_events(events,None)['missed'])
        with self.assertRaises(ValueError):score_events([], [dict(weapon='M4',camo='Gold',start=8,end=1)])

    def test_telemetry_is_disabled_before_ocr_sessions_are_created(self):
        from ocr_runtime import create_ocr
        calls=[]
        ort=types.SimpleNamespace(disable_telemetry_events=lambda:calls.append('disabled'))
        rapid=types.SimpleNamespace(RapidOCR=lambda **kwargs:calls.append('sessions') or kwargs)
        with patch.dict(sys.modules,{'onnxruntime':ort,'rapidocr_onnxruntime':rapid}):
            config=create_ocr()
        self.assertEqual(calls,['disabled','sessions'])
        self.assertFalse(config['use_cls'])


if __name__=='__main__':unittest.main()
