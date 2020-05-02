import collections
import logging
import time

import util


class Stats:
    def __init__(self):
        self.printing = True
        self.thread = util.start_daemon(self.run)
        self.trackers = self.create_trackers()

    def create_trackers(self):
        return (
            collections.Counter(),
            collections.defaultdict(list),
        )

    def count(self, key, delta=1):
        self.trackers[0][str(key)] += delta

    def meter(self, key, value):
        self.trackers[1][key].append(value)

    def run(self):
        prev_cols = None
        while True:
            time.sleep(3)
            (counters, meters) = self.trackers
            self.trackers = self.create_trackers()
            record = {}
            for key, count in counters.items():
                record['# ' + key] = str(count)
            for key, values in meters.items():
                value = sum(values) / len(values)
                if value < 1000:
                    record['avg ' + key] = '{:#.3g}'.format(value)
                else:
                    record['avg ' + key] = str(value).split('.')[0]
            if not record:
                continue
            cols = sorted(record.keys())
            if self.printing:
                if cols != prev_cols:
                    logging.info('{}'.format(' | '.join(cols)))
                logging.info(' | '.join(
                    ' '*(len(col) - len(record[col])) + record[col]
                    for col in cols
                ))
            prev_cols = cols

INSTANCE = Stats()
COUNT = INSTANCE.count
METER = INSTANCE.meter
