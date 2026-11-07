"""Real offline diarization on the official four-speaker WAV, CPU only."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import sherpa_onnx as so
import soundfile as sf
from scipy.signal import resample_poly
from service.config import ROOT
base=ROOT/'models/diarization';rows=[]
for name in ('nemo_en_titanet_small.onnx','wespeaker_en_voxceleb_resnet34.onnx'):
    config=so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(base/'sherpa-onnx-pyannote-segmentation-3-0/model.onnx'),window_shift_ratio=.1),num_threads=4,provider='cpu'),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(base/name),num_threads=4,provider='cpu'),
        clustering=so.FastClusteringConfig(num_clusters=-1,threshold=.5),min_duration_on=.3,min_duration_off=.35)
    assert config.validate();model=so.OfflineSpeakerDiarization(config)
    audio,rate=sf.read(ROOT/'reports/0-four-speakers-zh.wav',dtype='float32')
    audio=resample_poly(audio,16000,rate)
    if audio.ndim>1:audio=audio.mean(axis=1)
    start=time.perf_counter();segments=model.process(audio).sort_by_start_time();seconds=time.perf_counter()-start
    extractor=so.SpeakerEmbeddingExtractor(config.embedding);vectors=[]
    for file in ('reports/listening/original-1.wav','reports/listening/original-2.wav'):
        clip,r=sf.read(ROOT/file,dtype='float32');clip=resample_poly(clip,16000,r)
        stream=extractor.create_stream();stream.accept_waveform(sample_rate=16000,waveform=clip);stream.input_finished()
        v=np.asarray(extractor.compute(stream));vectors.append(v/(np.linalg.norm(v)+1e-9))
    row={'model':name,'input_s':len(audio)/16000,'compute_s':seconds,'rtf':seconds/(len(audio)/16000),
        'detected_speakers':len({s.speaker for s in segments}),'source_reference_cosine':float(np.dot(*vectors)),
        'segments':[{'start':s.start,'end':s.end,'speaker':s.speaker} for s in segments]}
    rows.append(row);print(json.dumps({k:v for k,v in row.items() if k!='segments'}),flush=True)
(ROOT/'reports/diarization-benchmark.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
