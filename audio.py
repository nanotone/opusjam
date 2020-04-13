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
        self.stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            input=True,
            frames_per_buffer=120,
            stream_callback=self.callback,
        )

    def stop(self, block=True):
        self.stream.stop_stream()
        self.stream.close()

    def callback(self, in_data, frame_count, time_info, status):
        if frame_count == 120:
            data = self.enc.encode(in_data, 120)
            for listener in self.listeners:
                listener(data)
        else:
            logging.warn("Incorrect input frame count {}".format(frame_count))
        return (None, pyaudio.paContinue)


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
        data = data[4:]
        while True:
            try:
                self.queue.put_nowait(data)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
