import time

import audio
import logorrhea
import net
import player
import recorder


if __name__ == '__main__':
    import logging
    import sys
    try:
        import readline
    except ModuleNotFoundError:
        pass
    logging.basicConfig(level=20)
    print('enter your name/alias: ', end='')
    name = '{}-{}'.format(input(), str(time.time())[-3:])
    print('enter relay server address: ', end='')
    relay_ip = input()
    print('connecting to {}...'.format(relay_ip))
    cli = net.Client((relay_ip, 5005), name)
    try:
        cli.rpc({'type': 'enter'})
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
    print("connected to relay at", relay_ip)
    units = []
    if '--silent' not in sys.argv:
        play = player.Player()
        play.start()
        cli.raw_listeners.append(play.put_payloads)
        units.append(play)
    broadcast = getattr(cli, 'broadcast_unreliably' if '--unreliable' in sys.argv else 'broadcast')
    rec = None
    try:
        while True:
            print('> ', end='')
            cmd = input()
            if cmd == 'record':
                if rec:
                    print("already recording")
                    continue
                rec = recorder.Recorder()
                rec.start()
                rec.listeners.append(broadcast)
                units.append(rec)
            elif cmd == 'mute':
                if not rec:
                    print("no recording to mute")
                    continue
                rec.stop()
                units.remove(rec)
                rec = None
            elif cmd == 'log':
                logorrhea.start_thread()
            elif cmd.startswith('tempo '):
                bpm = int(cmd.split()[1])
                cli.propose_tempo(bpm)
            elif cmd:
                print('eh wot?')
    except (EOFError, KeyboardInterrupt):
        print()
    for unit in units:
        unit.stop()
    cli.rpc({'type': 'leave'})
