/* ==========================================================================
   «Распознаватель» — app.js
   Одностраничный интерфейс. Все вызовы Python-API проходят через обёртку
   callApi(), которая логирует ЛЮБУЮ ошибку (в тост и в журнал программы) —
   «немых» сбоев больше не бывает.
   ========================================================================== */
"use strict";

const $ = (s) => document.querySelector(s);
const pyapi = () => (window.pywebview && window.pywebview.api) || null;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const state = {
  imagePath: null,
  imageName: null,
  imageBase64: null,
  lastLines: [],
  mode: "text",
  resultText: "",
  typing: false,
  settings: {
    ocr_langs: "auto", auto_copy: true,
    hotkey_recognize: "ctrl+shift+s", hotkey_screenshot: "ctrl+shift+p",
    autostart: false, screenshots_dir: "",
    close_action: "exit",
    light_rays_enabled: true,
    light_rays_preset: "spotlight",
    ui_theme: "spotlight",
    auto_translate: false,
    yandex_folder_id: "",
  },
  info: null,        // get_info: data_dir, screenshots_dir (по умолчанию)
  shotCount: 0,
  recording: null,   // какое поле горячей клавиши сейчас записывается
  pairs: [],         // доступные направления перевода [{src,tgt,label}]
  trLangs: null,     // каталог языков + пакеты (get_translation_langs)
  trFrom: "auto",
  trTo: "ru",
};

/* ---------------------------------------------------------------------------
   ЗВУКИ (WebAudio-синтез, без файлов): «бульк» на готово, клик на скриншот,
   низкий сигнал на ошибку. Включаются/выключаются в настройках (sound).
--------------------------------------------------------------------------- */
let _actx = null;
function actx() {
  if (!_actx) { try { _actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  return _actx;
}
function playSound(kind) {
  /* Звуки уведомлений работают ВСЕГДА (переключатель убран по просьбе
     владельца): «бульк» на готово, сигнал на ошибку. */
  const ctx = actx();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  const t = ctx.currentTime;
  const tone = (freq, start, dur, type = "sine", vol = 0.15) => {
    try {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type; o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, t + start);
      g.gain.exponentialRampToValueAtTime(vol, t + start + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + start + dur);
      o.connect(g); g.connect(ctx.destination);
      o.start(t + start); o.stop(t + start + dur + 0.05);
    } catch (e) {}
  };
  if (kind === "ok")        { tone(660, 0, 0.09); tone(880, 0.09, 0.15); }                 // «бульк»
  else if (kind === "qr")   { tone(740, 0, 0.07); tone(988, 0.07, 0.09); tone(1175, 0.15, 0.12); }
  else if (kind === "shot") { tone(1500, 0, 0.03, "square", 0.10); tone(900, 0.035, 0.05, "square", 0.08); }
  else if (kind === "err")  { tone(220, 0, 0.16, "sawtooth", 0.09); tone(170, 0.13, 0.22, "sawtooth", 0.09); }
}

/* ---------------------------------------------------------------------------
   ЕДИНАЯ обёртка вызовов Python-API: ошибки -> тост + журнал Python
--------------------------------------------------------------------------- */
async function callApi(method, ...args) {
  const a = pyapi();
  if (!a) {
    const m = "Python-API недоступен (окно ещё инициализируется?)";
    toast(m, "error");
    throw new Error(m);
  }
  try {
    return await a[method](...args);
  } catch (e) {
    const m = `Сбой вызова ${method}: ${e && e.message ? e.message : e}`;
    toast(m, "error", 6000);
    try { await a.js_error(m); } catch (_) {}
    throw e;
  }
}

/* Неперехваченные ошибки/обещания — тоже в журнал */
window.addEventListener("error", (e) => {
  const a = pyapi();
  if (a) { try { a.js_error(`JS: ${e.message} @${e.filename}:${e.lineno}`); } catch (_) {} }
});
window.addEventListener("unhandledrejection", (e) => {
  const a = pyapi();
  if (a) { try { a.js_error(`JS promise: ${e.reason}`); } catch (_) {} }
});

/* ---------------------------------------------------------------------------
   Тосты / статус / лоадер
--------------------------------------------------------------------------- */
const TOAST_ICONS = {
  success: '<svg class="toast-icon" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1 15l-5-5 1.4-1.4L11 14.2l6.6-6.6L19 9l-8 8z"/></svg>',
  error: '<svg class="toast-icon" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm5 13.6L15.6 17 12 13.4 8.4 17 7 15.6 10.6 12 7 8.4 8.4 7 12 10.6 15.6 7 17 8.4 13.4 12 17 15.6z"/></svg>',
  info: '<svg class="toast-icon" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>',
};
function toast(message, type = "info", ms = 3400, action = null) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = TOAST_ICONS[type] || TOAST_ICONS.info;
  const text = document.createElement("span");
  text.className = "toast-text";
  text.textContent = message;
  el.appendChild(text);
  if (action && action.label) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast-action";
    btn.textContent = action.label;
    btn.addEventListener("click", () => {
      try { action.onClick(); } catch (e) { /* действие уже сообщило */ }
      el.classList.add("hide");
      setTimeout(() => el.remove(), 220);
    });
    el.appendChild(btn);
  }
  $("#toastStack").appendChild(el);
  setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 320); }, ms);
}

function setStatus(text, mode = "idle") {
  $("#statusText").textContent = text;
  $("#statusDot").className = "status-dot" + (mode === "busy" ? " busy" : mode === "error" ? " error" : "");
}
let loaderCount = 0;
function showLoader(text = "Обработка…") {
  loaderCount++;
  $("#loaderText").textContent = text;
  $("#loaderOverlay").classList.remove("hidden");
  setStatus(text, "busy");
}
function hideLoader() {
  loaderCount = Math.max(0, loaderCount - 1);
  if (loaderCount === 0) {
    $("#loaderOverlay").classList.add("hidden");
    updateProgress(-1);
  }
}
/* Шкала прогресса: pct 0..100, pct<0 — спрятать.
   Дублируется ВНИЗУ в статус-баре (как просил пользователь) и в карточке
   лоадера (которая теперь не блокирует клики). */
function updateProgress(pct, text) {
  const track = $("#progressTrack"), fill = $("#progressFill"), p = $("#progressPct");
  const sWrap = $("#statusProgress"), sFill = $("#statusProgressFill"), sPct = $("#statusProgressPct");
  if (pct == null || pct < 0) {
    if (track) track.classList.add("hidden");
    if (p) p.classList.add("hidden");
    if (sWrap) sWrap.classList.remove("active");
    return;
  }
  const v = Math.max(0, Math.min(100, pct));
  if (track) track.classList.remove("hidden");
  if (fill) fill.style.width = v + "%";
  if (p) { p.classList.remove("hidden"); p.textContent = Math.round(v) + "%" + (v >= 100 ? " · готово" : ""); }
  if (sWrap) sWrap.classList.add("active");
  if (sFill) sFill.style.width = v + "%";
  if (sPct) sPct.textContent = Math.round(v) + "%";
  if (text) {
    if ($("#loaderText")) $("#loaderText").textContent = text;
    setStatus(text, "busy");
  }
}
window.onProgress = (pct, text) => updateProgress(pct, text);

/* Колбэки из Python */
window.onStatus = (t) => setStatus(t);
window.onError = (t) => { toast(t, "error", 6000); setStatus("Ошибка: " + t, "error"); playSound("err"); };

/* --- цветной журнал: ERROR — красный, WARN — жёлтый, OK — зелёный --- */
function logLevelOf(line) {
  if (line.indexOf("[ERROR]") >= 0) return "err";
  if (line.indexOf("[WARN]") >= 0) return "warn";
  if (line.indexOf("[OK]") >= 0) return "ok";
  return "info";
}
function appendLogLines(lines) {
  const box = $("#logBox");
  const empty = $("#logEmpty");
  if (empty) empty.remove();
  const frag = document.createDocumentFragment();
  for (const ln of lines) {
    if (!ln) continue;
    const d = document.createElement("div");
    d.className = "log-line log-" + logLevelOf(ln);
    d.textContent = ln;
    frag.appendChild(d);
  }
  box.appendChild(frag);
  if ($("#settingsDrawer").classList.contains("open")) box.scrollTop = box.scrollHeight;
}
function logBoxText() {
  return Array.from(document.querySelectorAll("#logBox .log-line"))
    .map((d) => d.textContent).join("\n");
}
window.onLogEntry = (line) => appendLogLines([line]);
/* Пакетная доставка строк журнала, накопленных до загрузки страницы */
window.onLogBulk = (lines) => appendLogLines(Array.isArray(lines) ? lines : [lines]);

/* ---------------------------------------------------------------------------
   Typewriter (React Bits)
--------------------------------------------------------------------------- */
function typeWriter(el, text, speed = 12) {
  el.textContent = "";
  el.classList.add("typing-caret");
  let i = 0;
  const step = () => {
    i = Math.min(text.length, i + Math.max(1, Math.ceil(text.length / 240)));
    el.textContent = text.slice(0, i);
    el.scrollTop = el.scrollHeight;
    if (i < text.length) setTimeout(step, speed);
    else el.classList.remove("typing-caret");
  };
  step();
}
function typeIntoTextarea(ta, text, speed = 10, onDone) {
  const token = (ta._typingToken || 0) + 1;
  ta._typingToken = token;
  ta.value = "";
  let i = 0;
  const step = () => {
    if (ta._typingToken !== token) return;
    i = Math.min(text.length, i + Math.max(1, Math.ceil(text.length / 280)));
    ta.value = text.slice(0, i);
    ta.scrollTop = ta.scrollHeight;
    if (i < text.length) setTimeout(step, speed);
    else if (onDone) onDone();
  };
  step();
}
function finishTyping(ta, text) {
  ta._typingToken = (ta._typingToken || 0) + 1;
  if (typeof text === "string") ta.value = text;
}

/* ---------------------------------------------------------------------------
   Ripple
--------------------------------------------------------------------------- */
document.addEventListener("pointerdown", (e) => {
  const btn = e.target.closest(".ripple");
  if (!btn) return;
  const r = btn.getBoundingClientRect();
  const size = Math.max(r.width, r.height);
  const m = document.createElement("span");
  m.className = "ripple-mark";
  m.style.width = m.style.height = size + "px";
  m.style.left = e.clientX - r.left - size / 2 + "px";
  m.style.top = e.clientY - r.top - size / 2 + "px";
  btn.appendChild(m);
  setTimeout(() => m.remove(), 600);
});

/* ---------------------------------------------------------------------------
   ФОН: частицы
--------------------------------------------------------------------------- */
function initParticles() {
  const canvas = $("#particles");
  const ctx = canvas.getContext("2d");
  let w, h, pts = [];
  const N = 42, D = 115;
  const cssRgb = (name, fallback) => {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) { return fallback; }
  };
  let C1 = cssRgb("--accent-rgb", "34,211,238");
  let C2 = cssRgb("--accent2-rgb", "139,92,246");
  let C3 = cssRgb("--stroke-rgb", "125,160,255");
  function readColors() {
    C1 = cssRgb("--accent-rgb", C1);
    C2 = cssRgb("--accent2-rgb", C2);
    C3 = cssRgb("--stroke-rgb", C3);
  }
  window.__refreshParticles = readColors;
  function resize() { w = canvas.width = innerWidth; h = canvas.height = innerHeight; }
  function spawn() {
    pts = Array.from({ length: N }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - .5) * .22, vy: (Math.random() - .5) * .22,
      r: Math.random() * 1.5 + .5,
      c: Math.random() < .5 ? 0 : 1,
    }));
  }
  let last = 0;
  function frame(ts) {
    requestAnimationFrame(frame);
    if (ts - last < 33) return;
    last = ts;
    ctx.clearRect(0, 0, w, h);
    for (const p of pts) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > w) p.vx *= -1;
      if (p.y < 0 || p.y > h) p.vy *= -1;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283);
      ctx.fillStyle = `rgba(${p.c ? C2 : C1},.45)`; ctx.fill();
    }
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const a = pts[i], b = pts[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
      if (d2 < D * D) {
        ctx.strokeStyle = `rgba(${C3},${(1 - Math.sqrt(d2) / D) * .12})`;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
    }
  }
  readColors();
  resize(); spawn();
  addEventListener("resize", () => { resize(); spawn(); });
  requestAnimationFrame(frame);
}

/* ---------------------------------------------------------------------------
   Панель заголовка + ресайз
--------------------------------------------------------------------------- */
function initWindowControls() {
  $("#btnMin").addEventListener("click", async () => {
    try { await callApi("win_minimize"); } catch (e) {}
  });
  $("#btnClose").addEventListener("click", async () => {
    try { await callApi("win_close"); } catch (e) {}
  });
  $("#titlebar").addEventListener("dblclick", async (e) => {
    if (e.target.closest(".tb-btn")) return;
    try { await callApi("win_maximize_toggle"); } catch (err) {}
  });

  /* Перетаскивание окна за верхнюю панель — своя реализация через
     Win32 (надежнее pywebview-drag-region при DPI/frameless). */
  let dragState = null;
  function onDragMove(ev) {
    if (!dragState) return;
    const dpr = (window.devicePixelRatio || 1);
    const dx = (ev.screenX - dragState.lastX) * dpr;
    const dy = (ev.screenY - dragState.lastY) * dpr;
    dragState.lastX = ev.screenX;
    dragState.lastY = ev.screenY;
    dragState.acc = dragState.acc
      ? { dx: dragState.acc.dx + dx, dy: dragState.acc.dy + dy }
      : { dx, dy };
    if (dragState.raf) return;
    dragState.raf = true;
    requestAnimationFrame(() => {
      if (!dragState) return;
      dragState.raf = false;
      const acc = dragState.acc;
      dragState.acc = null;
      if (acc) callApi("win_move", Math.round(acc.dx), Math.round(acc.dy)).catch(() => {});
    });
  }
  function onDragUp() {
    removeEventListener("mousemove", onDragMove);
    removeEventListener("mouseup", onDragUp);
    dragState = null;
  }
  $("#titlebar").addEventListener("mousedown", (e) => {
    if (e.button !== 0 || e.target.closest(".tb-btn")) return;
    dragState = { lastX: e.screenX, lastY: e.screenY, acc: null, raf: false };
    addEventListener("mousemove", onDragMove);
    addEventListener("mouseup", onDragUp);
    e.preventDefault();
  });

  window.onMaximized = () => {};

  function bindResize(el, useX, useY) {
    let sx = 0, sy = 0, sw = 0, sh = 0, raf = null, cur = null;
    const down = (e) => {
      e.preventDefault();
      sx = e.screenX; sy = e.screenY;
      sw = document.documentElement.clientWidth;
      sh = document.documentElement.clientHeight;
      addEventListener("mousemove", move);
      addEventListener("mouseup", up);
    };
    const move = (e) => {
      cur = [useX ? Math.max(1024, sw + (e.screenX - sx)) : null,
             useY ? Math.max(640, sh + (e.screenY - sy)) : null];
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = null;
        if (cur) callApi("win_resize", cur[0] != null ? cur[0] : sw, cur[1] != null ? cur[1] : sh).catch(() => {});
      });
    };
    const up = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", up); };
    el.addEventListener("mousedown", down);
  }
  bindResize($("#rzR"), true, false);
  bindResize($("#rzB"), false, true);
  bindResize($("#rzBR"), true, true);
}

/* ---------------------------------------------------------------------------
   Изображения: кнопка + Drag&Drop
--------------------------------------------------------------------------- */
function setPreview(base64, name) {
  state.imageBase64 = base64;
  state.lastLines = [];
  viewer.overlaySrc = null;
  viewer.overlayKey = "";
  viewer.overlayPromise = null;
  $("#previewImg").src = base64;
  $("#previewName").textContent = name || "";
  $("#previewCard").classList.remove("hidden");
  if (!$("#imageViewer").classList.contains("hidden")) closeImageViewer();
}

async function pickImage() {
  showLoader("Открытие файла…");
  try {
    const r = await callApi("pick_image");
    if (r && r.path) {
      state.imagePath = r.path; state.imageName = r.name;
      setPreview(r.base64, r.name);
      setStatus("Файл загружен: " + r.name);
      toast("Изображение загружено — распознаю…", "success");
      await autoRecognize(r.path);
    } else if (r && r.error) {
      toast(r.error, "error", 6000);
      playSound("err");
    }
  } catch (e) { /* callApi уже сообщил */ }
  finally { hideLoader(); }
}

/* АВТОраспознавание добавленного изображения: QR → текст, без кнопок */
async function autoRecognize(path) {
  showLoader("Распознаю…");
  updateProgress(2, "Смотрю, что на изображении…");
  try {
    const r = await callApi("recognize_file", path);
    if (!r || !r.ok) {
      if (r && r.error) { toast(r.error, "error", 6000); playSound("err"); }
      return;
    }
    if (r.mode === "qr") {
      showQrResult(r.results || [], `Найдено кодов: ${r.count}`);
      toast(`QR/штрих-код распознан (${r.count} шт.)`, "success");
      playSound("qr");
      if (r.count) autoCopy(state.resultText);
    } else if (r.text && r.text.trim()) {
      state.lastLines = Array.isArray(r.lines) ? r.lines : [];
      const det = r.detected ? ` · языки: ${String(r.detected).split("+").join(" + ").toUpperCase()}` : "";
      showTextResult(r.text, "Распознанный текст" + det);
      toast(`Текст распознан${r.confidence != null ? ` (${r.confidence}%)` : ""}${det}`, "success");
      playSound("ok");
      autoCopy(r.text);
      setTimeout(() => { maybeAutoTranslate().catch(() => {}); }, 180);
    } else {
      toast("Ни кодов, ни текста на изображении не найдено", "info");
      playSound("err");
    }
  } catch (e) { playSound("err"); }
  finally { hideLoader(); }
}

/* Клик по превью — открыть картинку в отдельном окне-лупе НАД картинкой */
function openImageZoom(e) {
  if (!state.imagePath || !pyapi()) return;
  const x = Math.round((e && e.screenX) || 0), y = Math.round((e && e.screenY) || 0);
  callApi("open_image_zoom", state.imagePath, x, y).catch(() => {});
}

/* ---------------------------------------------------------------------------
   Просмотр изображения: всё окно, перетаскивание, зум, перевод поверх
--------------------------------------------------------------------------- */
const viewer = { scale: 1, x: 0, y: 0, dragging: false, sx: 0, sy: 0,
                 overlaySrc: null, overlayKey: "", overlayPromise: null };

function resetViewerTransform() {
  viewer.scale = 1; viewer.x = 0; viewer.y = 0;
  applyViewerTransform();
}
function applyViewerTransform() {
  const img = $("#imageViewerImg");
  if (img) img.style.transform =
    `translate(${viewer.x}px, ${viewer.y}px) scale(${viewer.scale})`;
}
function openImageViewer() {
  if (!state.imageBase64) { toast("Сначала загрузите изображение", "info"); return; }
  const box = $("#imageViewer");
  $("#imageViewerImg").src = state.imageBase64;
  $("#imageViewerName").textContent = state.imageName || "";
  $("#imageOriginalBtn").classList.add("hidden");
  const overlayBtn = $("#imageOverlayBtn");
  if (overlayBtn) {
    overlayBtn.disabled = false;
    overlayBtn.textContent = viewer.overlaySrc ? "Показать перевод"
                                               : "Перевести поверх текста";
  }
  resetViewerTransform();
  setViewerMaximized(false);
  box.classList.remove("hidden");
  box.setAttribute("aria-hidden", "false");
  document.body.classList.add("viewer-open");
}
function closeImageViewer() {
  const box = $("#imageViewer");
  if (!box) return;
  box.classList.add("hidden");
  box.setAttribute("aria-hidden", "true");
  setViewerMaximized(false);
  document.body.classList.remove("viewer-open");
}
function overlayCacheKey() {
  return [state.imagePath || "", state.trFrom, state.trTo,
          state.settings.translate_provider || "local"].join("|");
}
function showOverlayImage(src, translated) {
  $("#imageViewerImg").src = src;
  $("#imageOriginalBtn").classList.toggle("hidden", !translated);
  const btn = $("#imageOverlayBtn");
  if (btn) {
    btn.disabled = !!translated;
    btn.textContent = translated ? "Перевод показан"
                                 : "Перевести поверх текста";
  }
  resetViewerTransform();
}
async function prefetchOverlay() {
  if (!state.imagePath || !state.lastLines || !state.lastLines.length) return;
  const key = overlayCacheKey();
  if (viewer.overlaySrc && viewer.overlayKey === key) return;
  if (viewer.overlayPromise && viewer.overlayPromise.key === key) {
    return viewer.overlayPromise.promise;
  }
  const promise = (async () => {
    try {
      const r = await callApi("translate_image_overlay", state.imagePath,
                              state.trFrom, state.trTo, state.lastLines);
      if (r && r.ok && overlayCacheKey() === key) {
        viewer.overlaySrc = r.base64;
        viewer.overlayKey = key;
      }
    } catch (e) { /* тихо: по кнопке повторим */ }
    finally {
      if (viewer.overlayPromise && viewer.overlayPromise.key === key) {
        viewer.overlayPromise = null;
      }
    }
  })();
  viewer.overlayPromise = { key, promise };
  return promise;
}
async function translateImageOverlay() {
  if (!state.imagePath) { toast("Сначала загрузите изображение", "info"); return; }
  const key = overlayCacheKey();
  if (viewer.overlaySrc && viewer.overlayKey === key) {
    showOverlayImage(viewer.overlaySrc, true);
    toast("Показан готовый перевод", "info");
    return;
  }
  if (viewer.overlayPromise && viewer.overlayPromise.key === key) {
    showLoader("Готовлю перевод…");
    await viewer.overlayPromise.promise;
    hideLoader();
    if (viewer.overlaySrc && viewer.overlayKey === key) {
      showOverlayImage(viewer.overlaySrc, true);
      toast("Показан готовый перевод", "info");
      return;
    }
  }
  showLoader("Распознаю и перевожу текст на изображении…");
  try {
    const r = await callApi("translate_image_overlay", state.imagePath,
                            state.trFrom, state.trTo, state.lastLines || []);
    if (overlayCacheKey() !== key) return;
    if (!r || !r.ok) {
      toast((r && r.error) || "Не удалось перевести текст на изображении",
            "error", 7000);
      playSound("err");
      return;
    }
    viewer.overlaySrc = r.base64;
    viewer.overlayKey = key;
    showOverlayImage(r.base64, true);
    toast(`Перевод наложен: ${r.translated} из ${r.lines} строк`, "success");
    playSound("ok");
  } catch (e) { /* callApi уже сообщил */ }
  finally { hideLoader(); }
}
function setViewerMaximized(on) {
  const box = $("#imageViewer");
  const btn = $("#imageFullBtn");
  box.classList.toggle("maximized", !!on);
  if (btn) {
    btn.textContent = on ? "⤢" : "⛶";
    btn.dataset.tooltip = on ? "Вернуть панель"
                             : "Развернуть внутри программы";
  }
}
function toggleViewerMaximized() {
  setViewerMaximized(!$("#imageViewer").classList.contains("maximized"));
}
function initImageViewer() {
  const pv = $("#previewImg");
  if (pv) pv.addEventListener("click", openImageViewer);
  const expand = $("#previewExpandBtn");
  if (expand) expand.addEventListener("click", openImageViewer);
  const overlay = $("#previewOverlayBtn");
  if (overlay) overlay.addEventListener("click", async () => {
    openImageViewer();
    await translateImageOverlay();
  });
  const close = $("#imageViewerClose");
  if (close) close.addEventListener("click", closeImageViewer);
  const tr = $("#imageOverlayBtn");
  if (tr) tr.addEventListener("click", translateImageOverlay);
  const orig = $("#imageOriginalBtn");
  if (orig) orig.addEventListener("click", () => {
    $("#imageViewerImg").src = state.imageBase64 || "";
    orig.classList.add("hidden");
    const btn = $("#imageOverlayBtn");
    if (btn) {
      btn.disabled = false;
      btn.textContent = viewer.overlaySrc ? "Показать перевод"
                                          : "Перевести поверх текста";
    }
    resetViewerTransform();
  });
  const full = $("#imageFullBtn");
  if (full) full.addEventListener("click", toggleViewerMaximized);
  const box = $("#imageViewer");
  if (box) box.addEventListener("click", (e) => {
    if (e.target === box) closeImageViewer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#imageViewer").classList.contains("hidden")) {
      closeImageViewer();
    }
  });
  const stage = $("#imageViewerStage");
  if (!stage) return;
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    viewer.scale = Math.min(6, Math.max(0.3, viewer.scale * factor));
    applyViewerTransform();
  }, { passive: false });
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    viewer.dragging = true;
    viewer.sx = e.clientX - viewer.x;
    viewer.sy = e.clientY - viewer.y;
    stage.classList.add("dragging");
    try { stage.setPointerCapture(e.pointerId); } catch (err) {}
  });
  stage.addEventListener("pointermove", (e) => {
    if (!viewer.dragging) return;
    viewer.x = e.clientX - viewer.sx;
    viewer.y = e.clientY - viewer.sy;
    applyViewerTransform();
  });
  const stop = (e) => {
    viewer.dragging = false;
    stage.classList.remove("dragging");
    try { stage.releasePointerCapture(e.pointerId); } catch (err) {}
  };
  stage.addEventListener("pointerup", stop);
  stage.addEventListener("pointercancel", stop);
}

async function handleDrop(file) {
  if (!/\.(png|jpe?g|bmp|gif|tiff?|webp)$/i.test(file.name)) {
    toast("Поддерживаются изображения: PNG, JPG, BMP, GIF, TIFF, WEBP", "error");
    return;
  }
  showLoader("Чтение файла…");
  try {
    const buf = await file.arrayBuffer();
    let bin = "";
    const b = new Uint8Array(buf);
    for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    const r = await callApi("save_dropped_file", file.name, btoa(bin));
    if (r && r.ok) {
      state.imagePath = r.path; state.imageName = r.name;
      setPreview(r.base64, r.name);
      toast("Изображение загружено — распознаю…", "success");
      hideLoader();
      await autoRecognize(r.path);
      return;
    } else toast((r && r.error) || "Не удалось сохранить файл", "error");
  } catch (e) { /* уже сообщено */ }
  finally { hideLoader(); }
}

function initDropZone() {
  const z = $("#dropZone");
  z.addEventListener("click", pickImage);
  ["dragenter", "dragover"].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.remove("dragover"); }));
  z.addEventListener("drop", e => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) handleDrop(f);
  });
}

/* ---------------------------------------------------------------------------
   Результаты
--------------------------------------------------------------------------- */
function showTextResult(text, title) {
  state.mode = "text";
  state.resultText = text;
  state.typing = true;
  $("#qrResults").classList.add("hidden");
  const ta = $("#mainOutput");
  ta.classList.remove("hidden");
  typeIntoTextarea(ta, text, 10, () => {
    if (state.resultText === text) state.typing = false;
  });
  if (title) $("#resultTitle").textContent = title;
}

function showQrResult(results, title) {
  state.mode = "qr";
  state.resultText = (results || []).map(r => r.text).join("\n");
  $("#mainOutput").classList.add("hidden");
  const box = $("#qrResults");
  box.classList.remove("hidden");
  box.innerHTML = "";
  if (!results || !results.length) {
    box.innerHTML = '<p class="placeholder">Коды не найдены. Попробуйте выделить область ближе к коду.</p>';
    return;
  }
  results.forEach((r, i) => {
    const d = document.createElement("div");
    d.className = "qr-item";
    d.style.animationDelay = i * 80 + "ms";
    const isLink = /^https?:\/\//i.test(r.text.trim());
    d.innerHTML = `<div class="qr-type">${escapeHtml(r.type)}${r.engine ? " · " + escapeHtml(r.engine) : ""}</div>` +
      `<div class="qr-text${isLink ? " is-link" : ""}"></div>`;
    box.appendChild(d);
    typeWriter(d.querySelector(".qr-text"), r.text);
  });
  if (title) $("#resultTitle").textContent = title;
}

function currentResultText() {
  if (state.mode === "qr") return state.resultText;
  if (state.typing) return state.resultText;
  return $("#mainOutput").value;
}

async function copyText(t, what) {
  if (!t || !t.trim()) { toast("Нечего копировать", "info"); return; }
  let ok = false;
  try { const r = await callApi("copy_to_clipboard", t); ok = r && r.ok; } catch (e) {}
  if (!ok) { try { await navigator.clipboard.writeText(t); ok = true; } catch (e) {} }
  toast(ok ? `${what} скопирован в буфер обмена` : "Не удалось скопировать", ok ? "success" : "error");
}

function autoCopy(t) {
  if (state.settings.auto_copy && t && t.trim() && pyapi()) {
    pyapi().copy_to_clipboard(t).catch(() => {});
  }
}

/* ---------------------------------------------------------------------------
   Действия
--------------------------------------------------------------------------- */
async function runScreenCapture() {
  showLoader("Выделите область на экране…");
  try {
    const r = await callApi("capture_smart");   // всегда: сначала QR, затем текст
    hideLoader();
    if (!r || r.cancelled) return;
    if (!r.ok) { if (r.error) toast(r.error, "error", 6000); return; }
    applyCaptureResult(r);
  } catch (e) { hideLoader(); }
}

function applyCaptureResult(r) {
  if (r.mode === "qr") {
    showQrResult(r.results || [], r.count ? `QR с экрана: найдено ${r.count}` : "QR с экрана: коды не найдены");
    if (r.count) { toast(`QR распознан (${r.count} шт.)`, "success"); playSound("qr"); autoCopy(state.resultText); }
    else { toast("QR-код в области не найден", "info"); playSound("err"); }
  } else {
    if (r.text && r.text.trim()) {
      const det = r.detected ? ` · языки: ${String(r.detected).split("+").join(" + ").toUpperCase()}` : "";
      showTextResult(r.text, "Текст с экрана" + det);
      if (r.warning) toast(r.warning, "info", 7000);
      else toast("Текст с экрана распознан" + det, "success");
      playSound("ok");
      autoCopy(r.text);
      setTimeout(() => { maybeAutoTranslate().catch(() => {}); }, 140);
    } else { toast("Текст в выделенной области не найден", "info"); playSound("err"); }
  }
}

window.onFilePicked = (r) => {
  /* Файл выбран из меню трея или быстрой панели: показываем превью и
     запускаем то же автораспознавание, что и при перетаскивании файла. */
  if (!r || !r.path) return;
  state.imagePath = r.path; state.imageName = r.name;
  setPreview(r.base64, r.name);
  setStatus("Файл загружен: " + r.name);
  toast("Изображение загружено — распознаю…", "success");
  autoRecognize(r.path);
};

window.onHotkeyResult = (r) => {
  if (!r || r.cancelled) return;
  if (!r.ok) { if (r.error) { toast(r.error, "error", 6000); playSound("err"); } return; }
  applyCaptureResult(r);
};

async function openScreenshotDefault(path) {
  try {
    const r = await callApi("open_image_default", path);
    if (!r || !r.ok) {
      toast((r && r.error) || "Не удалось открыть изображение", "error", 6000);
    }
  } catch (e) {
    toast("Не удалось открыть изображение", "error", 6000);
  }
}
function showShotSaved(path) {
  state.shotCount++;
  setStatus("Скриншот сохранён: " + path);
  const name = String(path || "").split(/[\\/]/).pop() || "скриншот";
  toast(`Скриншот сохранён: ${name}`, "success", 8000, {
    label: "Просмотр",
    onClick: () => openScreenshotDefault(path),
  });
  playSound("shot");
}

async function takeScreenshot(mode) {
  const win = mode === "window";
  showLoader(win ? "Наведите на окно и кликните…" : "Выделите область для скриншота…");
  try {
    const r = await callApi("capture_screenshot", false, mode || "region");
    hideLoader();
    if (!r || r.cancelled) return;
    if (!r.ok) { if (r.error) { toast(r.error, "error", 6000); playSound("err"); } return; }
    showShotSaved(r.path);
  } catch (e) { hideLoader(); }
}

window.onScreenshotResult = (r) => {
  if (!r || r.cancelled) return;
  if (!r.ok) { if (r.error) { toast(r.error, "error", 6000); playSound("err"); } return; }
  showShotSaved(r.path);
};

/* ---------------------------------------------------------------------------
   Перевод: выбор направления «с какого на какой» (синхронно в обоих окнах)
--------------------------------------------------------------------------- */
const LANG_LABELS = {
  en: "Английский", ru: "Русский", uk: "Украинский", de: "Немецкий",
  fr: "Французский", es: "Испанский", it: "Итальянский", pt: "Португальский",
  pl: "Польский", tr: "Турецкий", nl: "Нидерландский", cs: "Чешский",
  be: "Белорусский", kk: "Казахский", zh: "Китайский", ja: "Японский",
  ko: "Корейский", ar: "Арабский", he: "Иврит", el: "Греческий",
  sv: "Шведский", fi: "Финский",
};
function langLabel(code) { return LANG_LABELS[code] || String(code).toUpperCase(); }

function fillDirSelects() {
  // исходный язык может быть «Авто» (автоопределение); список языков
  // строится по установленным пакетам + направлениям из индекса Argos.
  const codes = [];
  const push = (c) => { if (c && !codes.includes(c)) codes.push(c); };
  push("ru"); push("en");
  (state.trLangs && state.trLangs.installed || []).forEach(p => { push(p[0]); push(p[1]); });
  (state.trLangs && state.trLangs.remote || []).forEach(p => { push(p.src); push(p.tgt); });
  if (!state.trLangs) {
    state.pairs.forEach(p => { push(p.src); push(p.tgt); });
  }
  if (codes.length <= 2) { codes.push("ru", "en"); }
  [["#trFrom", state.trFrom], ["#trTo", state.trTo], ["#trFrom2", state.trFrom], ["#trTo2", state.trTo]]
    .forEach(([sel, val]) => {
      const el = $(sel); if (!el) return;
      el.innerHTML = "";
      if (sel.indexOf("From") >= 0) {
        const o = document.createElement("option");
        o.value = "auto"; o.textContent = "Авто (определять язык)";
        if (val === "auto") o.selected = true;
        el.appendChild(o);
      }
      codes.forEach(c => {
        const o = document.createElement("option");
        o.value = c; o.textContent = langLabel(c);
        if (c === val) o.selected = true;
        el.appendChild(o);
      });
      if (val === "auto" && sel.indexOf("From") >= 0) el.value = "auto";
    });
}

function setDirection(src, tgt, save = true) {
  state.trFrom = src || state.trFrom;
  state.trTo = tgt || state.trTo;
  fillDirSelects();
  if (save) { try { localStorage.setItem("tr_dir", JSON.stringify([state.trFrom, state.trTo])); } catch (e) {} }
}

function initTranslationDirs() {
  try {
    const saved = JSON.parse(localStorage.getItem("tr_dir") || "null");
    if (Array.isArray(saved) && saved.length === 2) { state.trFrom = saved[0]; state.trTo = saved[1]; }
  } catch (e) {}
  ["#trFrom", "#trFrom2"].forEach(s => { const el = $(s); if (el) el.addEventListener("change", () => setDirection(el.value, state.trTo)); });
  ["#trTo", "#trTo2"].forEach(s => { const el = $(s); if (el) el.addEventListener("change", () => setDirection(state.trFrom, el.value)); });
  const swap = $("#trSwap");
  if (swap) swap.addEventListener("click", () => setDirection(state.trTo, state.trFrom));
  fillDirSelects();
}

async function loadTranslationPairs() {
  try {
    const r = await callApi("get_translation_pairs");
    state.pairs = (r && r.pairs) || [];
  } catch (e) { state.pairs = []; }
  if (!state.pairs.length) state.pairs = [{ src: "en", tgt: "ru", label: "Английский → Русский" }];
  fillDirSelects();
}

/* каталог языков + установленные/скачиваемые пакеты (один запрос) */
async function loadTranslationLangs() {
  try {
    const r = await callApi("get_translation_langs");
    if (r && r.ok) {
      state.trLangs = r;
      if (r.catalog) Object.assign(LANG_LABELS, r.catalog);
    }
  } catch (e) { /* офлайн без индекса — останутся установленные пакеты */ }
  fillDirSelects();
  refreshPacks();
}

/* Какой пакет нужно скачать для пары (null — перевод уже возможен) */
function packNeeded(src, tgt) {
  if (!state.trLangs || src === "auto") return null;
  const inst = state.trLangs.installed || [];
  const has = (a, b) => inst.some(p => p[0] === a && p[1] === b);
  if (has(src, tgt)) return null;
  if (has(src, "en") && has("en", tgt)) return null;
  if (has(src, "en")) return ["en", tgt];
  if (has("en", tgt)) return [src, "en"];
  const remote = state.trLangs.remote || [];
  if (remote.some(p => p.src === src && p.tgt === tgt)) return [src, tgt];
  if (remote.some(p => p.src === src && p.tgt === "en")) return [src, "en"];
  if (remote.some(p => p.src === "en" && p.tgt === tgt)) return ["en", tgt];
  return [src, tgt];
}

function remoteSize(src, tgt) {
  const r = (state.trLangs && state.trLangs.remote || []).find(p => p.src === src && p.tgt === tgt);
  return r && r.size ? Math.max(1, Math.round(r.size / 1048576)) : null;
}

async function ensurePackOrCancel(src, tgt) {
  const need = packNeeded(src, tgt);
  if (!need) return true;
  const [a, b] = need;
  const mb = remoteSize(a, b);
  const note = src === "auto" ? "" : "";
  const msg = `Для перевода ${langLabel(src)} → ${langLabel(tgt)} нужен языковой пакет ` +
    `${langLabel(a)} → ${langLabel(b)}${mb ? ` (~${mb} МБ)` : ""}.\n` +
    `Скачать сейчас? Один раз нужен интернет, дальше пакет работает офлайн.${note}`;
  if (!confirm(msg)) return false;
  showLoader(`Скачиваю пакет ${langLabel(a)} → ${langLabel(b)}…`);
  updateProgress(2, "Скачиваю языковой пакет…");
  try {
    const r = await callApi("download_translation_pack", a, b);
    if (!r || !r.ok) { toast((r && r.error) || "Не удалось скачать пакет", "error", 7000); playSound("err"); return false; }
    toast(`Пакет ${langLabel(a)} → ${langLabel(b)} установлен`, "success");
    await loadTranslationLangs();
    return true;
  } catch (e) { return false; }
  finally { hideLoader(); }
}

async function translateCurrent() {
  // Если текст ещё «печатается», сразу показываем его полностью: иначе
  // автоперевод успевал захватить только первые слова.
  if (state.mode === "text" && state.typing) {
    finishTyping($("#mainOutput"), state.resultText);
    state.typing = false;
  }
  const t = currentResultText();
  if (!t || !t.trim()) { toast("Сначала распознайте или введите текст", "info"); return; }
  const src = state.trFrom, tgt = state.trTo;
  const prov = state.settings.translate_provider || "local";
  showLoader("Перевожу…");
  if (prov === "local" && !(await ensurePackOrCancel(src, tgt))) {
    hideLoader();
    return;
  }
  updateProgress(3, `Перевод ${src === "auto" ? "авто" : langLabel(src)} → ${langLabel(tgt)}…`);
  try {
    const r = await callApi("translate_text", t, src, tgt);
    if (!r || !r.ok) { if (r && r.error) { toast(r.error, "error", 7000); playSound("err"); } return; }
    typeIntoTextarea($("#trOutput"), r.translated);
    const det = r.detected ? ` (язык: ${langLabel(r.detected)})` : "";
    const via = r.via ? ` (через ${langLabel(r.via)})` : "";
    toast(`Перевод готов: ${langLabel(r.src || src)} → ${langLabel(r.tgt || tgt)}${via}${det}`, "success");
    playSound("ok");
    autoCopy(r.translated);
    // Заранее готовим наложение на изображение: тогда кнопка «Перевести
    // поверх текста» откроет готовый результат, а не запустит OCR заново.
    if (state.imagePath && state.lastLines && state.lastLines.length) {
      prefetchOverlay().catch(() => {});
    }
  } catch (e) {}
  finally { hideLoader(); }
}

/* Автоперевод: после распознавания сразу переводим на русский. */
function setTargetRu() {
  state.trTo = "ru";
  ["#trTo", "#trTo2"].forEach((sel) => {
    const el = $(sel);
    if (el && [...el.options].some((o) => o.value === "ru")) el.value = "ru";
  });
}

async function maybeAutoTranslate() {
  if (!state.settings.auto_translate) return;
  if (!currentResultText().trim()) return;
  setTargetRu();
  await translateCurrent();
}

/* ---------------------------------------------------------------------------
   ИСТОРИЯ распознаваний
--------------------------------------------------------------------------- */
function fmtHistTime(iso) {
  try {
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch (e) { return iso || ""; }
}

function histItemHtml(x) {
  const isQr = x.kind === "qr";
  const src = x.source === "screen" ? "с экрана" : x.source === "file" ? "из файла" : "";
  const meta = [
    src,
    x.langs ? String(x.langs).split("+").join("+").toUpperCase() : "",
    x.confidence != null ? `${x.confidence}%` : "",
    x.count ? `${x.count} код(а)` : "",
  ].filter(Boolean).join(" · ");
  const text = String(x.text || "");
  const shown = text.length > 12000 ? text.slice(0, 12000) + "…" : text;
  return `<div class="hist-item" data-id="${escapeHtml(x.id)}">
    <div class="hist-head">
      <span class="hist-badge ${isQr ? "qr" : "ocr"}">${isQr ? "QR / код" : "Текст"}</span>
      <span class="hist-src">${escapeHtml(meta)}</span>
      <span class="hist-time">${escapeHtml(fmtHistTime(x.ts))}</span>
    </div>
    <div class="hist-text" tabindex="0" aria-label="Текст записи, прокручивается">${escapeHtml(shown)}</div>
    <div class="hist-actions">
      <button class="mini-btn ripple hist-use" data-id="${escapeHtml(x.id)}">Вставить в результат</button>
      <button class="mini-btn ripple hist-copy" data-id="${escapeHtml(x.id)}">Копировать</button>
      <button class="mini-btn ripple danger hist-del" data-id="${escapeHtml(x.id)}">Удалить</button>
    </div>
  </div>`;
}

async function refreshHistory() {
  const box = $("#historyList");
  const q = ($("#historySearch").value || "").trim();
  box.innerHTML = '<p class="placeholder">Загружаю…</p>';
  try {
    const r = await callApi("get_history", 300, q);
    const items = (r && r.items) || [];
    if (!items.length) {
      box.innerHTML = q
        ? '<p class="placeholder">Ничего не найдено по запросу.</p>'
        : '<p class="placeholder">История пуста. Распознайте текст или QR-код — запись появится здесь.</p>';
      return;
    }
    box.innerHTML = items.map(histItemHtml).join("");
    box.querySelectorAll(".hist-use").forEach(b => b.addEventListener("click", () => {
      const it = items.find(i => String(i.id) === b.dataset.id);
      if (!it) return;
      if (it.kind === "qr") {
        showQrResult(String(it.text).split("\n").map(t => ({ type: "Из истории", text: t })), "Результат из истории");
      } else {
        showTextResult(it.text, "Результат из истории");
      }
      closeHistory();
      toast("Запись подставлена в результат", "success");
    }));
    box.querySelectorAll(".hist-copy").forEach(b => b.addEventListener("click", () => {
      const it = items.find(i => String(i.id) === b.dataset.id);
      if (it) copyText(it.text, "Текст из истории");
    }));
    box.querySelectorAll(".hist-del").forEach(b => b.addEventListener("click", async () => {
      await callApi("history_delete", b.dataset.id);
      refreshHistory();
    }));
  } catch (e) {
    box.innerHTML = `<p class="placeholder">Ошибка загрузки истории: ${escapeHtml(e)}</p>`;
  }
}

function openHistory() {
  $("#historyDrawer").classList.add("open");
  $("#historyDrawer").setAttribute("aria-hidden", "false");
  $("#historyBackdrop").classList.remove("hidden");
  refreshHistory();
}
function closeHistory() {
  $("#historyDrawer").classList.remove("open");
  $("#historyDrawer").setAttribute("aria-hidden", "true");
  $("#historyBackdrop").classList.add("hidden");
}

function initHistory() {
  $("#historyBtn").addEventListener("click", openHistory);
  $("#historyClose").addEventListener("click", closeHistory);
  $("#historyBackdrop").addEventListener("click", closeHistory);
  $("#historyRefresh").addEventListener("click", refreshHistory);
  let t = null;
  $("#historySearch").addEventListener("input", () => {
    clearTimeout(t); t = setTimeout(refreshHistory, 300);
  });
  $("#historyClear").addEventListener("click", async () => {
    await callApi("history_clear");
    refreshHistory();
    toast("История очищена", "success");
  });
  addEventListener("keydown", e => {
    if (e.key === "Escape" && $("#historyDrawer").classList.contains("open")) closeHistory();
  });
}

/* ---------------------------------------------------------------------------
   список установленных языковых пакетов (карточка в настройках)
--------------------------------------------------------------------------- */
function refreshPacks() {
  const box = $("#packsList");
  if (!box) return;
  const packs = (state.trLangs && state.trLangs.packs) || [];
  if (!packs.length) {
    box.innerHTML = '<p class="placeholder">Пакеты перевода не установлены.</p>';
    return;
  }
  box.innerHTML = packs.map(p => {
    const mb = Math.max(1, Math.round((p.size || 0) / 1048576));
    return `<div class="pack-row">
      <span class="pack-tag ${p.bundled ? "" : "user"}">${p.bundled ? "в комплекте" : "скачан"}</span>
      <span class="pack-name">${escapeHtml(langLabel(p.src))} → ${escapeHtml(langLabel(p.tgt))}</span>
      <span class="pack-meta">${mb} МБ</span>
      ${p.bundled ? "" : `<button class="mini-btn ripple danger pack-del" data-src="${escapeHtml(p.src)}" data-tgt="${escapeHtml(p.tgt)}">Удалить</button>`}
    </div>`;
  }).join("");
  box.querySelectorAll(".pack-del").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(`Удалить пакет ${langLabel(b.dataset.src)} → ${langLabel(b.dataset.tgt)}?`)) return;
    await callApi("remove_translation_pack", b.dataset.src, b.dataset.tgt);
    await loadTranslationLangs();
    toast("Пакет удалён", "success");
  }));
}

/* ---------------------------------------------------------------------------
   Настройки: drawer, переключатели, горячие клавиши, автозапуск, журнал
--------------------------------------------------------------------------- */
function initDrawer() {
  const d = $("#settingsDrawer"), b = $("#drawerBackdrop");
  const open = async () => {
    d.classList.add("open"); b.classList.remove("hidden"); d.setAttribute("aria-hidden", "false");
    await refreshLog();
    await syncAutostartUI();
    loadTranslationLangs().catch(() => {});   // карточка языковых пакетов
  };
  const close = () => { d.classList.remove("open"); b.classList.add("hidden"); d.setAttribute("aria-hidden", "true"); };
  $("#settingsBtn").addEventListener("click", open);
  $("#drawerClose").addEventListener("click", close);
  b.addEventListener("click", close);
  addEventListener("keydown", e => { if (e.key === "Escape" && d.classList.contains("open")) close(); });
}

async function refreshLog() {
  try {
    const text = await callApi("get_log");
    const box = $("#logBox");
    box.innerHTML = "";
    appendLogLines(String(text || "").split("\n"));
    box.scrollTop = 1e9;
  } catch (e) {}
}

async function pushSettings() {
  try {
    const r = await callApi("save_settings", state.settings);
    if (r && r.ok === false) {
      toast(r.error || "Не удалось сохранить настройки", "error", 6000);
      if (r.settings) state.settings = Object.assign({}, state.settings, r.settings);
      updateHotkeyChips();
      refreshHotkeyFields();
      return false;
    }
    if (r && typeof r === "object") {
      state.settings = Object.assign({}, state.settings, r);
      updateHotkeyChips();
      refreshHotkeyFields();
      updateHotkeysStatus();
      refreshShotsDir();
    }
    return true;
  } catch (e) { return false; }
}

/* --- папка скриншотов (настраиваемая) --- */
function refreshShotsDir() {
  const el = $("#shotsDirPath");
  if (!el) return;
  const custom = state.settings.screenshots_dir || "";
  const def = (state.info && state.info.screenshots_dir) || "";
  const text = custom || (def ? def + "  (по умолчанию)" : "по умолчанию — рядом с программой");
  el.textContent = text;
  el.title = text;
}

async function syncAutostartUI() {
  try {
    const r = await callApi("get_autostart");
    if (r && typeof r.enabled === "boolean") {
      $("#setAutostart").checked = r.enabled;
      state.settings.autostart = r.enabled;
    }
  } catch (e) {}
}

/* --- запись комбинаций горячих клавиш ---
   Используем e.code — ФИЗИЧЕСКУЮ позицию клавиши, поэтому запись не зависит
   от раскладки: Ctrl+Shift+S при русской раскладке запишется как ctrl+shift+s,
   а не «ctrl+shift+ы». Имена клавиш — как в Python-библиотеке `keyboard`.
   Минимум — 2 клавиши (модификатор + основная), например ctrl+f9 или alt+q. */
const CODEMAP = {
  Space: "space", Tab: "tab", Enter: "enter", Escape: "esc",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  Delete: "delete", Insert: "insert", Home: "home", End: "end",
  PageUp: "page up", PageDown: "page down",
  Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]",
  Backslash: "\\", Semicolon: ";", Quote: "'", Comma: ",", Period: ".",
  Slash: "/", Backquote: "`",
  Numpad0: "num 0", Numpad1: "num 1", Numpad2: "num 2", Numpad3: "num 3",
  Numpad4: "num 4", Numpad5: "num 5", Numpad6: "num 6", Numpad7: "num 7",
  Numpad8: "num 8", Numpad9: "num 9", NumpadAdd: "num +", NumpadSubtract: "num -",
  NumpadMultiply: "num *", NumpadDivide: "num /", NumpadDecimal: "num .",
  NumpadEnter: "num enter",
};
const MOD_CODES = { Control: 1, Alt: 1, AltGraph: 1, Shift: 1, OS: 1, Meta: 1 };

function comboFromEvent(e) {
  if (e.key === "Escape") return null;         // Esc — отмена записи
  const code = e.code || "";
  if (!code || MOD_CODES[code]) return null;   // нажат только модификатор — ждём основную клавишу
  const parts = [];
  if (e.ctrlKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  if (e.metaKey) parts.push("windows");
  let key = null, m;
  if ((m = /^Key([A-Z])$/.exec(code))) key = m[1].toLowerCase();
  else if ((m = /^Digit([0-9])$/.exec(code))) key = m[1];
  else if (/^F([1-9]|1\d|2[0-4])$/.test(code)) key = code.toLowerCase();
  else key = CODEMAP[code] || null;
  if (!key || parts.includes(key)) return null;
  parts.push(key);
  return parts.length >= 2 ? parts.join("+") : null;   // минимум 2 клавиши
}

/* Красивое отображение: "ctrl+shift+s" -> "Ctrl + Shift + S" */
function formatHotkey(combo) {
  return String(combo || "").split("+").map(p => p.trim()).filter(Boolean)
    .map(p => p.length === 1 ? p.toUpperCase() : p.charAt(0).toUpperCase() + p.slice(1))
    .join(" + ");
}
function updateHotkeysStatus() {
  const el = $("#statusHotkeys");
  if (!el) return;
  el.textContent = `${formatHotkey(state.settings.hotkey_recognize)} — распознать · `
                 + `${formatHotkey(state.settings.hotkey_screenshot)} — скриншот`;
}
function refreshHotkeyFields() {
  const a = $("#hkRecognize"), b = $("#hkScreenshot");
  if (a) a.value = formatHotkey(state.settings.hotkey_recognize);
  if (b) b.value = formatHotkey(state.settings.hotkey_screenshot);
}

function initHotkeyRecorder() {
  const fields = {
    hkRecognize: { key: "hotkey_recognize", btn: "hkRecBtn" },
    hkScreenshot: { key: "hotkey_screenshot", btn: "hkShotBtn" },
  };
  refreshHotkeyFields();
  for (const [inputId, cfg] of Object.entries(fields)) {
    const input = $("#" + inputId), btn = $("#" + cfg.btn);
    btn.addEventListener("click", () => {
      if (state.recording) return;
      state.recording = cfg.key;
      input.classList.add("recording");
      btn.classList.add("recording");
      btn.textContent = "Нажмите клавиши…";
      input.value = "";
      const onKey = async (e) => {
        e.preventDefault(); e.stopPropagation();
        const combo = comboFromEvent(e);
        if (!combo) return;   // ждём полноценную комбинацию (≥2 клавиш)
        cleanup();
        input.value = formatHotkey(combo);
        state.settings[cfg.key] = combo;
        btn.textContent = "Проверяю…";
        const ok = await pushSettings();   // Python проверит, сохранит и перерегистрирует
        btn.textContent = "Записать";
        if (ok) toast(`Комбинация назначена: ${formatHotkey(combo)}`, "success");
        // при ошибке pushSettings уже откатил значение и показал тост
      };
      const onEsc = (e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cleanup();
          input.value = formatHotkey(state.settings[cfg.key] || ""); btn.textContent = "Записать"; }
      };
      const cleanup = () => {
        state.recording = null;
        input.classList.remove("recording");
        btn.classList.remove("recording");
        window.removeEventListener("keydown", onKey, true);
        window.removeEventListener("keydown", onEsc, true);
      };
      window.addEventListener("keydown", onKey, true);
      window.addEventListener("keydown", onEsc, true);
    });
  }
  $("#hkResetBtn").addEventListener("click", async () => {
    state.settings.hotkey_recognize = "ctrl+shift+s";
    state.settings.hotkey_screenshot = "ctrl+shift+p";
    refreshHotkeyFields();
    if (await pushSettings()) toast("Комбинации сброшены по умолчанию", "success");
  });
}

function updateHotkeyChips() {
  const fmt = (v) => (v || "").split("+").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("+");
  const a = $("#hkScreenChip");
  if (a) a.textContent = fmt(state.settings.hotkey_recognize);
  const b = $("#hkShotChip");
  if (b) b.textContent = fmt(state.settings.hotkey_screenshot);
}

/* ---------------------------------------------------------------------------
   Переключатель сервиса перевода на главном экране:
   [Локально] [Google] — значки + подпись, синхронен с настройками.
--------------------------------------------------------------------------- */
function refreshEngineSwitch() {
  const cur = state.settings.translate_provider || "local";
  document.querySelectorAll("#trEngine .tr-engine-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.engine === cur);
  });
}

function initEngineSwitch() {
  const box = $("#trEngine");
  if (!box) return;
  box.querySelectorAll(".tr-engine-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      const eng = b.dataset.engine;
      if (eng === (state.settings.translate_provider || "local")) return;
      state.settings.translate_provider = eng;
      refreshEngineSwitch();
      const trp = $("#setTrProvider");
      if (trp) trp.value = eng;
      const ok = await pushSettings();
      if (ok === false) return;
      if (eng === "local") toast("Перевод: локально — без интернета и ключей", "success", 3000);
      else toast("Перевод: Google (онлайн, без ключа — как в браузере)", "success", 3000);
    });
  });
  refreshEngineSwitch();
}

/* ---------------------------------------------------------------------------
   Темы оформления: семь палитр, синхронных с пресетами лучей.
   Тема меняет весь интерфейс (CSS-переменные) и рисунок фона.
--------------------------------------------------------------------------- */
const UI_THEMES = [
  { id: "spotlight", name: "Синяя" },
  { id: "sunbeam", name: "Янтарная" },
  { id: "stage", name: "Сцена" },
  { id: "searchlight", name: "Прожектор" },
  { id: "cathedral", name: "Собор" },
  { id: "underwater", name: "Подводная" },
  { id: "horizon", name: "Горизонт" },
];

function themeName(id) {
  const t = UI_THEMES.find((x) => x.id === id);
  return t ? t.name : "Синяя";
}

function updateThemeDock(active) {
  document.querySelectorAll("#themeList .theme-row").forEach((row) => {
    const on = row.dataset.theme === active;
    row.classList.toggle("active", on);
    row.setAttribute("aria-pressed", on ? "true" : "false");
  });
  const btn = $("#themeBtn");
  if (btn) btn.setAttribute("aria-label", "Тема оформления: " + themeName(active));
}

function applyUiTheme(id) {
  const theme = UI_THEMES.some((t) => t.id === id) ? id : "spotlight";
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeDock(theme);
  if (window.__refreshParticles) {
    try { window.__refreshParticles(); } catch (e) {}
  }
  return theme;
}

function setUiTheme(id, save = true) {
  const theme = UI_THEMES.some((t) => t.id === id) ? id : "spotlight";
  state.settings.ui_theme = theme;
  state.settings.light_rays_preset = theme;
  applyLightRays();
  if (save) pushSettings();
}

function initThemeDock() {
  const pop = $("#themePop");
  const btn = $("#themeBtn");
  if (!pop || !btn) return;
  const setOpen = (open) => {
    pop.classList.toggle("hidden", !open);
    btn.classList.toggle("active", open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  };
  setOpen(false);
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(pop.classList.contains("hidden"));
  });
  document.addEventListener("click", (e) => {
    if (pop.classList.contains("hidden")) return;
    if (pop.contains(e.target) || btn.contains(e.target)) return;
    setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });
  document.querySelectorAll("#themeList .theme-row").forEach((row) => {
    row.addEventListener("click", () => {
      setUiTheme(row.dataset.theme);
      toast("Тема: " + themeName(row.dataset.theme), "success", 2200);
      setOpen(false);
    });
  });
  updateThemeDock(state.settings.ui_theme || "spotlight");
}

function applyLightRays() {
  const enabled = state.settings.light_rays_enabled !== false;
  const theme = state.settings.ui_theme || state.settings.light_rays_preset || "spotlight";
  const preset = state.settings.light_rays_preset || theme;
  applyUiTheme(theme);
  if (window.LightRays) {
    window.LightRays.setPreset(preset);
    window.LightRays.setEnabled(enabled);
  }
  const sw = $("#setLightRays");
  if (sw) sw.checked = enabled;
  const sel = $("#setLightRaysPreset");
  if (sel) { sel.value = theme; sel.disabled = !enabled; }
}

function initSettings() {
  const map = { setAutoCopy: "auto_copy", setQuickPanel: "quick_panel" };
  for (const [id, key] of Object.entries(map)) {
    const el = $("#" + id);
    if (!el) continue;
    el.checked = state.settings[key] !== false;
    el.addEventListener("change", () => {
      state.settings[key] = el.checked;
      if (key === "quick_panel") {
        toast(el.checked ? "Быстрая панель включена" : "Быстрая панель выключена", "success", 2600);
      }
      pushSettings();
    });
  }

  const autoTr = $("#autoTranslate");
  if (autoTr) {
    autoTr.checked = !!state.settings.auto_translate;
    autoTr.addEventListener("change", () => {
      state.settings.auto_translate = autoTr.checked;
      if (autoTr.checked) setTargetRu();
      pushSettings();
      toast(autoTr.checked ? "Автоперевод на русский включён" : "Автоперевод выключен", "success", 2600);
    });
  }

  /* кнопка «Проверить звук» убрана по просьбе владельца —
     звуки уведомлений работают и так, при каждом готовом распознавании. */

  /* фон «Световые лучи»: тумблер + семь пресетов */
  const lrSwitch = $("#setLightRays");
  if (lrSwitch) {
    lrSwitch.checked = state.settings.light_rays_enabled !== false;
    lrSwitch.addEventListener("change", () => {
      state.settings.light_rays_enabled = lrSwitch.checked;
      applyLightRays();
      pushSettings();
      toast(lrSwitch.checked ? "Анимированный фон включён" : "Анимированный фон выключен", "success", 2400);
    });
  }
  const lrPreset = $("#setLightRaysPreset");
  if (lrPreset) {
    lrPreset.value = state.settings.ui_theme || state.settings.light_rays_preset || "spotlight";
    lrPreset.disabled = state.settings.light_rays_enabled === false;
    lrPreset.addEventListener("change", () => {
      setUiTheme(lrPreset.value);
      const label = lrPreset.options[lrPreset.selectedIndex].text;
      toast("Тема: " + label, "success", 2400);
    });
  }
  applyLightRays();

  /* источник перевода / распознавания + ключи + прозрачность панели */
  const trp = $("#setTrProvider");
  if (trp) {
    trp.value = state.settings.translate_provider || "local";
    trp.addEventListener("change", () => {
      state.settings.translate_provider = trp.value;
      refreshEngineSwitch();
      pushSettings();
      toast(trp.value === "local" ? "Перевод: локально (без интернета)" : "Перевод: Google (онлайн)",
            "success", 2600);
    });
  }
  initEngineSwitch();
  const op = $("#setPanelOpacity");
  if (op) {
    op.value = state.settings.quick_panel_opacity == null ? 100 : state.settings.quick_panel_opacity;
    const lab = $("#panelOpacityVal");
    if (lab) lab.textContent = op.value + "%";
    op.addEventListener("input", () => { if (lab) lab.textContent = op.value + "%"; });
    op.addEventListener("change", () => {
      state.settings.quick_panel_opacity = parseInt(op.value, 10);
      pushSettings();
    });
  }
  updateHotkeyChips();

  /* действие кнопки ✕: закрыть программу или свернуть в трей */
  const ca = $("#setCloseAction");
  if (ca) {
    ca.value = state.settings.close_action || "exit";
    ca.addEventListener("change", async () => {
      state.settings.close_action = ca.value;
      if (await pushSettings()) {
        toast(ca.value === "tray"
          ? "✕ теперь сворачивает программу в трей (иконка справа внизу)"
          : "✕ снова закрывает программу", "success", 4200);
      } else ca.value = state.settings.close_action || "exit";
    });
  }

  const ch = $("#chooseShotsDirBtn");
  if (ch) ch.addEventListener("click", async () => {
    try {
      const r = await callApi("choose_screenshots_dir");
      if (r && r.ok) {
        state.settings.screenshots_dir = r.path;
        refreshShotsDir();
        toast("Папка скриншотов: " + r.path, "success", 5000);
      }
    } catch (e) {}
  });
  const rs = $("#resetShotsDirBtn");
  if (rs) rs.addEventListener("click", async () => {
    try {
      const r = await callApi("reset_screenshots_dir");
      if (r && r.ok) {
        state.settings.screenshots_dir = "";
        refreshShotsDir();
        toast("Папка скриншотов по умолчанию: " + r.path, "success", 5000);
      }
    } catch (e) {}
  });
  refreshShotsDir();
  $("#setAutostart").addEventListener("change", async () => {
    state.settings.autostart = $("#setAutostart").checked;
    await pushSettings();   // Python создаст/удалит ярлык в папке «Автозагрузка»
  });

  $("#copyLogBtn").addEventListener("click", () => copyText(logBoxText(), "Журнал"));
  $("#clearLogBtn").addEventListener("click", async () => {
    try { await callApi("clear_log"); $("#logBox").innerHTML = ""; toast("Журнал очищен", "success"); } catch (e) {}
  });
  $("#openShotsBtn").addEventListener("click", () => callApi("open_screenshots_dir").catch(() => {}));
  $("#openDataBtn").addEventListener("click", () => callApi("open_data_dir").catch(() => {}));
  initHotkeyRecorder();
}

/* ---------------------------------------------------------------------------
   Кнопки + старт
--------------------------------------------------------------------------- */
function bindButtons() {
  $("#pickBtn").addEventListener("click", pickImage);
  $("#screenBtn").addEventListener("click", runScreenCapture);
  $("#shotBtn").addEventListener("click", () => takeScreenshot("region"));
  const swb = $("#shotWinBtn");
  if (swb) swb.addEventListener("click", () => takeScreenshot("window"));
  initImageViewer();
  const fb = $("#statusFolderBtn");
  if (fb) fb.addEventListener("click", () => callApi("open_screenshots_dir").catch(() => {}));
  $("#copyBtn").addEventListener("click", () => copyText(currentResultText(), "Результат"));
  $("#translateBtn").addEventListener("click", translateCurrent);
  $("#clearBtn").addEventListener("click", () => {
    finishTyping($("#mainOutput"), ""); $("#qrResults").innerHTML = "";
    state.resultText = ""; state.mode = "text"; state.typing = false;
    $("#mainOutput").classList.remove("hidden"); $("#qrResults").classList.add("hidden");
    $("#resultTitle").textContent = "Результат распознавания";
    setStatus("Результат очищен");
  });
  $("#copyTrBtn").addEventListener("click", () => copyText($("#trOutput").value, "Перевод"));
  $("#clearTrBtn").addEventListener("click", () => { $("#trOutput").value = ""; });
  $("#mainOutput").addEventListener("input", () => {
    if (state.mode === "text") {
      state.resultText = $("#mainOutput").value;
      state.typing = false;
      finishTyping($("#mainOutput"));
    }
  });
}

async function onReady() {
  // Защита от двойного pywebviewready/таймаута: реальная инициализация
  // должна выполниться только один раз.
  if (window.__appReady) return;
  if (pyapi()) window.__appReady = true;
  initParticles();
  initWindowControls();
  initDropZone();
  initDrawer();
  initHistory();
  bindButtons();
  initThemeDock();

  if (!pyapi()) {
    setStatus("Python-API не подключён — демонстрационный режим", "error");
    toast("Запустите программу через Raspoznavatel.exe", "error", 6000);
    initSettings();
    initTranslationDirs();
    return;
  }
  try {
    state.settings = Object.assign({}, state.settings, await callApi("get_settings"));
    updateHotkeyChips();
    state.settings.ocr_langs = "auto";
    initSettings();
    updateHotkeysStatus();
    initTranslationDirs();
    await loadTranslationPairs();
    // Не блокируем старт сетевым индексом Argos: локальные пакеты уже
    // доступны, удалённый список догружается в фоне.
    loadTranslationLangs().catch(() => {});
    const info = await callApi("get_info");
    state.info = info;
    $("#versionLabel").textContent = info.version;
    refreshShotsDir();
    setStatus(`Готов к работе · ${formatHotkey(state.settings.hotkey_recognize)} — распознать · ${formatHotkey(state.settings.hotkey_screenshot)} — скриншот`);
    pyapi().js_log("Интерфейс загружен").catch(() => {});
  } catch (e) {
    setStatus("Ошибка инициализации: " + e, "error");
  }
}

if (window.pywebview) onReady();
else {
  addEventListener("pywebviewready", onReady, { once: true });
  setTimeout(() => { if (!window.pywebview) onReady(); }, 1500);
}

/* ==========================================================================
   ТУЛТИПЫ — один общий слой поверх всего интерфейса.
   Подсказка живёт в <body> и позиционируется по координатам экрана, поэтому
   не обрезается краями окон, карточек и панелей.
   ========================================================================== */
(function initUiTooltips() {
  if (!document.body) return;
  const tip = document.createElement("div");
  tip.className = "ui-tooltip";
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);

  let current = null;
  let showTimer = 0;

  function hide() {
    clearTimeout(showTimer);
    showTimer = 0;
    current = null;
    tip.classList.remove("show");
  }

  function place(target) {
    const text = (target.getAttribute("data-tooltip") || "").trim();
    if (!text) return;
    tip.textContent = text;
    tip.style.left = "0px";
    tip.style.top = "0px";
    tip.classList.add("show");

    const r = target.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const margin = 8;
    const gap = 8;

    let left = r.left + r.width / 2 - t.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - t.width - margin));

    let top;
    if (r.top >= t.height + gap + margin) {
      top = r.top - t.height - gap;
    } else {
      top = r.bottom + gap;
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - t.height - margin));

    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }

  function schedule(target) {
    clearTimeout(showTimer);
    current = target;
    showTimer = setTimeout(function () {
      if (current === target && target.isConnected) place(target);
    }, 260);
  }

  document.addEventListener("pointerover", function (e) {
    const target = e.target.closest ? e.target.closest("[data-tooltip]") : null;
    if (!target) { hide(); return; }
    if (target === current) return;
    schedule(target);
  }, true);

  document.addEventListener("pointerout", function (e) {
    const target = e.target.closest ? e.target.closest("[data-tooltip]") : null;
    if (!target) return;
    if (e.relatedTarget && target.contains(e.relatedTarget)) return;
    hide();
  }, true);

  document.addEventListener("focusin", function (e) {
    const target = e.target.closest ? e.target.closest("[data-tooltip]") : null;
    if (target) schedule(target);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("pointerdown", hide, true);
  window.addEventListener("blur", hide);
  window.addEventListener("resize", hide);
  window.addEventListener("scroll", hide, true);
})();
