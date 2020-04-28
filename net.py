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


TIME_OFFSET = random.random()
def offset_time():
    return time.time() + TIME_OFFSET


class Peer:
    def __init__(self, name, addr):
        self.name = name
        self.addrs = [addr]
        self.mindiff = -1e10
        self.maxdiff = 1e10

    @property
    def addr(self):
        return self.addrs[0]

    def add(self, addr):
        self.addrs.append(addr)

    def remove(self, addr):
        self.addrs.remove(addr)

    def receive_pong(self, payload):
        now = offset_time()
        ping_time = payload.get('ping_time')
        pong_time = payload.get('time')
        if not (ping_time or pong_time):
            return
        stats.METER(
            'RT {}'.format(self.name),
            1000 * (now - ping_time),
        )
        self.mindiff = max(self.mindiff, pong_time - now)
        self.maxdiff = min(self.mindiff, pong_time - ping_time)


class PeerIndex:
    def __init__(self):
        self.peers = {}  # name -> Peer
        self.addrmap = {}  # addr -> name

    def list_peers(self):
        return [(name, peer.addr) for name, peer in self.peers.items()]

    def get_addr(self, name, default=None):
        try:
            return self.peers[name].addr
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
            self.peers[name] = Peer(name, addr)
        else:
            self.peers[name].add(addr)


class Listener:
    def __init__(self, client):
        self.queue = queue.Queue()
        self.listening = True
        self.seqs = []
        self.client = client

    def matches(self, payload, seq=None):
        return seq in self.seqs

    def receive(self, payload, peer):
        self.queue.put_nowait((payload, peer))

    def next_seq(self):
        seq = self.client.next_seq()
        self.seqs.append(seq)
        return seq


class Client:
    def __init__(self, relay_addr, name):
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
        self.peers.set_assoc('relay', relay_addr)
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
                # drop 5% of all packets, but re-roll die only 75% of the time
                if random.random() < 0.75:
                    self.dropped = (random.random() < 0.05)
                if not self.dropped:
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

    def rpc(self, msg, dst='relay'):
        listener = Listener(self)
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
        relay_addr = self.peers.get_addr('relay')
        while True:
            time.sleep(1)
            for peer in [{'name': 'relay'}] + self.known_peers:
                name = peer['name']
                if name == self.name:
                    continue
                addr = self.peers.get_addr(name)
                if not addr:
                    addr = tuple(peer['addr'])
                    logging.info("trying to reach " + name)
                msg = {'type': 'ping', 'from': self.name, 'seq': self.next_seq(), 'time': offset_time()}
                self.send(msg, addr)

    def receive_ping(self, payload, peer):
        reply = {
            'type': 'pong',
            'from': self.name,
            'seq': payload['seq'],
            'ping_time': payload['time'],
            'time': offset_time(),
        }
        self.send(reply, self.peers.get_addr(peer))

    def receive_pong(self, payload, peer):
        if peer == 'relay':
            self.known_peers = payload['clients']
        else:
            self.peers.peers[peer].receive_pong(payload)

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
        payload_type = payload.get('type')
        if payload_type == 'ping':
            self.receive_ping(payload, peer)
        elif payload_type == 'pong':
            self.receive_pong(payload, peer)
        else:
            for listener in self.listeners:
                if listener.matches(payload, seq):
                    listener.receive(payload, peer)
                    break
