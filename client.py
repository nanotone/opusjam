import time

import audio
import net


if __name__ == '__main__':
    import sys
    host_ip = sys.argv[1]
    cli = net.Client((host_ip, 5005))
    cli.rpc({'type': 'enter'})
    print("connected to host")
    player = audio.Player()
    player.start()
    cli.raw_listeners.append(player.put_packet)
    try:
        time.sleep(9999)
    except KeyboardInterrupt:
        print()
        player.playing = False
        cli.rpc({'type': 'leave'})
