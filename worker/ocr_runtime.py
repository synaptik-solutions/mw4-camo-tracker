"""Create local OCR with platform telemetry disabled before model sessions exist."""
def create_ocr():
    import onnxruntime
    # Official Python API: https://onnxruntime.ai/docs/api/python/api_summary.html#telemetry-events
    onnxruntime.disable_telemetry_events()
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(det_use_dilation=True, use_cls=False,
                    intra_op_num_threads=1, inter_op_num_threads=1)


def self_test():
    import cv2
    import numpy as np
    image=np.full((120,750,3),255,np.uint8)
    cv2.putText(image,'MILITARY CAMO 1',(20,80),cv2.FONT_HERSHEY_SIMPLEX,1.7,(0,0,0),3,cv2.LINE_AA)
    result,_=create_ocr()(image)
    text=' '.join(row[1] for row in result or [])
    if 'MILITARYCAMO1' not in ''.join(c for c in text.upper().replace('CAM0','CAMO') if c.isalnum()):
        raise RuntimeError('Packaged OCR failed to read the synthetic test card: '+text)
    return dict(ocrSelfTest='passed',text=text)
