import queue
import time

import opuslib
import pyaudio

import util


_pa = None
def get_audio():
    global _pa
    if _pa is None:
        _pa = pyaudio.PyAudio()
    return _pa


class Recorder:
    def __init__(self):
        self.enc = opuslib.Encoder(24000, 1, opuslib.APPLICATION_RESTRICTED_LOWDELAY)
        self.listeners = []

    def start(self):
        self.recording = True
        util.start_daemon(self.run)

    def stop(self):
        self.recording = False

    def run(self):
        stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            input=True,
            frames_per_buffer=120,
        )
        while self.recording:
            data = stream.read(120)
            data = self.enc.encode(data, len(data) >> 1)
            for listener in self.listeners:
                listener(data)
        stream.stop_stream()
        stream.close()


class Player:
    def __init__(self):
        self.dec = opuslib.Decoder(24000, 1)
        self.queue = queue.Queue(maxsize=5)

    def start(self):
        self.playing = True
        util.start_daemon(self.run)

    def stop(self):
        self.playing = False

    def run(self):
        stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            output=True,
            frames_per_buffer=120,
        )
        while self.playing:
            try:
                packet = self.queue.get_nowait()
            except queue.Empty:
                time.sleep(0.002)
                continue
            frame = self.dec.decode(packet, 120)
            stream.write(frame)
        stream.stop_stream()
        stream.close()

    def put_packet(self, data, addr):
        while True:
            try:
                self.queue.put_nowait(data)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
