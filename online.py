# -*- coding: utf-8 -*-
"""
online.py — онлайн-перевод и онлайн-OCR (Google / Яндекс) по желанию владельца.

Режимы выбираются в настройках: «Перевод: локально / Google / Яндекс» и
«OCR: локально / Google / Яндекс».

Что возможно БЕЗ ключей и что с ключами (проверено 2026-10-19):
  • Google Переводчик — работает БЕЗ ключа через публичный endpoint
    translate.googleapis.com/translate_a/single (неофициальный, но стабильный;
    при сбое программа АВТОМАТИЧЕСКИ падает обратно на локальный перевод).
  • Яндекс Переводчик — официально требует бесплатный ключ (API v1.5);
    ключ вводится в настройках, без ключа режим не включается.
  • OCR Google (Cloud Vision) и OCR Яндекс (Vision) — это платные облачные
    API с бесплатным лимитом, ОБА требуют ключ; ключ вводится в настройках.
    Бесплатного OCR «как у Гугла» без ключа не существует: распознавание
    картинок у Google/Yandex закрыто капчей и не предназначено для API.
Локальный режим остаётся основным: интернет не нужен вовсе.
"""

import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Raspoznavatel online-services)"}
TIMEOUT = 20

GOOGLE_TRANSLATE_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&dt=t&sl=%s&tl=%s&q=%s")
YANDEX_TRANSLATE_URL = (
    "https://translate.yandex.net/api/v1.5/tr.json/translate"
    "?key=%s&lang=%s&text=%s")
GOOGLE_VISION_URL = "https://vision.googleapis.com/v1/images:annotate?key=%s"
YANDEX_VISION_URL = "https://vision.api.cloud.yandex.net/vision/v1/annotate"


class OnlineError(Exception):
    """Онлайн-сервис недоступен/отказал — вызывающий падает на локальный режим."""


def _get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _post_json(url, payload, headers=None, timeout=TIMEOUT):
    data = json.dumps(payload).encode()
    h = dict(UA, **{"Content-Type": "application/json"})
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------------------
# Перевод
# ---------------------------------------------------------------------------

def parse_google_translate(raw: bytes):
    """
    Чистая функция: разбор ответа translate_a/single.
    :return: (текст, определённый язык) ; бросает OnlineError при мусоре.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise OnlineError(f"ответ Google не читается: {exc}")
    parts = []
    for chunk in (data[0] or []) if isinstance(data, list) else []:
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str):
            parts.append(chunk[0])
    text = "".join(parts).strip()
    detected = None
    if isinstance(data, list) and len(data) > 2 and isinstance(data[2], str):
        detected = data[2]
    if not text:
        raise OnlineError("Google вернул пустой перевод")
    return text, detected


def translate_google(text: str, src: str = "auto", tgt: str = "ru") -> dict:
    """Перевод через Google БЕЗ ключа. :return: {'translated','detected'}"""
    url = GOOGLE_TRANSLATE_URL % (
        urllib.parse.quote(src or "auto"),
        urllib.parse.quote(tgt or "ru"),
        urllib.parse.quote(text))
    try:
        raw = _get(url)
    except Exception as exc:
        raise OnlineError(f"Google недоступен: {exc}")
    translated, detected = parse_google_translate(raw)
    return {"translated": translated, "detected": detected, "via": "google"}


def parse_yandex_translate(raw: bytes):
    """Чистая функция: разбор ответа Яндекс API v1.5."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise OnlineError(f"ответ Яндекса не читается: {exc}")
    if data.get("code") != 200 or not data.get("text"):
        raise OnlineError("Яндекс отказал: %s" % (data.get("message") or data.get("code")))
    lang = (data.get("lang") or "").split("-")
    return "\n".join(data["text"]), (lang[0] if lang else None)


def translate_yandex(text: str, key: str, src: str = "auto", tgt: str = "ru") -> dict:
    """Перевод через Яндекс (нужен бесплатный ключ из настроек)."""
    if not key:
        raise OnlineError("для Яндекса нужен ключ (Настройки → Перевод)")
    pair = tgt if (src or "auto") == "auto" else f"{src}-{tgt}"
    url = YANDEX_TRANSLATE_URL % (
        urllib.parse.quote(key), urllib.parse.quote(pair),
        urllib.parse.quote(text))
    try:
        raw = _get(url)
    except Exception as exc:
        raise OnlineError(f"Яндекс недоступен: {exc}")
    translated, detected = parse_yandex_translate(raw)
    return {"translated": translated, "detected": detected, "via": "yandex"}


# ---------------------------------------------------------------------------
# OCR (только с ключами: это платные облачные API с бесплатным лимитом)
# ---------------------------------------------------------------------------

def ocr_google_vision(image_bytes: bytes, key: str) -> str:
    """Текст с картинки через Google Cloud Vision (ключ из настроек)."""
    if not key:
        raise OnlineError("для Google OCR нужен ключ (Настройки → Распознавание)")
    import base64
    payload = {"requests": [{
        "image": {"content": base64.b64encode(image_bytes).decode()},
        "features": [{"type": "TEXT_DETECTION"}]}]}
    try:
        raw = _post_json(GOOGLE_VISION_URL % urllib.parse.quote(key), payload)
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise OnlineError(f"Google Vision недоступен: {exc}")
    resp = (data.get("responses") or [{}])[0]
    if resp.get("error"):
        raise OnlineError("Google Vision: %s" % resp["error"].get("message"))
    text = (resp.get("fullTextAnnotation") or {}).get("text") or ""
    if not text.strip():
        raise OnlineError("Google Vision не нашёл текст")
    return text


def ocr_yandex_vision(image_bytes: bytes, key: str, folder_id: str = "") -> str:
    """Текст с картинки через Yandex Vision (ключ и каталог из настроек)."""
    if not key:
        raise OnlineError("для Яндекс OCR нужен ключ (Настройки → Распознавание)")
    if not folder_id:
        raise OnlineError("для Яндекс OCR нужен ID каталога Яндекс Cloud "
                          "(Настройки → Распознавание)")
    import base64
    payload = {"folderId": folder_id,
               "analyzeSpecs": [{
                   "features": [{"type": "TEXT_DETECTION",
                                 "textDetectionConfig": {
                                     "languageCodes": ["ru", "en"]}}],
                   "image": {"content": base64.b64encode(image_bytes).decode()}}]}
    try:
        raw = _post_json(YANDEX_VISION_URL, payload,
                         headers={"Authorization": "Api-Key %s" % key})
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise OnlineError(f"Yandex Vision недоступен: {exc}")
    results = data.get("results") or []
    if not results and data.get("message"):
        raise OnlineError("Yandex Vision: %s" % data.get("message"))
    texts = []
    for res in results:
        ann = ((res.get("textAnnotation") or {}).get("pages") or [{}])
        for page in ann:
            for line in (page.get("lines") or []):
                texts.append("".join(w.get("text", "") for w in line.get("words") or []))
    text = "\n".join(t for t in texts if t.strip())
    if not text.strip():
        raise OnlineError("Yandex Vision не нашёл текст")
    return text


def probe(provider: str, key: str = "") -> dict:
    """Быстрая проверка доступности провайдера (для журнала/настроек)."""
    try:
        if provider == "google":
            translate_google("hello", "auto", "ru")
            return {"ok": True, "provider": provider}
        if provider == "yandex":
            if not key:
                return {"ok": False, "provider": provider, "error": "нужен ключ"}
            translate_yandex("hello", key, "auto", "ru")
            return {"ok": True, "provider": provider}
    except OnlineError as exc:
        return {"ok": False, "provider": provider, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "provider": provider, "error": str(exc)}
    return {"ok": False, "provider": provider, "error": "неизвестный провайдер"}
