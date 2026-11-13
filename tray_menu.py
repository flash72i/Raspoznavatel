# -*- coding: utf-8 -*-
"""
tray_menu.py — собственное контекстное меню для значка в трее.

Стандартное меню Windows умеет только сплошной цвет и квадратные углы.
Здесь меню — отдельное слоистое окно (WS_EX_LAYERED): фон рисуется Pillow
(градиент, узор из точек, мягкое свечение, скруглённые углы и тень), пункты
подсвечиваются скруглённой плашкой, иконки рисуются вручную. Снаружи меню
выглядит как часть интерфейса приложения.

Модуль вызывается из потока трея (там уже есть насос сообщений); show_menu()
запускает модальный цикл и возвращает id выбранного пункта или None.
"""

import ctypes
import time
from ctypes import wintypes

if __name__ == "__main__":  # pragma: no cover - ручной предпросмотр
    raise SystemExit("Модуль используется из tray.py")

# --- размеры (1x, CSS-пиксели) ---
MENU_W = 286
MENU_PAD = 10
ITEM_H = 40
SEP_H = 12
R_MENU = 14
SHADOW = 14
S = 3                 # рисуем в 3× и уменьшаем — сглаживание

WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_KEYDOWN = 0x0100
WM_ACTIVATE = 0x0006
WM_MOUSEACTIVATE = 0x0021
WM_NULL = 0x0000
WM_DESTROY = 0x0002
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_UP = 0x26
VK_DOWN = 0x28
WA_INACTIVE = 0
MA_ACTIVATE = 1
SW_SHOW = 5
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
ULW_ALPHA = 0x00000002
AC_SRC_ALPHA = 0x00000001

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
    ctypes.c_size_t, ctypes.c_ssize_t)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
                ("SourceConstantAlpha", wintypes.BYTE),
                ("AlphaFormat", wintypes.BYTE)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


_INSTANCES = {}
_PROC = None
_CLASS_READY = False
_U = None
_G = None


def _api():
    global _U, _G, _PROC, _CLASS_READY
    if _U is not None:
        return _U, _G
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    _U, _G = u, g

    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 ctypes.c_size_t, ctypes.c_ssize_t]
    u.RegisterClassW.restype = wintypes.BOOL
    u.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    u.GetMessageW.restype = ctypes.c_int
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                              wintypes.UINT, wintypes.UINT]
    u.TranslateMessage.restype = wintypes.BOOL
    u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.restype = ctypes.c_ssize_t
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.PostMessageW.restype = wintypes.BOOL
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                               ctypes.c_size_t, ctypes.c_ssize_t]
    u.ShowWindow.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetFocus.restype = wintypes.HWND
    u.SetFocus.argtypes = [wintypes.HWND]
    u.GetDC.restype = wintypes.HDC
    u.GetDC.argtypes = [wintypes.HWND]
    u.ReleaseDC.restype = ctypes.c_int
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.UpdateLayeredWindow.restype = wintypes.BOOL
    u.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
        ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
        ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD]
    u.SetWindowPos.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_uint]
    u.MonitorFromPoint.restype = wintypes.HMONITOR
    u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    u.GetMonitorInfoW.restype = wintypes.BOOL
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    u.LoadCursorW.restype = wintypes.HANDLE
    u.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    u.DestroyWindow.restype = wintypes.BOOL
    u.DestroyWindow.argtypes = [wintypes.HWND]

    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFO),
                                   wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.DeleteObject.restype = wintypes.BOOL
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.restype = wintypes.BOOL
    g.DeleteDC.argtypes = [wintypes.HDC]

    _PROC = WNDPROC(_wnd_proc)

    wc = _WNDCLASSW()
    wc.style = 0
    wc.lpfnWndProc = _PROC
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.hCursor = u.LoadCursorW(None, ctypes.c_void_p(32512))
    wc.lpszClassName = "RaspoznavatelMenuClass"
    if not u.RegisterClassW(ctypes.byref(wc)):
        # класс уже зарегистрирован (перезапуск трея в том же процессе)
        if ctypes.GetLastError() not in (0, 1410):
            pass
    _CLASS_READY = True
    return u, g


# ---------------------------------------------------------------------------
# Рисование
# ---------------------------------------------------------------------------
def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _lighter(c, t):
    return _mix(c, (255, 255, 255), t)


def _darker(c, t):
    return _mix(c, (0, 0, 0), t)


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\seguisb.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _draw_icon(d, name, cx, cy, s, color):
    lw = max(2, int(1.4 * s))
    if name == "window":
        d.rounded_rectangle([(cx - 7) * s, (cy - 5.5) * s,
                             (cx + 7) * s, (cy + 5.5) * s],
                            radius=2 * s, outline=color, width=lw)
        d.line([(cx - 7) * s, (cy - 2.5) * s, (cx + 7) * s, (cy - 2.5) * s],
               fill=color, width=max(1, s // 2))
    elif name == "panel":
        d.rounded_rectangle([(cx - 7) * s, (cy - 4) * s,
                             (cx + 7) * s, (cy + 4) * s],
                            radius=2 * s, outline=color, width=lw)
        for i in (-3, 0, 3):
            d.ellipse([(cx + i - 0.9) * s, (cy - 0.9) * s,
                       (cx + i + 0.9) * s, (cy + 0.9) * s], fill=color)
    elif name == "image":
        d.rounded_rectangle([(cx - 7) * s, (cy - 5) * s,
                             (cx + 7) * s, (cy + 5) * s],
                            radius=2 * s, outline=color, width=lw)
        d.polygon([(cx - 5) * s, (cy + 3) * s, (cx - 1) * s, (cy - 2) * s,
                   (cx + 2) * s, (cy + 2) * s, (cx + 3.5) * s, (cy + 0.5) * s,
                   (cx + 5) * s, (cy + 3) * s], fill=color)
        d.ellipse([(cx + 2) * s, (cy - 3.5) * s,
                   (cx + 4) * s, (cy - 1.5) * s], fill=color)
    elif name == "screen":
        d.rounded_rectangle([(cx - 7) * s, (cy - 5) * s,
                             (cx + 7) * s, (cy + 3.5) * s],
                            radius=1.5 * s, outline=color, width=lw)
        d.line([cx * s, (cy + 3.5) * s, cx * s, (cy + 6) * s],
               fill=color, width=lw)
        d.line([(cx - 3.5) * s, (cy + 6) * s, (cx + 3.5) * s, (cy + 6) * s],
               fill=color, width=lw)
    elif name == "shot":
        L = 4
        for x0, y0, dx, dy in ((-7, -6, 1, 1), (7, -6, -1, 1),
                               (-7, 6, 1, -1), (7, 6, -1, -1)):
            d.line([(cx + x0) * s, (cy + y0) * s,
                    (cx + x0 + dx * L) * s, (cy + y0) * s], fill=color, width=lw)
            d.line([(cx + x0) * s, (cy + y0) * s,
                    (cx + x0) * s, (cy + y0 + dy * L) * s], fill=color, width=lw)
        d.ellipse([(cx - 2) * s, (cy - 2) * s, (cx + 2) * s, (cy + 2) * s],
                  outline=color, width=lw)
    elif name == "shot_win":
        d.rounded_rectangle([(cx - 7) * s, (cy - 6) * s,
                             (cx + 6) * s, (cy + 6) * s],
                            radius=2 * s, outline=color, width=lw)
        d.line([(cx - 4) * s, (cy - 3) * s, (cx + 3) * s, (cy - 3) * s],
               fill=color, width=max(1, s // 2))
    elif name == "exit":
        d.rounded_rectangle([(cx - 6) * s, (cy - 6) * s,
                             (cx + 2) * s, (cy + 6) * s],
                            radius=2 * s, outline=color, width=lw)
        d.line([(cx - 1) * s, (cy) * s, (cx + 7) * s, (cy) * s],
               fill=color, width=lw)
        d.polygon([(cx + 4) * s, (cy - 2.5) * s, (cx + 7.5) * s, (cy) * s,
                   (cx + 4) * s, (cy + 2.5) * s], fill=color)


def _render(rows, menu_h, bg, accent, hover_id, shadow, side=None):
    from PIL import Image, ImageDraw
    W = (MENU_W + 2 * SHADOW) * S
    H = (menu_h + 2 * SHADOW) * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(shadow)

    bg = tuple(bg)
    accent = tuple(accent)
    m = SHADOW * S
    x0, y0 = m, m
    x1, y1 = m + MENU_W * S - 1, m + menu_h * S - 1

    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    # градиент
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top, bot = _lighter(bg, 0.13), _darker(bg, 0.22)
    for y in range(y0, y1 + 1):
        gd.line([(x0, y), (x1, y)],
                fill=_mix(top, bot, (y - y0) / max(1, y1 - y0)) + (255,))
    # свечение сверху
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdd = ImageDraw.Draw(glow)
    cx, cy = x0 + int(MENU_W * S * 0.25), y0 + int(10 * S)
    maxr = int(MENU_W * S * 0.65)
    for r in range(maxr, 0, -max(1, maxr // 44)):
        gdd.ellipse([cx - r, cy - r, cx + r, cy + r],
                    fill=accent + (int(26 * (1 - r / maxr)),))
    grad = Image.alpha_composite(grad, glow)
    # точки
    pat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pat)
    step = 9 * S
    for yy in range(y0 + step // 2, y1, step):
        for xx in range(x0 + step // 2, x1, step):
            pd.ellipse([xx, yy, xx + 1.2 * S, yy + 1.2 * S],
                       fill=(255, 255, 255, 16))
    grad = Image.alpha_composite(grad, pat)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([x0, y0, x1, y1],
                                           radius=R_MENU * S, fill=255)
    # рамку и верхний блик рисуем на фоне ДО маски — иначе полупрозрачные
    # пиксели по краю «съедали» фон и сквозь меню просвечивал рабочий стол
    dg = ImageDraw.Draw(grad)
    border_col = _mix(bg, _lighter(accent, 0.15), 70 / 255)
    dg.rounded_rectangle([x0, y0, x1, y1], radius=R_MENU * S,
                         outline=border_col + (255,), width=max(1, S // 2))
    hl = _mix(bg, (255, 255, 255), 34 / 255)
    dg.line([(x0 + R_MENU * S, y0 + S), (x1 - R_MENU * S, y0 + S)],
            fill=hl + (255,), width=max(1, S // 3))
    panel.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(panel)

    text_color = (236, 239, 246, 255)
    f = _font(int(12.4 * S))
    for row in rows:
        y = y0 + row["y"] * S
        bg_now = _mix(top, bot,
                      (row["y"] + ITEM_H / 2) / max(1, menu_h))
        if row["kind"] == "sep":
            ly = y + SEP_H * S // 2
            sep = _mix(bg_now, accent, 38 / 255)
            d.line([(x0 + 16 * S, ly), (x1 - 16 * S, ly)],
                   fill=sep + (255,), width=max(1, S // 3))
            continue
        rh = ITEM_H * S
        hovered = (row["id"] == hover_id)
        if hovered:
            is_exit = (row["id"] == 2)
            if is_exit:
                fill = _mix(bg_now, (220, 38, 38), 55 / 255)
                line = _mix(bg_now, (255, 160, 160), 85 / 255)
                bar = _mix(bg_now, (255, 160, 160), 150 / 255)
            else:
                fill = _mix(bg_now, accent, 26 / 255)
                line = _mix(bg_now, accent, 62 / 255)
                bar = _mix(bg_now, accent, 150 / 255)
            d.rounded_rectangle([x0 + 7 * S, y + 3 * S,
                                 x1 - 7 * S, y + rh - 4 * S],
                                radius=9 * S, fill=fill + (255,),
                                outline=line + (255,),
                                width=max(1, S // 3))
            d.rounded_rectangle([x0 + 7 * S, y + 11 * S,
                                 x0 + 10 * S, y + rh - 11 * S],
                                radius=2 * S, fill=bar + (255,))
        color = (235, 205, 205, 255) if row["id"] == 2 else text_color
        if hovered and row["id"] == 2:
            color = (255, 255, 255, 255)
        _draw_icon(d, row["icon"], SHADOW + 30,
                   SHADOW + row["y"] + ITEM_H / 2, S, color)
        ty = y + (rh - 12.4 * S) / 2 - 1 * S
        d.text(((SHADOW + 50) * S, ty), row["text"], font=f, fill=color)

    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(panel)
    if side:
        d2 = ImageDraw.Draw(out)
        base_y = (SHADOW + menu_h) * S - 1
        tip_y = base_y + int(9 * S)
        cx = (SHADOW + MENU_W - 26) * S if side == "left" else (SHADOW + 26) * S
        d2.polygon([(cx - 8 * S, base_y), (cx + 8 * S, base_y), (cx, tip_y)],
                   fill=_lighter(bg, 0.08) + (255,))
        d2.line([(cx - 8 * S, base_y), (cx, tip_y), (cx + 8 * S, base_y)],
                fill=_mix(bg, accent, 0.55) + (255,), width=max(1, S // 2))
    return out.resize((MENU_W + 2 * SHADOW, menu_h + 2 * SHADOW),
                      Image.LANCZOS)


# ---------------------------------------------------------------------------
# Окно и цикл сообщений
# ---------------------------------------------------------------------------
def _wnd_proc(hwnd, msg, wparam, lparam):
    inst = _INSTANCES.get(int(hwnd))
    if inst is None:
        return _U.DefWindowProcW(hwnd, msg, wparam, lparam)
    return inst.on_message(msg, wparam, lparam)


class _Popup:
    def __init__(self, items, bg, accent):
        self.items = items
        self.bg = bg
        self.accent = accent
        self.rows, self.menu_h = self._layout(items)
        self.hwnd = None
        self.x = self.y = 0
        self.w = MENU_W + 2 * SHADOW
        self.h = self.menu_h + 2 * SHADOW
        self.hover = None
        self.side = "left"
        self.selected = None
        self._running = False
        self._shown_at = 0.0
        self._memdc = None
        self._bmp = None
        self._old_bmp = None
        self._screen = None
        self._shadow = None

    @staticmethod
    def _layout(items):
        rows = []
        y = MENU_PAD
        for iid, text in items:
            if iid == "sep":
                rows.append({"kind": "sep", "y": y})
                y += SEP_H
            else:
                rows.append({"kind": "item", "id": iid, "text": text or "",
                             "icon": _icon_for(iid), "y": y})
                y += ITEM_H
        y += MENU_PAD
        return rows, y

    def _make_shadow(self):
        from PIL import Image, ImageDraw, ImageFilter
        W, H = self.w * S, self.h * S
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        d.rounded_rectangle(
            [SHADOW * S, (SHADOW + 3) * S,
             (SHADOW + MENU_W) * S, (SHADOW + self.menu_h + 3) * S],
            radius=R_MENU * S, fill=(0, 0, 0, 155))
        return sh.filter(ImageFilter.GaussianBlur(9 * S))

    def _position(self, anchor):
        u = _U
        try:
            left, right, top, bottom = [int(v) for v in anchor]
        except (TypeError, ValueError):
            left = right = int(anchor[0])
            top = bottom = int(anchor[1])
        pt = wintypes.POINT((left + right) // 2, bottom)
        mon = u.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if mon and u.GetMonitorInfoW(mon, ctypes.byref(mi)):
            work = mi.rcWork
        else:
            work = wintypes.RECT(0, 0, 1920, 1080)
        vis_h = self.h - 2 * SHADOW
        gap = 10
        # Сначала пробуем справа от значка, иначе — вплотную слева.
        if right + gap + MENU_W <= work.right - 4:
            x = right + gap - SHADOW
            self.side = "right"
        else:
            x = left - gap - MENU_W - SHADOW
            self.side = "left"
        y = top - 6 - vis_h - SHADOW
        if y < work.top + 4:
            y = bottom + 6 - SHADOW
        x = min(max(x, work.left + 4 - SHADOW),
                work.right - MENU_W - 4 - SHADOW)
        y = min(max(y, work.top + 4 - SHADOW),
                work.bottom - vis_h - 4 - SHADOW)
        self.x, self.y = int(x), int(y)

    def _update(self, img):
        u, g = _U, _G
        W, H = img.size
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = W
        bmi.bmiHeader.biHeight = -H
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        if self._screen is None:
            self._screen = u.GetDC(None)
            self._memdc = g.CreateCompatibleDC(self._screen)
        hbmp = g.CreateDIBSection(self._screen, ctypes.byref(bmi), 0,
                                  ctypes.byref(bits), None, 0)
        if not hbmp:
            return
        data = img.tobytes("raw", "BGRA")
        ctypes.memmove(bits, data, len(data))
        old = g.SelectObject(self._memdc, hbmp)
        pt_dst = wintypes.POINT(self.x, self.y)
        pt_src = wintypes.POINT(0, 0)
        size = wintypes.SIZE(W, H)
        blend = _BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
        u.UpdateLayeredWindow(self.hwnd, self._screen, ctypes.byref(pt_dst),
                              ctypes.byref(size), self._memdc,
                              ctypes.byref(pt_src), 0, ctypes.byref(blend),
                              ULW_ALPHA)
        g.SelectObject(self._memdc, old)
        g.DeleteObject(hbmp)

    def _draw(self):
        if self._shadow is None:
            self._shadow = self._make_shadow()
        img = _render(self.rows, self.menu_h, self.bg, self.accent,
                      self.hover, self._shadow, self.side)
        self._update(img)

    def _hit(self, mx, my):
        y = my - SHADOW
        for row in self.rows:
            if row["kind"] == "sep":
                continue
            if row["y"] <= y <= row["y"] + ITEM_H:
                return row["id"]
        return None

    def on_message(self, msg, wparam, lparam):
        if msg == WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            key = self._hit(x, y)
            if key != self.hover:
                self.hover = key
                self._draw()
            return 0
        if msg == WM_LBUTTONUP:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            key = self._hit(x, y)
            if key is not None:
                self.selected = key
                self.close()
            return 0
        if msg == WM_RBUTTONUP:
            self.close()
            return 0
        if msg == WM_KEYDOWN:
            vk = int(wparam)
            if vk == VK_ESCAPE:
                self.close()
            elif vk == VK_RETURN:
                if self.hover is not None:
                    self.selected = self.hover
                    self.close()
            elif vk in (VK_UP, VK_DOWN):
                ids = [r["id"] for r in self.rows if r["kind"] == "item"]
                if ids:
                    try:
                        i = ids.index(self.hover)
                    except ValueError:
                        i = -1 if vk == VK_DOWN else 0
                    self.hover = ids[(i + (1 if vk == VK_DOWN else -1)) % len(ids)]
                    self._draw()
            return 0
        if msg == WM_ACTIVATE:
            if (int(wparam) & 0xFFFF) == WA_INACTIVE:
                # окно могло не успеть стать активным — не закрываем в первые 0.3 с
                if time.time() - self._shown_at > 0.3:
                    self.close()
            return 0
        if msg == WM_MOUSEACTIVATE:
            return MA_ACTIVATE
        if msg == WM_DESTROY:
            return 0
        return _U.DefWindowProcW(self.hwnd, msg, wparam, lparam)

    def close(self):
        self._running = False
        if self.hwnd:
            _U.PostMessageW(self.hwnd, WM_NULL, 0, 0)

    def run(self, anchor):
        u, g = _api()
        self._position(anchor)
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        self.hwnd = u.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
            "RaspoznavatelMenuClass", "", WS_POPUP,
            self.x, self.y, self.w, self.h, None, None, hinst, None)
        if not self.hwnd:
            return None
        _INSTANCES[int(self.hwnd)] = self
        try:
            self._draw()
            u.SetForegroundWindow(self.hwnd)
            u.ShowWindow(self.hwnd, SW_SHOW)
            u.SetFocus(self.hwnd)
            self._shown_at = time.time()
            self._running = True
            msg = wintypes.MSG()
            while self._running:
                r = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r in (0, -1):
                    break
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            _INSTANCES.pop(int(self.hwnd), None)
            try:
                u.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None
            if self._memdc:
                try:
                    g.DeleteDC(self._memdc)
                except Exception:
                    pass
                self._memdc = None
            if self._screen:
                try:
                    u.ReleaseDC(None, self._screen)
                except Exception:
                    pass
                self._screen = None
        return self.selected


def _icon_for(iid):
    return {
        1: "window",      # IDM_TOGGLE
        3: "panel",       # IDM_PANEL
        4: "image",       # IDM_IMAGE
        5: "screen",      # IDM_SCREEN
        6: "shot",        # IDM_SHOT
        7: "shot_win",    # IDM_SHOT_WIN
        2: "exit",        # IDM_EXIT
    }.get(iid, "window")


def show_menu(items, bg, accent, anchor):
    """
    Показывает меню в точке anchor (x, y) и возвращает id выбранного пункта.
    bg/accent — RGB-кортежи темы. Возвращает None, если меню закрыто.
    """
    if not _CLASS_READY:
        _api()
    pop = _Popup(items, bg, accent)
    return pop.run(anchor)
