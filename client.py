import time

import audio
import net


if __name__ == '__main__':
    import logging
    import readline
    import sys
    logging.basicConfig(level=20)
    print('enter relay server address: ', end='')
    host_ip = input()
    print('connecting to {}...'.format(host_ip))
    cli = net.Client((host_ip, 5005))
    try:
        cli.rpc({'type': 'enter'})
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
    print("connected to host at", host_ip)
    player = audio.Player()
    player.start()
    cli.raw_listeners.append(player.put_packet)
    recorder = None
    units = [player]
    try:
        while True:
            print('> ', end='')
            cmd = input()
            if cmd == 'record':
                if recorder:
                    print("already recording")
                    continue
                recorder = audio.Recorder()
                recorder.start()
                recorder.listeners.append(cli.broadcast)
                units.append(recorder)
            elif cmd == 'mute':
                if not recorder:
                    print("no recording to mute")
                    continue
                recorder.stop()
                units.remove(recorder)
                recorder = None
            elif cmd:
                print('eh wot?')
    except (EOFError, KeyboardInterrupt):
        print()
    for unit in units:
        unit.stop()
    cli.rpc({'type': 'leave'})
