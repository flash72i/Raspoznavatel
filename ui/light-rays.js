/* ==========================================================================
   light-rays.js — анимированный фон «Световые лучи» (WebGL2).

   Порт компонента LightRays с reactbits.dev (React Bits, MIT) на чистый JS:
   тот же вершинный/фрагментный шейдер, те же параметры и семь пресетов
   (spotlight, sunbeam, stage, searchlight, cathedral, underwater, horizon).

   Публичный API (window.LightRays):
     PRESETS          — список пресетов [{value,label}, ...]
     init(box, canvas, preset) — создать фон (повторный вызов вернёт существу-
                        ющий экземпляр)
     setPreset(name)  — переключить пресет
     setEnabled(bool) — включить/выключить фон
     getPreset()      — текущий пресет

   Фон рисуется на canvas за интерфейсом (z-index в styles.css), не ловит
   мышь, останавливает анимацию, когда окно скрыто, и уважает
   prefers-reduced-motion. Разрешение ограничено PIXEL_BUDGET — на слабых
   машинах шейдер не «съедает» GPU.
   ========================================================================== */
(function () {
  "use strict";

  var PIXEL_BUDGET = 2.4e6;
  var MAX_PULSES = 4;

  var ORIGINS = {
    "top-left": { anchor: [0, -0.2], dir: [0, 1] },
    "top-center": { anchor: [0.5, -0.2], dir: [0, 1] },
    "top-right": { anchor: [1, -0.2], dir: [0, 1] },
    left: { anchor: [-0.2, 0.5], dir: [1, 0] },
    right: { anchor: [1.2, 0.5], dir: [-1, 0] },
    "bottom-left": { anchor: [0, 1.2], dir: [0, -1] },
    "bottom-center": { anchor: [0.5, 1.2], dir: [0, -1] },
    "bottom-right": { anchor: [1, 1.2], dir: [0, -1] }
  };

  /* Значения по умолчанию — ровно как LOOK в исходном компоненте. */
  var LOOK = {
    raysOrigin: "top-center",
    raysColor: "#ffffff",
    raysSpeed: 1,
    lightSpread: 0.5,
    rayLength: 3,
    rayDensity: 1,
    tilt: 0,
    raySharpness: 0.35,
    glow: 0.6,
    haze: 0.25,
    atmosphere: 1,
    intensity: 1,
    fadeDistance: 1,
    saturation: 1,
    mouseInfluence: 0.1,
    noiseAmount: 0,
    distortion: 0,
    pulsating: false,
    followMouse: true,
    cursorShadow: true,
    clickPulse: true,
    intro: true,
    lightMode: false,
    opacity: 1,
    maxDevicePixelRatio: 2
  };

  /* Семь пресетов со страницы reactbits.dev/backgrounds/light-rays. */
  var PRESETS = {
    spotlight: {},
    sunbeam: {
      raysOrigin: "top-left", tilt: -32, raysColor: "#FFD39A",
      lightSpread: 1, rayDensity: 1.3, glow: 0.9, haze: 0.45,
      atmosphere: 0, intensity: 1.3
    },
    stage: {
      lightSpread: 0.22, rayLength: 2.2, raySharpness: 0.15,
      glow: 1.1, haze: 0.6
    },
    searchlight: {
      lightSpread: 0.16, raySharpness: 0.2, glow: 0.5,
      haze: 0.5, intensity: 1.2, mouseInfluence: 0.6
    },
    cathedral: {
      raysOrigin: "top-right", tilt: 25, lightSpread: 0.7, rayDensity: 1.8,
      raySharpness: 0.75, glow: 0.4, haze: 0.5, intensity: 1.2
    },
    underwater: {
      raysColor: "#7FE3FF", raysSpeed: 0.5, lightSpread: 1, rayDensity: 1.6,
      raySharpness: 0.5, haze: 0.5, atmosphere: 0.7, distortion: 0.12
    },
    horizon: {
      raysOrigin: "bottom-center", raysColor: "#FFB070", lightSpread: 1.4,
      rayLength: 2, glow: 1, haze: 0.2, atmosphere: 0
    }
  };

  var PRESET_OPTIONS = [
    { value: "spotlight", label: "Spotlight" },
    { value: "sunbeam", label: "Sunbeam" },
    { value: "stage", label: "Stage" },
    { value: "searchlight", label: "Searchlight" },
    { value: "cathedral", label: "Cathedral" },
    { value: "underwater", label: "Underwater" },
    { value: "horizon", label: "Horizon" }
  ];

  var VERTEX = [
    "#version 300 es",
    "const vec2 corners[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));",
    "void main() {",
    "  gl_Position = vec4(corners[gl_VertexID], 0.0, 1.0);",
    "}"
  ].join("\n");

  var FRAGMENT = [
    "#version 300 es",
    "precision highp float;",
    "uniform vec2 uResolution;",
    "uniform float uScale;",
    "uniform float uTime;",
    "uniform vec2 uSource;",
    "uniform vec2 uAim;",
    "uniform float uReach;",
    "uniform vec3 uColor;",
    "uniform float uSpread;",
    "uniform float uLength;",
    "uniform float uFade;",
    "uniform float uSaturation;",
    "uniform float uPulsating;",
    "uniform float uNoise;",
    "uniform float uDistortion;",
    "uniform float uDensity;",
    "uniform float uSharpness;",
    "uniform float uGlow;",
    "uniform float uHaze;",
    "uniform float uAtmosphere;",
    "uniform float uIntensity;",
    "uniform vec4 uShadow;",
    "uniform vec4 uPulses[" + MAX_PULSES + "];",
    "uniform vec2 uIntro;",
    "uniform float uLight;",
    "uniform float uOpacity;",
    "out vec4 fragColor;",
    "",
    "float hash(vec2 p) {",
    "  p = fract(p * vec2(123.34, 456.21));",
    "  p += dot(p, p + 45.32);",
    "  return fract(p.x * p.y);",
    "}",
    "",
    "float valueNoise(vec2 p) {",
    "  vec2 i = floor(p);",
    "  vec2 f = p - i;",
    "  vec2 w = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);",
    "  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), w.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), w.x), w.y);",
    "}",
    "",
    "float shape(float strength, float width) {",
    "  float edge = max(mix(0.5, 0.08, uSharpness), width);",
    "  return mix(strength, smoothstep(0.62 - edge, 0.62 + edge, strength), uSharpness);",
    "}",
    "",
    "void main() {",
    "  vec2 coord = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y) / uScale;",
    "  vec2 delta = coord - uSource;",
    "  float distance = length(delta);",
    "  vec2 dir = delta / max(distance, 1e-4);",
    "  float cosAngle = dot(dir, uAim);",
    "  float angle = cosAngle + uDistortion * sin(uTime * 2.0 + distance * 0.02) * 0.2;",
    "  float slope = fwidth(angle);",
    "  float depth = distance / uReach;",
    "",
    "  float source = exp(-depth * depth * 9.0) * 0.9 + exp(-depth * 3.2) * 0.25;",
    "  float glowLight = uGlow * source * smoothstep(-0.2, 0.6, cosAngle);",
    "  float spread = pow(max(angle, 0.0), 1.0 / uSpread);",
    "  float lengthFalloff = clamp(1.0 - distance / (uReach * uLength), 0.0, 1.0);",
    "  float fadeFalloff = clamp(1.0 - distance / (uReach * uFade), 0.5, 1.0);",
    "  float envelope = spread * lengthFalloff * fadeFalloff;",
    "  float reveal = uIntensity * uIntro.y * (1.0 - smoothstep(uIntro.x - 0.35, uIntro.x, depth));",
    "  if ((envelope * 1.6 + glowLight) * reveal < 0.0015) {",
    "    fragColor = vec4(0.0);",
    "    return;",
    "  }",
    "",
    "  float phaseA = angle * 36.2214 * uDensity + uTime * 1.5;",
    "  float phaseB = -angle * 21.11349 * uDensity + uTime * 1.5;",
    "  float phaseC = angle * 22.3991 * uDensity + uTime * 1.1;",
    "  float phaseD = -angle * 18.0234 * uDensity + uTime * 1.1;",
    "  float strengthA = clamp(0.75 + 0.15 * sin(phaseA) + 0.2 * cos(phaseB), 0.0, 1.0);",
    "  float strengthB = clamp(0.75 + 0.15 * sin(phaseC) + 0.2 * cos(phaseD), 0.0, 1.0);",
    "  float widthA = abs(0.15 * 36.2214 * cos(phaseA) + 0.2 * 21.11349 * sin(phaseB)) * uDensity * slope;",
    "  float widthB = abs(0.15 * 22.3991 * cos(phaseC) + 0.2 * 18.0234 * sin(phaseD)) * uDensity * slope;",
    "  float pulseA = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 4.5) : 1.0;",
    "  float pulseB = uPulsating > 0.5 ? 0.8 + 0.2 * sin(uTime * 3.3) : 1.0;",
    "  float rayLight = envelope * (0.5 * shape(strengthA, widthA) * pulseA + 0.4 * shape(strengthB, widthB) * pulseB);",
    "",
    "  if (uHaze > 0.0) {",
    "    float around = atan(uAim.x * dir.y - uAim.y * dir.x, cosAngle);",
    "    vec2 drift = vec2(around * 2.2 + uTime * 0.035, depth * 2.6 - uTime * 0.11);",
    "    float fog = 0.65 * valueNoise(drift * vec2(3.0, 1.0)) + 0.35 * valueNoise(drift * vec2(7.0, 2.3) + 4.1);",
    "    rayLight *= mix(1.0, 0.25 + 1.2 * fog, uHaze);",
    "  }",
    "",
    "  if (uShadow.z > 0.0) {",
    "    vec2 toCursor = uShadow.xy - uSource;",
    "    float cursorDistance = length(toCursor);",
    "    float along = dot(delta, toCursor) / max(cursorDistance * cursorDistance, 1e-4);",
    "    float side = abs(delta.x * toCursor.y - delta.y * toCursor.x) / max(cursorDistance, 1e-4);",
    "    float trail = max(along - 1.0, 0.0);",
    "    float width = uShadow.w * along + 0.22 * trail * cursorDistance;",
    "    float behind = smoothstep(0.97, 1.25, along) * exp(-trail * 1.1);",
    "    float shade = (1.0 - smoothstep(width * 0.3, width * 1.6, side)) * behind;",
    "    rayLight *= 1.0 - uShadow.z * 0.62 * shade;",
    "  }",
    "",
    "  float boost = 0.0;",
    "  for (int i = 0; i < " + MAX_PULSES + "; i++) {",
    "    vec4 wave = uPulses[i];",
    "    if (wave.z <= 0.0) continue;",
    "    float x = (depth - wave.x) / wave.y;",
    "    boost += wave.z * exp(-x * x);",
    "  }",
    "  float light = (rayLight * (1.0 + boost) + glowLight) * reveal;",
    "",
    "  if (uNoise > 0.0) {",
    "    float n = fract(sin(dot(coord * 0.02 + uTime * 0.1, vec2(12.9898, 78.233))) * 43758.5453123);",
    "    light *= 1.0 - uNoise + uNoise * n;",
    "  }",
    "",
    "  float near = clamp(1.2 - distance / (uResolution.y / uScale), 0.0, 1.0);",
    "  vec3 tint = mix(vec3(0.9), vec3(0.1, 0.3, 0.5) + near * vec3(0.8, 0.6, 0.5), uAtmosphere);",
    "  float gray = dot(tint, vec3(0.299, 0.587, 0.114));",
    "  vec3 hue = max(mix(vec3(gray), tint, uSaturation), 0.0) * uColor;",
    "",
    "  float grain = (fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5) / 255.0;",
    "  if (uLight > 0.5) {",
    "    vec3 color = hue * light;",
    "    float energy = max(color.r, max(color.g, color.b));",
    "    vec3 tone = clamp(1.0 - (1.0 - hue / max(max(hue.r, max(hue.g, hue.b)), 1e-4)) * 1.8, 0.0, 1.0);",
    "    float warm = clamp((min(tone.r, tone.g) - tone.b) * 2.0, 0.0, 1.0);",
    "    vec3 ink = tone * (mix(0.66, 0.94, warm) - 0.1 * smoothstep(0.4, 1.2, energy));",
    "    float density = clamp(0.82 * (1.0 - exp(-1.5 * energy * energy)) * uOpacity + grain, 0.0, 1.0);",
    "    fragColor = vec4(ink * density, density);",
    "    return;",
    "  }",
    "  float level = light < 0.75 ? light : 0.75 + 0.25 * (1.0 - exp(-(light - 0.75) / 0.25));",
    "  float top = max(hue.r, max(hue.g, hue.b));",
    "  hue = mix(hue, vec3(top), smoothstep(0.8, 1.0, level) * 0.45);",
    "  vec3 shown = clamp(hue * level, 0.0, 1.0) * level;",
    "  fragColor = vec4(clamp(shown + grain, 0.0, level) * uOpacity, level * uOpacity);",
    "}"
  ].join("\n");

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function parseColor(value) {
    var text = String(value || "").trim();
    var hex = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
    if (hex) {
      var full = hex[1].length === 3
        ? hex[1].replace(/./g, function (digit) { return digit + digit; })
        : hex[1];
      return [0, 2, 4].map(function (index) {
        return parseInt(full.slice(index, index + 2), 16) / 255;
      });
    }
    var rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(text);
    if (rgb) {
      return [rgb[1], rgb[2], rgb[3]].map(function (channel) {
        return clamp(parseFloat(channel) / 255, 0, 1);
      });
    }
    return null;
  }

  function compile(gl, type, source) {
    var shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      if (window.console) console.error(gl.getShaderInfoLog(shader));
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  function link(gl) {
    var vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
    var fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    var program = vertex && fragment ? gl.createProgram() : null;
    if (!vertex || !fragment || !program) {
      if (vertex) gl.deleteShader(vertex);
      if (fragment) gl.deleteShader(fragment);
      return null;
    }
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      if (window.console) console.error(gl.getProgramInfoLog(program));
      gl.deleteProgram(program);
      return null;
    }
    var uniforms = {};
    var count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
    for (var index = 0; index < count; index++) {
      var info = gl.getActiveUniform(program, index);
      if (info) {
        uniforms[info.name.replace(/\[0\]$/, "")] = gl.getUniformLocation(program, info.name);
      }
    }
    return { program: program, uniforms: uniforms };
  }

  function smoother(t) {
    var x = clamp(t, 0, 1);
    return x * x * x * (x * (x * 6 - 15) + 10);
  }

  function buildSettings(presetName) {
    var preset = PRESETS[presetName] || PRESETS.spotlight;
    var s = Object.assign({}, LOOK, preset);
    return {
      origin: ORIGINS[s.raysOrigin] || ORIGINS["top-center"],
      color: parseColor(s.raysColor) || [1, 1, 1],
      speed: Math.max(0, s.raysSpeed),
      spread: Math.max(0.001, s.lightSpread),
      length: Math.max(0.01, s.rayLength),
      density: clamp(s.rayDensity, 0.1, 6),
      tilt: (clamp(s.tilt, -90, 90) * Math.PI) / 180,
      sharpness: clamp(s.raySharpness, 0, 1),
      glow: Math.max(0, s.glow),
      haze: clamp(s.haze, 0, 1),
      atmosphere: clamp(s.atmosphere, 0, 1),
      intensity: Math.max(0, s.intensity),
      pulsating: !!s.pulsating,
      fade: Math.max(0.01, s.fadeDistance),
      saturation: Math.max(0, s.saturation),
      follow: !!s.followMouse,
      influence: clamp(s.mouseInfluence, 0, 1),
      cursorShadow: !!s.cursorShadow,
      clickPulse: !!s.clickPulse,
      noise: clamp(s.noiseAmount, 0, 1),
      distortion: Number(s.distortion) || 0,
      intro: !!s.intro,
      light: !!s.lightMode,
      opacity: clamp(s.opacity, 0, 1),
      maxRatio: clamp(s.maxDevicePixelRatio, 0.5, 3)
    };
  }

  function LightRaysEngine(container, canvas, preset) {
    this.container = container;
    this.canvas = canvas;
    this.preset = PRESETS[preset] ? preset : "spotlight";
    this.settings = buildSettings(this.preset);
    this.gl = null;
    this.shader = null;
    this.vao = null;
    this.raf = 0;
    this.last = 0;
    this.time = 0;
    this.opening = 1;
    this.reduced = false;
    this.enabled = true;
    this.visible = true;
    this.pageVisible = document.visibilityState !== "hidden";
    this.lost = false;
    this.resizePending = false;
    this.size = { width: 1, height: 1, ratio: 1 };
    this.pointer = { x: 0.5, y: 0.5, inside: false, seen: false };
    this.aim = { x: 0.5, y: 0.5 };
    this.shade = { x: 0.5, y: 0.5, presence: 0 };
    this.pulses = [];
    this.pulseData = new Float32Array(MAX_PULSES * 4);
    this._handlers = [];
    this._ro = null;
    this._io = null;
    this._frame = this._frame.bind(this);
    this._init();
  }

  LightRaysEngine.prototype._on = function (target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    this._handlers.push([target, type, fn, opts]);
  };

  LightRaysEngine.prototype._init = function () {
    var gl = this.canvas.getContext("webgl2", {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance"
    });
    if (!gl) {
      if (window.console) console.warn("LightRays: WebGL2 недоступен — фон отключён");
      this.enabled = false;
      this.container.style.display = "none";
      return;
    }
    this.gl = gl;
    if (!this._initGL()) {
      this.enabled = false;
      this.container.style.display = "none";
      return;
    }
    this.reduced = !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    this.opening = (this.settings.intro && !this.reduced) ? 0 : 1;

    var self = this;

    this._on(window, "pointermove", function (event) {
      var spot = self._locate(event);
      if (!self.pointer.inside && spot.inside) {
        self.shade.x = spot.x;
        self.shade.y = spot.y;
      }
      self.pointer.x = spot.x;
      self.pointer.y = spot.y;
      self.pointer.inside = spot.inside;
      self.pointer.seen = true;
      self._wake();
    }, { passive: true });

    this._on(window, "pointerdown", function (event) {
      var spot = self._locate(event);
      if (!spot.inside || !self.settings.clickPulse || self.reduced) return;
      self.pulses.push({ age: 0 });
      if (self.pulses.length > MAX_PULSES) self.pulses.shift();
      self._wake();
    }, { passive: true });

    var onLeave = function () {
      self.pointer.inside = false;
      self._wake();
    };
    this._on(document.documentElement, "pointerleave", onLeave);
    this._on(window, "pointerup", function (event) {
      if (event.pointerType !== "mouse") onLeave();
    }, { passive: true });
    this._on(window, "pointercancel", function (event) {
      if (event.pointerType !== "mouse") onLeave();
    }, { passive: true });

    this._on(this.canvas, "webglcontextlost", function (event) {
      event.preventDefault();
      self.lost = true;
      cancelAnimationFrame(self.raf);
      self.raf = 0;
    });
    this._on(this.canvas, "webglcontextrestored", function () {
      self.lost = false;
      self._initGL();
      self._wake();
    });

    this._on(document, "visibilitychange", function () {
      self.pageVisible = document.visibilityState !== "hidden";
      self._wake();
    });

    if (window.ResizeObserver) {
      this._ro = new ResizeObserver(function () {
        self._resize();
        self._wake();
      });
      this._ro.observe(this.container);
    }

    if (window.IntersectionObserver) {
      this._io = new IntersectionObserver(function (entries) {
        self.visible = entries.some(function (entry) { return entry.isIntersecting; });
        self._wake();
      });
      this._io.observe(this.container);
    }

    this._resize();
    this._wake();
  };

  LightRaysEngine.prototype._initGL = function () {
    if (!this.gl) return false;
    this.shader = link(this.gl);
    if (!this.shader) return false;
    this.vao = this.gl.createVertexArray();
    return true;
  };

  LightRaysEngine.prototype._locate = function (event) {
    var rect = this.container.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / Math.max(1, rect.width),
      y: (event.clientY - rect.top) / Math.max(1, rect.height),
      inside: event.clientX >= rect.left &&
        event.clientX <= rect.right &&
        event.clientY >= rect.top &&
        event.clientY <= rect.bottom
    };
  };

  LightRaysEngine.prototype._resize = function () {
    this.resizePending = true;
  };

  LightRaysEngine.prototype._applyResize = function () {
    var s = this.settings;
    var rect = this.container.getBoundingClientRect();
    var cssWidth = Math.max(1, rect.width);
    var cssHeight = Math.max(1, rect.height);
    var detail = s.density * (0.35 + 0.65 * s.sharpness);
    var sampling = Math.max(clamp(0.35 + 0.3 * detail, 0.5, 2), s.noise > 0 ? 1 : 0);
    var ratio = Math.min(
      window.devicePixelRatio || 1,
      s.maxRatio,
      sampling,
      Math.sqrt(PIXEL_BUDGET / (cssWidth * cssHeight))
    );
    var width = Math.max(1, Math.round(cssWidth * ratio));
    var height = Math.max(1, Math.round(cssHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    this.size.width = cssWidth;
    this.size.height = cssHeight;
    this.size.ratio = width / cssWidth;
  };

  LightRaysEngine.prototype._wake = function () {
    if (!this.enabled || this.lost || !this.visible || !this.pageVisible) return;
    if (this.raf) return;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this._frame);
  };

  LightRaysEngine.prototype._frame = function (now) {
    this.raf = 0;
    try {
      if (this.resizePending) {
        this.resizePending = false;
        this._applyResize();
      }
      if (this.lost || !this.enabled) return;

      var s = this.settings;
      var dt = clamp((now - this.last) / 1000 || 0, 0, 0.05);
      this.last = Math.max(this.last, now);
      this.time += dt * s.speed * (this.reduced ? 0.35 : 1);
      if (this.opening < 1) this.opening = Math.min(1, this.opening + dt / 1.8);

      var steer = 1 - Math.exp(-dt / 0.2);
      var aimX = s.follow && this.pointer.seen ? this.pointer.x : 0.5;
      var aimY = s.follow && this.pointer.seen ? this.pointer.y : 0.5;
      this.aim.x += (aimX - this.aim.x) * steer;
      this.aim.y += (aimY - this.aim.y) * steer;
      var glide = 1 - Math.exp(-dt / 0.08);
      this.shade.x += (this.pointer.x - this.shade.x) * glide;
      this.shade.y += (this.pointer.y - this.shade.y) * glide;
      var shading = this.pointer.inside && s.cursorShadow && !this.reduced;
      this.shade.presence += ((shading ? 1 : 0) - this.shade.presence) *
        (1 - Math.exp(-dt / (shading ? 0.25 : 0.5)));

      for (var index = this.pulses.length - 1; index >= 0; index--) {
        this.pulses[index].age += dt;
        if (this.pulses[index].age >= 2) this.pulses.splice(index, 1);
      }
      this.pulseData.fill(0);
      for (var p = 0; p < this.pulses.length; p++) {
        var age = this.pulses[p].age;
        this.pulseData[p * 4] = 0.05 + age * 1.05;
        this.pulseData[p * 4 + 1] = 0.14 + age * 0.14;
        this.pulseData[p * 4 + 2] = 0.9 * smoother(age / 0.15) * (1 - smoother(age / 2));
      }

      var width = this.size.width;
      var height = this.size.height;
      var sourceX = s.origin.anchor[0] * width;
      var sourceY = s.origin.anchor[1] * height;
      var cos = Math.cos(s.tilt);
      var sin = Math.sin(s.tilt);
      var dirX = s.origin.dir[0] * cos - s.origin.dir[1] * sin;
      var dirY = s.origin.dir[0] * sin + s.origin.dir[1] * cos;
      if (s.follow && s.influence > 0) {
        var mx = this.aim.x * width - sourceX;
        var my = this.aim.y * height - sourceY;
        var ml = Math.hypot(mx, my) || 1;
        var bx = dirX + (mx / ml - dirX) * s.influence;
        var by = dirY + (my / ml - dirY) * s.influence;
        var bl = Math.hypot(bx, by) || 1;
        dirX = bx / bl;
        dirY = by / bl;
      }
      var eased = 1 - Math.pow(1 - this.opening, 3);

      var gl = this.gl;
      var u = this.shader.uniforms;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(this.shader.program);
      gl.bindVertexArray(this.vao);
      gl.uniform2f(u.uResolution, this.canvas.width, this.canvas.height);
      gl.uniform1f(u.uScale, this.size.ratio);
      gl.uniform1f(u.uTime, this.time);
      gl.uniform2f(u.uSource, sourceX, sourceY);
      gl.uniform2f(u.uAim, dirX, dirY);
      gl.uniform1f(u.uReach, Math.max(width, height));
      gl.uniform3f(u.uColor, s.color[0], s.color[1], s.color[2]);
      gl.uniform1f(u.uSpread, s.spread);
      gl.uniform1f(u.uLength, s.length);
      gl.uniform1f(u.uFade, s.fade);
      gl.uniform1f(u.uSaturation, s.saturation);
      gl.uniform1f(u.uPulsating, s.pulsating ? 1 : 0);
      gl.uniform1f(u.uNoise, s.noise);
      gl.uniform1f(u.uDistortion, s.distortion);
      gl.uniform1f(u.uDensity, s.density);
      gl.uniform1f(u.uSharpness, s.sharpness);
      gl.uniform1f(u.uGlow, s.glow);
      gl.uniform1f(u.uHaze, s.haze);
      gl.uniform1f(u.uAtmosphere, s.atmosphere);
      gl.uniform1f(u.uIntensity, s.intensity);
      gl.uniform4f(u.uShadow, this.shade.x * width, this.shade.y * height,
        this.shade.presence, 16);
      gl.uniform4fv(u.uPulses, this.pulseData);
      gl.uniform2f(u.uIntro, eased * 2.6, smoother(this.opening / 0.5));
      gl.uniform1f(u.uLight, s.light ? 1 : 0);
      gl.uniform1f(u.uOpacity, s.opacity);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      var settling =
        Math.abs(this.aim.x - aimX) > 1e-4 ||
        Math.abs(this.aim.y - aimY) > 1e-4 ||
        (this.shade.presence > 1e-3 &&
          Math.abs(this.shade.x - this.pointer.x) + Math.abs(this.shade.y - this.pointer.y) > 1e-4) ||
        Math.abs((shading ? 1 : 0) - this.shade.presence) > 1e-3 ||
        this.pulses.length > 0;
      var busy = s.speed > 0 || this.opening < 1 || settling;
      if (busy && this.visible && this.pageVisible && this.enabled) {
        this.raf = requestAnimationFrame(this._frame);
      }
    } catch (exc) {
      if (window.console) console.warn("LightRays: кадр не отрисован", exc);
    }
  };

  LightRaysEngine.prototype.setPreset = function (name) {
    if (!PRESETS[name]) name = "spotlight";
    this.preset = name;
    this.settings = buildSettings(name);
    this._wake();
  };

  LightRaysEngine.prototype.getPreset = function () {
    return this.preset;
  };

  LightRaysEngine.prototype.setEnabled = function (on) {
    this.enabled = !!on;
    this.container.style.display = this.enabled ? "" : "none";
    if (!this.enabled) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
      if (this.gl && this.shader && !this.gl.isContextLost()) {
        this.gl.clearColor(0, 0, 0, 0);
        this.gl.clear(this.gl.COLOR_BUFFER_BIT);
      }
      return;
    }
    this._resize();
    this._wake();
  };

  LightRaysEngine.prototype.destroy = function () {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (var i = 0; i < this._handlers.length; i++) {
      var h = this._handlers[i];
      try { h[0].removeEventListener(h[1], h[2], h[3]); } catch (e) { /* ignore */ }
    }
    this._handlers = [];
    if (this._ro) this._ro.disconnect();
    if (this._io) this._io.disconnect();
    if (this.gl && this.shader && !this.gl.isContextLost()) {
      this.gl.deleteVertexArray(this.vao);
      this.gl.deleteProgram(this.shader.program);
    }
  };

  var instance = null;

  var api = {
    PRESETS: PRESET_OPTIONS,
    init: function (container, canvas, preset) {
      if (instance) return instance;
      if (!container || !canvas) return null;
      instance = new LightRaysEngine(container, canvas, preset || "spotlight");
      return instance;
    },
    setPreset: function (name) {
      if (instance) instance.setPreset(name);
    },
    setEnabled: function (on) {
      if (instance) instance.setEnabled(on);
    },
    getPreset: function () {
      return instance ? instance.getPreset() : null;
    },
    get instance() {
      return instance;
    }
  };

  window.LightRays = api;

  function autoInit() {
    var box = document.getElementById("lightRays");
    var canvas = document.getElementById("lightRaysCanvas");
    if (box && canvas) api.init(box, canvas, "spotlight");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit, { once: true });
  } else {
    autoInit();
  }
})();
