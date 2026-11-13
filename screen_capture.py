# -*- coding: utf-8 -*-
"""
screen_capture.py — затемнение экрана, выделение области мышью, снимок.

Схема:
  1. Полноэкранное полупрозрачное окно (tkinter) поверх всех окон.
  2. Пользователь растягивает прямоугольник мышью (Esc — отмена).
  3. Снимок области: основной способ — PIL.ImageGrab (нативный GDI, самый
     надёжный на Windows), запасной — mss.
  4. Снимок сохраняется в папку данных; в интерфейс передаётся только
     МАЛЕНЬКОЕ превью (сжатый JPEG до 640 px) — большие base64-строки
     ломают мост pywebview и замедляют работу.
"""

import base64
import io
import os
import time

import config
import log

# PIL и mss импортируются ЛЕНИВО (при первом использовании) — импорт
# библиотек на старте задерживал появление окна.
_PIL = None          # (Image, ImageGrab) или None
_MSS = None          # (mss, mss.tools) или None
_PIL_CHECKED = False
_MSS_CHECKED = False


def _get_pil():
    global _PIL, _PIL_CHECKED
    if not _PIL_CHECKED:
        _PIL_CHECKED = True
        try:
            from PIL import Image, ImageGrab
            _PIL = (Image, ImageGrab)
        except Exception:  # pragma: no cover
            _PIL = None
    return _PIL


def _get_mss():
    global _MSS, _MSS_CHECKED
    if not _MSS_CHECKED:
        _MSS_CHECKED = True
        try:
            import mss
            import mss.tools
            _MSS = (mss, mss.tools)
        except Exception:  # pragma: no cover
            _MSS = None
    return _MSS


def pil_available() -> bool:
    """Доступен ли Pillow (проверка без кэшированного тяжёлого импорта на старте)."""
    return _get_pil() is not None


def mss_available() -> bool:
    """Доступен ли mss."""
    return _get_mss() is not None


class CaptureError(Exception):
    """Ошибка захвата экрана."""


class RegionSelector:
    """
    Полноэкранный оверлей для выделения прямоугольной области мышью.
    Возвращает {'left','top','width','height'} в экранных пикселях или None.
    """

    def __init__(self):
        self.region = None

    def select(self):
        import tkinter as tk  # локальный импорт — не грузим Tk при старте

        # Windows: делаем процесс DPI-осведомым, чтобы координаты выделения
        # совпадали с физическими пикселями экрана (иначе на масштабе 125/150%
        # рамка «уезжает» от курсора, а снимок получается не той области).
        if os.name == "nt":
            try:
                import ctypes
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    ctypes.windll.user32.SetProcessDpiAware()
            except Exception:
                pass

        root = tk.Tk()
        root.title("Выделите область")
        root.attributes("-fullscreen", True)
        root.attributes("-alpha", 0.35)          # затемнение экрана
        root.attributes("-topmost", True)
        root.configure(bg="black", cursor="crosshair")

        canvas = tk.Canvas(root, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            root.winfo_screenwidth() // 2, 40,
            text="Зажмите левую кнопку мыши и выделите нужную область экрана",
            fill="#22d3ee", font=("Segoe UI", 15, "bold")
        )
        canvas.create_text(
            root.winfo_screenwidth() // 2, 68,
            text="Отпустите кнопку — область будет распознана.  Esc или правая кнопка — отмена.",
            fill="#9fb0e8", font=("Segoe UI", 11)
        )

        state = {"start": None, "rect_id": None, "size_id": None}

        def on_press(event):
            state["start"] = (event.x_root, event.y_root)
            state["rect_id"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#22d3ee", width=2)
            state["size_id"] = canvas.create_text(
                event.x + 6, event.y + 14, anchor="nw", text="",
                fill="#22d3ee", font=("Segoe UI", 10, "bold"))

        def on_drag(event):
            if state["start"] is None or state["rect_id"] is None:
                return
            x0 = state["start"][0] - root.winfo_rootx()
            y0 = state["start"][1] - root.winfo_rooty()
            canvas.coords(state["rect_id"], x0, y0, event.x, event.y)
            if state["size_id"] is not None:
                w = abs(event.x - x0)
                h = abs(event.y - y0)
                canvas.coords(state["size_id"], min(x0, event.x) + 6, min(y0, event.y) + 8)
                canvas.itemconfigure(state["size_id"], text=f"{w} × {h}")

        def on_release(event):
            if state["start"] is None:
                return
            x0, y0 = state["start"]
            x1, y1 = event.x_root, event.y_root
            left, top = min(x0, x1), min(y0, y1)
            width, height = abs(x1 - x0), abs(y1 - y0)
            if width > 5 and height > 5:
                self.region = {"left": left, "top": top,
                               "width": width, "height": height}
            root.destroy()

        def on_escape(_event=None):
            root.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", on_escape)
        root.bind("<Button-3>", on_escape)   # правая кнопка — тоже отмена

        log.info("Окно выделения области открыто")
        root.mainloop()
        log.info("Окно выделения области закрыто")
        return self.region


def grab_region(region: dict) -> str:
    """
    Снимок области экрана. Основной способ — PIL.ImageGrab (нативный GDI),
    запасной — mss. Возвращает путь к сохранённому PNG.
    """
    out_path = os.path.join(config.TMP_DIR, f"capture_{int(time.time() * 1000)}.png")
    left, top = int(region["left"]), int(region["top"])
    width, height = int(region["width"]), int(region["height"])

    # --- способ 1: PIL.ImageGrab (самый надёжный на Windows) ---
    pil = _get_pil()
    if pil is not None:
        ImageGrab = pil[1]
        try:
            im = ImageGrab.grab(
                bbox=(left, top, left + width, top + height),
                all_screens=True,
            )
            try:
                im.save(out_path, "PNG")
            finally:
                im.close()
            log.ok(f"Снимок {width}×{height} сохранён (ImageGrab): {out_path}")
            return out_path
        except Exception as exc:
            log.warn(f"ImageGrab не сработал ({exc}) — пробую mss")

    # --- способ 2: mss ---
    m = _get_mss()
    if m is not None:
        mss, mss_tools = m
        try:
            with mss.mss() as sct:
                shot = sct.grab({"left": left, "top": top,
                                 "width": width, "height": height})
                png_bytes = mss_tools.to_png(shot.rgb, shot.size)
            with open(out_path, "wb") as f:
                f.write(png_bytes)
            log.ok(f"Снимок {width}×{height} сохранён (mss): {out_path}")
            return out_path
        except Exception as exc:
            raise CaptureError(f"Не удалось сделать снимок экрана: {exc}") from exc

    raise CaptureError("Компоненты захвата экрана (PIL/mss) недоступны.")


def grab_window(hwnd, region: dict = None) -> str:
    """
    Снимок КОНКРЕТНОГО окна по HWND через PrintWindow.

    В отличие от grab_region не захватывает окна, лежащие сверху: видно
    именно содержимое выбранного окна. При неудаче — обычный снимок области.
    """
    if os.name != "nt":
        if region:
            return grab_region(region)
        raise CaptureError("Снимок окна поддерживается только в Windows.")
    pil = _get_pil()
    if pil is None:
        if region:
            return grab_region(region)
        raise CaptureError("Компоненты захвата экрана (Pillow) недоступны.")
    Image = pil[0]
    out_path = os.path.join(config.TMP_DIR, f"capture_{int(time.time() * 1000)}.png")

    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    hdc = mem_dc = bmp = old_obj = None
    try:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise CaptureError("GetWindowRect не вернул размеры окна")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise CaptureError("окно свёрнуто или имеет нулевой размер")
        hdc = user32.GetWindowDC(hwnd)
        if not hdc:
            raise CaptureError("GetWindowDC не вернул контекст окна")
        mem_dc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
        if not mem_dc or not bmp:
            raise CaptureError("не удалось создать буфер изображения")
        old_obj = gdi32.SelectObject(mem_dc, bmp)
        # PW_RENDERFULLCONTENT=2 — захват DWM-содержимого (Chrome, проводник,
        # игры и т.п.). Если не поддержано, пробуем обычный PrintWindow.
        ok = user32.PrintWindow(hwnd, mem_dc, 2)
        if not ok:
            ok = user32.PrintWindow(hwnd, mem_dc, 0)
        if not ok:
            raise CaptureError("PrintWindow отказал")

        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = width
        bi.bmiHeader.biHeight = -height       # top-down
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        buf = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem_dc, bmp, 0, height, buf,
                               ctypes.byref(bi), 0):
            raise CaptureError("GetDIBits отказал")
        img = Image.frombuffer("RGB", (width, height), buf,
                               "raw", "BGRX", 0, 1)
        if img.convert("L").getextrema()[1] == 0:
            raise CaptureError("PrintWindow вернул пустое изображение")
        img.save(out_path, "PNG")
        log.ok(f"Снимок окна {width}×{height} сохранён (PrintWindow): {out_path}")
        return out_path
    except Exception as exc:
        log.warn(f"PrintWindow не сработал ({exc}) — снимаю область экрана")
        if region:
            return grab_region(region)
        raise CaptureError(f"Не удалось снять окно: {exc}") from exc
    finally:
        if mem_dc and old_obj:
            gdi32.SelectObject(mem_dc, old_obj)
        if bmp:
            gdi32.DeleteObject(bmp)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        if hdc:
            user32.ReleaseDC(hwnd, hdc)


def file_to_base64(path: str) -> str:
    """Читает файл и возвращает data-URL (используется только для мелких файлов)."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{data}"


def preview_base64(path: str, max_side: int = 640, quality: int = 72) -> str:
    """
    МАЛЕНЬКОЕ превью изображения (JPEG, до max_side px) в виде data-URL.
    Именно оно передаётся в интерфейс — мост pywebview надёжно работает
    только с небольшими строками (десятки-сотни КБ, не мегабайты).
    """
    pil = _get_pil()
    if pil is None:
        return ""
    Image = pil[0]
    try:
        with Image.open(path) as src:
            im = src.convert("RGB") if src.mode not in ("RGB", "L") else src
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as exc:
        log.warn(f"Не удалось построить превью: {exc}")
        return ""


def capture_region_interactive():
    """
    Полный цикл: выделение области -> снимок.
    :return: {'path', 'base64'(превью), 'width', 'height'} или None (отмена)
    """
    region = RegionSelector().select()
    if not region:
        return None
    time.sleep(0.25)   # даём окну выделения полностью закрыться
    path = grab_region(region)
    return {
        "path": path,
        "base64": preview_base64(path),
        "width": region["width"],
        "height": region["height"],
    }


# ---------------------------------------------------------------------------
# Window picker (выбор окна с подсветкой при наведении)
# Алгоритм поиска окна под курсором — из инструмента владельца
# (window-measurer): WindowFromPoint -> GetAncestor(GA_ROOT) -> спуск по
# Z-order мимо своих/невидимых/тултипов -> фолбэк EnumWindows.
# ---------------------------------------------------------------------------

_SKIP_CLASSES = ("tooltips_class32", "MSCTFIME UI", "IME", "MSCTFIME UI Manager")
GA_ROOT = 2
GW_HWNDNEXT = 2


def _own_hwnds():
    """HWND окон нашего процесса (их не предлагаем выбрать)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    mine = set()
    pid = os.getpid()
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            mine.add(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return mine


def _pickable(hwnd, pt, own):
    """Можно ли предложить это окно: видимое, не свёрнутое, не своё, не тултип."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    if not hwnd or hwnd in own:
        return False
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 63)
    if buf.value in _SKIP_CLASSES:
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    if not (rect.left <= pt.x <= rect.right and rect.top <= pt.y <= rect.bottom):
        return False
    return (rect.left, rect.top, rect.right, rect.bottom)


def window_under_cursor():
    """
    (hwnd, прямоугольник) окна под курсором или None.
    Чистый Win32; на других ОС возвращает None.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return None
    own = _own_hwnds()
    hwnd = user32.WindowFromPoint(pt)
    if hwnd:
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root:
            hwnd = root
    for _ in range(64):                       # спуск по Z-order мимо мусора
        got = _pickable(hwnd, pt, own)
        if got:
            return (hwnd, got)
        nxt = user32.GetWindow(hwnd, GW_HWNDNEXT)
        if not nxt:
            break
        hwnd = nxt
    # фолбэк: перечисление top-level окон (Z-order: первые = верхние)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = []

    def cb(h, _lp):
        got = _pickable(h, pt, own)
        if got:
            found.append((h, got))
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def window_rect_under_cursor():
    """Прямоугольник окна под курсором (для совместимости)."""
    found = window_under_cursor()
    return found[1] if found else None


def capture_window_interactive():
    """
    «Режим окна»: экран замораживается (снимок поверх), окно под курсором
    подсвечивается рамкой,левый клик — снять это окно, ESC/правый клик — отмена.
    :return: {'path','base64','width','height'} или None
    """
    try:
        region = WindowPicker().select()
    except Exception as exc:
        log.warn(f"Выбор окна не удался: {exc}")
        return None
    if not region:
        return None
    time.sleep(0.2)
    hwnd = region.get("hwnd")
    if hwnd:
        # Снимаем само окно, а не область экрана: иначе в кадр попадут
        # окна, лежащие сверху.
        path = grab_window(hwnd, region)
    else:
        path = grab_region(region)
    return {
        "path": path,
        "base64": preview_base64(path),
        "width": region["width"],
        "height": region["height"],
    }


class WindowPicker:
    """Замороженный экран + подсветка окна под курсором (красная рамка)."""

    ACCENT = "#ff3b5c"

    def select(self):
        try:
            import tkinter as tk
            from PIL import ImageGrab, ImageTk
        except Exception as exc:
            log.warn(f"Window picker недоступен: {exc}")
            return None
        # DPI-осведомлённость — как в RegionSelector: иначе на масштабе
        # 125/150% рамка подсветки «уезжает» от реальных границ окна.
        if os.name == "nt":
            try:
                import ctypes
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    ctypes.windll.user32.SetProcessDpiAware()
            except Exception:
                pass
        try:
            shot = ImageGrab.grab(all_screens=True)
        except Exception:
            try:
                shot = ImageGrab.grab()
            except Exception as exc:
                log.warn(f"Не удалось заморозить экран: {exc}")
                return None
        root = tk.Tk()
        root.title("Скриншот окна")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.configure(bg="black")
        try:
            root.attributes("-alpha", 0.97)
        except Exception:
            pass
        # master=root обязателен: после предыдущих Tk-окон стандартный root
        # может быть уже уничтожен, и картинка получает имя в мёртвом
        # интерпретаторе («image ... doesn't exist»).
        photo = ImageTk.PhotoImage(shot, master=root)
        # Держим ссылку на изображение: иначе Tk может собрать его сборщиком
        # мусора, и canvas падает с «image ... doesn't exist».
        root._screen_photo = photo
        canvas = tk.Canvas(root, highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        # подсказка поверх замороженного экрана (как в RegionSelector)
        try:
            sw = root.winfo_screenwidth()
            canvas.create_rectangle(0, 0, sw, 84, fill="#141821", outline="")
            canvas.create_text(
                sw // 2, 30,
                text="Наведите на окно — оно подсветится красной рамкой",
                fill="#22d3ee", font=("Segoe UI", 15, "bold"))
            canvas.create_text(
                sw // 2, 58,
                text="Клик — снять выделенное окно.  Esc или правая кнопка — отмена.",
                fill="#9fb0e8", font=("Segoe UI", 11))
        except Exception as exc:
            log.warn(f"Window picker: подсказка не нарисовалась: {exc}")
        state = {"rect_item": None, "label_item": None, "result": None,
                 "hwnd": None,
                 "off_x": shot.size[0] - root.winfo_screenwidth(),
                 "err_logged": False}

        def redraw():
            try:
                found = window_under_cursor()
            except Exception as exc:
                if not state["err_logged"]:
                    state["err_logged"] = True
                    log.warn(f"Window picker: сбой поиска окна под курсором: {exc}")
                found = None
            rect = found[1] if found else None
            if state["rect_item"]:
                canvas.delete(state["rect_item"])
                state["rect_item"] = None
            if state["label_item"]:
                canvas.delete(state["label_item"])
                state["label_item"] = None
            if not rect:
                state["hwnd"] = None
                return
            x1, y1, x2, y2 = rect
            state["rect_item"] = canvas.create_rectangle(
                x1 + 1, y1 + 1, x2 - 1, y2 - 1, outline=self.ACCENT, width=3)
            state["label_item"] = canvas.create_text(
                x1 + 6, y1 + 10, anchor="nw", fill=self.ACCENT,
                font=("Segoe UI", 10, "bold"),
                text="%d × %d" % (x2 - x1, y2 - y1))
            state["result"] = rect
            state["hwnd"] = found[0]

        def on_move(_e):
            redraw()

        def on_click(_e):
            if not state["result"]:
                return          # окна под курсором нет — клик игнорируем, не отмена
            x1, y1, x2, y2 = state["result"]
            state["picked"] = {"hwnd": state.get("hwnd"),
                               "left": x1, "top": y1,
                               "width": max(1, x2 - x1),
                               "height": max(1, y2 - y1)}
            root.destroy()

        def on_cancel(_e=None):
            state["picked"] = None
            root.destroy()

        state["picked"] = "none"
        canvas.bind("<Motion>", on_move)
        canvas.bind("<Button-1>", on_click)
        canvas.bind("<Escape>", on_cancel)
        canvas.bind("<Button-3>", on_cancel)
        redraw()
        root.mainloop()
        picked = state.get("picked")
        if not picked or picked == "none":
            return None
        log.info(f"Выбрано окно: {picked['width']}×{picked['height']}")
        return picked


def cleanup_temp_captures(max_files: int = 10):
    """Удаляет старые временные снимки."""
    try:
        files = [
            os.path.join(config.TMP_DIR, f)
            for f in os.listdir(config.TMP_DIR)
            if f.startswith(("capture_", "drop_", "overlay_"))
            and f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff"))
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[max_files:]:
            os.remove(old)
    except OSError:
        pass
