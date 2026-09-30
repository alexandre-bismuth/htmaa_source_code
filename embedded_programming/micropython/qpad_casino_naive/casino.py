# The casino: shared bank, game clock and the screen currently shown.
from cards import Deck, rng
from gfx import Gfx
from ui import Led
from menu import Menu
from roulette import Roulette
from blackjack import Blackjack
from poker import Holdem

MENU, ROULETTE, BLACKJACK, POKER = 0, 1, 2, 3
FRAME_MS = 33                                      # 30 fps


class Casino:
    def __init__(self, display, touch):
        self.display = display
        self.gfx = Gfx(display)
        self.touch = touch
        self.led = Led()
        self.deck = Deck()
        self.bank = 1000
        self.screen = MENU
        self.clock = 0                             # game time in ms (the benchmark simulates it)
        self.menu = Menu(self)
        self.games = [Roulette(self), Blackjack(self), Holdem(self)]

    def now(self):
        return self.clock

    def reset(self, seed, clock):
        self.bank = 1000
        self.screen = MENU
        rng.state = seed
        self.clock = clock
        self.menu.reset()
        for game in self.games:
            game.reset()
        self.led.flash(None, clock)

    def open_game(self, index):
        self.screen = index + 1
        self.games[index].enter()

    def open_menu(self):
        self.screen = MENU

    def current(self):
        return self.menu if self.screen == MENU else self.games[self.screen - 1]

    def update(self, events):
        self.led.update(self.clock)
        self.current().update(events)

    def draw(self):
        self.gfx.clear()
        self.current().draw(self.gfx)
