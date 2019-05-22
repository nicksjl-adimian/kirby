import logging

from threading import Thread, Event

LEADER_KEY = "_KIRBY_LEADER"
LEADER_KEY_LEASE = 0.5  # seconds

logger = logging.getLogger(__name__)


class Timer(Thread):
    """Call a function after a specified number of seconds:

    t = Timer(30.0, f, args=[], kwargs={})
    t.start()
    t.cancel() # stop the timer's action if it's still waiting
    """

    def __init__(self, interval, function, args=None, kwargs=None):
        Thread.__init__(self)
        self.interval = interval or LEADER_KEY_LEASE
        self.function = function
        self.args = args or []
        self.kwargs = kwargs or {}
        self.finished = Event()
        self.ready = Event()

    def cancel(self):
        """Stop the timer if it hasn't finished yet"""
        self.finished.set()

    def run(self):
        while True:
            self.finished.wait(self.interval)
            if not self.finished.is_set():
                self.function(*self.args, **self.kwargs)
                self.ready.set()
            else:
                break


def make_me_leader(identity, server, check_ttl):
    # Key should live on at least the time of check_ttl,
    # otherwise we might have gaps during which nobody is the leader.
    # We're using 2x the check_ttl time to be sure as long as the leader lives
    # it is able to reclaim its leader position
    expiry = int(2 * check_ttl * 1000)

    logger.info(f"setting up leader to {identity} for {expiry}ms")
    return server.set(
        name=LEADER_KEY, value=identity.encode("utf-8"), nx=True, px=expiry
    )


class Election:
    def __init__(self, identity, server, check_ttl=None):
        self.identity = identity
        self.server = server
        self.check_ttl = check_ttl

        self.timer = Timer(
            self.check_ttl, make_me_leader, (identity, server, check_ttl)
        )

    def __enter__(self):
        logger.info(f"starting election process for {self.identity}")
        self.timer.start()

        # The first activation might take some time,
        # so we are waiting a bit before moving on
        self.timer.ready.wait(self.check_ttl * 2)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info(f"withdrawing from election process for {self.identity}")
        self.timer.cancel()

    def is_leader(self):
        current_leader = self.server.get(LEADER_KEY)
        if current_leader:
            current_leader = current_leader.decode("utf-8")
        logger.info(f"[{self.identity}] current leader: {current_leader}")
        return current_leader == self.identity
