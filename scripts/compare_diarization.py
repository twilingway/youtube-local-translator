"""Calibrate on all four official examples, without using the user's live stream."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np,soundfile as sf,sherpa_onnx as so
from scipy.signal import resample_poly
from service.config import ROOT
base=ROOT/'models/diarization';rows=[]
for model,thresholds in [('nemo_en_titanet_small.onnx',(.6,.7,.8)),('wespeaker_en_voxceleb_resnet34.onnx',(.35,.4,.5))]:
    for threshold in thresholds:
        config=so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(base/'sherpa-onnx-pyannote-segmentation-3-0/model.onnx'),window_shift_ratio=.1),num_threads=4,provider='cpu'),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=str(base/model),num_threads=4,provider='cpu'),
            clustering=so.FastClusteringConfig(num_clusters=-1,threshold=threshold),min_duration_on=.3,min_duration_off=.35)
        sd=so.OfflineSpeakerDiarization(config)
        for name,expected in [('0-four-speakers-zh.wav',4),('1-two-speakers-en.wav',2),('2-two-speakers-en.wav',2),('3-two-speakers-en.wav',2)]:
            a,r=sf.read(ROOT/'reports'/name,dtype='float32');a=resample_poly(a,16000,r)
            if a.ndim>1:a=a.mean(axis=1)
            started=time.perf_counter();segments=sd.process(a).sort_by_start_time()
            row={'model':model,'threshold':threshold,'file':name,'expected':expected,'detected':len({s.speaker for s in segments}),
                 'compute_s':time.perf_counter()-started,'input_s':len(a)/16000}
            rows.append(row);print(json.dumps(row),flush=True)
(ROOT/'reports/diarization-comparison.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
