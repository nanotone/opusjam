import logging
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
        self.thread = util.start_daemon(self.run)

    def stop(self, block=True):
        self.recording = False
        if block:
            self.thread.join()
        logging.info("Recorder thread stopped and joined")

    def run(self):
        stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            input=True,
            frames_per_buffer=120,
        )
        while self.recording:
            data = stream.read(120, exception_on_overflow=False)
            if not data:
                logging.warn("Overflow? " + repr(data))
                continue
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
        self.thread = util.start_daemon(self.run)

    def stop(self, block=True):
        self.playing = False
        if block:
            self.thread.join()
        logging.info("Player thread stopped and joined")

    def run(self):
        stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            output=True,
            frames_per_buffer=120,
        )
        last_log = 0
        while self.playing:
            try:
                packet = self.queue.get_nowait()
            except queue.Empty:
                time.sleep(0.002)
                continue
            frame = self.dec.decode(packet, 120)
            stream.write(frame)
            now = time.time()
            if now - last_log > 1:
                if last_log:
                    logging.info("played {} frames in {:.3f} sec; queue size {}".format(
                        frames, now - last_log, self.queue.qsize()
                    ))
                frames = 0
                last_log = now
            frames += 1
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
