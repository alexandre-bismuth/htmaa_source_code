# Host stand-in for the rp2 module: the PIO program is not run; each state machine echoes the timeout,
# which reads as a charge time of 0 (untouched pad).
class PIO:
    OUT_LOW = 0


def asm_pio(**kwargs):
    return lambda program: program


class StateMachine:
    def __init__(self, sm_id, program, **kwargs):
        self.fifo = 0

    def active(self, on=None):
        pass

    def put(self, value):
        self.fifo = value

    def get(self):
        return self.fifo
