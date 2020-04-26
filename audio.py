import collections
import heapq
import logging
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


Packet = collections.namedtuple('Packet', ['seq', 'data'])

class Channel:
    __slots__ = (
        'accept_rate',
        'decoded',
        'decoder',
        'decoder_lock',
        'decoder_thread',
        'dupe_check',
        'heap',
        'heap_lock',
        'last_packet_time',
        'last_played',
        'ready_next_rate',
        'ready_rate',
        'wake_event',
        'wake_lock',
    )

    def __init__(self):
        self.accept_rate = 1.0
        self.ready_rate = 1.0
        self.ready_next_rate = 0.0
        self.decoded = None
        self.decoder = opuslib.Decoder(24000, 1)
        self.decoder_lock = threading.Lock()
        self.dupe_check = util.DupeCheck()
        self.heap = []
        self.heap_lock = threading.Lock()
        self.last_packet_time = None
        self.wake_event = threading.Event()
        self.wake_lock = threading.Lock()
        self.decoder_thread = util.start_daemon(self.run_decoder)
        self.last_played = None

    def enqueue(self, seq, data):
        """Enqueue a packet with its sequence number, and wake the decoder."""
        self.last_packet_time = time.time()
        if not self.dupe_check.receive(seq):
            return
        #stats.METER('recv %', self.dupe_check.receive_rate * 100)
        self.accept_rate *= 0.995
        if not self.last_played or seq > self.last_played:
            with self.heap_lock:
                heapq.heappush(self.heap, Packet(seq, data))
            self.accept_rate += 0.005
            self.wake_event.set()
        #stats.METER('accept', self.accept_rate)

    def dequeue(self):
        packet = None
        self.ready_next_rate *= 0.995
        try:
            stats.METER('buffer', len(self.heap)*5)
            if self.last_played:
                with self.heap_lock:
                    while self.heap[0].seq <= self.last_played:
                        heapq.heappop(self.heap)
                    if self.heap[0].seq == self.last_played + 1:
                        packet = heapq.heappop(self.heap)
                        if self.heap[0].seq == packet.seq + 1:
                            self.ready_next_rate += 0.005
            else:
                with self.heap_lock:
                    packet = heapq.heappop(self.heap)
        except IndexError:
            pass
        stats.METER('readynext', self.ready_next_rate)
        return packet

    def run_decoder(self):
        while True:
            self.wake_event.wait()
            self.wake_event.clear()
            if self.decoded:
                continue
            packet = self.dequeue()
            if not packet:
                continue  # out of luck! sleep until more data comes
            self.decoder_lock.acquire()
            data = self.decoder.decode(packet.data, 120)
            self.wake_lock.acquire()
            self.decoded = Packet(packet.seq, data)
            self.decoder_lock.release()
            self.wake_event.clear()
            self.wake_lock.release()

    def read_decoded(self):
        """Return whatever is in the decoded buffer (possibly None) and wake
        the decoder thread to let it know the buffer is empty."""
        packet = self.decoded
        with self.wake_lock:
            self.decoded = None
            self.wake_event.set()
        return packet

    def get_audio(self):
        """Return a valid chunk of usable audio, regardless of whether the
        decoder has real packets queued up."""
        stats.METER('ready', self.ready_rate)
        self.ready_rate *= 0.995
        packet = self.read_decoded()  # wakes decoder
        if self.should_play(packet):
            self.ready_rate += 0.005
            self.adjust_buffer()
            return packet.data
        # Prepare to decode a dropped frame, so acquire the lock first.
        self.decoder_lock.acquire()
        # If decoder was busy, it should already have provided fresh audio.
        if self.should_play(self.decoded):
            self.decoder_lock.release()
            packet = self.read_decoded()  # remember to wake decoder
            self.ready_rate += 0.005
            self.adjust_buffer()
            return packet.data
        if self.last_played:
            data = self.decoder.decode(b'', 120)
            self.decoder_lock.release()
            stats.COUNT('missing')
            self.last_played += 1
            self.adjust_buffer()
            return data
        else:
            return Player.SILENCE

    def should_play(self, packet):
        if not packet or (self.last_played and packet.seq != self.last_played + 1):
            return False
        self.last_played = packet.seq
        return True

    def adjust_buffer(self):
        if self.ready_rate < 0.9:
            self.last_played -= 1
            self.ready_next_rate = self.ready_rate
            self.ready_rate = 1.0
            stats.COUNT("<<=")
        elif self.ready_next_rate > 0.95:
            self.last_played += 1
            self.ready_rate = self.ready_next_rate
            self.ready_next_rate = 0.0
            stats.COUNT("=>>")
