import threading


def start_daemon(func, *args):
    thread = threading.Thread(target=func, args=args, daemon=True)
    thread.start()
    return thread


class DupeCheck:
    """Detects duplicates in last 128 sequence numbers."""

    # This class should really be written in C.
    __slots__ = ('array', 'latest')
    ZEROS = b'\0' * 128

    def __init__(self):
        self.array = bytearray(128)
        self.latest = -1

    def receive(self, seq):
        if seq <= self.latest - 128:
            return False  # too old
        seq_idx = seq % 128
        if seq > self.latest:
            if seq >= self.latest + 128:
                self.array[:] = DupeCheck.ZEROS
            else:
                latest_idx = self.latest % 128
                if seq_idx > latest_idx:
                    self.array[latest_idx + 1 : seq_idx + 1] = DupeCheck.ZEROS[latest_idx + 1 : seq_idx + 1]
                else:
                    self.array[latest_idx + 1:] = DupeCheck.ZEROS[latest_idx + 1:]
                    self.array[:seq_idx + 1] = DupeCheck.ZEROS[:seq_idx + 1]
            self.latest = seq
        result = not self.array[seq_idx]
        self.array[seq_idx] = 1
        return result

    def saw(self, seq):
        return self.latest - 128 < seq <= self.latest and bool(self.array[seq % 128])

    @property
    def receive_rate(self):
        return sum(self.array) / 128.0
