import pyaudio


def get_audio():
    global PY_AUDIO
    if PY_AUDIO is None:
        PY_AUDIO = pyaudio.PyAudio()
    return PY_AUDIO

PY_AUDIO = None
