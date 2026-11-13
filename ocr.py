# -*- coding: utf-8 -*-
"""
ocr.py — офлайн-распознавание текста (OCR) через локальный Tesseract .

Поддерживается ЛЮБОЙ язык, для которого в папке resources/tessdata лежит
файл <код>.traineddata (по умолчанию: русский, английский, китайский,
украинский, немецкий, французский, испанский, итальянский, португальский,
польский, турецкий, нидерландский, чешский, белорусский, казахский).
Новые языки добавляются простым копированием .traineddata в эту папку.

Режим «авто»: параллельные пробы языков (rus/eng/chi_sim) → выбор НАБОРА
языков (1-3) → комбинированный финальный проход.

ИСПРАВЛЕНИЕ «русский с экрана распознаётся коряво или не распознаётся»:
  Раньше выполнялся ОДИН проход с одной предобработкой (Оцу-бинаризация)
  и одним режимом разметки (--psm 3). Для текста с экрана (антиалиасинг,
  цветные и ТЁМНЫЕ фоны, мелкий кегль) Оцу нередко «съедал» символы, а
  psm 3 ошибался на однострочных областях.
  Теперь перед финальным проходом идёт быстрый ТУРНИР вариантов:
    plain      — серый, увеличенный (Ланцош) до ≥1400 px: лучший вариант
                 для экранных снимков с антиалиасингом;
    otsu       — бинаризация по Оцу: документы и фото с ровным фоном;
    otsu_inv   — инвертированный Оцу: СВЕТЛЫЙ текст на тёмном фоне
                 (тёмные темы программ и сайтов — частый случай!);
    adaptive   — адаптивный порог: неравномерная подсветка, фото с экрана.
  Каждый вариант прогоняется параллельно (ThreadPool) на копии умеренного
  размера, побеждает вариант с лучшей средней уверенностью по словам;
  финальный проход выполняется ПОБЕДИТЕЛЕМ на полном разрешении.
  Для однострочных/блочных областей дополнительно соревнуются режимы
  разметки --psm 6 (блок) и --psm 3 (авто).
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import log

# Переменная окружения для Tesseract: где лежат .traineddata
os.environ.setdefault("TESSDATA_PREFIX", config.TESSDATA_DIR)

try:
    import pytesseract
    from pytesseract import Output

    _cmd = config.find_tesseract_cmd()
    if _cmd:
        pytesseract.pytesseract.tesseract_cmd = _cmd
    # tesseract.exe запускает сама библиотека pytesseract — без флагов
    # скрытия Windows показывала бы чёрное окно консоли на каждое распознавание.
    # Прокидываем CREATE_NO_WINDOW внутрь библиотеки (см. proc.py).
    import proc
    proc.patch_module(pytesseract.pytesseract)
    PYTESSERACT_AVAILABLE = True
except Exception:  # pragma: no cover
    PYTESSERACT_AVAILABLE = False

# cv2/numpy импортируются ЛЕНИВО (тяжёлый импорт ~1-3 с — не тормозим запуск)
_cv2 = None
_np = None


def _get_cv2():
    """Ленивая загрузка OpenCV: возвращает (cv2, np) или (None, None)."""
    global _cv2, _np
    if _cv2 is None:
        try:
            import cv2
            import numpy as np
            _cv2, _np = cv2, np
        except Exception:
            return None, None
    return _cv2, _np


class OcrError(Exception):
    """Ошибка распознавания текста."""


# Языки-зонды для определения письменности (идут параллельно)
PROBE_LANGS = ("rus", "eng", "chi_sim")

# Отличительные символы языков (латиница) — для уточнения европейского языка
DIACRITIC_HINTS = {
    "deu": set("äöüßÄÖÜ"),
    "fra": set("àâçèêëîïôùûœÀÂÇÈÊÎÏÔÙÛŒ"),
    "spa": set("ñ¿¡Ñ"),
    "ita": set("àèìòùÀÈÌÒÙ"),
    "por": set("ãõÃÕ"),
    "pol": set("ąćęłńśźżĄĆĘŁŃŚŹŻ"),
    "ces": set("ěřůďťňĚŘŮŤŇ"),
    "tur": set("ğışĞİŞ"),
}
# Отличительные символы кириллических языков
CYRILLIC_HINTS = {
    "ukr": set("іїєґІЇЄҐ"),
    # «Ы» — обычная русская буква, признаком белорусского она не является
    # (та же ошибка, что исправлена в translator._CYR_HINTS, урок L51).
    "bel": set("ўіЎІ"),
    "kaz": set("әғқңөұүһіӘҒҚҢӨҰҮҺ"),
}

# --- параметры турнира вариантов  -------------------------------------
TOURNAMENT_MAX_SIDE = 1600    # размер копии для турнира (баланс скорость/точность)
PROBE_MAX_SIDE = 700          # размер копии для проб языка
PLAIN_MIN_SIDE = 1400         # до какого размера увеличивать мелкие снимки
TOURNAMENT_PSM = (6, 3)       # соревнующиеся режимы разметки страницы
FAST_CONF = 88                # уверенность plain/psm6, при которой турнир не нужен
FAST_HINT_CONF = 75           # уверенность языковой пробы для быстрого пути


def available_lang_codes():
    """Коды языков, доступных по файлам .traineddata."""
    return [l["code"] for l in config.get_available_langs()]


def _resolve_langs(langs):
    """
    Приводит входной параметр языков к строке Tesseract.
    langs: 'auto' | ['rus','eng'] | 'rus+eng' | None
    Возвращает (lang_str, is_auto)
    """
    if langs == "auto" or not langs:
        return "auto", True
    if isinstance(langs, str):
        langs = [c.strip() for c in langs.split("+") if c.strip()]
    avail = set(available_lang_codes())
    picked = [c for c in langs if c in avail]
    if not picked:
        picked = [c for c in ("rus", "eng") if c in avail] or list(avail)[:1]
    return "+".join(picked), False


def _check_lang_files(lang_str: str):
    for lang in lang_str.split("+"):
        path = os.path.join(config.TESSDATA_DIR, f"{lang}.traineddata")
        if not os.path.isfile(path):
            raise OcrError(
                f"Не найден языковой файл «{lang}.traineddata». "
                "Положите его в папку App/resources/tessdata."
            )


def _load_gray(image_path: str):
    """Полноразмерное изображение в градациях серого (или None)."""
    cv2, np = _get_cv2()
    if cv2 is None:
        return None
    try:
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        return img
    except Exception:
        return None


def _load_gray_small(image_path: str, max_side: int = PROBE_MAX_SIDE):
    """Загружает уменьшенную копию в градациях серого (для быстрых проб)."""
    img = _load_gray(image_path)
    if img is None:
        return None
    try:
        cv2, _ = _get_cv2()
        h, w = img.shape[:2]
        m = max(h, w)
        if m > max_side:
            img = cv2.resize(img, (int(w * max_side / m), int(h * max_side / m)),
                             interpolation=cv2.INTER_AREA)
        return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Определение языков (параллельные пробы + комбинированный набор)
# ---------------------------------------------------------------------------

def _script_counts(text: str) -> dict:
    """Счётчики символов по письменностям (чистая функция — тестируема)."""
    c = {"cyr": 0, "lat": 0, "cjk": 0}
    for ch in text:
        o = ord(ch)
        if 0x0400 <= o <= 0x04FF:
            c["cyr"] += 1
        elif (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A) or (0x00C0 <= o <= 0x024F):
            c["lat"] += 1
        elif (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0xF900 <= o <= 0xFAFF):
            c["cjk"] += 1
    return c


def choose_langs(probes: dict, available: list) -> list:
    """
    Чистая функция выбора языков по результатам проб.
    :param probes: {lang: (text, confidence)}
    :param available: список доступных кодов языков
    :return: упорядоченный список (1-3 языка) для КОМБИНИРОВАННОГО финального
             прохода, например ['rus', 'eng'] для смешанного текста.
    """
    if not available:
        return ["eng"]
    confs = {l: float(c) for l, (t, c) in probes.items()}
    all_text = " ".join(t for t, _ in probes.values())
    sc = _script_counts(all_text)
    letters = max(1, sc["cyr"] + sc["lat"] + sc["cjk"])
    cyr_r, lat_r = sc["cyr"] / letters, sc["lat"] / letters

    chosen = []
    # CJK: китайская проба на НЕкитайском тексте «галлюцинирует» иероглифами,
    # поэтому её собственный текст НЕ считается доказательством письменности.
    # Верим только уверенной пробе (≥68% и ≥3 иероглифов) либо иероглифам,
    # которые увидели ДРУГИЕ движки.
    chi_text, chi_conf = probes.get("chi_sim", ("", -1.0))
    chi_cjk = _script_counts(chi_text)["cjk"]
    other_text = " ".join(t for l, (t, c) in probes.items() if l != "chi_sim")
    other_cjk = _script_counts(other_text)["cjk"]
    if "chi_sim" in available and ((chi_conf >= 68 and chi_cjk >= 3) or other_cjk >= 5):
        chosen.append("chi_sim")
    # письменность считается присутствующей, если её доля заметна
    # ИЛИ соответствующая проба дала высокую уверенность
    if "rus" in available and (cyr_r >= 0.10 or confs.get("rus", -1) >= 58):
        chosen.append("rus")
    if "eng" in available and (lat_r >= 0.10 or confs.get("eng", -1) >= 58):
        chosen.append("eng")

    # кириллические «родственники»: отличительные буквы в тексте пробы rus
    if cyr_r >= 0.10 or "rus" in chosen:
        rus_text = probes.get("rus", ("", 0))[0]
        for lang, marks in CYRILLIC_HINTS.items():
            if lang in available and (marks & set(rus_text)) and len(chosen) < 3:
                if lang not in chosen:
                    chosen.append(lang)

    # европейская диакритика: добавляем ОДИН самый вероятный язык
    if lat_r >= 0.10:
        votes = []
        chars = set(all_text)
        for lang, marks in DIACRITIC_HINTS.items():
            hits = len(chars & marks)
            if hits and lang in available:
                votes.append((hits, lang))
        votes.sort(reverse=True)
        for _, lang in votes[:1]:
            if lang not in chosen and len(chosen) < 3:
                chosen.append(lang)

    if not chosen:
        # ничего не уверенно — берём язык с лучшей пробной уверенностью,
        # иначе первый доступный (rus/eng в приоритете)
        if confs:
            best = max(confs.items(), key=lambda kv: kv[1])[0]
            if best in available:
                chosen = [best]
        if not chosen:
            chosen = [c for c in ("rus", "eng") if c in available][:1] or [available[0]]

    # сортировка по уверенности (первый язык Tesseract слегка приоритетнее)
    chosen.sort(key=lambda l: -confs.get(l, 0))
    return chosen[:3]


def _run_once(img, lang_str: str, psm: int):
    """
    Один проход Tesseract по матрице изображения.
    :return: (text, confidence, words, data)
    """
    from PIL import Image
    pil_img = Image.fromarray(img)
    data = pytesseract.image_to_data(
        pil_img, lang=lang_str, output_type=Output.DICT,
        config=f"--psm {psm} --oem 1 -c preserve_interword_spaces=1"
    )
    words = []
    for t, c in zip(data.get("text", []), data.get("conf", [])):
        t = str(t or "").strip()
        if t and float(c) >= 0:
            words.append((t, float(c)))
    text = _text_from_data(data)
    conf = sum(c for _, c in words) / len(words) if words else -1.0
    return text, conf, len(words), data


def _probe_one(pil_img, lang):
    """Один пробный прогон на уменьшенной копии. Возвращает (текст, уверенность)."""
    try:
        data = pytesseract.image_to_data(
            pil_img, lang=lang, output_type=Output.DICT,
            config="--psm 6 --oem 1 -c preserve_interword_spaces=1"
        )
        words = []
        for t, c in zip(data.get("text", []), data.get("conf", [])):
            t = str(t or "").strip()
            if t and float(c) >= 0:
                words.append((t, float(c)))
        text = " ".join(w for w, _ in words)
        conf = sum(c for _, c in words) / len(words) if words else -1.0
        return text, conf
    except Exception as exc:
        log.warn(f"Проба языка «{lang}» не удалась: {exc}")
        return "", -1.0


def detect_language(image_path: str, progress_cb=None) -> dict:
    """
    Автоопределение набора языков изображения.
    Параллельные пробные прогоны (rus/eng/chi_sim) на УВЕЛИЧЕННОЙ копии
    (700 px и psm 6 вместо 480 px и psm 3 — мелкий экранный текст
    перестал «теряться» на этапе определения языка) → choose_langs().

    :param progress_cb: необязательный колбэк (pct:int, text:str)
    :return: {'lang': 'rus+eng', 'langs': [...], 'scores': [...], 'tried': N}
    """
    if not PYTESSERACT_AVAILABLE:
        raise OcrError("Компонент OCR (pytesseract) недоступен.")
    codes = available_lang_codes()
    if not codes:
        raise OcrError("В папке tessdata нет ни одного языка (.traineddata).")
    if len(codes) == 1:
        return {"lang": codes[0], "langs": codes[:1], "scores": [(codes[0], 0.0)], "tried": 1}

    from PIL import Image
    small = _load_gray_small(image_path, max_side=PROBE_MAX_SIDE)
    pil_img = Image.fromarray(small) if small is not None else Image.open(image_path)

    probe_langs = [l for l in PROBE_LANGS if l in codes] or codes[:3]

    def _report(pct, txt):
        if progress_cb:
            try:
                progress_cb(pct, txt)
            except Exception:
                pass

    probes = {}
    try:
        with ThreadPoolExecutor(max_workers=min(3, len(probe_langs))) as ex:
            futs = {ex.submit(_probe_one, pil_img, l): l for l in probe_langs}
            done = 0
            for fut in as_completed(futs):
                probes[futs[fut]] = fut.result()
                done += 1
                _report(10 + int(35 * done / len(futs)),
                        f"Определяю язык… ({done}/{len(futs)})")
    finally:
        try:
            pil_img.close()
        except Exception:
            pass

    langs = choose_langs(probes, codes)
    scores = sorted(((l, c) for l, (t, c) in probes.items()), key=lambda x: -x[1])
    log.info(f"Автоопределение языков: «{'+'.join(langs)}» "
             f"(пробы: {', '.join(f'{l}={round(c, 1)}' for l, c in scores)})")
    return {"lang": "+".join(langs), "langs": langs, "scores": scores, "tried": len(probes)}


# ---------------------------------------------------------------------------
# варианты предобработки и турнир между ними
# ---------------------------------------------------------------------------

def _make_variants(gray):
    """
    Словарь вариантов предобработки: имя -> матрица (градации серого).
    Чистая логика на cv2-матрице — тестируема через _variant_names().
    """
    cv2, _ = _get_cv2()
    variants = {}
    g = gray
    h, w = g.shape[:2]
    if max(h, w) < PLAIN_MIN_SIDE:
        scale = PLAIN_MIN_SIDE / float(max(h, w))
        g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    variants["plain"] = g
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["otsu"] = otsu
    variants["otsu_inv"] = cv2.bitwise_not(otsu)
    variants["adaptive"] = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10)
    return variants


def variant_names():
    """Имена вариантов предобработки (порядок = приоритет при равенстве очков)."""
    return ["plain", "otsu", "otsu_inv", "adaptive"]


def _downscale(img, max_side: int):
    cv2, _ = _get_cv2()
    h, w = img.shape[:2]
    m = max(h, w)
    if m > max_side:
        img = cv2.resize(img, (int(w * max_side / m), int(h * max_side / m)),
                         interpolation=cv2.INTER_AREA)
    return img


def score_candidate(text: str, conf: float, words: int) -> float:
    """
    Оценка кандидата турнира (чистая функция — тестируема).
    Средняя уверенность слов + небольшой бонус за объём найденного текста;
    пустые и «однословные галлюцинации» штрафуются.
    """
    if words <= 0 or conf < 0:
        return -1.0
    t = (text or "").strip()
    if len(t) < 2:
        return -1.0
    score = conf
    if words >= 3:
        score += 4.0
    elif words == 2:
        score += 2.0
    if len(t) < 4:
        score -= 5.0
    return score


def pick_best(candidates: list):
    """
    Выбирает победителя турнира (чистая функция — тестируема).
    :param candidates: [(name, psm, text, conf, words), ...]
    :return: лучший кандидат или None.
    """
    scored = []
    for cand in candidates:
        name, psm, text, conf, words = cand
        s = score_candidate(text, conf, words)
        # при равенстве очков — приоритет у варианта/psm с меньшим индексом
        rank = (variant_names().index(name) if name in variant_names() else 99) * 10 + \
               (TOURNAMENT_PSM.index(psm) if psm in TOURNAMENT_PSM else 99)
        scored.append((s, -rank, cand))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not scored or scored[0][0] <= -1.0:
        return None
    return scored[0][2]


def _tournament(gray, lang_str: str, progress_cb=None, fast_hint=False):
    """
    Турнир вариантов предобработки × режимов psm на копии ≤ TOURNAMENT_MAX_SIDE.
    :param fast_hint: языковые пробы уже дали высокую уверенность — сначала
                      пробуем plain/psm6 и при успехе не запускаем турнир.
    :return: (winner или None, full_variants, was_full_size)
             winner = (name, psm, text, conf, words, data)
    """
    cv2, _ = _get_cv2()

    def _report(pct, txt):
        if progress_cb:
            try:
                progress_cb(pct, txt)
            except Exception:
                pass

    h, w = gray.shape[:2]
    full_size = max(h, w) <= TOURNAMENT_MAX_SIDE
    work = gray if full_size else _downscale(gray, TOURNAMENT_MAX_SIDE)
    variants = _make_variants(work)

    jobs = []
    for name in variant_names():
        for psm in TOURNAMENT_PSM:
            jobs.append((name, psm))
    # «otsu_inv» и «adaptive» проверяем только с psm 6 — экономим время:
    jobs = [(n, p) for (n, p) in jobs if not (n in ("otsu_inv", "adaptive") and p == 3)]

    # Быстрый путь: языковые пробы уже показали высокую уверенность
    # (чистый экранный снимок). Тогда plain/psm6 на рабочем размере почти
    # наверняка победит, и полный турнир из шести прогонов Tesseract не нужен.
    # Если снимок шумный, пробы уверенности не дают — турнир идёт как раньше,
    # без лишних прогонов.
    results = []
    if fast_hint:
        _report(45, "Пробую основной вариант…")
        try:
            text, conf, words, data = _run_once(variants["plain"], lang_str, 6)
            if conf >= FAST_CONF and words >= 2 and len((text or "").strip()) >= 2:
                log.info(f"OCR-турнир: быстрый путь plain/psm6 "
                         f"(уверенность {round(conf, 1)}%, слов {words})")
                return ("plain", 6, text, conf, words, data), variants, full_size
            results.append(("plain", 6, text, conf, words, data))
            jobs = [j for j in jobs if j != ("plain", 6)]
        except Exception as exc:
            log.warn(f"Турнир OCR: быстрая проба plain/psm6 не удалась: {exc}")

    _report(50, f"Подбираю обработку изображения… ({len(jobs)} проб)")
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
        futs = {ex.submit(_run_once, variants[name], lang_str, psm): (name, psm)
                for name, psm in jobs}
        done = 0
        for fut in as_completed(futs):
            name, psm = futs[fut]
            try:
                text, conf, words, data = fut.result()
            except Exception as exc:
                log.warn(f"Турнир OCR: проба {name}/psm{psm} не удалась: {exc}")
                text, conf, words, data = "", -1.0, 0, None
            results.append((name, psm, text, conf, words, data))
            done += 1
            _report(50 + int(25 * done / len(futs)),
                    f"Подбираю обработку… ({done}/{len(futs)})")

    scored = [(r[0], r[1], r[2], r[3], r[4]) for r in results]
    best = pick_best(scored)
    winner = None
    if best:
        for r in results:
            if (r[0], r[1]) == (best[0], best[1]):
                winner = r
                break
    if winner:
        log.info(f"OCR-турнир: победил вариант «{winner[0]}» psm {winner[1]} "
                 f"(уверенность {round(winner[3], 1)}%, слов {winner[4]})")
    else:
        log.warn("OCR-турнир: ни один вариант не дал текста")
    return winner, variants, full_size


def _preprocess(image_path: str) -> str:
    """
    Запасной путь (без cv2 недоступен турнир): лёгкая предобработка —
    градации серого, увеличение мелких изображений, бинаризация по Оцу.
    Возвращает путь к подготовленному файлу (или исходный путь).
    """
    cv2, np = _get_cv2()
    if cv2 is None:
        return image_path
    try:
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return image_path
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        if max(h, w) < 1000:
            scale = 1000.0 / max(h, w)
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out_path = os.path.join(config.TMP_DIR, "_ocr_prepared.png")
        ok, buf = cv2.imencode(".png", binary)
        if ok:
            buf.tofile(out_path)
            return out_path
    except Exception:
        pass
    return image_path


def _text_from_data(data) -> str:
    """
    Собирает полный текст из результата image_to_data (по номерам
    блоков/абзацев/строк). Позволяет НЕ запускать tesseract второй раз
    (image_to_string) — финальный проход становится вдвое быстрее,
    а слова и уверенность берутся из одного и того же прогона.
    """
    lines = {}
    try:
        for i, txt in enumerate(data.get("text", [])):
            txt = str(txt or "").strip()
            if not txt:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(txt)
    except Exception:
        return ""
    return "\n".join(" ".join(words) for words in lines.values())


def _lines_from_data(data, scale: float = 1.0):
    """Группирует слова image_to_data в строки с координатами."""
    if not data:
        return []
    grouped = {}
    for i, raw in enumerate(data.get("text", [])):
        txt = str(raw or "").strip()
        if not txt:
            continue
        try:
            c = float(data["conf"][i])
        except Exception:
            continue
        if c < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        item = grouped.get(key)
        if item is None:
            grouped[key] = {"words": [txt], "x0": x, "y0": y,
                            "x1": x + w, "y1": y + h, "confs": [c]}
        else:
            item["words"].append(txt)
            item["confs"].append(c)
            item["x0"] = min(item["x0"], x)
            item["y0"] = min(item["y0"], y)
            item["x1"] = max(item["x1"], x + w)
            item["y1"] = max(item["y1"], y + h)
    inv = 1.0 / scale
    out = []
    for key in sorted(grouped):
        item = grouped[key]
        out.append({
            "text": " ".join(item["words"]),
            "box": [int(item["x0"] * inv), int(item["y0"] * inv),
                    int((item["x1"] - item["x0"]) * inv),
                    int((item["y1"] - item["y0"]) * inv)],
            "conf": round(sum(item["confs"]) / len(item["confs"]), 1),
        })
    return out


def ocr_image(image_path: str, langs=None, progress_cb=None) -> dict:
    """
    Распознаёт ВЕСЬ текст на изображении (поддерживает смешанные языки).

    перед финальным проходом — турнир вариантов предобработки
    (plain/otsu/otsu_inv/adaptive × psm 6/3); победитель применяется
    к полному разрешению (если изображение уже ≤ TOURNAMENT_MAX_SIDE —
    результат турнира и есть финальный, второй проход не нужен).

    :param image_path: путь к файлу изображения
    :param langs: 'auto' — определить автоматически (набор языков),
                  либо список/строку ['rus','eng'] / 'rus+eng'
    :param progress_cb: колбэк (pct:int, text:str) для шкалы прогресса
    :return: {'text', 'lang', 'confidence', 'words', 'detected', 'variant',
              'lines' — строки с координатами для наложения перевода}
    """
    if not PYTESSERACT_AVAILABLE:
        raise OcrError("Компонент OCR (pytesseract) недоступен.")
    if not os.path.isfile(image_path):
        raise OcrError(f"Файл не найден: {image_path}")

    def _report(pct, txt):
        if progress_cb:
            try:
                progress_cb(pct, txt)
            except Exception:
                pass

    _report(5, "Готовлю изображение…")
    detected = None
    fast_hint = False
    lang_str, is_auto = _resolve_langs(langs)
    if is_auto:
        det = detect_language(image_path, progress_cb=progress_cb)
        detected = det["lang"]
        lang_str = detected
        fast_hint = max((float(c) for _, c in det.get("scores", [])),
                        default=0.0) >= FAST_HINT_CONF
    _check_lang_files(lang_str)
    log.info(f"OCR: файл «{os.path.basename(image_path)}», языки «{lang_str}»")

    gray = _load_gray(image_path)
    text = ""
    confs = []
    lines = []
    line_scale = 1.0
    variant_used = "legacy"
    try:
        if gray is not None:
            winner, _variants, full_size = _tournament(
                gray, lang_str, progress_cb, fast_hint=fast_hint)
            if winner is None:
                # ни один вариант не дал текста — честно возвращаем пустоту
                variant_used = "none"
                data = None
            elif full_size:
                # турнир шёл на полном разрешении — второй проход не нужен.
                # ВАЖНО: _make_variants() увеличивает мелкие снимки до
                # PLAIN_MIN_SIDE, поэтому координаты слов надо вернуть
                # к масштабу ИСХОДНОГО изображения.
                _name, _psm, text, _conf, _words, data = winner
                h0, w0 = gray.shape[:2]
                if max(h0, w0) < PLAIN_MIN_SIDE:
                    line_scale = PLAIN_MIN_SIDE / float(max(h0, w0))
                confs = [float(c) for c, w in zip(data.get("conf", []), data.get("text", []))
                         if float(c) >= 0 and str(w).strip()]
                variant_used = f"{winner[0]}+psm{winner[1]}"
            else:
                # финальный проход победителем на ПОЛНОМ разрешении
                _report(80, "Финальное распознавание…")
                name, psm = winner[0], winner[1]
                full_variants = _make_variants(gray)
                text, _conf, _words, data = _run_once(full_variants[name], lang_str, psm)
                confs = [float(c) for c, w in zip(data.get("conf", []), data.get("text", []))
                         if float(c) >= 0 and str(w).strip()]
                variant_used = f"{name}+psm{psm} (полный размер)"
        else:
            # OpenCV недоступен — прежний одиночный проход
            _report(50, f"Распознаю текст ({lang_str.replace('+', ' + ')})…")
            prepared = _preprocess(image_path)
            data = None
            try:
                from PIL import Image
                with Image.open(prepared) as im:
                    data = pytesseract.image_to_data(
                        im, lang=lang_str, output_type=Output.DICT,
                        config="--psm 3 --oem 1 -c preserve_interword_spaces=1"
                    )
                text = _text_from_data(data)
            finally:
                if prepared != image_path and os.path.isfile(prepared):
                    try:
                        os.remove(prepared)
                    except OSError:
                        pass
            if data is not None:
                confs = [float(c) for c, w in zip(data.get("conf", []), data.get("text", []))
                         if float(c) >= 0 and str(w).strip()]
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrError(
            "Не найден движок Tesseract-OCR (папка App/resources/tesseract)."
        ) from exc
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"Сбой распознавания текста: {exc}") from exc

    text = re.sub(r"[ \t]+\n", "\n", (text or "").strip())
    confidence = round(sum(confs) / len(confs), 1) if confs else None
    # Координаты строк — из того же прогона Tesseract, без повторного OCR.
    # При запасном пути без OpenCV координаты подготовленного файла не
    # соответствуют исходнику, поэтому строки не отдаём.
    if gray is not None and data:
        lines = _lines_from_data(data, line_scale)

    _report(100, "")
    log.ok(f"OCR завершён: {len(text)} симв., уверенность {confidence}%, "
           f"языки {lang_str}, вариант {variant_used}")
    return {
        "text": text,
        "lang": lang_str,
        "confidence": confidence,
        "words": len(confs),
        "detected": detected,
        "variant": variant_used,
        "lines": lines,
    }


def _screen_score(text: str, conf: float) -> float:
    """Оценка кандидата для экрана: слова важнее «уверенной» мешанины."""
    t = (text or "").strip()
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", t)
    letters = sum(len(w) for w in words)
    if conf < 0 or letters < 4:
        return -1.0
    coverage = letters / max(1, len(t))
    bad = sum(1 for w in t.split()
              if w and not re.search(r"[A-Za-zА-Яа-яЁё]", w))
    return (conf * 0.6 + min(30, letters) * 1.5 +
            min(8, len(words)) * 3.0 + coverage * 18.0 - bad * 2.0)


_SHORT_OK = {"QR", "OK", "ID", "AI", "UI", "IT", "IP", "PC", "TV",
             "HD", "4K", "3D", "VK", "RF"}
# Короткие слова, которые нельзя принимать за мусорный префикс.
_SHORT_WORDS = {
    "а", "в", "во", "вы", "да", "до", "ее", "её", "ей", "ею", "же", "за",
    "и", "из", "их", "к", "ко", "ли", "мы", "на", "над", "не", "ни", "но",
    "о", "об", "он", "она", "они", "от", "по", "под", "про", "с", "со",
    "так", "то", "ты", "у", "я",
    "a", "an", "i", "in", "on", "at", "to", "of", "or", "is", "it", "as",
    "by", "be", "we", "he", "she", "my", "no", "so", "up", "us", "do",
    "go", "if", "me", "ok", "id", "qr", "ai", "ui", "ip", "pc", "tv",
    "hd", "4k", "3d", "vk", "rf",
}
_BAD_PREFIX_PUNCT = set("()[]{}«»|\\/")


def clean_screen_text(text: str) -> str:
    """Убирает служебные значки и обрывки в начале строк экранного OCR.

    Например, «» |) ps Freebutt Tiny» превращается в «Freebutt Tiny»,
    а строка «iF) -» отбрасывается. Числа, даты и короткие слова
    («На», «В», «Не», «По», «123») сохраняются.
    """
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        while tokens:
            tok = tokens[0]
            core = tok.strip(".,!?;:()[]{}«»\"'`—–-")
            letters = sum(1 for ch in core if ch.isalpha())
            digits = sum(1 for ch in core if ch.isdigit())
            # Число в начале строки — это дата, сумма или пункт списка.
            if digits and not letters:
                break
            if letters >= 3:
                break
            low = core.lower()
            if low in _SHORT_WORDS or low in _SHORT_OK:
                if not (set(tok) & _BAD_PREFIX_PUNCT):
                    break
            # Заглавная короткая кириллическая/латинская буква — обычно
            # настоящее слово или инициал, а не «iF)»/«ps».
            if letters and core[:1].isupper() and not (set(tok) & _BAD_PREFIX_PUNCT):
                break
            if digits and letters:
                break
            tokens.pop(0)
        cleaned = " ".join(tokens).strip()
        if cleaned and re.search(r"[A-Za-zА-Яа-яЁё0-9]", cleaned):
            out.append(cleaned)
    return "\n".join(out)


def ocr_screen(image_path: str, langs=None, progress_cb=None) -> dict:
    """
    OCR для снимков экрана: мелкий текст интерфейса.

    В отличие от обычного ocr_image не растягивает картинку до 1400 px
    (для области 171×116 это 8× и сплошное мыло), а пробует увеличение
    2× и 3× с повышением резкости и psm 6/11. Побеждает не просто самая
    высокая уверенность, а правдоподобный текст: с буквами и словами.
    """
    if not PYTESSERACT_AVAILABLE:
        raise OcrError("Компонент OCR (pytesseract) недоступен.")
    if not os.path.isfile(image_path):
        raise OcrError(f"Файл не найден: {image_path}")
    lang_str, is_auto = _resolve_langs(langs)
    detected = None
    if is_auto:
        det = detect_language(image_path)
        lang_str = det["lang"]
        detected = det["lang"]
    _check_lang_files(lang_str)

    gray = _load_gray(image_path)
    if gray is None:
        raise OcrError("Не удалось открыть снимок экрана.")
    cv2, _ = _get_cv2()
    h, w = gray.shape[:2]
    scales = [s for s in (2, 3) if max(h, w) * s <= 2600] or [1]
    variants = []
    for s in scales:
        img = gray if s == 1 else cv2.resize(
            gray, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        blur = cv2.GaussianBlur(img, (0, 0), 1.0)
        sharp = cv2.addWeighted(img, 1.7, blur, -0.7, 0)
        variants.append((f"x{s}_sharp", sharp))

    def _report(pct, txt):
        if progress_cb:
            try:
                progress_cb(pct, txt)
            except Exception:
                pass

    langs_to_try = [lang_str]
    avail = set(available_lang_codes())
    # Чистый английский вариант нужен даже когда автоопределение выбрало
    # «eng+rus»: русская модель в смеси портит английские подписи («пут»
    # вместо «Tiny»). Для русского текста он проиграет по оценке.
    if "eng" in avail and lang_str != "eng":
        langs_to_try.append("eng")
    jobs = [(f"{lang}:{name}", img, psm, lang)
            for lang in langs_to_try for name, img in variants
            for psm in (6, 11)]
    results = []
    _report(20, "Распознаю мелкий текст…")
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
        futs = {ex.submit(_run_once, img, lang, psm): (name, psm)
                for name, img, psm, lang in jobs}
        done = 0
        for fut in as_completed(futs):
            name, psm = futs[fut]
            try:
                text, conf, words, data = fut.result()
            except Exception as exc:
                log.warn(f"OCR экрана: проба {name}/psm{psm} не удалась: {exc}")
                text, conf, words, data = "", -1.0, 0, None
            results.append((name, psm, text, conf, words, data))
            done += 1
            _report(20 + int(65 * done / len(futs)),
                    f"Распознаю мелкий текст… ({done}/{len(futs)})")

    def plausible(text, conf, words):
        if words <= 0 or conf < 0:
            return False
        t = (text or "").strip()
        letters = sum(1 for ch in t if ch.isalpha())
        if letters < 4 or letters / max(1, len(t)) < 0.45:
            return False
        return any(len(word) >= 3 and word.isalpha() for word in t.split())

    good = [r for r in results if plausible(r[2], r[3], r[4])]
    # psm 11 полезен для разреженного текста, но на мелких подписях часто
    # рвёт слова; при прочих равных предпочитаем структурный psm 6.
    scored = [(_screen_score(r[2], r[3]) - (6.0 if r[1] == 11 else 0.0), r)
              for r in good]
    scored.sort(key=lambda item: item[0], reverse=True)
    winner = scored[0][1] if scored and scored[0][0] > 0 else None
    # Если лучший вариант содержит кириллицу, но почти такой же результат
    # есть в чисто латинском варианте — для английских подписей он точнее
    # («Tiny» вместо «пут»). Для русского текста латинский вариант заметно
    # слабее и не выбирается.
    if winner and re.search(r"[А-Яа-яЁё]", winner[2] or ""):
        best_score = scored[0][0]
        latin = [(s, r) for s, r in scored
                 if s >= best_score * 0.85
                 and not re.search(r"[А-Яа-яЁё]", r[2] or "")]
        if latin:
            winner = latin[0][1]
    if winner:
        win_lang = winner[0].split(":", 1)[0] if ":" in winner[0] else lang_str
        cleaned = clean_screen_text(winner[2])
        if cleaned != (winner[2] or "").strip():
            log.info("OCR экрана: убран служебный префикс/мусор")
        log.info(f"OCR экрана: победил {winner[0]}/psm{winner[1]} "
                 f"(уверенность {round(winner[3], 1)}%, слов {winner[4]})")
        _report(100, "")
        return {"text": cleaned, "lang": win_lang,
                "confidence": round(winner[3], 1), "words": winner[4],
                "detected": detected,
                "variant": f"{winner[0]}+psm{winner[1]}"}
    log.warn("OCR экрана: уверенного текста не найдено")
    _report(100, "")
    return {"text": "", "lang": lang_str, "confidence": None, "words": 0,
            "detected": detected, "variant": "none"}


def ocr_lines(image_path: str, langs=None) -> dict:
    """
    Распознаёт текст ПО СТРОКАМ и возвращает координаты для наложения перевода.

    :return: {'lang': str, 'width': int, 'height': int,
              'lines': [{'text': str, 'box': [x, y, w, h], 'conf': float}, ...]}
    """
    if not PYTESSERACT_AVAILABLE:
        raise OcrError("Компонент OCR (pytesseract) недоступен.")
    if not os.path.isfile(image_path):
        raise OcrError(f"Файл не найден: {image_path}")
    lang_str, is_auto = _resolve_langs(langs)
    if is_auto:
        det = detect_language(image_path)
        lang_str = det["lang"]
    _check_lang_files(lang_str)

    gray = _load_gray(image_path)
    if gray is None:
        raise OcrError("Не удалось открыть изображение для наложения перевода.")
    cv2, _ = _get_cv2()
    h, w = gray.shape[:2]
    scale = 1.0
    work = gray
    if max(h, w) < 1200:
        scale = 1200.0 / max(h, w)
        work = cv2.resize(gray, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)

    text, conf, words, data = _run_once(work, lang_str, 6)
    if words == 0:
        text, conf, words, data = _run_once(work, lang_str, 3)
    if not words or data is None:
        return {"lang": lang_str, "width": w, "height": h, "lines": []}

    grouped = {}
    for i, raw in enumerate(data.get("text", [])):
        txt = str(raw or "").strip()
        if not txt:
            continue
        try:
            c = float(data["conf"][i])
        except Exception:
            continue
        if c < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x = int(data["left"][i])
        y = int(data["top"][i])
        bw = int(data["width"][i])
        bh = int(data["height"][i])
        item = grouped.get(key)
        if item is None:
            grouped[key] = {"words": [txt], "x0": x, "y0": y,
                            "x1": x + bw, "y1": y + bh, "confs": [c]}
        else:
            item["words"].append(txt)
            item["confs"].append(c)
            item["x0"] = min(item["x0"], x)
            item["y0"] = min(item["y0"], y)
            item["x1"] = max(item["x1"], x + bw)
            item["y1"] = max(item["y1"], y + bh)

    inv = 1.0 / scale
    lines = []
    for key in sorted(grouped):
        item = grouped[key]
        lines.append({
            "text": " ".join(item["words"]),
            "box": [int(item["x0"] * inv), int(item["y0"] * inv),
                    int((item["x1"] - item["x0"]) * inv),
                    int((item["y1"] - item["y0"]) * inv)],
            "conf": round(sum(item["confs"]) / len(item["confs"]), 1),
        })
    log.info(f"OCR строк: {len(lines)}, языки «{lang_str}», "
             f"размер {w}x{h}")
    return {"lang": lang_str, "width": w, "height": h, "lines": lines}


def check_engine() -> dict:
    """Проверка доступности движка OCR (для диагностики)."""
    result = {"ok": False, "version": None, "langs": [], "error": None}
    if not PYTESSERACT_AVAILABLE:
        result["error"] = "pytesseract не установлен"
        return result
    try:
        result["version"] = str(pytesseract.get_tesseract_version())
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"Tesseract не найден: {exc}"
        return result
    result["langs"] = available_lang_codes()
    return result
