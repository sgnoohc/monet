#!/usr/bin/env python3
"""Curses TUI calculator with switchable skins (Office / TI-83)."""

import curses
import math
import re
import time
import sys

# ─── Expression Engine ────────────────────────────────────────────────────────

# Token types
NUM, OP, FUNC, CONST, LPAR, RPAR = "NUM", "OP", "FUNC", "CONST", "LPAR", "RPAR"

TOKEN_RE = re.compile(r"""
    (?P<NUM>\d+\.?\d*|\.\d+)                     |
    (?P<FUNC>sin|cos|tan|log|ln|sqrt)(?=\()      |
    (?P<CONST>pi|e|ANS)                           |
    (?P<OP>[+\-*/%^])                             |
    (?P<LPAR>\()                                  |
    (?P<RPAR>\))                                  |
    (?P<WS>\s+)
""", re.VERBOSE)


def tokenize(expr):
    """Tokenize expression string into (type, value) pairs."""
    tokens = []
    for m in TOKEN_RE.finditer(expr):
        if m.lastgroup == "WS":
            continue
        tokens.append((m.lastgroup, m.group()))
    return tokens


def _insert_implicit_mult(tokens):
    """Insert * between adjacent tokens where multiplication is implied."""
    result = []
    for i, tok in enumerate(tokens):
        result.append(tok)
        if i + 1 < len(tokens):
            cur_t, _ = tok
            nxt_t, _ = tokens[i + 1]
            # Cases: NUM LPAR, NUM FUNC, NUM CONST, RPAR LPAR, RPAR FUNC,
            #        RPAR NUM, CONST LPAR, CONST FUNC, CONST NUM, RPAR CONST,
            #        CONST CONST, NUM NUM (shouldn't happen but safe)
            if cur_t in (NUM, RPAR, CONST) and nxt_t in (NUM, LPAR, FUNC, CONST):
                result.append((OP, "*"))
    return result


class CalcEngine:
    """Pure math engine — no UI. Recursive-descent parser."""

    def __init__(self):
        self.expression = ""
        self.result = ""
        self.ans = 0.0
        self.error = False

    def append(self, text):
        if self.error:
            self.expression = ""
            self.result = ""
            self.error = False
        self.expression += text

    def backspace(self):
        if self.error:
            self.expression = ""
            self.result = ""
            self.error = False
        else:
            self.expression = self.expression[:-1]

    def clear(self):
        self.expression = ""
        self.result = ""
        self.error = False

    def evaluate(self):
        if not self.expression.strip():
            return
        try:
            tokens = tokenize(self.expression)
            tokens = _insert_implicit_mult(tokens)
            parser = _Parser(tokens, self.ans)
            val = parser.parse_expr()
            if parser.pos < len(parser.tokens):
                raise ValueError("Unexpected token")
            if isinstance(val, float) and val == int(val) and abs(val) < 1e15:
                val = int(val)
            self.ans = float(val)
            self.result = str(val)
            self.error = False
        except Exception:
            self.result = "Error"
            self.error = True


class _Parser:
    """Recursive-descent parser for math expressions."""

    def __init__(self, tokens, ans_val):
        self.tokens = tokens
        self.pos = 0
        self.ans = ans_val

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def _eat(self, expected_type=None, expected_val=None):
        t, v = self._peek()
        if expected_type and t != expected_type:
            raise ValueError(f"Expected {expected_type}, got {t}")
        if expected_val and v != expected_val:
            raise ValueError(f"Expected {expected_val}, got {v}")
        self.pos += 1
        return (t, v)

    def parse_expr(self):
        """expr = term (('+' | '-') term)*"""
        left = self.parse_term()
        while True:
            t, v = self._peek()
            if t == OP and v in ("+", "-"):
                self._eat()
                right = self.parse_term()
                left = left + right if v == "+" else left - right
            else:
                break
        return left

    def parse_term(self):
        """term = unary (('*' | '/' | '%') unary)*"""
        left = self.parse_unary()
        while True:
            t, v = self._peek()
            if t == OP and v in ("*", "/", "%"):
                self._eat()
                right = self.parse_unary()
                if v == "*":
                    left = left * right
                elif v == "/":
                    if right == 0:
                        raise ValueError("Division by zero")
                    left = left / right
                else:
                    left = left % right
            else:
                break
        return left

    def parse_unary(self):
        """unary = '-' unary | power"""
        t, v = self._peek()
        if t == OP and v == "-":
            self._eat()
            return -self.parse_unary()
        return self.parse_power()

    def parse_power(self):
        """power = atom ('^' unary)  — right-associative"""
        base = self.parse_atom()
        t, v = self._peek()
        if t == OP and v == "^":
            self._eat()
            exp = self.parse_unary()
            return base ** exp
        return base

    def parse_atom(self):
        """atom = NUM | CONST | FUNC '(' expr ')' | '(' expr ')'"""
        t, v = self._peek()
        if t == NUM:
            self._eat()
            return float(v)
        if t == CONST:
            self._eat()
            if v == "pi":
                return math.pi
            elif v == "e":
                return math.e
            elif v == "ANS":
                return self.ans
        if t == FUNC:
            _, fname = self._eat()
            self._eat(LPAR)
            arg = self.parse_expr()
            self._eat(RPAR)
            funcs = {
                "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log10, "ln": math.log, "sqrt": math.sqrt,
            }
            return funcs[fname](arg)
        if t == LPAR:
            self._eat()
            val = self.parse_expr()
            self._eat(RPAR)
            return val
        raise ValueError(f"Unexpected: {t} {v}")


# ─── Color Pairs ──────────────────────────────────────────────────────────────

# Office skin color pair IDs (20-29)
C_OFF_BODY = 20
C_OFF_DISPLAY = 21
C_OFF_NUM = 22
C_OFF_OPER = 23
C_OFF_FUNC = 24
C_OFF_SPECIAL = 25
C_OFF_EQUALS = 26
C_OFF_HIGHLIGHT = 27
C_OFF_FRAME = 28

# TI-83 skin color pair IDs (30-39)
C_TI_BODY = 30
C_TI_DISPLAY = 31
C_TI_TOPROW = 32
C_TI_FUNCROW = 33
C_TI_NUM = 34
C_TI_OPER = 35
C_TI_ENTER = 36
C_TI_HIGHLIGHT = 37
C_TI_FRAME = 38

C_STATUS = 40


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    hi = curses.COLORS >= 256

    # Office
    if hi:
        curses.init_pair(C_OFF_BODY, curses.COLOR_WHITE, 236)
        curses.init_pair(C_OFF_DISPLAY, curses.COLOR_GREEN, 22)
        curses.init_pair(C_OFF_NUM, curses.COLOR_WHITE, 240)
        curses.init_pair(C_OFF_OPER, curses.COLOR_WHITE, 172)
        curses.init_pair(C_OFF_FUNC, curses.COLOR_WHITE, 24)
        curses.init_pair(C_OFF_SPECIAL, curses.COLOR_WHITE, 124)
        curses.init_pair(C_OFF_EQUALS, curses.COLOR_WHITE, 28)
        curses.init_pair(C_OFF_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(C_OFF_FRAME, curses.COLOR_WHITE, 236)
    else:
        curses.init_pair(C_OFF_BODY, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_DISPLAY, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_NUM, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_OPER, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_FUNC, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_SPECIAL, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_EQUALS, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(C_OFF_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(C_OFF_FRAME, curses.COLOR_WHITE, curses.COLOR_BLACK)

    # TI-83
    if hi:
        curses.init_pair(C_TI_BODY, curses.COLOR_WHITE, 235)
        curses.init_pair(C_TI_DISPLAY, curses.COLOR_GREEN, 58)
        curses.init_pair(C_TI_TOPROW, curses.COLOR_WHITE, 17)
        curses.init_pair(C_TI_FUNCROW, curses.COLOR_YELLOW, 238)
        curses.init_pair(C_TI_NUM, curses.COLOR_WHITE, 233)
        curses.init_pair(C_TI_OPER, curses.COLOR_WHITE, 25)
        curses.init_pair(C_TI_ENTER, curses.COLOR_WHITE, 17)
        curses.init_pair(C_TI_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(C_TI_FRAME, curses.COLOR_WHITE, 235)
    else:
        curses.init_pair(C_TI_BODY, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(C_TI_DISPLAY, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(C_TI_TOPROW, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(C_TI_FUNCROW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(C_TI_NUM, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(C_TI_OPER, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(C_TI_ENTER, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(C_TI_HIGHLIGHT, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(C_TI_FRAME, curses.COLOR_WHITE, curses.COLOR_BLACK)

    curses.init_pair(C_STATUS, curses.COLOR_WHITE, curses.COLOR_BLUE)


# ─── Skin Base & Definitions ─────────────────────────────────────────────────

# Button categories for color mapping
CAT_NUM = "num"
CAT_OPER = "oper"
CAT_FUNC = "func"
CAT_SPECIAL = "special"
CAT_EQUALS = "equals"
CAT_TOPROW = "toprow"    # TI-83 specific
CAT_FUNCROW = "funcrow"  # TI-83 specific

# Button width/height
BTN_W = 8   # chars wide including border
BTN_H = 3   # rows tall including border
BTN_GAP = 1 # gap between buttons


class Button:
    """A calculator button."""
    __slots__ = ("label", "action", "category")

    def __init__(self, label, action=None, category=CAT_NUM):
        self.label = label
        self.action = action or label  # what gets appended to expression
        self.category = category


class Skin:
    """Base class for calculator skins."""

    name = ""
    cols = 0
    rows = 0
    buttons = []  # list of lists (row x col)

    # Color pair mapping: category -> color pair id
    color_map = {}
    body_color = 0
    display_color = 0
    frame_color = 0
    highlight_color = 0
    title_lines = []  # header text lines

    def total_width(self):
        return self.cols * (BTN_W + BTN_GAP) - BTN_GAP + 4  # 2 border + 2 pad

    def total_height(self):
        # title + display(4) + gap(1) + button grid + border(2) + status(1)
        return len(self.title_lines) + 4 + 1 + self.rows * (BTN_H + BTN_GAP) - BTN_GAP + 3

    def btn_color(self, btn):
        return self.color_map.get(btn.category, self.color_map.get(CAT_NUM, 0))


class OfficeSkin(Skin):
    name = "Office Calculator"
    cols = 4
    rows = 8
    title_lines = ["OFFICE CALCULATOR"]

    buttons = [
        [Button("AC", "CLEAR", CAT_SPECIAL), Button("BS", "BS", CAT_SPECIAL),
         Button("%", "%", CAT_OPER), Button("/", "/", CAT_OPER)],
        [Button("7", "7"), Button("8", "8"), Button("9", "9"), Button("*", "*", CAT_OPER)],
        [Button("4", "4"), Button("5", "5"), Button("6", "6"), Button("-", "-", CAT_OPER)],
        [Button("1", "1"), Button("2", "2"), Button("3", "3"), Button("+", "+", CAT_OPER)],
        [Button("0", "0"), Button(".", "."), Button("(", "("), Button(")", ")")],
        [Button("sin", "sin(", CAT_FUNC), Button("cos", "cos(", CAT_FUNC),
         Button("tan", "tan(", CAT_FUNC), Button("^", "^", CAT_OPER)],
        [Button("log", "log(", CAT_FUNC), Button("ln", "ln(", CAT_FUNC),
         Button("sqrt", "sqrt(", CAT_FUNC), Button("pi", "pi", CAT_FUNC)],
        [Button("e", "e", CAT_FUNC), Button("ANS", "ANS", CAT_FUNC),
         Button("EXE", "EVAL", CAT_EQUALS), Button("OFF", "QUIT", CAT_SPECIAL)],
    ]

    color_map = {
        CAT_NUM: C_OFF_NUM,
        CAT_OPER: C_OFF_OPER,
        CAT_FUNC: C_OFF_FUNC,
        CAT_SPECIAL: C_OFF_SPECIAL,
        CAT_EQUALS: C_OFF_EQUALS,
    }
    body_color = C_OFF_BODY
    display_color = C_OFF_DISPLAY
    frame_color = C_OFF_FRAME
    highlight_color = C_OFF_HIGHLIGHT


class TI83Skin(Skin):
    name = "TI-83 Plus"
    cols = 5
    rows = 8
    title_lines = ["TEXAS INSTRUMENTS", "TI-83 Plus"]

    buttons = [
        [Button("2nd", "2ND", CAT_TOPROW), Button("MODE", "MODE", CAT_TOPROW),
         Button("DEL", "BS", CAT_TOPROW), Button("ALPH", "ALPH", CAT_TOPROW),
         Button("CLR", "CLEAR", CAT_TOPROW)],
        [Button("sin", "sin(", CAT_FUNCROW), Button("cos", "cos(", CAT_FUNCROW),
         Button("tan", "tan(", CAT_FUNCROW), Button("^", "^", CAT_FUNCROW),
         Button("sqrt", "sqrt(", CAT_FUNCROW)],
        [Button("log", "log(", CAT_FUNC), Button("ln", "ln(", CAT_FUNC),
         Button("(", "("), Button(")", ")"), Button("/", "/", CAT_OPER)],
        [Button("7", "7"), Button("8", "8"), Button("9", "9"),
         Button("*", "*", CAT_OPER), Button("ANS", "ANS", CAT_FUNC)],
        [Button("4", "4"), Button("5", "5"), Button("6", "6"),
         Button("-", "-", CAT_OPER), Button("pi", "pi", CAT_FUNC)],
        [Button("1", "1"), Button("2", "2"), Button("3", "3"),
         Button("+", "+", CAT_OPER), Button("e", "e", CAT_FUNC)],
        [Button("0", "0"), Button(".", "."), Button("(-)", "NEG"),
         Button("%", "%", CAT_OPER), Button("OFF", "QUIT", CAT_SPECIAL)],
        [Button("ENTER", "EVAL", CAT_EQUALS), Button("ENTER", "EVAL", CAT_EQUALS),
         Button("ENTER", "EVAL", CAT_EQUALS), Button("ENTER", "EVAL", CAT_EQUALS),
         Button("ENTER", "EVAL", CAT_EQUALS)],
    ]

    color_map = {
        CAT_NUM: C_TI_NUM,
        CAT_OPER: C_TI_OPER,
        CAT_FUNC: C_TI_NUM,
        CAT_TOPROW: C_TI_TOPROW,
        CAT_FUNCROW: C_TI_FUNCROW,
        CAT_EQUALS: C_TI_ENTER,
        CAT_SPECIAL: C_TI_TOPROW,
    }
    body_color = C_TI_BODY
    display_color = C_TI_DISPLAY
    frame_color = C_TI_FRAME
    highlight_color = C_TI_HIGHLIGHT


# ─── CalcApp ──────────────────────────────────────────────────────────────────

class CalcApp:
    """Main curses application."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.engine = CalcEngine()
        self.skins = [OfficeSkin(), TI83Skin()]
        self.skin_idx = 0
        self.cursor_row = 0
        self.cursor_col = 0
        self._pressed = None  # (row, col) for flash effect
        self._pressed_time = 0

    @property
    def skin(self):
        return self.skins[self.skin_idx]

    def _safe_addstr(self, win, y, x, text, attr=0):
        """Write string, clipping to window bounds."""
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x >= max_x:
            return
        avail = max_x - x - 1
        if avail <= 0:
            return
        text = text[:avail]
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _clamp_cursor(self):
        skin = self.skin
        self.cursor_row = max(0, min(self.cursor_row, skin.rows - 1))
        self.cursor_col = max(0, min(self.cursor_col, skin.cols - 1))

    def _handle_action(self, action):
        """Process a button action."""
        if action == "CLEAR":
            self.engine.clear()
        elif action == "BS":
            self.engine.backspace()
        elif action == "EVAL":
            self.engine.evaluate()
        elif action == "QUIT":
            return False
        elif action == "NEG":
            self.engine.append("(-")
        elif action in ("2ND", "MODE", "ALPH"):
            pass  # no-op for now
        else:
            self.engine.append(action)
        return True

    def _draw_button(self, win, y, x, btn, highlighted, pressed):
        """Draw a single 8x3 button."""
        skin = self.skin
        if highlighted:
            attr = curses.color_pair(skin.highlight_color) | curses.A_BOLD
        else:
            attr = curses.color_pair(skin.btn_color(btn))

        label = btn.label
        pad_total = BTN_W - 2 - len(label)
        pad_l = pad_total // 2
        pad_r = pad_total - pad_l
        centered = " " * pad_l + label + " " * pad_r

        if pressed:
            # Pressed flash: filled block borders
            self._safe_addstr(win, y,     x, "▄" + "█" * (BTN_W - 2) + "▄", attr)
            self._safe_addstr(win, y + 1, x, "█" + centered + "█", attr)
            self._safe_addstr(win, y + 2, x, "▀" + "█" * (BTN_W - 2) + "▀", attr)
        else:
            # Normal: box-drawing border
            self._safe_addstr(win, y,     x, "┌" + "─" * (BTN_W - 2) + "┐", attr)
            self._safe_addstr(win, y + 1, x, "│" + centered + "│", attr)
            self._safe_addstr(win, y + 2, x, "└" + "─" * (BTN_W - 2) + "┘", attr)

    def _draw(self):
        """Full redraw."""
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        skin = self.skin

        needed_w = skin.total_width()
        needed_h = skin.total_height()

        if max_y < needed_h or max_x < needed_w:
            msg = f"Terminal too small ({max_x}x{max_y}), need {needed_w}x{needed_h}"
            try:
                self.stdscr.addstr(max_y // 2, max(0, (max_x - len(msg)) // 2), msg[:max_x - 1])
            except curses.error:
                pass
            self.stdscr.refresh()
            return

        body_attr = curses.color_pair(skin.body_color)
        frame_attr = curses.color_pair(skin.frame_color)
        disp_attr = curses.color_pair(skin.display_color)

        # Center the calculator
        off_x = (max_x - needed_w) // 2
        off_y = (max_y - needed_h - 1) // 2  # -1 for status bar
        if off_y < 0:
            off_y = 0

        # Fill body background
        for row in range(off_y, off_y + needed_h - 1):
            self._safe_addstr(self.stdscr, row, off_x, " " * needed_w, body_attr)

        # Outer frame
        self._safe_addstr(self.stdscr, off_y, off_x,
                          "╔" + "═" * (needed_w - 2) + "╗", frame_attr)
        for row in range(off_y + 1, off_y + needed_h - 2):
            self._safe_addstr(self.stdscr, row, off_x, "║", frame_attr)
            self._safe_addstr(self.stdscr, row, off_x + needed_w - 1, "║", frame_attr)
        self._safe_addstr(self.stdscr, off_y + needed_h - 2, off_x,
                          "╚" + "═" * (needed_w - 2) + "╝", frame_attr)

        # Title
        cy = off_y + 1
        for line in skin.title_lines:
            tx = off_x + (needed_w - len(line)) // 2
            self._safe_addstr(self.stdscr, cy, tx, line, frame_attr | curses.A_BOLD)
            cy += 1

        # Display area
        disp_x = off_x + 2
        disp_w = needed_w - 4
        self._safe_addstr(self.stdscr, cy, disp_x,
                          "┌" + "─" * (disp_w - 2) + "┐", disp_attr)
        cy += 1
        # Result line (right-aligned)
        result_str = self.engine.result if self.engine.result else ""
        rpad = max(0, disp_w - 2 - len(result_str))
        self._safe_addstr(self.stdscr, cy, disp_x,
                          "│" + " " * rpad + result_str + " " * max(0, disp_w - 2 - rpad - len(result_str)) + "│",
                          disp_attr)
        cy += 1
        # Expression line (left-aligned with >)
        expr_str = "> " + self.engine.expression
        epad = max(0, disp_w - 2 - len(expr_str))
        self._safe_addstr(self.stdscr, cy, disp_x,
                          "│" + expr_str[:disp_w - 2] + " " * max(0, epad) + "│",
                          disp_attr)
        cy += 1
        self._safe_addstr(self.stdscr, cy, disp_x,
                          "└" + "─" * (disp_w - 2) + "┘", disp_attr)
        cy += 2  # gap

        # Button grid
        btn_off_x = off_x + 2
        now = time.monotonic()
        show_pressed = (self._pressed is not None and (now - self._pressed_time) < 0.15)

        # TI-83 ENTER row spans all 5 columns — draw as one wide button
        for r, btn_row in enumerate(skin.buttons):
            # Check if this is the ENTER mega-row (TI-83 last row)
            is_enter_row = (isinstance(skin, TI83Skin) and r == skin.rows - 1)

            if is_enter_row:
                # Draw one wide ENTER button spanning all columns
                btn = btn_row[0]
                by = cy + r * (BTN_H + BTN_GAP)
                bx = btn_off_x
                full_w = skin.cols * (BTN_W + BTN_GAP) - BTN_GAP
                highlighted = (r == self.cursor_row)
                pressed = show_pressed and self._pressed[0] == r

                if highlighted:
                    attr = curses.color_pair(skin.highlight_color) | curses.A_BOLD
                else:
                    attr = curses.color_pair(skin.btn_color(btn))

                label = "ENTER"
                pad_total = full_w - 2 - len(label)
                pad_l = pad_total // 2
                pad_r = pad_total - pad_l
                centered = " " * pad_l + label + " " * pad_r

                if pressed:
                    self._safe_addstr(self.stdscr, by,     bx, "▄" + "█" * (full_w - 2) + "▄", attr)
                    self._safe_addstr(self.stdscr, by + 1, bx, "█" + centered + "█", attr)
                    self._safe_addstr(self.stdscr, by + 2, bx, "▀" + "█" * (full_w - 2) + "▀", attr)
                else:
                    self._safe_addstr(self.stdscr, by,     bx, "┌" + "─" * (full_w - 2) + "┐", attr)
                    self._safe_addstr(self.stdscr, by + 1, bx, "│" + centered + "│", attr)
                    self._safe_addstr(self.stdscr, by + 2, bx, "└" + "─" * (full_w - 2) + "┘", attr)
            else:
                for c, btn in enumerate(btn_row):
                    bx = btn_off_x + c * (BTN_W + BTN_GAP)
                    by = cy + r * (BTN_H + BTN_GAP)
                    highlighted = (r == self.cursor_row and c == self.cursor_col)
                    pressed_here = show_pressed and self._pressed == (r, c)
                    self._draw_button(self.stdscr, by, bx, btn, highlighted, pressed_here)

        # Status bar
        status_y = max_y - 1
        status_attr = curses.color_pair(C_STATUS)
        skin_hint = "Office" if self.skin_idx == 0 else "TI-83"
        status = f" hjkl/arrows:move  Enter:press  s:skin({skin_hint})  q:quit  Type digits/ops directly "
        self._safe_addstr(self.stdscr, status_y, 0, status.ljust(max_x - 1), status_attr)

        self.stdscr.refresh()

    def _flash_button(self, row, col):
        """Trigger pressed flash for a button."""
        self._pressed = (row, col)
        self._pressed_time = time.monotonic()

    def _find_button_for_key(self, ch_str):
        """Find button (row, col) matching a direct-type key."""
        skin = self.skin
        # Map typed chars to button actions
        key_action_map = {
            "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
            "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
            ".": ".", "+": "+", "-": "-", "*": "*", "/": "/",
            "%": "%", "^": "^", "(": "(", ")": ")",
        }
        action = key_action_map.get(ch_str)
        if action is None:
            return None, None
        for r, btn_row in enumerate(skin.buttons):
            for c, btn in enumerate(btn_row):
                if btn.action == action:
                    return r, c
        return None, None

    def run(self):
        """Main event loop."""
        self.stdscr.keypad(True)
        curses.curs_set(0)
        self.stdscr.timeout(50)  # 50ms for flash timing
        _init_colors()
        self._clamp_cursor()

        while True:
            self._draw()

            ch = self.stdscr.getch()
            if ch == -1:
                continue

            skin = self.skin

            # TI-83 ENTER row: cursor_col doesn't matter
            is_enter_row = isinstance(skin, TI83Skin) and self.cursor_row == skin.rows - 1

            # Navigation
            if ch in (ord("h"), curses.KEY_LEFT):
                if not is_enter_row:
                    self.cursor_col = (self.cursor_col - 1) % skin.cols
            elif ch in (ord("l"), curses.KEY_RIGHT):
                if not is_enter_row:
                    self.cursor_col = (self.cursor_col + 1) % skin.cols
            elif ch in (ord("k"), curses.KEY_UP):
                self.cursor_row = (self.cursor_row - 1) % skin.rows
                # If moving to ENTER row, col doesn't matter; if leaving, clamp
                self._clamp_cursor()
            elif ch in (ord("j"), curses.KEY_DOWN):
                self.cursor_row = (self.cursor_row + 1) % skin.rows
                self._clamp_cursor()

            # Press button
            elif ch in (10, 13, ord(" ")):
                btn = skin.buttons[self.cursor_row][self.cursor_col]
                self._flash_button(self.cursor_row, self.cursor_col)
                self._draw()
                curses.napms(100)
                self._pressed = None
                if not self._handle_action(btn.action):
                    break

            # Toggle skin
            elif ch == ord("s"):
                self.skin_idx = (self.skin_idx + 1) % len(self.skins)
                self._clamp_cursor()

            # Quit
            elif ch == ord("q"):
                break

            # Direct typing: = triggers evaluate
            elif ch == ord("="):
                # Flash the EXE/ENTER button
                for r, btn_row in enumerate(skin.buttons):
                    for c, btn in enumerate(btn_row):
                        if btn.action == "EVAL":
                            self._flash_button(r, c)
                            break
                self._draw()
                curses.napms(100)
                self._pressed = None
                self.engine.evaluate()

            # c for clear
            elif ch == ord("c"):
                for r, btn_row in enumerate(skin.buttons):
                    for c, btn in enumerate(btn_row):
                        if btn.action == "CLEAR":
                            self._flash_button(r, c)
                            break
                self._draw()
                curses.napms(100)
                self._pressed = None
                self.engine.clear()

            # Backspace
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                for r, btn_row in enumerate(skin.buttons):
                    for c, btn in enumerate(btn_row):
                        if btn.action == "BS":
                            self._flash_button(r, c)
                            break
                self._draw()
                curses.napms(100)
                self._pressed = None
                self.engine.backspace()

            # Direct digit/operator typing
            else:
                ch_str = chr(ch) if 0 <= ch < 256 else None
                if ch_str:
                    r, c = self._find_button_for_key(ch_str)
                    if r is not None:
                        self._flash_button(r, c)
                        self._draw()
                        curses.napms(100)
                        self._pressed = None
                        btn = skin.buttons[r][c]
                        self._handle_action(btn.action)


def main(stdscr):
    app = CalcApp(stdscr)
    app.run()


if __name__ == "__main__":
    curses.wrapper(main)
