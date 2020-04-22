import collections
import heapq
import json
import logging
import queue
import random
import socket
import struct
import threading
import time

import stats
import util


class PeerIndex:
    def __init__(self):
        self.peers = {}  # name -> list(addr)
        self.addrmap = {}  # addr -> name

    def list_peers(self):
        return [(peer, addrset[0]) for peer, addrset in self.peers.items()]

    def get_addr(self, name, default=None):
        try:
            return self.peers[name][0]
        except KeyError:
            return default

    def get_name(self, addr):
        return self.addrmap.get(addr)

    def set_assoc(self, name, addr):
        oldname = self.addrmap.get(addr)
        if oldname == name:
            return
        logging.info('{} is {}'.format(name, addr))
        self.addrmap[addr] = name
        if oldname:
            self.peers[oldname].remove(addr)
        if name not in self.peers:
            self.peers[name] = [addr]
        else:
            self.peers[name].append(addr)


class Listener:
    def __init__(self):
        self.queue = queue.Queue()
        self.listening = True

    def receive(self, payload, peer):
        self.queue.put_nowait((payload, peer))


class SeqListener(Listener):
    def __init__(self, client):
        super().__init__()
        self.seqs = []
        self.client = client

    def matches(self, payload, seq=None):
        return seq in self.seqs

    def next_seq(self):
        seq = self.client.next_seq()
        self.seqs.append(seq)
        return seq


class TypeListener(Listener):
    def __init__(self, msgtype, receive_func):
        super().__init__()
        self.msgtype = msgtype
        self.receive = receive_func

    def matches(self, payload, seq=None):
        return payload.get('type') == self.msgtype


class Client:
    def __init__(self, host_addr, name):
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.port = random.randint(49152, 65535)
        self.sock.bind(('', self.port))
        self.seq = -1
        self.seq_lock = threading.Lock()
        self.listeners = [] 
        self.raw_listeners = []
        self.known_peers = []
        self.peers = PeerIndex()
        self.peers.set_assoc('host', host_addr)
        self.broadcast_seq = 0
        self.payloads = collections.deque()
        util.start_daemon(self.read_loop)
        util.start_daemon(self.ping_loop)

    def next_seq(self):
        with self.seq_lock:
            self.seq += 1
            return self.seq

    def prepare_broadcast(self, data):
        self.broadcast_seq += 1
        payload = struct.pack('!II', self.broadcast_seq, len(data)) + data
        self.payloads.appendleft(payload)
        if len(self.payloads) > 3:
            self.payloads.pop()
        return b''.join(self.payloads)

    def broadcast_unreliably(self, data):
        if not getattr(self, 'delay_thread', None):
            self.delay_heap = []
            self.delay_heap_lock = threading.Lock()
            self.delay_heap_change = threading.Event()
            self.delay_thread = util.start_daemon(self.broadcast_delayed)
            self.dropped = False
        if random.random() < 0.5:  # re-roll die only half the time
            self.dropped = (random.random() < 0.10)  # drop 10% of all packets
        if self.dropped:
            return
        send_time = time.time() + random.expovariate(40)  # average 25 ms
        item = (send_time, self.prepare_broadcast(data))
        with self.delay_heap_lock:
            heapq.heappush(self.delay_heap, item)
            if random.random() < 0.01:  # dupe 1% of packets
                heapq.heappush(self.delay_heap, (item[0] + random.expovariate(100), item[1]))
            self.delay_heap_change.set()

    def broadcast_delayed(self):
        while True:
            if not self.delay_heap:
                time.sleep(0.001)
                continue
            with self.delay_heap_lock:
                (send_time, data) = self.delay_heap[0]
                self.delay_heap_change.clear()
            wait = send_time - time.time()
            if wait <= 0:
                self.broadcast(data, prepared=True)
                with self.delay_heap_lock:
                    heapq.heappop(self.delay_heap)
            else:
                self.delay_heap_change.wait(timeout=wait)

    def broadcast(self, data, prepared=False):
        if not prepared:
            data = self.prepare_broadcast(data)
        for peer in self.known_peers:
            name = peer['name']
            if name == self.name:
                continue
            addr = self.peers.get_addr(name)
            if addr:
                self.sock.sendto(data, addr)

    def send(self, msg, addr):
        payload = json.dumps(msg).encode('ascii')
        self.sock.sendto(payload, addr)

    def rpc(self, msg, dst='host'):
        listener = SeqListener(self)
        self.listeners.append(listener)
        util.start_daemon(self.multisend, msg, dst, listener)
        try:
            payload, peer = listener.queue.get(timeout=10)
        except queue.Empty:
            raise Exception("no RPC response from {}".format(dst)) from None
        listener.listening = False
        self.listeners.remove(listener)
        return payload

    def multisend(self, msg, peer, listener):
        logging.info("multisending <{}> to {}".format(msg['type'], peer))
        msg['from'] = self.name
        while listener.listening:
            msg['seq'] = listener.next_seq()
            addr = self.peers.get_addr(peer)
            self.send(msg, addr)
            time.sleep(1)

    def ping_loop(self):
        self.listeners.append(TypeListener('ping', self.receive_ping))
        self.listeners.append(TypeListener('pong', self.receive_pong))
        host_addr = self.peers.get_addr('host')
        while True:
            time.sleep(1)
            for peer in [{'name': 'host'}] + self.known_peers:
                name = peer['name']
                if name == self.name:
                    continue
                addr = self.peers.get_addr(name)
                if not addr:
                    addr = tuple(peer['addr'])
                    logging.info("trying to reach " + name)
                msg = {'type': 'ping', 'from': self.name, 'seq': self.next_seq(), 'time': time.time()}
                self.send(msg, addr)

    def receive_ping(self, payload, peer):
        self.send({'type': 'pong', 'from': self.name, 'seq': payload['seq'], 'time': payload['time']}, self.peers.get_addr(peer))

    def receive_pong(self, payload, peer):
        if peer == 'host':
            self.known_peers = payload['clients']
        else:
            stats.METER(
                'rt {}'.format(peer),
                1000 * (time.time() - payload['time']),
            )

    def read_loop(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            if data[0] != 0x7b or data[-1] != 0x7d:
                payloads = []
                idx = 0
                while idx < len(data):
                    (seq, size) = struct.unpack('!II', data[idx : idx+8])
                    idx += 8
                    payloads.append((seq, data[idx : idx+size]))
                    idx += size
                name = self.peers.get_name(addr)
                if name is not None:
                    for listener in self.raw_listeners:
                        listener(payloads, name)
                continue
            payload = json.loads(data.decode('ascii'))
            if 'from' in payload:
                name = payload['from']
                self.peers.set_assoc(name, addr)
            else:
                name = self.peers.get_name(addr)
            self.dispatch(payload, name)

    def dispatch(self, payload, peer):
        seq = payload.get('seq')
        if seq is None:
            return
        for listener in self.listeners:
            if listener.matches(payload, seq):
                listener.receive(payload, peer)
                break
