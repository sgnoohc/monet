#!/usr/bin/env python3
"""Space Attack — terminal space shooter."""

import curses
import time
import random

# ── Dimensions ──────────────────────────────────────────────────────────
WIN_W, WIN_H = 130, 58
INNER_W, INNER_H = WIN_W - 2, WIN_H - 2

FPS = 15
FRAME_MS = 1000 // FPS

# ── Difficulty presets ──────────────────────────────────────────────────
#  (label, shoot_chance, move_interval, description)
DIFFICULTIES = {
    "easy":      ("EASY",      0.04,  3, "Relaxed pace, slow aliens"),
    "medium":    ("MEDIUM",    0.078, 2, "Balanced challenge"),
    "difficult": ("DIFFICULT", 0.14,  1, "Fast and aggressive"),
    "insane":    ("INSANE",    0.25,  1, "Pure chaos"),
}
DIFF_ORDER = ["easy", "medium", "difficult", "insane"]

# ── Sprites ─────────────────────────────────────────────────────────────
PLAYER_SPRITE = [
    " /\\ ",
    "/==\\",
]

FIGHTER_SPRITE_A = [
    "/oo\\",
    "\\--/",
    " \\/ ",
]

FIGHTER_SPRITE_B = [
    "{@@}",
    "<-->",
    " /\\ ",
]

BOMBER_SPRITE = [
    "[00]",
    "|~~|",
    "\\##/",
]

BUNKER_TEMPLATE = [
    list("########"),
    list("########"),
    list("########"),
    list("###  ###"),
    list("###  ###"),
]

# ── Explosion frames ───────────────────────────────────────────────────
EXPLOSION_FRAMES = [
    ["\\|/", "-*-", "/|\\"],
    [" . ", "...", " . "],
    ["   ", " ' ", "   "],
]
EXPLOSION_DURATION = len(EXPLOSION_FRAMES)

# ── Title art ───────────────────────────────────────────────────────────
LOGO = [
    r"  ____  ____   _    ____ _____      _  _____ _____  _    ____ _  __",
    r" / ___||  _ \ / \  / ___| ____|    / \|_   _|_   _|/ \  / ___| |/ /",
    r" \___ \| |_) / _ \| |   |  _|     / _ \ | |   | | / _ \| |   | ' / ",
    r"  ___) |  __/ ___ \ |___| |___   / ___ \| |   | |/ ___ \ |___| . \ ",
    r" |____/|_| /_/   \_\____|_____| /_/   \_\_|   |_/_/   \_\____|_|\_" + "\\",
]
LOGO_W = max(len(line) for line in LOGO)

# ── Colors ──────────────────────────────────────────────────────────────
C_PLAYER       = 1
C_FIGHTER_A    = 2
C_FIGHTER_B    = 3
C_BOMBER       = 4
C_BUNKER       = 5
C_PROJ_PLAYER  = 6
C_PROJ_ALIEN   = 7
C_BOMB         = 8
C_BORDER       = 9
C_STATUS       = 10
C_MSG          = 11
C_HP_MID       = 12
C_HP_LOW       = 13
C_EXPLOSION    = 14
C_LOGO         = 15
C_MENU_SEL     = 16
C_MENU         = 17

# ── Speeds (in frames) ─────────────────────────────────────────────────
PROJ_MOVE_INTERVAL    = 2
BOMB_MOVE_INTERVAL    = 3
BOMB_BLAST_RADIUS     = 2
LASER_BLAST_RADIUS    = 1
PLAYER_SHOOT_COOLDOWN = 5

# ── Alien HP ────────────────────────────────────────────────────────────
FIGHTER_HP = 2
BOMBER_HP  = 3


# ════════════════════════════════════════════════════════════════════════
#  Entity classes
# ════════════════════════════════════════════════════════════════════════

class Entity:
    def __init__(self, x, y, sprite):
        self.x = x
        self.y = y
        self.sprite = sprite
        self.alive = True

    @property
    def w(self):
        return max(len(row) for row in self.sprite)

    @property
    def h(self):
        return len(self.sprite)

    def draw(self, win, color_pair):
        for row_i, row in enumerate(self.sprite):
            for col_i, ch in enumerate(row):
                if ch == " ":
                    continue
                sy = self.y + row_i
                sx = self.x + col_i
                if 0 <= sx < INNER_W and 0 <= sy < INNER_H:
                    try:
                        win.addstr(sy + 1, sx + 1, ch, curses.color_pair(color_pair))
                    except curses.error:
                        pass


class Player(Entity):
    def __init__(self):
        x = (INNER_W - 4) // 2
        y = INNER_H - 2
        super().__init__(x, y, PLAYER_SPRITE)
        self.cooldown = 0

    def move_left(self):
        self.x = max(0, self.x - 1)

    def move_right(self):
        self.x = min(INNER_W - self.w, self.x + 1)

    def shoot(self):
        if self.cooldown > 0:
            return None
        self.cooldown = PLAYER_SHOOT_COOLDOWN
        px = self.x + self.w // 2
        py = self.y - 1
        return Projectile(px, py, -1)

    def tick(self):
        if self.cooldown > 0:
            self.cooldown -= 1


class Alien(Entity):
    is_bomber = False
    points = 100
    color = C_FIGHTER_A

    def __init__(self, x, y, sprite, hp, shoot_chance):
        super().__init__(x, y, sprite)
        self.hp = hp
        self.max_hp = hp
        self.shoot_chance = shoot_chance

    def take_hit(self):
        self.hp -= 1
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def try_shoot(self):
        if random.random() < self.shoot_chance:
            px = self.x + self.w // 2
            py = self.y + self.h
            return Projectile(px, py, 1)
        return None

    def hp_color(self):
        ratio = self.hp / self.max_hp
        if ratio > 0.6:
            return self.color
        elif ratio > 0.3:
            return C_HP_MID
        else:
            return C_HP_LOW

    def draw(self, win, color_pair=None):
        super().draw(win, self.hp_color())


class Fighter(Alien):
    is_bomber = False
    points = 100

    def __init__(self, x, y, shoot_chance, variant=0):
        sprite = FIGHTER_SPRITE_A if variant == 0 else FIGHTER_SPRITE_B
        self.color = C_FIGHTER_A if variant == 0 else C_FIGHTER_B
        super().__init__(x, y, sprite, FIGHTER_HP, shoot_chance)


class Bomber(Alien):
    is_bomber = True
    points = 150
    color = C_BOMBER

    def __init__(self, x, y, shoot_chance):
        super().__init__(x, y, BOMBER_SPRITE, BOMBER_HP, shoot_chance)

    def try_shoot(self):
        if random.random() < self.shoot_chance:
            px = self.x + self.w // 2
            py = self.y + self.h
            return Bomb(px, py)
        return None


def make_alien_grid(shoot_chance):
    cols, rows = 8, 5
    alien_w = 4
    h_gap = 3
    v_gap = 1
    grid_w = cols * alien_w + (cols - 1) * h_gap
    start_x = (INNER_W - grid_w) // 2
    start_y = 2
    aliens = []
    for r in range(rows):
        for c in range(cols):
            ax = start_x + c * (alien_w + h_gap)
            ay = start_y + r * (3 + v_gap)
            if r < 2:
                aliens.append(Bomber(ax, ay, shoot_chance))
            else:
                aliens.append(Fighter(ax, ay, shoot_chance, variant=c % 2))
    return aliens


class Bunker(Entity):
    def __init__(self, x, y):
        grid = [row[:] for row in BUNKER_TEMPLATE]
        sprite = ["".join(r) for r in grid]
        super().__init__(x, y, sprite)
        self.grid = grid

    def damage_at(self, gx, gy):
        lx = gx - self.x
        ly = gy - self.y
        if 0 <= lx < len(self.grid[0]) and 0 <= ly < len(self.grid):
            if self.grid[ly][lx] != " ":
                self.grid[ly][lx] = " "
                self._rebuild_sprite()
                return True
        return False

    def damage_area(self, gx, gy, radius):
        hit = False
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                lx = (gx + dx) - self.x
                ly = (gy + dy) - self.y
                if 0 <= lx < len(self.grid[0]) and 0 <= ly < len(self.grid):
                    if self.grid[ly][lx] != " ":
                        self.grid[ly][lx] = " "
                        hit = True
        if hit:
            self._rebuild_sprite()
        return hit

    def _rebuild_sprite(self):
        self.sprite = ["".join(r) for r in self.grid]

    @property
    def is_destroyed(self):
        return all(ch == " " for row in self.grid for ch in row)


class Projectile(Entity):
    is_bomb = False

    def __init__(self, x, y, direction):
        ch = "|" if direction == -1 else ":"
        super().__init__(x, y, [ch])
        self.direction = direction
        self.move_timer = 0

    def update(self):
        self.move_timer += 1
        if self.move_timer < PROJ_MOVE_INTERVAL:
            return
        self.move_timer = 0
        self.y += self.direction

    def out_of_bounds(self):
        return self.y < 0 or self.y >= INNER_H


class Bomb(Projectile):
    is_bomb = True

    def __init__(self, x, y):
        super().__init__(x, y, 1)
        self.sprite = ["*"]

    def update(self):
        self.move_timer += 1
        if self.move_timer < BOMB_MOVE_INTERVAL:
            return
        self.move_timer = 0
        self.y += self.direction


class Explosion:
    """Visual-only explosion effect that lasts a few frames."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.frame = 0
        self.alive = True

    def update(self):
        self.frame += 1
        if self.frame >= EXPLOSION_DURATION:
            self.alive = False

    def draw(self, win):
        if not self.alive:
            return
        sprite = EXPLOSION_FRAMES[self.frame]
        cx = self.x - 1
        cy = self.y - 1
        for row_i, row in enumerate(sprite):
            for col_i, ch in enumerate(row):
                if ch == " ":
                    continue
                sy = cy + row_i
                sx = cx + col_i
                if 0 <= sx < INNER_W and 0 <= sy < INNER_H:
                    try:
                        win.addstr(sy + 1, sx + 1, ch,
                                   curses.color_pair(C_EXPLOSION) | curses.A_BOLD)
                    except curses.error:
                        pass


# ── Collision helpers ───────────────────────────────────────────────────

def collides(proj, entity):
    return (entity.x <= proj.x < entity.x + entity.w and
            entity.y <= proj.y < entity.y + entity.h)


def projectile_hits_bunker(proj, bunker):
    if not collides(proj, bunker):
        return False
    if proj.is_bomb:
        return bunker.damage_area(proj.x, proj.y, BOMB_BLAST_RADIUS)
    if proj.direction == 1:
        return bunker.damage_area(proj.x, proj.y, LASER_BLAST_RADIUS)
    return bunker.damage_at(proj.x, proj.y)


# ════════════════════════════════════════════════════════════════════════
#  Title Screen
# ════════════════════════════════════════════════════════════════════════

def show_title(stdscr):
    """Show logo and difficulty menu. Returns difficulty key or None to quit."""
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.clear()
    term_h, term_w = stdscr.getmaxyx()
    selected = 1  # default to medium

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        # draw logo centered (all lines use same x based on max width)
        logo_start_y = max(1, (term_h - 20) // 2)
        logo_x = max(0, (term_w - LOGO_W) // 2)
        for i, line in enumerate(LOGO):
            if logo_start_y + i >= term_h:
                break
            max_chars = term_w - logo_x
            if max_chars <= 0:
                continue
            try:
                stdscr.addstr(logo_start_y + i, logo_x, line[:max_chars],
                              curses.color_pair(C_LOGO) | curses.A_BOLD)
            except curses.error:
                pass

        # subtitle
        sub = "~ Defend Earth from the alien invasion ~"
        sub_y = logo_start_y + len(LOGO) + 1
        if sub_y < term_h:
            sx = max(0, (term_w - len(sub)) // 2)
            try:
                stdscr.addstr(sub_y, sx, sub[:term_w - sx],
                              curses.color_pair(C_MENU))
            except curses.error:
                pass

        # difficulty menu
        menu_y = logo_start_y + len(LOGO) + 4
        header = "SELECT DIFFICULTY"
        if menu_y < term_h:
            hx = max(0, (term_w - len(header)) // 2)
            try:
                stdscr.addstr(menu_y, hx, header[:term_w - hx],
                              curses.color_pair(C_MSG) | curses.A_BOLD)
            except curses.error:
                pass

        for i, key in enumerate(DIFF_ORDER):
            row_y = menu_y + 2 + i
            if row_y >= term_h:
                break
            label, _, _, desc = DIFFICULTIES[key]
            line = f"  {label:<12} {desc}"
            lx = max(0, (term_w - 40) // 2)
            if i == selected:
                attr = curses.color_pair(C_MENU_SEL) | curses.A_BOLD
                line = "> " + line[2:]
            else:
                attr = curses.color_pair(C_MENU)
            try:
                stdscr.addstr(row_y, lx, line[:term_w - lx], attr)
            except curses.error:
                pass

        # controls hint
        hint = "UP/DOWN = Select   ENTER = Start   Q = Quit"
        hint_y = menu_y + 8
        if hint_y < term_h:
            hintx = max(0, (term_w - len(hint)) // 2)
            try:
                stdscr.addstr(hint_y, hintx, hint[:term_w - hintx],
                              curses.color_pair(C_STATUS))
            except curses.error:
                pass

        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            stdscr.clear()
            continue
        if key == ord("q") or key == ord("Q"):
            return None
        elif key == curses.KEY_UP:
            selected = (selected - 1) % len(DIFF_ORDER)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(DIFF_ORDER)
        elif key in (curses.KEY_ENTER, 10, 13):
            return DIFF_ORDER[selected]


# ════════════════════════════════════════════════════════════════════════
#  Game
# ════════════════════════════════════════════════════════════════════════

class Game:
    def __init__(self, stdscr, difficulty):
        self.stdscr = stdscr
        self.difficulty = difficulty
        _, self.shoot_chance, self.move_interval, _ = DIFFICULTIES[difficulty]
        self.setup_curses()
        self.reset()

    def setup_curses(self):
        curses.curs_set(0)
        self.stdscr.nodelay(True)

        term_h, term_w = self.stdscr.getmaxyx()
        oy = max(1, (term_h - WIN_H) // 2)
        ox = max(0, (term_w - WIN_W) // 2)
        self.field_win = curses.newwin(WIN_H, WIN_W, oy, ox)
        self.status_y = oy - 1 if oy > 0 else 0
        self.field_ox = ox

    def reset(self):
        self.state = "playing"
        self.score = 0
        self.player = Player()
        self.aliens = make_alien_grid(self.shoot_chance)
        self.alien_dir = 1
        self.alien_move_timer = 0
        by = INNER_H - 10
        spacing = INNER_W // 5
        self.bunkers = [
            Bunker(spacing * 1 - 4, by),
            Bunker(spacing * 2 - 4, by),
            Bunker(spacing * 3 - 4, by),
            Bunker(spacing * 4 - 4, by),
        ]
        self.projectiles = []
        self.explosions = []

    # ── Input ───────────────────────────────────────────────────────────
    def handle_input(self):
        while True:
            key = self.stdscr.getch()
            if key == -1:
                break
            if key == ord("q") or key == ord("Q"):
                return "quit"
            if self.state != "playing":
                if key == ord("r") or key == ord("R"):
                    self.reset()
                elif key == ord("m") or key == ord("M"):
                    return "menu"
                continue
            if key == curses.KEY_LEFT:
                self.player.move_left()
            elif key == curses.KEY_RIGHT:
                self.player.move_right()
            elif key == ord(" "):
                p = self.player.shoot()
                if p:
                    self.projectiles.append(p)
        return None

    # ── Update ──────────────────────────────────────────────────────────
    def _alive_aliens(self):
        return [a for a in self.aliens if a.alive]

    def _spawn_explosion(self, x, y):
        self.explosions.append(Explosion(x, y))

    def update(self):
        if self.state != "playing":
            return

        self.player.tick()
        alive = self._alive_aliens()

        # update explosions
        for e in self.explosions:
            e.update()
        self.explosions = [e for e in self.explosions if e.alive]

        # alien formation movement
        self.alien_move_timer += 1
        if self.alien_move_timer >= self.move_interval and alive:
            self.alien_move_timer = 0
            reverse = False
            for a in alive:
                nx = a.x + self.alien_dir
                if nx <= 0 or nx >= INNER_W - a.w:
                    reverse = True
                    break
            if reverse:
                self.alien_dir *= -1
                for a in alive:
                    a.y += 1
            else:
                for a in alive:
                    a.x += self.alien_dir

        # check if any alien reached bottom
        for a in alive:
            if a.y + a.h >= INNER_H:
                self.state = "lost"
                return

        # random alien shoots
        if alive:
            shooter = random.choice(alive)
            ap = shooter.try_shoot()
            if ap:
                self.projectiles.append(ap)

        # move projectiles
        for p in self.projectiles:
            p.update()

        # remove out-of-bounds
        self.projectiles = [p for p in self.projectiles if not p.out_of_bounds()]

        # collision detection
        remaining = []
        for p in self.projectiles:
            hit = False
            if p.direction == -1:
                # player projectile -> aliens
                for a in alive:
                    if a.alive and collides(p, a):
                        dead = a.take_hit()
                        self._spawn_explosion(p.x, p.y)
                        if dead:
                            self.score += a.points
                        hit = True
                        break
                # player projectile -> bunkers
                if not hit:
                    for b in self.bunkers:
                        if not b.is_destroyed and projectile_hits_bunker(p, b):
                            self._spawn_explosion(p.x, p.y)
                            hit = True
                            break
            else:
                # alien projectile -> player
                if collides(p, self.player):
                    self._spawn_explosion(p.x, p.y)
                    self.state = "lost"
                    hit = True
                # alien projectile -> bunkers
                if not hit:
                    for b in self.bunkers:
                        if not b.is_destroyed and projectile_hits_bunker(p, b):
                            self._spawn_explosion(p.x, p.y)
                            hit = True
                            break
            if not hit:
                remaining.append(p)
        self.projectiles = remaining

        if not self._alive_aliens():
            self.state = "won"

        if all(b.is_destroyed for b in self.bunkers):
            self.state = "lost"

    # ── Draw ────────────────────────────────────────────────────────────
    def draw(self):
        win = self.field_win
        win.erase()
        win.border()

        # entities
        self.player.draw(win, C_PLAYER)
        for a in self.aliens:
            if a.alive:
                a.draw(win)
        for b in self.bunkers:
            if not b.is_destroyed:
                b.draw(win, C_BUNKER)
        for p in self.projectiles:
            if p.direction == -1:
                color = C_PROJ_PLAYER
            elif p.is_bomb:
                color = C_BOMB
            else:
                color = C_PROJ_ALIEN
            p.draw(win, color)

        # explosions on top
        for e in self.explosions:
            e.draw(win)

        # end-state overlay
        if self.state in ("won", "lost"):
            msg1 = "YOU WIN!" if self.state == "won" else "GAME OVER"
            msg2 = f"Score: {self.score}"
            msg3 = "R=Restart  M=Menu  Q=Quit"
            cy = WIN_H // 2
            cx1 = (WIN_W - len(msg1)) // 2
            cx2 = (WIN_W - len(msg2)) // 2
            cx3 = (WIN_W - len(msg3)) // 2
            try:
                win.addstr(cy - 2, cx1, msg1, curses.color_pair(C_MSG) | curses.A_BOLD)
                win.addstr(cy,     cx2, msg2, curses.color_pair(C_MSG))
                win.addstr(cy + 2, cx3, msg3, curses.color_pair(C_MSG))
            except curses.error:
                pass

        # status bar
        alive_count = sum(1 for a in self.aliens if a.alive)
        diff_label = DIFFICULTIES[self.difficulty][0]
        status = (f" SPACE ATTACK  [{diff_label}]   "
                  f"Score: {self.score}   Aliens: {alive_count}   "
                  f"Arrows=Move  Space=Shoot  Q=Quit")
        try:
            self.stdscr.addstr(self.status_y, self.field_ox,
                               status[:WIN_W].ljust(WIN_W),
                               curses.color_pair(C_STATUS) | curses.A_BOLD)
        except curses.error:
            pass

        self.stdscr.noutrefresh()
        win.noutrefresh()
        curses.doupdate()

    # ── Main loop ───────────────────────────────────────────────────────
    def run(self):
        while True:
            t0 = time.monotonic()
            action = self.handle_input()
            if action == "quit":
                return "quit"
            if action == "menu":
                return "menu"
            self.update()
            self.draw()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            remaining = max(0, FRAME_MS - elapsed_ms)
            curses.napms(remaining)


# ════════════════════════════════════════════════════════════════════════

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_PLAYER,      curses.COLOR_GREEN,   -1)
    curses.init_pair(C_FIGHTER_A,   curses.COLOR_RED,     -1)
    curses.init_pair(C_FIGHTER_B,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_BOMBER,      curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_BUNKER,      curses.COLOR_CYAN,    -1)
    curses.init_pair(C_PROJ_PLAYER, curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_PROJ_ALIEN,  curses.COLOR_RED,     -1)
    curses.init_pair(C_BOMB,        curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_BORDER,      curses.COLOR_WHITE,   -1)
    curses.init_pair(C_STATUS,      curses.COLOR_WHITE,   -1)
    curses.init_pair(C_MSG,         curses.COLOR_YELLOW,  curses.COLOR_BLACK)
    curses.init_pair(C_HP_MID,      curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_HP_LOW,      curses.COLOR_WHITE,   -1)
    curses.init_pair(C_EXPLOSION,   curses.COLOR_RED,     -1)
    curses.init_pair(C_LOGO,        curses.COLOR_CYAN,    -1)
    curses.init_pair(C_MENU_SEL,    curses.COLOR_GREEN,   -1)
    curses.init_pair(C_MENU,        curses.COLOR_WHITE,   -1)


def main(stdscr):
    init_colors()

    while True:
        difficulty = show_title(stdscr)
        if difficulty is None:
            break
        stdscr.clear()
        stdscr.refresh()
        result = Game(stdscr, difficulty).run()
        if result == "quit":
            break
        # result == "menu" loops back to title


if __name__ == "__main__":
    curses.wrapper(main)
