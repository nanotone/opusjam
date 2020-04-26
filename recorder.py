import logging

import opuslib
import pyaudio

import audio


class Recorder:
    def __init__(self):
        self.enc = opuslib.Encoder(24000, 1, opuslib.APPLICATION_RESTRICTED_LOWDELAY)
        self.enc.bitrate = 64000
        self.enc.lsb_depth = 16
        self.enc.packet_loss_perc = 25
        self.enc.signal = opuslib.SIGNAL_MUSIC
        self.listeners = []

    def start(self):
        self.stream = audio.get_audio().open(
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


