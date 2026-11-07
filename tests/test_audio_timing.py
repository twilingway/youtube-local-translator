"""Actual FFmpeg checks: duration and pitch, not subjective speech quality."""
import shutil
import numpy as np
import pytest
from scipy.signal import periodogram
from service.audio_timing import fit_speech

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
@pytest.mark.parametrize('target',[2.,1.])
def test_compression_fits_interval_and_preserves_pitch(target):
    rate=24000;t=np.arange(rate*4)/rate
    audio=(.1*np.sin(2*np.pi*180*t)).astype(np.float32)
    result,stats=fit_speech(audio,rate,target)
    assert target-.15<=len(result)/rate<=target+.04
    frequencies,power=periodogram(result[rate//10:-rate//10],rate)
    assert abs(frequencies[np.argmax(power)]-180)<3
    assert stats['tempo']>1 and stats['timing_error_s']<=.04

def test_short_speech_is_neither_slowed_nor_padded():
    rate=24000;t=np.arange(rate)/rate
    audio=(.1*np.sin(2*np.pi*180*t)).astype(np.float32)
    result,stats=fit_speech(audio,rate,3)
    assert len(result)==len(audio) and stats['tempo']==1
