import threading


def start_daemon(func, *args):
    thread = threading.Thread(target=func, args=args, daemon=True)
    thread.start()
    return thread
