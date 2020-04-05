import json
import socket
import time


#outbound = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

CLIENTS = {}

def list_clients():
    now = time.time()
    if now - getattr(list_clients, 'last_prune_time', 0) > 5:
        stale = [addr for addr, cli in CLIENTS.items() if now - cli['last_ping'] > 15]
        for addr in stale:
            del CLIENTS[addr]
        list_clients.last_prune_time = now
    return [
        {'name': cli['name'], 'addr': addr} for addr, cli in CLIENTS.items()
    ]


def handle_msg(body, addr):
    msgtype = body['type']
    if msgtype == 'enter':
        name = body['from']
        CLIENTS[addr] = {'name': name, 'last_ping': time.time()}
        return {'youare': addr, 'clients': list_clients()}
    if msgtype == 'ping':
        if addr in CLIENTS:
            CLIENTS[addr]['last_ping'] = time.time()
        return {'type': 'pong', 'clients': list_clients()}
    if msgtype == 'leave':
        CLIENTS.pop(addr, None)
        return {}


if __name__ == '__main__':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 5005))
    while True:
        data, addr = sock.recvfrom(1024)
        print(addr, "->", data)
        try:
            body = json.loads(data.decode('ascii'))
            reply = handle_msg(body, addr)
            if reply is None:
                continue
        except Exception:
            continue
        reply['from'] = 'host'
        if 'seq' in body:
            reply['seq'] = body['seq']
        sock.sendto(json.dumps(reply).encode('ascii'), addr)
