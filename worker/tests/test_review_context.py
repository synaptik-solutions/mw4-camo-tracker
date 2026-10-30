from pathlib import Path
import sys
import unittest
import base64
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from capture_pipeline import CapturePump,review_capture_region,extract_detection_frame
from completion_banner import review_image

class ReviewContextTests(unittest.TestCase):
    def test_same_frame_icon_above_detector_is_preserved_at_multiple_resolutions(self):
        for width,height in ((1280,720),(1920,1080),(3840,2160)):
            with self.subTest(width=width):
                monitor=dict(left=0,top=0,width=width,height=height)
                region=dict(left=round(width*.27),top=round(height*.25),width=round(width*.46),height=round(height*.5))
                source=np.zeros((height,width,3),np.uint8)
                # The observed center icon is above the original detector's top edge.
                x0,x1=round(width*.47),round(width*.53);y0,y1=round(height*.15),round(height*.22)
                source[y0:y1,x0:x1]=(0,190,240)
                expanded=review_capture_region(region,[monitor,monitor],'center')
                x,y,w,h=(expanded[k] for k in ('left','top','width','height'))
                context=source[y:y+h,x:x+w]
                detection=extract_detection_frame(context,region,expanded)
                original=source[region['top']:region['top']+region['height'],region['left']:region['left']+region['width']]
                np.testing.assert_array_equal(detection,original)
                self.assertFalse(np.any(detection))
                image=review_image(detection,(.9,(100,10,330,22),'challenge'),context)
                decoded=cv2.imdecode(np.frombuffer(base64.b64decode(image.split(',')[1]),np.uint8),cv2.IMREAD_COLOR)
                self.assertGreater(decoded.shape[0],200)
                self.assertGreater(int(decoded[:,:,2].max()),200)
                self.assertLessEqual(max(decoded.shape[:2]),1600)

    def test_context_stays_on_selected_negative_coordinate_monitor(self):
        monitor=dict(left=-1920,top=-100,width=1920,height=1080)
        region=dict(left=-1900,top=-80,width=800,height=500)
        expanded=review_capture_region(region,[monitor,monitor],'center')
        self.assertEqual(expanded['left'],-1920);self.assertEqual(expanded['top'],-100)
        self.assertLessEqual(expanded['left']+expanded['width'],0)
        self.assertLessEqual(expanded['top']+expanded['height'],980)

    def test_single_grab_delivers_detection_and_context(self):
        captures=[];observed=[]
        monitor=dict(left=0,top=0,width=1280,height=720)
        region=dict(left=345,top=180,width=588,height=360)
        class Source:
            monitors=[monitor,monitor];backend='fake'
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def grab(self,requested):
                if captures:raise StopIteration
                captures.append(requested)
                return np.full((requested['height'],requested['width'],3),88,np.uint8)
        def inspect(frame,name):
            observed.append(frame.shape)
            return (.9,(130,8,330,22),'challenge'),{}
        with CapturePump(Source,inspect,lambda:'now',6) as pump:
            pump.configure([dict(name='center',region=region)])
            item=pump.queue.get(2)
            self.assertIsNotNone(item)
            self.assertEqual(item.frame.shape,(360,588,3))
            self.assertGreater(item.review_frame.shape[0],360)
            self.assertGreater(item.review_frame.shape[1],588)
        self.assertEqual(len(captures),1)
        self.assertEqual(observed,[(360,588,3)])

    def test_noisy_images_remain_within_storage_limit(self):
        noise=np.random.default_rng(21).integers(0,256,(1080,1920,3),np.uint8)
        image=review_image(noise,(.9,(0,0,10,10)),noise)
        self.assertIsNotNone(image);self.assertLess(len(image),1500000)
