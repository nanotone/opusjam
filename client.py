import time

import audio
import net


if __name__ == '__main__':
    import sys
    host_ip = sys.argv[1]
    cli = net.Client((host_ip, 5005))
    cli.rpc({'type': 'enter'})
    print("connected to host")
    units = []
    if 'play' in sys.argv or 'rec' not in sys.argv:
        player = audio.Player()
        player.start()
        cli.raw_listeners.append(player.put_packet)
        units.append(player)
    if 'rec' in sys.argv:
        recorder = audio.Recorder()
        recorder.start()
        recorder.listeners.append(cli.broadcast)
        units.append(recorder)
    try:
        time.sleep(9999)
    except KeyboardInterrupt:
        print()
    for unit in units:
        unit.stop()
    cli.rpc({'type': 'leave'})
