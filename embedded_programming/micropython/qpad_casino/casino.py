# The casino: shared bank, game clock and the screen currently shown.
import gfx
import ui
from cards import Deck, rng
from ui import Led, LED_OFF

MENU, ROULETTE, BLACKJACK, POKER = 0, 1, 2, 3
FRAME_MS = 33                                      # 30 fps


class Casino:
    def __init__(self, display, touch):
        from menu import Menu
        from roulette import Roulette
        from blackjack import Blackjack
        from poker import Holdem
        self.display = display
        gfx.init(display)
        ui.build_sprites()
        self.touch = touch
        self.led = Led()
        self.deck = Deck()
        self.bank = 1000
        self.screen = MENU
        self.clock = 0                             # game time in ms (the benchmark simulates it)
        self.menu = Menu(self)
        self.games = (Roulette(self), Blackjack(self), Holdem(self))

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
        self.led.flash(LED_OFF, clock)

    def open_game(self, index):
        self.screen = index + 1
        self.games[index].enter()

    def open_menu(self):
        self.screen = MENU

    def update(self, events):
        self.led.update(self.clock)
        if self.screen == MENU:
            self.menu.update(events)
        else:
            self.games[self.screen - 1].update(events)

    def draw(self):
        gfx.clear()
        if self.screen == MENU:
            self.menu.draw()
        else:
            self.games[self.screen - 1].draw()
