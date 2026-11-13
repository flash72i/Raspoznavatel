# -*- coding: utf-8 -*-
import base64
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "installer_mockup" / "preview.html"
TAILWIND = ROOT / "installer_custom" / "tailwind.js"
FONT_CSS = ROOT / "installer_assets" / "fonts.css"
OUT = ROOT / "installer_mockup" / "installer_ui.html"
CACHE = ROOT / "installer_assets" / "font_cache"
CACHE.mkdir(parents=True, exist_ok=True)

html = SRC.read_text(encoding="utf-8")
tailwind = TAILWIND.read_text(encoding="utf-8")
font_css = FONT_CSS.read_text(encoding="utf-8-sig")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

# 1. Tailwind — внутрь файла.
html = html.replace(
    '<script src="https://cdn.tailwindcss.com"></script>',
    "<script>" + tailwind.replace("</script>", "<\\/script>") + "</script>",
)

# 2. Google Fonts — без сети, все woff2 как data URI.
def _font_url(match):
    url = match.group(0)
    name = url.rsplit("/", 1)[-1]
    cache = CACHE / name
    if not cache.is_file():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            cache.write_bytes(r.read())
    b64 = base64.b64encode(cache.read_bytes()).decode("ascii")
    return "data:font/woff2;base64," + b64

font_css = re.sub(r"https://fonts\.gstatic\.com/[^)\s]+", _font_url, font_css)
html = re.sub(r'\s*<link rel="preconnect"[^>]*>', "", html)
html = re.sub(r'\s*<link href="https://fonts\.googleapis\.com[^>]*>', "", html)
html = html.replace("</head>", "<style>\n" + font_css + "\n</style>\n</head>")

# 3. Убираем внешний desktop-фон и растягиваем окно на весь WebView2.
extra_css = """
<style>
  html, body {
    width: 833px !important;
    height: 541px !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: #070B16 !important;
  }
  body { display: block !important; }
  body > .absolute { display: none !important; }
  #rsp-window {
    width: 1040px !important;
    height: 675.5px !important;
    border: 0 !important;
    border-radius: 18px !important;
    overflow: hidden !important;
    box-shadow: none !important;
    transform: scale(0.801);
    transform-origin: top left;
  }
  #rsp-window main { padding: 18px 24px !important; }
  #rsp-main-content > div:first-child { margin-bottom: 12px !important; }
  #rsp-main-content > div:nth-child(2) { margin-bottom: 12px !important; }
  #rsp-card-install, #rsp-card-portable { padding: 16px !important; }
  #rsp-card-install > div.h-28, #rsp-card-portable > div.h-28 { height: 88px !important; }
  #rsp-bottom-panel { padding-top: 8px !important; }
  #rsp-bottom-panel > div:first-child { padding-top: 6px !important; padding-bottom: 6px !important; }
  #rsp-bottom-panel footer { padding-top: 4px !important; }
  @keyframes rspEqPulse {
    0%, 100% { transform: scaleY(0.55); opacity: .62; }
    50% { transform: scaleY(1.25); opacity: 1; }
  }
  #rsp-equalizer > div {
    transform-origin: center bottom;
    animation: rspEqPulse 1.25s ease-in-out infinite;
  }
  #rsp-equalizer > div:nth-child(2n) { animation-delay: .14s; }
  #rsp-equalizer > div:nth-child(3n) { animation-delay: .28s; }
  #rsp-equalizer > div:nth-child(4n) { animation-delay: .42s; }
  #rsp-card-install, #rsp-card-portable {
    cursor: pointer;
    -webkit-user-select: none;
    user-select: none;
  }
  #rsp-card-install.rsp-selected, #rsp-card-portable.rsp-selected {
    border-color: #22D3EE !important;
    box-shadow: 0 0 0 1px rgba(34,211,238,.55), 0 0 34px rgba(34,211,238,.20) !important;
  }
  #rsp-card-install:not(.rsp-selected), #rsp-card-portable:not(.rsp-selected) {
    opacity: .88;
  }
  #rsp-card-install:not(.rsp-selected) {
    border-color: #233154 !important;
    box-shadow: none !important;
  }
  .rsp-busy #rsp-next { pointer-events: none; opacity: .55; }
  #rsp-overlay button:hover { filter: brightness(1.12); }
</style>
"""
html = html.replace("</head>", extra_css + "</head>")

# 4. ID для интерактивных элементов.
repls = [
    ('<div class="relative w-[1040px] h-[740px]', '<div id="rsp-window" class="relative w-[1040px] h-[740px]'),
    ('<div class="group relative rounded-xl bg-[#111A35]/90 border border-aurora-cyan/70',
     '<div id="rsp-card-install" data-mode="install" class="group relative rounded-xl bg-[#111A35]/90 border border-aurora-cyan/70'),
    ('<div class="group relative rounded-xl bg-[#0E152B]/70 border border-[#233154]',
     '<div id="rsp-card-portable" data-mode="portable" class="group relative rounded-xl bg-[#0E152B]/70 border border-[#233154]'),
    ('<button class="px-5 py-2.5 rounded-lg border border-[#233153]',
     '<button id="rsp-back" class="px-5 py-2.5 rounded-lg border border-[#233153]'),
    ('<button class="px-4 py-2.5 rounded-lg text-xs font-medium text-txt-muted',
     '<button id="rsp-cancel" class="px-4 py-2.5 rounded-lg text-xs font-medium text-txt-muted'),
    ('<button class="relative px-8 py-2.5 rounded-lg bg-gradient-to-r',
     '<button id="rsp-next" class="relative px-8 py-2.5 rounded-lg bg-gradient-to-r'),
]
for old, new in repls:
    if old not in html:
        raise SystemExit("NOT_FOUND: " + old[:80])
    html = html.replace(old, new, 1)

html = html.replace('<span class="text-aurora-cyan/80">NTFS/ReFS</span>', '')

eq_old = '<div class="h-6 w-full flex items-center gap-[3px] px-1 py-1 rounded bg-space-950/60 border border-[#1C2744]">'
eq_new = '<div id="rsp-equalizer" class="h-6 w-full flex items-center justify-center gap-[3px] px-1 py-1 rounded bg-space-950/60 border border-[#1C2744]">'
if eq_old not in html:
    raise SystemExit("EQ_NOT_FOUND")
html = html.replace(eq_old, eq_new, 1)

script = r"""
<script>
(function () {
  const post = (obj) => {
    try { if (window.chrome && window.chrome.webview) window.chrome.webview.postMessage(obj); } catch (e) {}
  };
  const installCard = document.getElementById('rsp-card-install');
  const portableCard = document.getElementById('rsp-card-portable');
  const next = document.getElementById('rsp-next');
  const back = document.getElementById('rsp-back');
  const cancel = document.getElementById('rsp-cancel');
  const header = document.querySelector('header');
  let mode = 'install';

  function setMode(m) {
    mode = m;
    if (installCard) installCard.classList.toggle('rsp-selected', m === 'install');
    if (portableCard) portableCard.classList.toggle('rsp-selected', m === 'portable');
  }
  setMode('install');
  if (installCard) installCard.addEventListener('click', () => setMode('install'));
  if (portableCard) portableCard.addEventListener('click', () => setMode('portable'));

  if (next) next.addEventListener('click', () => {
    document.body.classList.add('rsp-busy');
    post({ action: 'next', mode: mode });
  });
  if (cancel) cancel.addEventListener('click', () => post({ action: 'close' }));
  if (back) back.addEventListener('click', () => post({ action: 'close' }));

  const caps = document.querySelectorAll('.caption-btn');
  if (caps.length >= 3) {
    caps[0].addEventListener('click', () => post({ action: 'minimize' }));
    caps[1].addEventListener('click', () => post({ action: 'maximize' }));
    caps[2].addEventListener('click', () => post({ action: 'close' }));
  }
  if (header) header.addEventListener('mousedown', (e) => {
    if (e.target.closest('button')) return;
    post({ action: 'drag' });
  });

  let overlay = null;
  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'rsp-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(4,7,16,.94);backdrop-filter:blur(18px);display:flex;align-items:center;justify-content:center;padding:28px;';
    overlay.innerHTML =
      '<div style="width:620px;max-width:88vw;border:1px solid rgba(34,211,238,.32);border-radius:20px;background:linear-gradient(145deg,#111A35 0%,#070B16 68%);box-shadow:0 0 90px rgba(34,211,238,.16),inset 0 1px 0 rgba(148,163,255,.16);padding:28px 30px;color:#E8ECFF;font-family:Inter,Segoe UI,sans-serif;">' +
        '<div style="display:flex;gap:16px;align-items:center;margin-bottom:20px;">' +
          '<div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22D3EE,#8B5CF6);display:flex;align-items:center;justify-content:center;box-shadow:0 0 24px rgba(34,211,238,.35);">' +
            '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#04101C" stroke-width="2"><path d="M4 7V4h3M20 7V4h-3M4 17v3h3M20 17v3h-3"/><circle cx="12" cy="12" r="3" fill="#04101C"/></svg>' +
          '</div>' +
          '<div><div id="rsp-ov-kicker" style="font-size:10px;letter-spacing:.18em;color:#67E8F9;font-family:monospace;text-transform:uppercase;">RASPOZNAVATEL SETUP</div>' +
          '<div id="rsp-ov-title" style="font-size:20px;font-weight:700;margin-top:3px;">Установка «Распознаватель»</div></div>' +
        '</div>' +
        '<div id="rsp-ov-sub" style="font-size:12px;color:#9AA5C9;line-height:1.5;margin-bottom:14px;">Подготавливаю файлы…</div>' +
        '<div style="height:8px;border-radius:99px;background:#0A1022;border:1px solid #1C2946;overflow:hidden;"><div id="rsp-ov-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#22D3EE,#34D399);transition:width .25s ease;"></div></div>' +
        '<div id="rsp-ov-text" style="font-size:11px;color:#64708F;margin-top:10px;min-height:16px;">Это может занять около минуты.</div>' +
        '<div id="rsp-ov-actions" style="display:flex;justify-content:flex-end;gap:10px;margin-top:22px;"></div>' +
      '</div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function actionButton(text, action, primary) {
    const b = document.createElement('button');
    b.textContent = text;
    b.style.cssText = primary
      ? 'border:0;border-radius:10px;padding:10px 18px;background:linear-gradient(90deg,#0E8A9E,#14B8A6,#06B6D4);color:#040C1A;font-weight:700;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;'
      : 'border:1px solid #233153;border-radius:10px;padding:10px 18px;background:#0A1022;color:#C7D2FE;font-weight:600;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;';
    b.addEventListener('click', () => post({ action: action }));
    return b;
  }

  window.rspProgress = function (pct, text) {
    const o = ensureOverlay();
    o.querySelector('#rsp-ov-title').textContent = 'Установка «Распознаватель»';
    o.querySelector('#rsp-ov-bar').style.width = Math.max(0, Math.min(100, Number(pct) || 0)) + '%';
    if (text) o.querySelector('#rsp-ov-sub').textContent = text;
    o.querySelector('#rsp-ov-text').textContent = 'Не закрывайте окно установщика.';
  };

  window.rspDone = function (mode, path, app) {
    const o = ensureOverlay();
    o.querySelector('#rsp-ov-kicker').textContent = 'RASPOZNAVATEL · 2.7.0';
    o.querySelector('#rsp-ov-title').textContent = 'Готово';
    o.querySelector('#rsp-ov-sub').textContent = mode === 'portable' ? 'Портативная версия распакована.' : 'Программа установлена.';
    o.querySelector('#rsp-ov-bar').style.width = '100%';
    o.querySelector('#rsp-ov-text').textContent = path || '';
    const actions = o.querySelector('#rsp-ov-actions');
    actions.innerHTML = '';
    actions.appendChild(actionButton('Закрыть', 'close', false));
    actions.appendChild(actionButton('Запустить', 'run', true));
  };

  window.rspError = function (text) {
    const o = ensureOverlay();
    o.querySelector('#rsp-ov-kicker').textContent = 'RASPOZNAVATEL · ОШИБКА';
    o.querySelector('#rsp-ov-title').textContent = 'Не удалось завершить';
    o.querySelector('#rsp-ov-sub').textContent = text || 'Неизвестная ошибка.';
    o.querySelector('#rsp-ov-bar').style.width = '0%';
    const actions = o.querySelector('#rsp-ov-actions');
    actions.innerHTML = '';
    actions.appendChild(actionButton('Закрыть', 'close', false));
  };
})();
</script>
"""
progress_script = r"""
<style>
  #rsp-progress-page { display: none; flex: 1; flex-direction: column; justify-content: center; position: relative; z-index: 10; }
  body.rsp-progress-mode #rsp-main-content,
  body.rsp-progress-mode #rsp-bottom-panel { display: none !important; }
  body.rsp-progress-mode #rsp-progress-page { display: flex !important; }
  body.rsp-progress-mode main { justify-content: center !important; }
  #rsp-progress-actions button:hover { filter: brightness(1.12); }
</style>
<script>
(function () {
  const main = document.querySelector('#rsp-window main');
  if (!main) return;
  const blocks = main.querySelectorAll(':scope > div.relative.z-10');
  blocks.forEach((el) => {
    if (el.classList.contains('pt-4')) el.id = 'rsp-bottom-panel';
    else if (!el.id) el.id = 'rsp-main-content';
  });

  const page = document.createElement('div');
  page.id = 'rsp-progress-page';
  page.innerHTML =
    '<div style="width:100%;max-width:540px;margin:0 auto;color:#E8ECFF;font-family:Inter,Segoe UI,sans-serif;">' +
      '<div style="font-family:monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#67E8F9;">RASPOZNAVATEL · INSTALL</div>' +
      '<h2 id="rsp-progress-title" style="margin:7px 0 0;font-size:26px;line-height:1.2;font-weight:700;color:#F1F5FF;">Установка «Распознаватель»</h2>' +
      '<p id="rsp-progress-text" style="margin:12px 0 0;font-size:13px;line-height:1.55;color:#9AA5C9;">Подготавливаю файлы…</p>' +
      '<div style="margin-top:32px;height:8px;border-radius:999px;background:#0A1022;border:1px solid #1C2946;overflow:hidden;">' +
        '<div id="rsp-progress-bar" style="height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,#22D3EE,#34D399);transition:width .3s ease;"></div>' +
      '</div>' +
      '<div style="margin-top:9px;display:flex;justify-content:space-between;gap:16px;font-family:monospace;font-size:11px;color:#64708F;">' +
        '<span id="rsp-progress-label">Подготовка</span><span id="rsp-progress-pct">0%</span>' +
      '</div>' +
      '<div id="rsp-progress-path" style="display:none;margin-top:12px;font-family:monospace;font-size:11px;line-height:1.5;color:#9AA5C9;word-break:break-all;"></div>' +
      '<div id="rsp-progress-actions" style="margin-top:30px;display:flex;justify-content:flex-end;align-items:center;gap:10px;"></div>' +
    '</div>';
  main.insertBefore(page, main.firstChild);

  const bar = page.querySelector('#rsp-progress-bar');
  const pctEl = page.querySelector('#rsp-progress-pct');
  const textEl = page.querySelector('#rsp-progress-text');
  const titleEl = page.querySelector('#rsp-progress-title');
  const labelEl = page.querySelector('#rsp-progress-label');
  const pathEl = page.querySelector('#rsp-progress-path');
  const actions = page.querySelector('#rsp-progress-actions');
  let currentMode = 'install';

  const post = (obj) => {
    try { if (window.chrome && window.chrome.webview) window.chrome.webview.postMessage(obj); } catch (e) {}
  };
  const show = () => document.body.classList.add('rsp-progress-mode');
  const setProgress = (pct, text, label) => {
    show();
    const n = Math.max(0, Math.min(100, Number(pct) || 0));
    bar.style.width = n + '%';
    pctEl.textContent = n + '%';
    if (text) textEl.textContent = text;
    if (label) labelEl.textContent = label;
  };
  const makeButton = (text, action, primary) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    b.style.cssText = primary
      ? 'border:0;border-radius:10px;padding:10px 18px;background:linear-gradient(90deg,#0E8A9E,#14B8A6,#06B6D4);color:#040C1A;font-weight:700;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;'
      : 'border:1px solid #233153;border-radius:10px;padding:10px 18px;background:#0A1022;color:#C7D2FE;font-weight:600;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;';
    b.addEventListener('click', () => post({ action }));
    return b;
  };

  const cancel = makeButton('Отмена', 'cancel', false);
  cancel.id = 'rsp-progress-cancel';
  cancel.addEventListener('click', () => {
    cancel.disabled = true;
    cancel.textContent = 'Отмена…';
  });
  actions.appendChild(cancel);

  const next = document.getElementById('rsp-next');
  if (next) next.addEventListener('click', () => {
    setProgress(4, 'Подготавливаю установку…', 'Подготовка');
  });

  window.rspPrepare = function (mode, path) {
    currentMode = mode === 'portable' ? 'portable' : 'install';
    show();
    titleEl.textContent = currentMode === 'portable' ? 'Распаковка «Распознаватель»' : 'Установка «Распознаватель»';
    textEl.textContent = currentMode === 'portable' ? 'Подготавливаю распаковку…' : 'Подготавливаю установку…';
    pathEl.textContent = path || '';
    pathEl.style.display = path ? 'block' : 'none';
    labelEl.textContent = 'Подготовка';
  };

  window.rspProgress = function (pct, text) {
    setProgress(pct, text, currentMode === 'portable' ? 'Распаковка' : 'Установка');
  };

  window.rspDone = function (mode, path, app) {
    show();
    currentMode = mode === 'portable' ? 'portable' : 'install';
    titleEl.textContent = 'Готово';
    textEl.textContent = mode === 'portable' ? 'Портативная версия распакована.' : 'Программа установлена.';
    bar.style.width = '100%';
    pctEl.textContent = '100%';
    labelEl.textContent = 'Готово';
    pathEl.textContent = path || '';
    pathEl.style.display = 'block';
    actions.innerHTML = '';
    actions.appendChild(makeButton('Закрыть', 'close', false));
    actions.appendChild(makeButton('Запустить', 'run', true));
  };

  window.rspError = function (text) {
    show();
    titleEl.textContent = 'Не удалось установить';
    textEl.textContent = text || 'Неизвестная ошибка.';
    bar.style.width = '0%';
    pctEl.textContent = '0%';
    labelEl.textContent = 'Ошибка';
    pathEl.style.display = 'none';
    actions.innerHTML = '';
    actions.appendChild(makeButton('Закрыть', 'close', false));
  };
})();
</script>
"""

folder_script = r"""
<style>
  #rsp-folder-page { display: none; flex: 1; flex-direction: column; justify-content: center; position: relative; z-index: 10; }
  body.rsp-folder-mode #rsp-main-content,
  body.rsp-folder-mode #rsp-bottom-panel { display: none !important; }
  body.rsp-folder-mode #rsp-folder-page { display: flex !important; }
  body.rsp-folder-mode #rsp-progress-page { display: none !important; }
  body.rsp-folder-mode main { justify-content: center !important; }
  body.rsp-progress-mode #rsp-folder-page { display: none !important; }
  #rsp-folder-page input::selection { background: rgba(34,211,238,.35); }
</style>
<script>
(function () {
  const main = document.querySelector('#rsp-window main');
  if (!main) return;
  let defaultInstall = 'C:\\Program Files\\Raspoznavatel';
  let defaultPortable = 'Raspoznavatel-Portable';
  let currentMode = 'install';
  const page = document.createElement('div');
  page.id = 'rsp-folder-page';
  page.innerHTML =
    '<div style="width:100%;max-width:540px;margin:0 auto;color:#E8ECFF;font-family:Inter,Segoe UI,sans-serif;">' +
      '<div style="font-family:monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#67E8F9;">RASPOZNAVATEL · INSTALL</div>' +
      '<h2 id="rsp-folder-title" style="margin:7px 0 0;font-size:26px;line-height:1.2;font-weight:700;color:#F1F5FF;">Куда установить?</h2>' +
      '<p id="rsp-folder-sub" style="margin:12px 0 0;font-size:13px;line-height:1.55;color:#9AA5C9;">Выберите папку. По умолчанию — <span style="color:#E8ECFF;">Program Files</span>; для записи туда Windows запросит подтверждение администратора.</p>' +
      '<div id="rsp-folder-label" style="margin-top:24px;font-family:monospace;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#64708F;">Папка установки</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
        '<input id="rsp-path" type="text" spellcheck="false" style="min-width:0;flex:1;height:40px;border:1px solid #233153;border-radius:9px;background:#0A1022;color:#E8ECFF;padding:0 12px;outline:none;font-family:monospace;font-size:11px;" />' +
        '<button id="rsp-browse" type="button" style="border:1px solid #233153;border-radius:9px;background:#0A1022;color:#C7D2FE;padding:0 14px;font-family:Inter,Segoe UI,sans-serif;font-size:12px;font-weight:600;cursor:pointer;">Обзор…</button>' +
      '</div>' +
      '<div id="rsp-folder-note" style="margin-top:9px;font-size:11px;color:#64708F;">Можно указать любую папку, доступную для записи.</div>' +
      '<div style="margin-top:28px;display:flex;justify-content:space-between;align-items:center;gap:10px;">' +
        '<button id="rsp-folder-back" type="button" style="border:1px solid #233153;border-radius:10px;padding:10px 18px;background:#0A1022;color:#C7D2FE;font-weight:600;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;">Назад</button>' +
        '<button id="rsp-folder-install" type="button" style="border:0;border-radius:10px;padding:10px 20px;background:linear-gradient(90deg,#0E8A9E,#14B8A6,#06B6D4);color:#040C1A;font-weight:700;font-size:12px;font-family:Inter,Segoe UI,sans-serif;cursor:pointer;">Установить</button>' +
      '</div>' +
    '</div>';
  main.insertBefore(page, main.firstChild);

  const input = page.querySelector('#rsp-path');
  const browse = page.querySelector('#rsp-browse');
  const back = page.querySelector('#rsp-folder-back');
  const start = page.querySelector('#rsp-folder-install');
  const next = document.getElementById('rsp-next');
  const portableCard = document.getElementById('rsp-card-portable');
  const installCard = document.getElementById('rsp-card-install');
  const folderTitle = page.querySelector('#rsp-folder-title');
  const folderSub = page.querySelector('#rsp-folder-sub');
  const folderLabel = page.querySelector('#rsp-folder-label');
  const folderNote = page.querySelector('#rsp-folder-note');
  input.value = defaultInstall;

  const intro = document.querySelector('#rsp-main-content p');
  if (intro) {
    intro.innerHTML = 'Выберите режим. Для установки в <span class="text-aurora-cyan font-medium">Program Files</span> Windows запросит подтверждение. Портативная версия работает без прав администратора.';
  }
  document.querySelectorAll('span').forEach((el) => {
    const text = el.textContent.trim();
    if (text === 'Путь: %LocalAppData%') el.textContent = 'Путь: Program Files';
    if (text === 'БЕЗ ПРАВ АДМИНА') el.textContent = 'ПО ЗАПРОСУ';
    if (text === 'USER LEVEL') el.textContent = 'UAC';
  });

  const checkIcon = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>';
  const radioInstall = document.querySelector('#rsp-card-install .rounded-full.bg-aurora-cyan');
  const radioPortable = document.querySelector('#rsp-card-portable .rounded-full.border-2');
  const syncRadios = (mode) => {
    const check = (color) => 'width:20px;height:20px;border-radius:999px;display:flex;align-items:center;justify-content:center;' + (color ? 'background:' + color + ';color:#04101C;' : 'border:2px solid #3D4F7C;');
    const empty = '<div style="width:8px;height:8px;border-radius:999px;background:transparent;"></div>';
    if (radioInstall) {
      radioInstall.className = 'w-5 h-5 rounded-full flex items-center justify-center';
      radioInstall.setAttribute('style', check(mode === 'install' ? '#22D3EE' : null));
      radioInstall.innerHTML = mode === 'install' ? checkIcon : empty;
    }
    if (radioPortable) {
      radioPortable.className = 'w-5 h-5 rounded-full flex items-center justify-center';
      radioPortable.setAttribute('style', check(mode === 'portable' ? '#22D3EE' : null));
      radioPortable.innerHTML = mode === 'portable' ? checkIcon : empty;
    }
  };
  syncRadios('install');
  if (installCard) installCard.addEventListener('click', () => syncRadios('install'));
  if (portableCard) portableCard.addEventListener('click', () => syncRadios('portable'));

  const post = (obj) => {
    try { if (window.chrome && window.chrome.webview) window.chrome.webview.postMessage(obj); } catch (e) {}
  };
  const showFolder = (mode) => {
    currentMode = mode === 'portable' ? 'portable' : 'install';
    document.body.classList.remove('rsp-progress-mode', 'rsp-busy');
    document.body.classList.add('rsp-folder-mode');
    if (currentMode === 'portable') {
      folderTitle.textContent = 'Куда распаковать?';
      folderSub.textContent = 'Портативная версия будет распакована в выбранную папку. По умолчанию — рядом с установщиком; путь можно изменить.';
      folderLabel.textContent = 'Папка распаковки';
      folderNote.textContent = 'Портативная версия не использует реестр Windows.';
      start.textContent = 'Распаковать';
      input.value = defaultPortable || 'Raspoznavatel-Portable';
    } else {
      folderTitle.textContent = 'Куда установить?';
      folderSub.textContent = 'Выберите папку. По умолчанию — Program Files; для записи туда Windows запросит подтверждение администратора.';
      folderLabel.textContent = 'Папка установки';
      folderNote.textContent = 'Можно указать любую папку, доступную для записи.';
      start.textContent = 'Установить';
      input.value = defaultInstall || 'C:\\Program Files\\Raspoznavatel';
    }
  };
  const hideFolder = () => document.body.classList.remove('rsp-folder-mode');

  if (next) next.addEventListener('click', (event) => {
    const selectedMode = portableCard && portableCard.classList.contains('rsp-selected') ? 'portable' : 'install';
    event.preventDefault();
    event.stopImmediatePropagation();
    showFolder(selectedMode);
  }, true);

  browse.addEventListener('click', () => post({ action: 'browse', path: input.value.trim() }));
  back.addEventListener('click', hideFolder);
  start.addEventListener('click', () => {
    const path = input.value.trim();
    if (!path) { input.focus(); return; }
    const activeMode = currentMode;
    hideFolder();
    document.body.classList.add('rsp-busy');
    if (window.rspPrepare) window.rspPrepare(activeMode, path);
    if (window.rspProgress) window.rspProgress(4, activeMode === 'portable' ? 'Подготавливаю распаковку…' : 'Подготавливаю установку…');
    post({ action: 'next', mode: activeMode, path: path });
  });

  try {
    if (window.chrome && window.chrome.webview) {
      window.chrome.webview.addEventListener('message', (event) => {
        const data = event.data || {};
        if (data.action === 'path' && data.path) input.value = data.path;
        if (data.action === 'defaults') {
          if (data.installPath) defaultInstall = data.installPath;
          if (data.portablePath) defaultPortable = data.portablePath;
          if (document.body.classList.contains('rsp-folder-mode'))
            input.value = currentMode === 'portable' ? defaultPortable : defaultInstall;
        }
      });
    }
  } catch (e) {}
})();
</script>
"""

if "</body>" not in html:
    raise SystemExit("NO_BODY")
html = html.replace("</body>", script + progress_script + folder_script + "</body>", 1)
OUT.write_text(html, encoding="utf-8")
print("WROTE", OUT, len(html))
print("HAS_CDN", "cdn.tailwindcss.com" in html)
print("HAS_GOOGLE", "fonts.googleapis.com" in html)
print("HAS_WHITE", "white" in html.lower())
