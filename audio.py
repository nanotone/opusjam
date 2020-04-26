import ctypes

import numpy
import pyaudio


PY_AUDIO = None

SILENCE = b'\0' * 240
FADE_IN = numpy.linspace(0, 1, num=120)
FADE_OUT = numpy.linspace(1, 0, num=120)


def get_audio():
    global PY_AUDIO
    if PY_AUDIO is None:
        PY_AUDIO = pyaudio.PyAudio()
    return PY_AUDIO


def numpyify(frame):
    if isinstance(frame, numpy.ndarray):
        return frame
    return numpy.frombuffer(frame, dtype=numpy.int16)


def mix(frames):
    if not frames:
        return SILENCE
    if len(frames) == 1:
        return frames[0]
    frames = [numpyify(frame) for frame in frames]
    assert all(len(frame) == 120 for frame in frames)
    return numpy.mean(frames, axis=0, dtype=numpy.int16)


def crossfade(one, two):
    return (numpyify(one)*FADE_OUT + numpyify(two)*FADE_IN).astype(numpy.int16)
