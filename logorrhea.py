import queue
import time

import util


QUEUE = None


def log(*args):
    if QUEUE:
        msg = ' '.join(str(arg) for arg in args)
        QUEUE.put((time.time(), msg))


def start_thread():
    if not QUEUE:
        util.start_daemon(write_log)


def write_log():
    global QUEUE
    start = time.time()
    QUEUE = queue.Queue()
    with open('logorrhea.txt', 'w') as fh:
        while True:
            (tstamp, msg) = QUEUE.get()
            fh.write('{:.1f} {}\n'.format(1000*(tstamp - start), msg))
