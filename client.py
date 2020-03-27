import json
import queue
import random
import socket
import threading
import time
import uuid


def start_daemon(func, *args):
    thread = threading.Thread(target=func, args=args, daemon=True)
    thread.start()
    return thread


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
        return self.addrmap[addr]

    def set_assoc(self, name, addr):
        oldname = self.addrmap.get(addr)
        if oldname == name:
            return
        print(name, "is", addr)
        self.addrmap[addr] = name
        if oldname:
            self.peers[oldname].remove(addr)
        if name not in self.peers:
            self.peers[name] = [addr]
        else:
            self.peers[name].append(addr)

PEER_INDEX = PeerIndex()


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
    def __init__(self):
        self.name = str(uuid.uuid4())[:8]
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.port = random.randint(49152, 65535)
        self.sock.bind(('', self.port))
        self.seq = -1
        self.seq_lock = threading.Lock()
        self.listeners = [] 
        self.known_peers = []
        start_daemon(self.read_loop)
        start_daemon(self.ping_loop)

    def next_seq(self):
        with self.seq_lock:
            self.seq += 1
            return self.seq

    def send(self, msg, addr):
        payload = json.dumps(msg).encode('ascii')
        self.sock.sendto(payload, addr)

    def rpc(self, msg, dst='host'):
        listener = SeqListener(self)
        self.listeners.append(listener)
        start_daemon(self.multisend, msg, dst, listener)
        try:
            payload, peer = listener.queue.get(timeout=10)
        except queue.Empty:
            raise Exception("no RPC response from {}".format(dst)) from None
        listener.listening = False
        self.listeners.remove(listener)
        return payload

    def multisend(self, msg, peer, listener):
        print("multisending <{}> to {}".format(msg['type'], peer))
        msg['from'] = self.name
        while listener.listening:
            msg['seq'] = listener.next_seq()
            addr = PEER_INDEX.get_addr(peer)
            self.send(msg, addr)
            time.sleep(1)

    def ping_loop(self):
        self.listeners.append(TypeListener('ping', self.receive_ping))
        self.listeners.append(TypeListener('pong', self.receive_pong))
        host_addr = PEER_INDEX.get_addr('host')
        while True:
            time.sleep(1)
            for peer in [{'name': 'host'}] + self.known_peers:
                name = peer['name']
                if name == self.name:
                    continue
                addr = PEER_INDEX.get_addr(name)
                if not addr:
                    addr = tuple(peer['addr'])
                    print("trying to reach", addr)
                msg = {'type': 'ping', 'from': self.name, 'seq': self.next_seq(), 'time': time.time()}
                self.send(msg, addr)

    def receive_ping(self, payload, peer):
        self.send({'type': 'pong', 'from': self.name, 'seq': payload['seq'], 'time': payload['time']}, PEER_INDEX.get_addr(peer))

    def receive_pong(self, payload, peer):
        if peer == 'host':
            self.known_peers = payload['clients']
        else:
            print("round-trip to {}: {:.1f} ms".format(
                peer, 1000*(time.time() - payload['time'])))

    def read_loop(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            payload = json.loads(data.decode('ascii'))
            if 'from' in payload:
                name = payload['from']
                PEER_INDEX.set_assoc(name, addr)
            else:
                name = PEER_INDEX.get_name(addr)
            self.dispatch(payload, name)

    def dispatch(self, payload, peer):
        seq = payload.get('seq')
        if seq is None:
            pass
            return
        for listener in self.listeners:
            if listener.matches(payload, seq):
                listener.receive(payload, peer)
                break


if __name__ == '__main__':
    import sys
    host_ip = sys.argv[1]
    PEER_INDEX.set_assoc('host', (host_ip, 5005))
    cli = Client()
    cli.rpc({'type': 'enter'})
    print("connected to host")
    time.sleep(10)
