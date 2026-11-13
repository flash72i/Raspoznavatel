# -*- coding: utf-8 -*-
"""
quick_panel.py — плавающая панель быстрого доступа (tkinter, свой поток).

Мини-панель 282×52 px поверх всех окон. Дизайн рисуется Pillow: скруглённая
панель с градиентом, узором из точек и мягким свечением, скруглённые кнопки
с иконками и подписями, аккуратные подсказки и мини-меню режимов скриншота.
Кнопки: «Фото», «Экран», «Снимок» (у последней при наведении выезжают два
режима), булавка «поверх всех окон» и крестик.

Потоковая модель: окно Tk живёт в СВОЁМ потоке с mainloop; команды из чужих
потоков (трей, настройки, JS) приходят через очередь и выполняются опросом
root.after(...). Действия кнопок идут в рабочих потоках; пока действие
выполняется, на кнопке крутится кольцо загрузки.
"""

import os
import queue
import threading

import log

PANEL_W = 282
PANEL_H = 52

# --- геометрия (в пикселях 1x) ---
R_PANEL = 12
R_BTN = 9
BTN_W = 58
BTN_H = 36
BTN_Y = 8
PIN_W = 28
CLOSE_W = 28
BTN1_X = 22
BTN2_X = 86
BTN3_X = 150
PIN_X = 214
CLOSE_X = 246

SPIN = "#4de3f7"
DRAG_THRESHOLD = 4
SPIN_MS = 90

# --- палитра панели под тему приложения ---
THEME_COLORS = {
    "spotlight": {"bg": "#0d1326", "border": "#26314f"},
    "sunbeam":   {"bg": "#201607", "border": "#5c4320"},
    "stage":     {"bg": "#1c0d22", "border": "#543060"},
    "searchlight": {"bg": "#09101f", "border": "#23334f"},
    "cathedral": {"bg": "#0a1814", "border": "#1f4638"},
    "underwater": {"bg": "#062126", "border": "#1b4a4f"},
    "horizon":   {"bg": "#1a1006", "border": "#4f3a22"},
}

# три акцента кнопок: «Фото», «Экран», «Снимок»
THEME_ACCENTS = {
    "spotlight": ("#0ea5c4", "#7c3aed", "#d946ef"),
    "sunbeam":   ("#d97706", "#ea580c", "#eab308"),
    "stage":     ("#db2777", "#9333ea", "#e879f9"),
    "searchlight": ("#2563eb", "#0ea5e9", "#6366f1"),
    "cathedral": ("#059669", "#ca8a04", "#0d9488"),
    "underwater": ("#0d9488", "#0891b2", "#2563eb"),
    "horizon":   ("#ea580c", "#e11d48", "#f59e0b"),
}

_PANEL_TIP = {
    "image": "Загрузить изображение",
    "screen": "Распознать с экрана",
    "shot": "Скриншот: область или окно",
    "close": "Выключить панель",
}


def clamp_panel_pos(x, y, screen_w, screen_h, w=PANEL_W, h=PANEL_H):
    """
    Чистая функция: держит панель в пределах экрана.
    (None, None) или (-1, -1) = позиция не задана → сверху по центру.
    """
    try:
        screen_w = max(int(screen_w), w + 8)
        screen_h = max(int(screen_h), h + 8)
    except (TypeError, ValueError):
        return (0, 0)
    if x is None or y is None:
        return ((screen_w - w) // 2, min(96, max(4, (screen_h - h) // 6)))
    xi, yi = int(x), int(y)
    if (xi, yi) == (-1, -1):
        return ((screen_w - w) // 2, min(96, max(4, (screen_h - h) // 6)))
    return (min(max(xi, 0), screen_w - w), min(max(yi, 0), screen_h - h))


# ---------------------------------------------------------------------------
# Рисование панели через Pillow (сглаживание: рисуем в 3× и уменьшаем)
# ---------------------------------------------------------------------------
_S = 3
_FONTS = {}


def _hex(s):
    s = (s or "#ffffff").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _lighter(c, t):
    return _mix(c, (255, 255, 255), t)


def _darker(c, t):
    return _mix(c, (0, 0, 0), t)


def _font(size, bold=True):
    key = (size, bold)
    if key not in _FONTS:
        from PIL import ImageFont
        path = (r"C:\Windows\Fonts\seguisb.ttf" if bold
                else r"C:\Windows\Fonts\segoeui.ttf")
        try:
            _FONTS[key] = ImageFont.truetype(path, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


_PIN_GLYPH = {}


def _pin_glyph(px, color):
    """Белая канцелярская кнопка-закрепка из системного шрифта."""
    from PIL import Image, ImageDraw, ImageFont
    key = (int(px), tuple(color[:3]))
    if key in _PIN_GLYPH:
        return _PIN_GLYPH[key]
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf",
                                  max(32, int(px * 2)))
        img = Image.new("RGBA", (int(px * 3), int(px * 3)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((2, 2), "\U0001F4CC", font=font, embedded_color=True)
        bbox = img.getbbox()
        if not bbox:
            return None
        img = img.crop(bbox)
        mask = img.getchannel("A")
        tile = Image.new("RGBA", img.size, tuple(color[:3]) + (255,))
        tile.putalpha(mask)
        tile = tile.resize((int(px), int(px)), Image.LANCZOS)
        _PIN_GLYPH[key] = tile
        return tile
    except Exception:
        return None


def _draw_icon(d, name, cx, cy, s, color):
    """Иконки в единицах 1x; координаты умножаются на s."""
    lw = max(2, int(1.5 * s))
    if name == "image":
        d.rounded_rectangle([(cx - 7) * s, (cy - 5.5) * s,
                             (cx + 7) * s, (cy + 5.5) * s],
                            radius=2 * s, outline=color, width=lw)
        d.polygon([(cx - 5) * s, (cy + 3) * s, (cx - 1) * s, (cy - 2) * s,
                   (cx + 2) * s, (cy + 2) * s, (cx + 3.5) * s, (cy + 0.5) * s,
                   (cx + 5) * s, (cy + 3) * s], fill=color)
        d.ellipse([(cx + 2) * s, (cy - 3.5) * s,
                   (cx + 4.5) * s, (cy - 1) * s], fill=color)
    elif name == "screen":
        d.rounded_rectangle([(cx - 7) * s, (cy - 5) * s,
                             (cx + 7) * s, (cy + 4) * s],
                            radius=1.5 * s, outline=color, width=lw)
        d.line([cx * s, (cy + 4) * s, cx * s, (cy + 6.5) * s],
               fill=color, width=lw)
        d.line([(cx - 3.5) * s, (cy + 6.5) * s,
                (cx + 3.5) * s, (cy + 6.5) * s], fill=color, width=lw)
    elif name == "shot":
        L = 4
        for x0, y0, dx, dy in ((-7, -6, 1, 1), (7, -6, -1, 1),
                               (-7, 6, 1, -1), (7, 6, -1, -1)):
            d.line([(cx + x0) * s, (cy + y0) * s,
                    (cx + x0 + dx * L) * s, (cy + y0) * s],
                   fill=color, width=lw)
            d.line([(cx + x0) * s, (cy + y0) * s,
                    (cx + x0) * s, (cy + y0 + dy * L) * s],
                   fill=color, width=lw)
        d.ellipse([(cx - 2.2) * s, (cy - 2.2) * s,
                   (cx + 2.2) * s, (cy + 2.2) * s], outline=color, width=lw)
    elif name == "pin":  # обычная скрепка (спираль)
        d.line([(cx - 4) * s, (cy - 6) * s,
                (cx - 4) * s, (cy + 3) * s], fill=color, width=lw)
        d.arc([(cx - 4) * s, (cy + 2) * s,
               (cx + 3) * s, (cy + 7) * s], start=0, end=180,
              fill=color, width=lw)
        d.line([(cx + 3) * s, (cy + 5) * s,
                (cx + 3) * s, (cy - 3) * s], fill=color, width=lw)
        d.arc([(cx - 3) * s, (cy - 6) * s,
               (cx + 3) * s, (cy) * s], start=180, end=360,
              fill=color, width=lw)
        d.line([(cx - 3) * s, (cy - 3) * s,
                (cx - 3) * s, (cy + 2) * s], fill=color, width=lw)
        d.arc([(cx - 3) * s, (cy + 1) * s,
               (cx) * s, (cy + 4) * s], start=0, end=180,
              fill=color, width=lw)
    elif name == "close":
        d.line([(cx - 4) * s, (cy - 4) * s, (cx + 4) * s, (cy + 4) * s],
               fill=color, width=lw)
        d.line([(cx + 4) * s, (cy - 4) * s, (cx - 4) * s, (cy + 4) * s],
               fill=color, width=lw)


def _gradient_rect(img, box, c1, c2, radius):
    from PIL import Image, ImageDraw
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    for yy in range(h):
        t = yy / max(1, h - 1)
        td.line([(0, yy), (w, yy)], fill=_mix(c1, c2, t) + (255,))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                           radius=radius, fill=255)
    img.paste(tile, (x1, y1), mask)


def render_panel(theme, hover=None, pinned=False):
    """Панель целиком: фон, узор, кнопки. hover — ключ подсвеченной кнопки."""
    from PIL import Image, ImageDraw
    s = _S
    W, H = PANEL_W * s, PANEL_H * s
    cols = THEME_COLORS.get(theme, THEME_COLORS["spotlight"])
    bg = _hex(cols["bg"])
    border = _hex(cols["border"])
    accents = THEME_ACCENTS.get(theme, THEME_ACCENTS["spotlight"])
    acc = _hex(accents[0])

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bot = _lighter(bg, 0.08), _darker(bg, 0.14)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_mix(top, bot, y / max(1, H - 1)) + (255,))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = int(W * 0.20), int(-H * 0.15)
    maxr = int(W * 0.62)
    for r in range(maxr, 0, -max(1, maxr // 40)):
        gd.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=acc + (int(30 * (1 - r / maxr)),))
    img = Image.alpha_composite(img, glow)

    pat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pat)
    step = 9 * s
    for yy in range(step // 2, H, step):
        for xx in range(step // 2, W, step):
            pd.ellipse([xx, yy, xx + 1.2 * s, yy + 1.2 * s],
                       fill=(255, 255, 255, 18))
    img = Image.alpha_composite(img, pat)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1],
                                           radius=R_PANEL * s, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(out)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R_PANEL * s,
                        outline=border + (235,), width=max(1, s // 2))
    d.line([(R_PANEL * s, s), (W - R_PANEL * s, s)],
           fill=(255, 255, 255, 30), width=max(1, s // 3))

    # «ручка» перетаскивания
    for i in range(3):
        yy = (20 + i * 6) * s
        for xx in (9 * s, 14 * s):
            d.ellipse([xx, yy, xx + 2.2 * s, yy + 2.2 * s],
                      fill=(255, 255, 255, 70))

    # три кнопки действий
    for key, x, color, label, icon in (
            ("image", BTN1_X, accents[0], "Фото", "image"),
            ("screen", BTN2_X, accents[1], "Экран", "screen"),
            ("shot", BTN3_X, accents[2], "Снимок", "shot")):
        base = _hex(color)
        box = [x * s, BTN_Y * s, (x + BTN_W) * s - 1, (BTN_Y + BTN_H) * s - 1]
        _gradient_rect(out, box, _lighter(base, 0.24), base, R_BTN * s)
        hovered = (hover == key)
        d.rounded_rectangle(box, radius=R_BTN * s,
                            outline=(255, 255, 255, 130 if hovered else 42),
                            width=max(2, int(1.4 * s)) if hovered else max(1, s // 3))
        if hovered:
            d.line([(x + R_BTN) * s, (BTN_Y + 1) * s,
                    (x + BTN_W - R_BTN) * s, (BTN_Y + 1) * s],
                   fill=(255, 255, 255, 90), width=max(1, s // 3))
        _draw_icon(d, icon, x + BTN_W / 2, BTN_Y + 11, s,
                   (255, 255, 255, 240))
        f = _font(int(8.6 * s), True)
        tw = d.textlength(label, font=f)
        d.text(((x + BTN_W / 2) * s - tw / 2, (BTN_Y + 21) * s),
               label, font=f, fill=(255, 255, 255, 245))

    # булавка
    pbox = [PIN_X * s, BTN_Y * s, (PIN_X + PIN_W) * s - 1,
            (BTN_Y + BTN_H) * s - 1]
    pin_hover = (hover == "pin")
    if pinned:
        _gradient_rect(out, pbox, _lighter(acc, 0.15), acc, R_BTN * s)
        pin_fill = (255, 255, 255, 60)
    else:
        pin_fill = (255, 255, 255, 26 if pin_hover else 14)
        d.rounded_rectangle(pbox, radius=R_BTN * s, fill=pin_fill)
    d.rounded_rectangle(pbox, radius=R_BTN * s,
                        outline=(255, 255, 255, 110 if pin_hover or pinned else 40),
                        width=max(1, s // 3))
    pin_color = (255, 255, 255) if pinned else (215, 221, 235)
    glyph = _pin_glyph(int(15 * s), pin_color)
    if glyph is not None:
        gx = int((PIN_X + PIN_W / 2) * s - glyph.width / 2)
        gy = int((BTN_Y + BTN_H / 2) * s - glyph.height / 2)
        out.alpha_composite(glyph, (gx, gy))
    else:
        _draw_icon(d, "pin", PIN_X + PIN_W / 2, BTN_Y + BTN_H / 2, s,
                   (255, 255, 255, 245) if pinned else (255, 255, 255, 190))

    # крестик
    cbox = [CLOSE_X * s, BTN_Y * s, (CLOSE_X + CLOSE_W) * s - 1,
            (BTN_Y + BTN_H) * s - 1]
    close_hover = (hover == "close")
    if close_hover:
        d.rounded_rectangle(cbox, radius=R_BTN * s, fill=(220, 38, 38, 110))
    d.rounded_rectangle(cbox, radius=R_BTN * s,
                        outline=(255, 255, 255, 70 if close_hover else 36),
                        width=max(1, s // 3))
    _draw_icon(d, "close", CLOSE_X + CLOSE_W / 2, BTN_Y + BTN_H / 2, s,
               (255, 255, 255, 250 if close_hover else 175))

    return out.resize((PANEL_W, PANEL_H), Image.LANCZOS)


def _hit_rects():
    return [
        {"key": "image", "x": BTN1_X, "y": BTN_Y, "w": BTN_W, "h": BTN_H},
        {"key": "screen", "x": BTN2_X, "y": BTN_Y, "w": BTN_W, "h": BTN_H},
        {"key": "shot", "x": BTN3_X, "y": BTN_Y, "w": BTN_W, "h": BTN_H},
        {"key": "pin", "x": PIN_X, "y": BTN_Y, "w": PIN_W, "h": BTN_H},
        {"key": "close", "x": CLOSE_X, "y": BTN_Y, "w": CLOSE_W, "h": BTN_H},
    ]


def _apply_round_region(win, w, h, r):
    """Скругляет само окно Tk: углы обрезаются регионом Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        u.GetParent.restype = wintypes.HWND
        u.GetParent.argtypes = [wintypes.HWND]
        g.CreateRoundRectRgn.restype = wintypes.HRGN
        g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        u.SetWindowRgn.restype = wintypes.BOOL
        u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        handles = {int(win.winfo_id())}
        parent = u.GetParent(wintypes.HWND(int(win.winfo_id())))
        if parent:
            handles.add(int(parent))
        for hw in handles:
            hrgn = g.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
            if not u.SetWindowRgn(wintypes.HWND(hw), hrgn, True):
                g.DeleteObject(hrgn)
    except Exception:
        pass


class _TipWindow:
    """Подсказка панели: тёмная скруглённая плашка под кнопкой."""

    def __init__(self, root, x, y, text, theme):
        import tkinter as tk
        from PIL import Image, ImageDraw, ImageTk
        cols = THEME_COLORS.get(theme, THEME_COLORS["spotlight"])
        bg = _hex(cols["bg"])
        border = _hex(cols["border"])
        s = _S
        f = _font(int(8.6 * s), True)
        tmp = Image.new("RGBA", (10, 10))
        d = ImageDraw.Draw(tmp)
        tw = int(d.textlength(text, font=f))
        w = int(tw / s) + 18
        h = 24
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=8 * s,
                            fill=_lighter(bg, 0.05) + (250,),
                            outline=border + (240,), width=max(1, s // 2))
        d.text((9 * s, 6 * s), text, font=f, fill=(232, 236, 255, 250))
        img = img.resize((w, h), Image.LANCZOS)
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.photo = ImageTk.PhotoImage(img)
        cv = tk.Canvas(self.win, width=w, height=h, highlightthickness=0,
                       bd=0, bg=cols["bg"])
        cv.pack()
        cv.create_image(0, 0, anchor="nw", image=self.photo)
        self._cv = cv
        self.win.update_idletasks()
        tx, ty = clamp_panel_pos(x - w // 2, y + 6,
                                 self.win.winfo_screenwidth(),
                                 self.win.winfo_screenheight(), w, h)
        _apply_round_region(self.win, w, h, 8)
        self.win.geometry("%dx%d+%d+%d" % (w, h, tx, ty))
        self.win.update_idletasks()

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


class QuickPanel:
    """Плавающая панель. show/hide/toggle/stop безопасны из любого потока."""

    def __init__(self, on_image, on_screen, on_shot, on_close,
                 get_pos=None, save_pos=None,
                 on_pin=None, is_pinned=None, opacity=None, theme=None):
        self.on_image = on_image
        self.on_screen = on_screen
        self.on_shot = on_shot
        self.on_close = on_close
        self.get_pos = get_pos or (lambda: (-1, -1))
        self.save_pos = save_pos or (lambda x, y: None)
        self.on_pin = on_pin or (lambda pinned: None)
        self.is_pinned = is_pinned or (lambda: True)
        self._opacity = opacity if opacity is not None else 100
        self._theme = theme or "spotlight"
        self._cmd = queue.Queue()
        self._thread = None
        self._root = None
        self._canvas = None
        self._bg_item = None
        self._visible = False
        self._stopped = False
        self._busy = {}
        self._photos = {}
        self._hover = None
        self._drag = None
        self._pressed = None
        self._pressed_xy = None
        self._moved = False
        self._spin_key = None
        self._spin_angle = 0
        self._spin_timer = None
        self._tip = None
        self._tip_timer = None
        self._popup = None
        self._popup_photos = {}
        self._popup_hover = None
        self._popup_timer = None
        self._last_geom = ""

    # -------------------------------------------------- публичный API ---
    def apply_theme(self, theme):
        self._theme = theme or "spotlight"
        self._put("theme")

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="quick-panel")
        self._thread.start()
        return True

    def show(self):
        self._put("show")

    def hide(self):
        self._put("hide")

    def toggle(self):
        self._put("hide" if self._visible else "show")

    def visible(self):
        return bool(self._visible)

    def refresh_pin(self):
        self._put("pin")

    def set_opacity(self, percent):
        try:
            self._opacity = min(100, max(30, int(percent)))
        except (TypeError, ValueError):
            return
        self._put("opacity")

    def stop(self):
        self._stopped = True
        self._put("quit")
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=4.0)

    def _put(self, cmd):
        try:
            self._cmd.put_nowait(cmd)
        except Exception:
            pass

    # ------------------------------------------------------ поток Tk ---
    def _run(self):
        try:
            import tkinter as tk
        except Exception as exc:
            log.warn(f"Быстрая панель недоступна (нет tkinter): {exc}")
            return
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDpiAware()
                except Exception:
                    pass
        try:
            root = tk.Tk()
        except Exception as exc:
            log.warn(f"Быстрая панель не создалась: {exc}")
            return
        self._root = root
        root.title("Распознаватель — быстрая панель")
        root.overrideredirect(True)
        root.attributes("-topmost", bool(self.is_pinned()))
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass
        try:
            root.attributes("-alpha", self._opacity / 100.0)
        except Exception:
            pass
        root.resizable(False, False)

        cols = THEME_COLORS.get(self._theme, THEME_COLORS["spotlight"])
        self._canvas = tk.Canvas(root, width=PANEL_W, height=PANEL_H,
                                 highlightthickness=0, bd=0, bg=cols["bg"])
        self._canvas.pack(fill="both", expand=True)
        self._ensure_photos()
        self._bg_item = self._canvas.create_image(
            0, 0, anchor="nw", image=self._photos[None])
        cv = self._canvas
        cv.bind("<Motion>", self._on_motion)
        cv.bind("<Enter>", self._on_enter)
        cv.bind("<Leave>", self._on_leave)
        cv.bind("<Button-1>", self._on_press)
        cv.bind("<B1-Motion>", self._on_drag)
        cv.bind("<ButtonRelease-1>", self._on_release)

        sx, sy = root.winfo_screenwidth(), root.winfo_screenheight()
        px, py = self.get_pos()
        x, y = clamp_panel_pos(px, py, sx, sy)
        root.geometry("%dx%d+%d+%d" % (PANEL_W, PANEL_H, x, y))
        root.update_idletasks()
        _apply_round_region(root, PANEL_W, PANEL_H, R_PANEL)
        root.withdraw()
        root.after(80, self._poll)
        log.info("Быстрая панель готова (282×52, современный дизайн)")
        try:
            root.mainloop()
        finally:
            self._visible = False
            self._root = None

    # ------------------------------------------------------------ фото ---
    def _ensure_photos(self):
        from PIL import ImageTk
        need = [None, "image", "screen", "shot", "pin", "close"]
        if all(k in self._photos for k in need):
            return
        pinned = bool(self.is_pinned())
        self._photos = {}
        for key in need:
            img = render_panel(self._theme, hover=key, pinned=pinned)
            # master обязателен: иначе после предыдущих Tk-окон картинка
            # может получить мёртвый интерпретатор.
            self._photos[key] = ImageTk.PhotoImage(img, master=self._root)

    def _apply_bg(self):
        if self._canvas is None or self._bg_item is None:
            return
        photo = self._photos.get(self._hover) or self._photos.get(None)
        if photo is not None:
            self._canvas.itemconfigure(self._bg_item, image=photo)

    # ---------------------------------------------------------- события ---
    def _point_key(self, x, y):
        for r in _hit_rects():
            if r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]:
                return r["key"]
        return None

    def _on_enter(self, _e):
        pass

    def _on_leave(self, _e):
        self._hover = None
        self._apply_bg()
        self._hide_tip()
        self._popup_hide_soon()

    def _on_motion(self, event):
        if self._drag is not None:
            return
        key = self._point_key(event.x, event.y)
        if key != self._hover:
            self._hover = key
            self._apply_bg()
            self._hide_tip()
            if key:
                self._tip_timer = self._canvas.after(
                    380, lambda k=key: self._show_tip(k))
            if key == "shot":
                self._popup_timer = self._canvas.after(200, self._popup_show)
            else:
                self._popup_hide_soon()

    def _on_press(self, event):
        root = self._root
        if root is None:
            return
        self._pressed = self._point_key(event.x, event.y)
        self._pressed_xy = (event.x_root, event.y_root)
        self._drag = (event.x_root, event.y_root, root.winfo_rootx(), root.winfo_rooty(), False)
        self._moved = False

    def _on_drag(self, event):
        root = self._root
        if root is None or self._drag is None:
            return
        ox, oy, wx, wy, moved = self._drag
        dx, dy = event.x_root - ox, event.y_root - oy
        if not moved and abs(dx) + abs(dy) <= DRAG_THRESHOLD:
            return
        self._moved = True
        self._hover = None
        self._apply_bg()
        self._hide_tip()
        x, y = clamp_panel_pos(wx + dx, wy + dy,
                               root.winfo_screenwidth(),
                               root.winfo_screenheight())
        root.geometry("+%d+%d" % (x, y))
        self._drag = (ox, oy, wx, wy, True)

    def _on_release(self, _event):
        moved = bool(self._drag and self._drag[4])
        key = self._pressed
        self._drag = None
        self._pressed = None
        self._pressed_xy = None
        if moved:
            root = self._root
            if root is not None:
                x, y = root.winfo_rootx(), root.winfo_rooty()
                threading.Thread(target=lambda: self.save_pos(x, y),
                                 daemon=True).start()
            return
        if key == "image":
            self._clicked("image")
        elif key == "screen":
            self._clicked("screen")
        elif key == "shot":
            self._popup_show()
        elif key == "pin":
            self._pin_clicked()
        elif key == "close":
            self._close()

    # ------------------------------------------------------------ подсказки ---
    def _tip_text(self, key):
        if key == "pin":
            return ("Открепить от всех окон" if self.is_pinned()
                    else "Закрепить поверх всех окон")
        return _PANEL_TIP.get(key)

    def _show_tip(self, key):
        text = self._tip_text(key)
        if not text or self._tip is not None or self._root is None:
            return
        try:
            r = next(r for r in _hit_rects() if r["key"] == key)
            root = self._root
            x = root.winfo_rootx() + r["x"] + r["w"] // 2
            y = root.winfo_rooty() + PANEL_H
            self._tip = _TipWindow(root, x, y, text, self._theme)
        except Exception as exc:
            log.warn(f"Панель: подсказка не создалась: {exc}")
            self._tip = None

    def _hide_tip(self):
        if self._tip_timer is not None and self._canvas is not None:
            try:
                self._canvas.after_cancel(self._tip_timer)
            except Exception:
                pass
        self._tip_timer = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    # ---------------------------------------------------- меню «Снимок» ---
    def _popup_show(self):
        root = self._root
        if root is None or self._popup is not None:
            return
        if self._popup_timer is not None:
            try:
                root.after_cancel(self._popup_timer)
            except Exception:
                pass
            self._popup_timer = None
        try:
            import tkinter as tk
            from PIL import Image, ImageDraw, ImageTk

            pw, ph = 196, 84
            cols = THEME_COLORS.get(self._theme, THEME_COLORS["spotlight"])
            bg = _hex(cols["bg"])
            border = _hex(cols["border"])
            acc = _hex(THEME_ACCENTS.get(self._theme,
                                         THEME_ACCENTS["spotlight"])[2])
            s = _S
            images = {}
            for hover in (None, 0, 1):
                img = Image.new("RGBA", (pw * s, ph * s), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle([0, 0, pw * s - 1, ph * s - 1], radius=12 * s,
                                    fill=_lighter(bg, 0.06) + (252,),
                                    outline=border + (240,), width=max(1, s // 2))
                for row, label in ((0, "Свободная область"), (1, "Режим окна")):
                    y = (10 + row * 36) * s
                    box = [10 * s, y, (pw - 10) * s - 1, y + 28 * s]
                    if hover == row:
                        d.rounded_rectangle(box, radius=8 * s,
                                            fill=acc + (95,),
                                            outline=(255, 255, 255, 95),
                                            width=max(1, s // 3))
                    else:
                        d.rounded_rectangle(box, radius=8 * s,
                                            fill=(255, 255, 255, 16),
                                            outline=(255, 255, 255, 26),
                                            width=max(1, s // 3))
                    f = _font(int(8.8 * s), True)
                    d.text((18 * s, y + 8 * s), label, font=f,
                           fill=(255, 255, 255, 245))
                img = img.resize((pw, ph), Image.LANCZOS)
                images[hover] = ImageTk.PhotoImage(img)

            pop = tk.Toplevel(root)
            pop.overrideredirect(True)
            pop.attributes("-topmost", True)
            cv = tk.Canvas(pop, width=pw, height=ph, highlightthickness=0,
                           bd=0, bg=cols["bg"])
            cv.pack()
            item = cv.create_image(0, 0, anchor="nw", image=images[None])
            self._popup = pop
            self._popup_photos = images
            self._popup_item = item
            self._popup_hover = None
            self._popup_canvas = cv

            def on_move(e):
                row = 0 if 10 <= e.y <= 38 else (1 if 46 <= e.y <= 74 else None)
                if row != self._popup_hover:
                    self._popup_hover = row
                    cv.itemconfigure(item, image=images[row])
            cv.bind("<Motion>", on_move)
            cv.bind("<Leave>", lambda e: self._popup_hide_soon())
            cv.bind("<Button-1>", lambda e: self._popup_pick(
                "region" if e.y < 42 else "window"))

            root.update_idletasks()
            x = root.winfo_rootx() + BTN3_X + BTN_W // 2 - pw // 2
            y = root.winfo_rooty() - ph - 6
            x, y = clamp_panel_pos(x, y, root.winfo_screenwidth(),
                                   root.winfo_screenheight(), pw, ph)
            pop.geometry("%dx%d+%d+%d" % (pw, ph, x, y))
            _apply_round_region(pop, pw, ph, 12)
            pop.deiconify()
        except Exception as exc:
            log.warn(f"Панель: меню режимов не открылось: {exc}")
            self._popup = None

    def _popup_hide_soon(self):
        root = self._root
        if root is None or self._popup is None:
            return
        if self._popup_timer is not None:
            try:
                root.after_cancel(self._popup_timer)
            except Exception:
                pass
        try:
            self._popup_timer = root.after(350, self._popup_hide)
        except Exception:
            pass

    def _popup_hide(self, now=False):
        if self._popup_timer is not None and self._root is not None:
            try:
                self._root.after_cancel(self._popup_timer)
            except Exception:
                pass
        self._popup_timer = None
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
        self._popup_photos = {}
        self._popup_hover = None

    def _popup_pick(self, mode):
        self._popup_hide()
        self._run_action("shot", mode)

    # ------------------------------------------------------------ спиннер ---
    def _spin_cmd(self, key, on):
        if on:
            self._spin_start(key)
        else:
            self._spin_stop()

    def _spin_start(self, key):
        self._spin_key = key
        self._spin_angle = 0
        self._spin_tick()

    def _spin_tick(self):
        cv = self._canvas
        if cv is None or self._spin_key is None:
            return
        try:
            cv.delete("spin")
            r = next(r for r in _hit_rects() if r["key"] == self._spin_key)
            cx = r["x"] + r["w"] / 2
            cy = r["y"] + r["h"] / 2
            rad = 11
            cv.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                           outline="#2d3a55", width=2, tags="spin")
            cv.create_arc(cx - rad, cy - rad, cx + rad, cy + rad,
                          start=self._spin_angle, extent=100, style="arc",
                          outline=SPIN, width=2, tags="spin")
            self._spin_angle = (self._spin_angle + 35) % 360
            self._spin_timer = cv.after(SPIN_MS, self._spin_tick)
        except Exception:
            self._spin_stop()

    def _spin_stop(self):
        self._spin_key = None
        if self._spin_timer is not None and self._canvas is not None:
            try:
                self._canvas.after_cancel(self._spin_timer)
            except Exception:
                pass
        self._spin_timer = None
        if self._canvas is not None:
            try:
                self._canvas.delete("spin")
            except Exception:
                pass

    # -------------------------------------------------------- действия ---
    def _poll(self):
        root = self._root
        if root is None:
            return
        try:
            while True:
                cmd = self._cmd.get_nowait()
                if cmd == "show":
                    root.deiconify()
                    root.lift()
                    root.attributes("-topmost", bool(self.is_pinned()))
                    root.update_idletasks()
                    _apply_round_region(root, PANEL_W, PANEL_H, R_PANEL)
                    self._visible = True
                    self._last_geom = root.winfo_geometry()
                elif cmd == "hide":
                    self._popup_hide(now=True)
                    self._hide_tip()
                    root.withdraw()
                    self._visible = False
                elif isinstance(cmd, tuple) and cmd and cmd[0] == "spin":
                    self._spin_cmd(cmd[1], bool(cmd[2]))
                elif cmd == "opacity":
                    try:
                        root.attributes("-alpha", self._opacity / 100.0)
                    except Exception:
                        pass
                elif cmd == "pin":
                    self._photos = {}
                    self._ensure_photos()
                    self._apply_bg()
                    root.attributes("-topmost", bool(self.is_pinned()))
                elif cmd == "theme":
                    cols = THEME_COLORS.get(self._theme,
                                            THEME_COLORS["spotlight"])
                    root.configure(bg=cols["bg"])
                    if self._canvas is not None:
                        self._canvas.configure(bg=cols["bg"])
                    self._photos = {}
                    self._ensure_photos()
                    self._apply_bg()
                    self._popup_hide(now=True)
                elif cmd == "quit":
                    self._popup_hide(now=True)
                    self._hide_tip()
                    root.quit()
                    return
        except queue.Empty:
            pass
        except Exception as exc:
            log.warn(f"Быстрая панель: сбой команды: {exc}")
        try:
            root.after(80, self._poll)
        except Exception:
            pass

    def _clicked(self, key):
        if self._busy.get(key):
            return
        if key == "shot":
            self._popup_show()
            return
        self._run_action(key, None)

    def _run_action(self, key, mode):
        self._busy[key] = True
        self._put(("spin", key, True))

        def work():
            try:
                if key == "image":
                    self.on_image()
                elif key == "screen":
                    self.on_screen()
                else:
                    self.on_shot(mode or "region")
            except Exception as exc:
                log.error(f"Быстрая панель: действие не удалось: {exc}")
            finally:
                self._busy[key] = False
                self._put(("spin", key, False))
        threading.Thread(target=work, daemon=True).start()

    def _pin_clicked(self):
        def work():
            try:
                self.on_pin(not self.is_pinned())
            except Exception as exc:
                log.warn(f"Панель: не удалось сохранить «поверх окон»: {exc}")
            self._put("pin")
        threading.Thread(target=work, daemon=True).start()

    def _close(self):
        self._visible = False
        try:
            self.on_close()
        except Exception as exc:
            log.warn(f"Быстрая панель: не удалось сохранить выключение: {exc}")
        self._put("hide")

    def _spawn(self, fn):
        threading.Thread(target=self._call, args=(fn,), daemon=True).start()

    def _call(self, fn):
        try:
            fn()
        except Exception as exc:
            log.error(f"Быстрая панель: действие не удалось: {exc}")
