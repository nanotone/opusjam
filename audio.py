import logging
import queue
import threading
import time

import opuslib
import pyaudio

import stats
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
        self.enc.bitrate = 64000
        self.enc.lsb_depth = 16
        self.enc.packet_loss_perc = 25
        self.enc.signal = opuslib.SIGNAL_MUSIC
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
    SILENCE = b'\0' * 240

    def __init__(self):
        self.channels = {}

    def start(self):
        self.stream = get_audio().open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            output=True,
            frames_per_buffer=120,
            stream_callback=self.callback,
        )

    def stop(self, block=True):
        self.stream.stop_stream()
        self.stream.close()

    def put_payloads(self, payloads, peer_name):
        channel = self.channels.get(peer_name)
        if not channel:
            # in lieu of a lock, use attribute assignment to synchronize
            channels = dict(self.channels)
            channels[peer_name] = channel = Channel()
            self.channels = channels
        for (seq, data) in payloads:
            channel.enqueue(seq, data)

    def callback(self, in_data, frame_count, time_info, status):
        now = time.time()
        channels = self.channels
        for channel in channels.values():
            if channel.last_packet_time and now - channel.last_packet_time < 5:
                data = channel.get_audio()
                break
        else:
            data = Player.SILENCE
        assert len(data) == 240
        return (data, pyaudio.paContinue)


class Channel:
    __slots__ = (
        'accept_rate',
        'decoded',
        'decoded_seq',
        'decoder',
        'decoder_lock',
        'decoder_thread',
        'dequeue_to',
        'dupe_check',
        'last_packet_time',
        'latest_seq',
        'queue',
        'wake_event',
        'wake_lock',
    )

    def __init__(self):
        self.accept_rate = 1.0
        self.decoded = None
        self.decoder = opuslib.Decoder(24000, 1)
        self.decoder_lock = threading.Lock()
        self.dequeue_to = -1
        self.dupe_check = util.DupeCheck()
        self.decoded_seq = -1
        self.last_packet_time = None
        self.latest_seq = -1
        self.queue = queue.PriorityQueue()
        self.wake_event = threading.Event()
        self.wake_lock = threading.Lock()
        self.decoder_thread = util.start_daemon(self.run_decoder)

    def enqueue(self, seq, data):
        """Enqueue a packet with its sequence number, and wake the decoder."""
        self.last_packet_time = time.time()
        if not self.dupe_check.receive(seq):
            return
        #stats.METER('recv %', self.dupe_check.receive_rate * 100)
        if seq > self.decoded_seq:
            if self.decoded_seq == -1:
                self.decoded_seq = seq - 1
            self.accept_rate = self.accept_rate * 0.9 + 0.1
            if seq > self.latest_seq:
                self.latest_seq = seq
                self.dequeue_to = seq - 3
            stats.METER('seqrange', self.latest_seq - self.decoded_seq)
            self.queue.put_nowait((seq, data))
            self.wake_event.set()
        else:
            self.accept_rate *= 0.9
        stats.METER('accept', self.accept_rate)

    def dequeue(self):
        while True:
            try:
                (seq, packet) = self.queue.get_nowait()
            except queue.Empty:
                return (None, None)
            if seq > self.decoded_seq:
                break
        if seq > self.dequeue_to:
            # call it an underflow to preserve qsize (but requeue for later)
            self.queue.put_nowait((seq, packet))
            self.dequeue_to += 1
            return (None, None)
        self.decoded_seq = seq
        if self.dequeue_to - seq > 2 and not self.dupe_check.saw(seq + 1):
            self.decoded_seq = seq + 1
        self.dequeue_to += 1
        return (seq, packet)

    def run_decoder(self):
        while True:
            self.wake_event.wait()
            self.wake_event.clear()
            if self.decoded:
                continue
            seq, packet = self.dequeue()
            if not packet:
                continue  # out of luck! sleep until more data comes
            self.decoder_lock.acquire()
            data = self.decoder.decode(packet, 120)
            self.wake_lock.acquire()
            self.decoded = data
            self.decoder_lock.release()
            self.wake_event.clear()
            self.wake_lock.release()

    def read_decoded(self):
        """Return whatever is in the decoded buffer (possibly None) and wake
        the decoder thread to let it know the buffer is empty."""
        data = self.decoded
        with self.wake_lock:
            self.decoded = None
            self.wake_event.set()
        return data

    def get_audio(self):
        """Return a valid chunk of usable audio, regardless of whether the
        decoder has real packets queued up."""
        data = self.read_decoded()  # wakes decoder
        if data:
            stats.COUNT('present')
            return data
        # Prepare to decode a dropped frame, so acquire the lock first.
        self.decoder_lock.acquire()
        # If decoder was busy, it should already have provided fresh audio.
        if self.decoded:
            self.decoder_lock.release()
            return self.read_decoded()  # wakes decoder
        data = self.decoder.decode(b'', 120)
        self.decoder_lock.release()
        stats.COUNT('missing')
        return data
