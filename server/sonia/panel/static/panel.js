/*
 * Panel de control de Sonnia: lógica de la página.
 *
 * Sin dependencias ni paso de compilación. La misma página la sirve el
 * orquestador en local (una sola Sonnia) y el Worker de Cloudflare (todas las
 * Sonnias conectadas). Contrato completo en docs/panel.md:
 *   GET  /api/instances  Sonnias conocidas y conflictos (duplicados)
 *   GET  /api/status     instantánea completa de la Sonnia elegida (?instance=)
 *   GET  /api/gallery    imágenes que esa Sonnia puede mostrar (?instance=)
 *   POST /api/action     acciones (cabecera X-Sonia-Panel: 1 e "instance" en el cuerpo)
 *   WS   /api/events     estado, mensajes para Unity, registro y lista de Sonnias;
 *                        {"type": "select"} cambia de Sonnia sin reconectar
 *
 * Si el WebSocket se cae, se reintenta con espera creciente y mientras tanto
 * se sondea /api/status para que la página no se quede congelada. Un 401 de
 * la API significa que caducó la sesión del panel en Cloudflare: a /login.
 */
"use strict";

(() => {
  // ------------------------------------------------------------ constantes

  const API_INSTANCES = "/api/instances";
  const API_STATUS = "/api/status";
  const API_GALLERY = "/api/gallery";
  const API_ACTION = "/api/action";
  const API_EVENTS = "/api/events";
  const LOGIN_URL = "/login";
  const STORAGE_KEY = "sonia-panel.instance";

  const DEFAULT_AWAY_MESSAGE = "Me fui a ver una charla, regreso en un momento";
  const MIC_GATE_MAX = 0.2;
  const GATE_SLIDER_MAX = 1000;

  const STATUS_STALE_MS = 8000; // sin nada por el WebSocket en este tiempo: reconectar
  const WS_CONNECT_TIMEOUT_MS = 10000;
  const POLL_INTERVAL_MS = 3000; // sondeo de /api/status mientras no hay WebSocket
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 15000;
  const STARTUP_GRACE_MS = 4000; // no alarmar mientras la página arranca
  const INSTANCES_REFRESH_MS = 10000; // lista de Sonnias cuando no llega por el WebSocket
  const INSTANCES_TIMEOUT_MS = 4000; // al arrancar no se espera más a la lista
  const SELECT_HISTORY_TIMEOUT_MS = 3000; // tras cambiar de Sonnia, espera su historial
  const ACTION_TIMEOUT_MS = 15000;
  const CONTROL_LOCK_MS = 2500; // tras tocar un control, el estado del servidor no lo pisa
  const PARTIAL_LINE_STALE_MS = 20000;
  const MAX_CHAT_LINES = 200;
  const MAX_LOG_LINES = 400;
  const MAX_TOASTS = 3;
  const TUNING_SEND_MS = 150; // un deslizador de Developer manda como mucho esto a menudo

  // Ajustes de «Developer». Mismos límites que TUNING_LIMITS en control.py: la
  // boca y el movimiento en multiplicadores de lo que trae la escena y la cámara
  // sobre su plano base.
  const TUNING_SPEC = {
    mouth: [
      { key: "open", label: "Apertura de la boca", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Cerrada", "Muy abierta"] },
      { key: "jaw", label: "Mandíbula en las sílabas fuertes", min: 0, max: 3, step: 0.1, def: 1, unit: "%", ends: ["Nada", "Mucha"] },
      { key: "closure", label: "Cierre de labios (p, b, m)", min: 0, max: 1.5, step: 0.05, def: 1, unit: "%", ends: ["Sin cierre", "Muy marcado"] },
      { key: "speed", label: "Rapidez de la boca", min: 0.5, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Blanda", "Nítida"] },
    ],
    camera: [
      { key: "zoom", label: "Zoom", min: 0.5, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Más lejos", "Más cerca"] },
      { key: "height", label: "Altura", min: -0.5, max: 0.5, step: 0.01, def: 0, unit: "cm", ends: ["Más abajo", "Más arriba"] },
      { key: "distance", label: "Distancia", min: -0.6, max: 1, step: 0.02, def: 0, unit: "cm", ends: ["Más cerca", "Más lejos"] },
      { key: "side", label: "Lateral", min: -0.4, max: 0.4, step: 0.01, def: 0, unit: "cm", ends: ["Izquierda", "Derecha"] },
      { key: "tilt", label: "Inclinación", min: -15, max: 15, step: 0.5, def: 0, unit: "°", ends: ["Mira arriba", "Mira abajo"] },
    ],
    idle: [
      { key: "breath", label: "Respiración", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Sin respirar", "Muy marcada"] },
      { key: "accents", label: "Acentos al hablar", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Sin acentos", "Muy marcados"] },
      { key: "speed", label: "Ritmo del reposo", min: 0.5, max: 1.5, step: 0.05, def: 1, unit: "%", ends: ["Más lento", "Más rápido"] },
    ],
  };

  const MODES = {
    conversation: { short: "Conversando", sentence: "Sonnia está conversando", already: "Sonnia ya está conversando." },
    greeter: { short: "Solo saludos", sentence: "Sonnia solo saluda", already: "Sonnia ya está en «Solo saludos»." },
    away: { short: "Fuera", sentence: "Sonnia está fuera", already: "Sonnia ya está fuera." },
  };

  const STATE_TEXT = {
    idle: "Esperando a que alguien le hable",
    listening: "Escuchando",
    thinking: "Pensando qué decir",
    speaking: "Hablando",
  };

  const STATE_SHORT = {
    idle: "En espera",
    listening: "Escuchando",
    thinking: "Pensando",
    speaking: "Hablando",
  };

  const HEALTH_ORDER = ["internet", "screen", "mic", "camera"];
  const HEALTH_NAMES = { internet: "Internet", screen: "Pantalla", mic: "Micrófono", camera: "Cámara" };
  const ENGINE_NAMES = { live: "GPT-Live", pipeline: "Motor de respaldo" };
  const LOG_LEVELS = { DEBUG: "depuración", WARNING: "aviso", ERROR: "error", CRITICAL: "error grave" };

  // Los números se muestran como en República Dominicana.
  const LOCALE = "es-DO";

  // ------------------------------------------------------------ utilidades

  const byId = (id) => document.getElementById(id);

  /** Crea un elemento con propiedades y atributos sencillos. Nunca usa innerHTML. */
  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("data-") || key.startsWith("aria-") || key === "role") node.setAttribute(key, value);
      else node[key] = value;
    }
    for (const child of children) {
      if (child !== null && child !== undefined) node.append(child);
    }
    return node;
  }

  /** Cambia el texto solo si es distinto, para no tocar el DOM dos veces por segundo sin motivo. */
  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  function setHidden(node, hidden) {
    if (node && node.hidden !== hidden) node.hidden = hidden;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function formatNumber(value, digits) {
    return new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  }

  function formatDuration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
    if (seconds < 60) return "menos de 1 min";
    const minutes = Math.round(seconds / 60);
    const hours = Math.floor(minutes / 60);
    return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
  }

  function formatAgo(ms) {
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds} s`;
    return formatDuration(seconds);
  }

  function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  /** "logo-sonnet" -> "Logo sonnet". */
  function prettyImageName(id) {
    if (id === "camera") return "Foto de la cámara";
    return capitalize(String(id).replace(/[-_]+/g, " ").trim());
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  /** "A", "A y B", "A, B y C". */
  function joinNames(names) {
    if (names.length <= 1) return names.join("");
    return `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}`;
  }

  /** "12:03:04" -> "12:03". */
  function shortTime(time) {
    return typeof time === "string" ? time.slice(0, 5) : "";
  }

  // La Sonnia elegida se recuerda en este navegador. El almacenamiento puede no
  // existir (modo privado, bloqueado): entonces simplemente no se recuerda.
  function loadStoredInstance() {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  }

  function storeInstance(id) {
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // Sin almacenamiento: no pasa nada.
    }
  }

  // El panel local solo se abre desde el propio equipo del stand.
  const isLocalPanel = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);

  // Los controles de ruido y el medidor usan escala de raíz cuadrada: los
  // niveles de voz son pequeños (0,01-0,1) y en escala lineal no se verían.
  function levelToFraction(level) {
    return Math.sqrt(clamp(level / MIC_GATE_MAX, 0, 1));
  }

  function gateToSlider(gate) {
    return Math.round(levelToFraction(gate) * GATE_SLIDER_MAX);
  }

  function sliderToGate(slider) {
    const fraction = clamp(slider / GATE_SLIDER_MAX, 0, 1);
    return Math.round(MIC_GATE_MAX * fraction * fraction * 1000) / 1000;
  }

  function describeGate(gate) {
    if (gate <= 0) return "Apagado";
    let word = "Alto";
    if (gate < 0.015) word = "Bajo";
    else if (gate < 0.05) word = "Medio";
    return `${word} (${formatNumber(gate, 3)})`;
  }

  // ------------------------------------------------------------ estado de la página

  const app = {
    status: null,
    caps: new Set(),
    capsKnown: false,
    lastContactAt: 0, // última respuesta del panel (WebSocket o HTTP)
    lastWsMessageAt: 0,
    startedAt: Date.now(),
    instances: [], // Sonnias que conoce el panel (en local, solo una)
    conflicts: { connected: [], conversing: [] },
    instancesFetchedAt: 0,
    instanceId: null, // la Sonnia que se controla
    preferredId: loadStoredInstance(), // la que eligió este navegador la última vez
    awaitingHistoryUntil: 0, // tras "select", lo que llegue antes del historial es de la anterior
    redirecting: false,
    started: false,
    ws: null,
    wsLive: false,
    wsCreatedAt: 0,
    wsOpenedAt: 0,
    retryDelay: RETRY_MIN_MS,
    retryTimer: 0,
    nextRetryAt: 0,
    pollTimer: 0,
    polling: false,
    pollOk: false,
    authExpired: false,
    gallery: [],
    galleryState: "loading", // loading | ready | error
    galleryAttemptAt: 0,
    notesBase: null, // último texto de avisos que vino del servidor y está en la caja
    lastPresence: null,
  };

  // Referencias a los elementos fijos de la página.
  const ui = {};

  function collectElements() {
    const ids = [
      "topbar-status", "topbar-name", "topbar-text", "topbar-state", "topbar-live", "topbar-live-text", "topbar-live-short",
      "instances", "instance-list",
      "dup-conversing", "dup-conversing-title", "dup-conversing-text", "keep-one-btn", "hero-kicker", "hero-disconnected", "cache-error", "offline-banner", "offline-detail", "slow-banner", "auth-banner",
      "reload-btn", "hero", "hero-mode", "hero-activity", "activity-dot", "hero-health", "hero-muted",
      "away-sign", "away-sign-text", "edit-sign-btn", "stop-btn", "greet-btn", "dance-btn", "logo-btn",
      "hide-btn", "mute-btn", "mute-label", "now-showing", "thumbs", "caption-input", "say-form",
      "say-input", "say-btn", "notes-form", "notes-input", "notes-btn", "notes-state", "volume-input",
      "volume-value", "gate-input", "gate-value", "gate-meter-fill", "gate-meter-mark",
      "gate-meter-caption", "health-list", "last-error", "last-error-text", "chat", "chat-empty",
      "voice-select", "voice-btn", "showcase-input", "anim-groups", "debug-input", "subtitles-input",
      "hero-debug", "ask-form", "ask-input", "ask-btn", "tune-mouth", "tune-camera", "tune-idle",
      "avatar-state", "avatar-edit-btn", "avatar-close-btn", "avatar-reset-btn",
      "guest-avatar-state", "guest-avatar-edit-btn", "guest-avatar-reset-btn",
      "restart-btn", "cache-progress", "cache-text", "cache-btn", "session-facts", "usage-facts", "log",
      "toasts", "confirm-dialog", "confirm-title", "confirm-text", "confirm-ok", "away-dialog",
      "away-title", "away-help", "away-text", "away-ok",
      "trivia-state", "trivia-question", "trivia-q", "trivia-opt-a", "trivia-opt-b", "trivia-opt-c",
      "trivia-start-btn", "trivia-restart-btn", "trivia-stop-btn", "trivia-note",
    ];
    for (const id of ids) {
      // "topbar-status" -> ui.topbarStatus
      ui[id.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = byId(id);
    }
    ui.modeButtons = Array.from(document.querySelectorAll("[data-set-mode]"));
    ui.gestureButtons = Array.from(document.querySelectorAll("[data-gesture]"));
    ui.triviaAnswerButtons = Array.from(document.querySelectorAll("[data-trivia-answer]"));
    ui.resetTuningButtons = Array.from(document.querySelectorAll("[data-reset-tuning]"));
    ui.syncNotes = Array.from(document.querySelectorAll("[data-sync-note]"));
    ui.tuningInputs = [];
  }

  // ------------------------------------------------------------ avisos flotantes

  function showToast(message, kind = "info") {
    const titles = { ok: "Hecho", error: "No se pudo", info: "Aviso" };
    const toast = el(
      "div",
      { class: `toast toast--${kind}`, role: kind === "error" ? "alert" : "status" },
      el("span", { class: "toast-title", text: titles[kind] || titles.info }),
      message,
    );
    ui.toasts.append(toast);
    while (ui.toasts.children.length > MAX_TOASTS) ui.toasts.firstElementChild.remove();
    const remove = () => toast.remove();
    toast.addEventListener("click", remove);
    setTimeout(remove, kind === "error" ? 9000 : 4500);
  }

  // ------------------------------------------------------------ peticiones HTTP

  /** Lee el cuerpo como JSON solo si lo es; si no (página de acceso, error del proxy), null. */
  async function readJson(response) {
    const type = response.headers.get("content-type") || "";
    if (!type.includes("json")) return null;
    try {
      const data = await response.json();
      return data && typeof data === "object" ? data : null;
    } catch {
      return null;
    }
  }

  /**
   * Cloudflare Access (si está delante) redirige a su propia página de acceso
   * cuando caduca la sesión: la petición llega como redirección opaca o HTML.
   */
  function looksLikeLogin(response, data) {
    if (response.type === "opaqueredirect") return true;
    if (data) return false;
    const html = (response.headers.get("content-type") || "").includes("text/html");
    return response.status === 403 || (response.status === 200 && html);
  }

  function setAuthExpired() {
    if (app.authExpired) return;
    app.authExpired = true;
    updateConnectionUi();
  }

  /** Un 401 de la API: caducó la sesión del panel en Cloudflare. En local nunca pasa. */
  function goToLogin() {
    setAuthExpired();
    if (app.redirecting) return;
    app.redirecting = true;
    location.assign(LOGIN_URL);
  }

  /** Añade ?instance=<id> de la Sonnia elegida (el panel local lo ignora). */
  function withInstance(url, id = app.instanceId) {
    if (!id) return url;
    return `${url}${url.includes("?") ? "&" : "?"}instance=${encodeURIComponent(id)}`;
  }

  /**
   * fetch con las opciones de siempre. Devuelve {response, data} (data es el
   * JSON o null). Se encarga del 401 y de la página de acceso de Cloudflare.
   */
  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      redirect: "manual",
      ...options,
    });
    if (response.status === 401) goToLogin();
    const data = await readJson(response);
    if (response.status !== 401 && looksLikeLogin(response, data)) setAuthExpired();
    return { response, data };
  }

  /** Mensaje para el operador cuando la respuesta no trae uno propio. */
  function defaultActionError(status) {
    if (status === 503) return "Esa Sonnia no está conectada al panel ahora mismo.";
    if (status === 504) return "Sonnia no contestó a tiempo. Mira si lo hizo antes de repetirlo.";
    if (status === 401) return "Tu sesión del panel caducó. Vuelve a entrar.";
    return `El panel respondió con un error (código ${status}). Inténtalo de nuevo.`;
  }

  /**
   * Manda una acción a una Sonnia (por defecto, la elegida) y enseña su
   * respuesta al operador. Devuelve {ok, message}. Con quiet solo avisa si
   * falla; con silent no avisa nunca (quien llama junta los resultados).
   */
  async function sendAction(action, params = {}, { button = null, quiet = false, silent = false, instance } = {}) {
    const target = instance === undefined ? app.instanceId : instance;
    const notify = (message, kind) => {
      if (!silent && (kind === "error" || !quiet)) showToast(message, kind);
    };
    setBusy(button, true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
    try {
      const body = { action, ...params };
      if (target) body.instance = target;
      const { response, data } = await apiFetch(API_ACTION, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Sonia-Panel": "1" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!data) {
        const message = app.authExpired
          ? "Tu acceso al panel caducó. Recarga la página para volver a entrar."
          : defaultActionError(response.status);
        notify(message, "error");
        return { ok: false, message };
      }
      markContact();
      const ok = response.ok && data.ok !== false;
      const serverMessage = typeof data.message === "string" ? data.message.trim() : "";
      const message = serverMessage || (ok ? "Listo." : defaultActionError(response.status));
      notify(message, ok ? "ok" : "error");
      // Sin WebSocket, refresca ya para que se vea el cambio sin esperar al sondeo.
      if (ok && !app.wsLive) pollStatus();
      return { ok, message };
    } catch (error) {
      const message =
        error && error.name === "AbortError"
          ? "Sonnia tardó demasiado en responder. Mira si lo hizo antes de repetirlo."
          : "No se pudo enviar: no hay conexión con el panel. Inténtalo de nuevo en unos segundos.";
      notify(message, "error");
      return { ok: false, message };
    } finally {
      clearTimeout(timer);
      setBusy(button, false);
    }
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.classList.toggle("is-busy", busy);
    if (busy) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
    refreshControls();
  }

  // ------------------------------------------------------------ conexión

  function markContact() {
    app.lastContactAt = Date.now();
  }

  function eventsUrl() {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    return withInstance(`${scheme}//${location.host}${API_EVENTS}`);
  }

  function connectWs() {
    clearTimeout(app.retryTimer);
    app.retryTimer = 0;
    app.nextRetryAt = 0;
    if (app.ws || app.redirecting) return;
    let ws;
    try {
      ws = new WebSocket(eventsUrl());
    } catch {
      scheduleReconnect();
      return;
    }
    app.ws = ws;
    ws.instanceId = app.instanceId; // la Sonnia con la que se abrió
    app.wsCreatedAt = Date.now();
    ws.addEventListener("open", () => {
      if (app.ws !== ws) return;
      app.wsOpenedAt = Date.now();
      // Si se cambió de Sonnia mientras conectaba, se pide la buena.
      if (app.instanceId && ws.instanceId !== app.instanceId) sendSelect(ws);
    });
    ws.addEventListener("message", (event) => {
      if (app.ws === ws) onWsMessage(event);
    });
    ws.addEventListener("close", () => {
      if (app.ws === ws) dropWs();
    });
    // Un error siempre viene seguido de close: ahí se gestiona.
    updateConnectionUi();
  }

  /** Pide por el WebSocket abierto la Sonnia elegida y descarta lo que llegue antes de su historial. */
  function sendSelect(ws) {
    try {
      ws.send(JSON.stringify({ type: "select", instance: app.instanceId }));
      ws.instanceId = app.instanceId;
      app.awaitingHistoryUntil = Date.now() + SELECT_HISTORY_TIMEOUT_MS;
    } catch {
      dropWs();
    }
  }

  /** Abandona el WebSocket actual y pasa a sondeo con reintento. */
  function dropWs() {
    const ws = app.ws;
    app.ws = null;
    app.wsLive = false;
    app.wsOpenedAt = 0;
    app.awaitingHistoryUntil = 0;
    if (ws && ws.readyState <= WebSocket.OPEN) {
      try {
        ws.close();
      } catch {
        // Ya estaba cerrándose.
      }
    }
    if (app.redirecting) return;
    startPolling();
    scheduleReconnect();
    updateConnectionUi();
  }

  function scheduleReconnect() {
    if (app.retryTimer) return;
    const delay = app.retryDelay;
    app.retryDelay = Math.min(app.retryDelay * 2, RETRY_MAX_MS);
    app.nextRetryAt = Date.now() + delay;
    app.retryTimer = setTimeout(() => {
      app.retryTimer = 0;
      connectWs();
    }, delay);
  }

  /** Reintenta ya (vuelve la red, el móvil se desbloquea...). */
  function reconnectNow() {
    if (app.ws) return;
    app.retryDelay = RETRY_MIN_MS;
    clearTimeout(app.retryTimer);
    app.retryTimer = 0;
    connectWs();
    pollStatus();
  }

  /** ¿Este estado es de la Sonnia elegida? (en Cloudflare trae "instance"; en local, no). */
  function statusIsForSelected(status) {
    const id = status && status.instance && status.instance.id;
    return !id || !app.instanceId || id === app.instanceId;
  }

  function onWsMessage(event) {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!data || typeof data !== "object") return;
    app.lastWsMessageAt = Date.now();
    markContact();
    if (!app.wsLive) {
      app.wsLive = true;
      app.retryDelay = RETRY_MIN_MS;
      stopPolling();
    }
    // Tras cambiar de Sonnia, lo que llegue antes de su historial es de la anterior.
    const switching = app.awaitingHistoryUntil > Date.now();
    switch (data.type) {
      case "instances":
        applyInstances(data);
        break;
      case "history":
        app.awaitingHistoryUntil = 0;
        applyHistory(data);
        break;
      case "status":
        if (!switching && statusIsForSelected(data.status)) applyStatus(data.status);
        break;
      case "message":
        if (!switching) handleOrchestratorMessage(data.message, true);
        break;
      case "log":
        if (!switching) appendLog(data);
        break;
      default:
        break;
    }
    updateConnectionUi();
  }

  function startPolling() {
    if (app.pollTimer) return;
    app.pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
    pollStatus();
  }

  function stopPolling() {
    clearInterval(app.pollTimer);
    app.pollTimer = 0;
  }

  /**
   * Pide la lista de Sonnias. Devuelve "ok", "unsupported" (servidor sin varias
   * Sonnias: se sigue como antes) o "error" (sin conexión).
   */
  async function fetchInstances({ timeout = ACTION_TIMEOUT_MS } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const { response, data } = await apiFetch(API_INSTANCES, { signal: controller.signal });
      if (response.ok && data) {
        markContact();
        app.instancesFetchedAt = Date.now();
        applyInstances(data);
        return "ok";
      }
      if (response.status === 404) {
        markContact();
        app.instancesFetchedAt = Date.now();
        return "unsupported";
      }
      return "error";
    } catch {
      return "error";
    } finally {
      clearTimeout(timer);
    }
  }

  /** Sondeo mientras no hay WebSocket: lista de Sonnias (cada poco) y estado de la elegida. */
  async function pollStatus() {
    if (app.polling || app.redirecting) return;
    app.polling = true;
    try {
      if (Date.now() - app.instancesFetchedAt > INSTANCES_REFRESH_MS) await fetchInstances();
      const requested = app.instanceId;
      const { response, data } = await apiFetch(withInstance(API_STATUS, requested));
      if (response.ok && data) {
        const wasOffline = connectionLevel() === "offline";
        app.pollOk = true;
        markContact();
        if (requested === app.instanceId && statusIsForSelected(data)) applyStatus(data);
        // El servidor ha vuelto: no esperes al siguiente reintento del WebSocket.
        if (wasOffline && !app.ws) connectWs();
      } else if (response.status === 404) {
        // Esa Sonnia ya no existe para el panel: al pedir la lista se elige otra.
        app.pollOk = true;
        markContact();
        app.instancesFetchedAt = 0;
      } else {
        app.pollOk = false;
      }
    } catch {
      app.pollOk = false;
    } finally {
      app.polling = false;
      updateConnectionUi();
    }
  }

  /** Vigila cada segundo que el WebSocket siga vivo y refresca avisos y tiempos. */
  function watchdog() {
    const now = Date.now();
    const ws = app.ws;
    if (ws) {
      const stuckConnecting = ws.readyState === WebSocket.CONNECTING && now - app.wsCreatedAt > WS_CONNECT_TIMEOUT_MS;
      const silentAfterOpen = !app.wsLive && app.wsOpenedAt && now - app.wsOpenedAt > STATUS_STALE_MS;
      // Si la Sonnia elegida está desconectada no llega su estado: el silencio no prueba nada.
      const staleLive = app.wsLive && selectedConnected() && now - app.lastWsMessageAt > STATUS_STALE_MS;
      if (stuckConnecting || silentAfterOpen || staleLive) dropWs();
    }
    // Con la Sonnia elegida desconectada el WebSocket puede estar callado: la
    // lista se pide de vez en cuando para saber si vuelve y si el panel responde.
    if (app.wsLive && !selectedConnected() && now - app.instancesFetchedAt > INSTANCES_REFRESH_MS) {
      app.instancesFetchedAt = now;
      fetchInstances().then((result) => {
        if (result === "error" && app.wsLive) dropWs();
      });
    }
    // Si la galería falló al arrancar, se reintenta cuando vuelve la conexión.
    if (app.galleryState === "error" && app.lastContactAt && now - app.galleryAttemptAt > 10000) loadGallery();
    renderInstances();
    updateConnectionUi();
  }

  function connectionLevel() {
    if (app.authExpired) return "auth";
    if (app.wsLive) return "live";
    const age = Date.now() - app.lastContactAt;
    if (app.lastContactAt && app.pollOk && age < POLL_INTERVAL_MS * 3) return "slow";
    if (!app.lastContactAt && Date.now() - app.startedAt < STARTUP_GRACE_MS) return "connecting";
    return "offline";
  }

  function updateConnectionUi() {
    const level = connectionLevel();
    setHidden(ui.authBanner, level !== "auth");
    setHidden(ui.slowBanner, level !== "slow");
    setHidden(ui.offlineBanner, level !== "offline");
    document.body.classList.toggle("is-offline", level === "offline" || level === "auth");
    if (level === "offline") {
      const parts = [];
      if (app.ws && app.ws.readyState === WebSocket.CONNECTING) parts.push("Reintentando ahora…");
      else if (app.nextRetryAt) {
        const seconds = Math.max(1, Math.ceil((app.nextRetryAt - Date.now()) / 1000));
        parts.push(`Reintento en ${seconds} s.`);
      }
      if (app.lastContactAt) parts.push(`Último dato hace ${formatAgo(Date.now() - app.lastContactAt)}.`);
      parts.push(
        isLocalPanel
          ? "Comprueba que Sonnia sigue abierta en este equipo."
          : "Comprueba la conexión a internet de este móvil o portátil.",
      );
      setText(ui.offlineDetail, parts.join(" "));
    }
    renderTopbar();
    renderHealthSummary();
    renderDisconnected();
  }

  // ------------------------------------------------------------ estado

  function applyStatus(status) {
    if (!status || typeof status !== "object") return;
    app.status = status;
    app.caps = new Set(Array.isArray(status.capabilities) ? status.capabilities : []);
    app.capsKnown = true;
    renderAll();
  }

  function currentMode() {
    const mode = app.status && app.status.mode;
    return MODES[mode] ? mode : "conversation";
  }

  function hasCap(spec) {
    return spec.split("|").some((cap) => app.caps.has(cap));
  }

  function renderAll() {
    const status = app.status;
    if (!status) return;
    renderHero(status);
    renderQuickActions(status);
    renderTrivia(status);
    renderImageState(status);
    renderSound(status);
    renderHealth(status);
    renderNotes(status);
    renderAdvanced(status);
    renderTuning(status);
    renderAvatar();
    renderCameraLive(status);
    renderSyncNotes(status);
    refreshControls();
    updateConnectionUi();
  }

  // Reglas extra para habilitar controles, además de capacidades y modo.
  const EXTRA_RULES = {
    cache: () => {
      const cache = app.status && app.status.voice_cache;
      return !cache || (!cache.busy && cache.ready < cache.total);
    },
    logo: () => app.galleryState !== "ready" || Boolean(logoImageId()),
    voice: () => Boolean(ui.voiceSelect.value) && ui.voiceSelect.value !== (app.status && app.status.voice),
    // Con el Modo Jean en marcha el orquestador no abre el editor.
    avatar_closed: () => !avatarInfo().editor_open && !guestActive(),
    avatar_open: () => Boolean(avatarInfo().editor_open),
    avatar_custom: () => Boolean(avatarInfo().custom) && !avatarInfo().editor_open,
    guest_avatar_custom: () => Boolean(guestAvatarInfo().custom) && !avatarInfo().editor_open,
    // Con el Modo Jean, Sonnia ha dejado su sitio al invitado: ni habla ni hace gestos.
    sonia_here: () => !guestActive(),
    trivia_idle: () => triviaInfo().available !== false && !triviaInfo().active && !guestActive(),
    trivia_active: () => Boolean(triviaInfo().active),
    trivia_asking: () => triviaInfo().phase === "asking",
  };

  /** Partida de trivia en curso (`trivia` del estado). */
  function triviaInfo() {
    const trivia = app.status && app.status.trivia;
    return trivia && typeof trivia === "object" ? trivia : {};
  }

  function avatarInfo() {
    const avatar = app.status && app.status.avatar;
    return avatar && typeof avatar === "object" ? avatar : {};
  }

  /** Avatar de Jean para el Modo Jean (`guest_avatar` del estado). */
  function guestAvatarInfo() {
    const avatar = app.status && app.status.guest_avatar;
    return avatar && typeof avatar === "object" ? avatar : {};
  }

  function guestActive() {
    const guest = app.status && app.status.guest;
    return Boolean(guest && typeof guest === "object" && guest.phase && guest.phase !== "off");
  }

  /**
   * Habilita o deshabilita cada control según las capacidades del motor, el
   * modo actual, sus reglas propias y si hay una acción suya en curso.
   */
  function refreshControls() {
    const mode = app.status ? currentMode() : null;
    // Sin estado de la Sonnia elegida, o con ella desconectada, las acciones no llegarían.
    const reachable = Boolean(app.status) && selectedConnected();
    for (const node of document.querySelectorAll("[data-cap]")) {
      const capOk = !app.capsKnown || hasCap(node.dataset.cap);
      const offModes = node.dataset.offModes ? node.dataset.offModes.split(" ") : [];
      const modeOk = !mode || !offModes.includes(mode);
      const rule = node.dataset.extra && EXTRA_RULES[node.dataset.extra];
      const extraOk = !rule || rule();
      const busy = node.classList.contains("is-busy");
      const disabled = !reachable || !capOk || !modeOk || !extraOk || busy;
      if (node.disabled !== disabled) node.disabled = disabled;
    }
    for (const note of document.querySelectorAll("[data-cap-note]")) {
      setHidden(note, !app.capsKnown || hasCap(note.dataset.capNote));
    }
    for (const note of document.querySelectorAll("[data-mode-note]")) {
      setHidden(note, mode !== note.dataset.modeNote);
    }
  }

  // ------------------------------------------------------------ varias Sonnias

  function findInstance(id) {
    return app.instances.find((instance) => instance.id === id) || null;
  }

  function selectedInstance() {
    return findInstance(app.instanceId);
  }

  /** ¿La Sonnia elegida está conectada al panel? Si no se sabe, se da por buena. */
  function selectedConnected() {
    const instance = selectedInstance();
    return !instance || instance.connected !== false;
  }

  function hasSeveralInstances() {
    return app.instances.length >= 2;
  }

  function baseName(instance) {
    return String(instance.name || instance.host || instance.id);
  }

  /**
   * Nombre para mostrar. Nadie tiene por qué ponerles nombre (PANEL_INSTANCE_NAME
   * es opcional): sale el del equipo y, si dos se llaman igual, se les añade el
   * final de su id (los 6 caracteres aleatorios de cache/instance_id).
   */
  function instanceName(instance) {
    if (!instance) return "Sonnia";
    const name = baseName(instance);
    const key = name.toLowerCase();
    const repeated = app.instances.some(
      (other) => other.id !== instance.id && baseName(other).toLowerCase() === key,
    );
    if (!repeated) return name;
    const suffix = String(instance.id).split("-").pop();
    return `${name} · ${suffix}`;
  }

  function nameOf(id) {
    return instanceName(findInstance(id) || { id });
  }

  /** "hace 12 min" desde last_seen (milisegundos desde 1970). */
  function lastSeenText(instance) {
    if (!isNumber(instance.last_seen)) return "";
    return `hace ${formatDuration(Math.max(0, (Date.now() - instance.last_seen) / 1000))}`;
  }

  function idList(value) {
    return Array.isArray(value) ? value.filter((id) => typeof id === "string") : [];
  }

  /** Llega la lista de Sonnias (al conectar, al cambiar algo o por sondeo). */
  function applyInstances(data) {
    const list = (Array.isArray(data.instances) ? data.instances : []).filter(
      (instance) => instance && typeof instance.id === "string" && instance.id,
    );
    const conflicts = data.conflicts && typeof data.conflicts === "object" ? data.conflicts : null;
    app.instances = list;
    if (conflicts) {
      app.conflicts = { connected: idList(conflicts.connected), conversing: idList(conflicts.conversing) };
    } else {
      // Sin "conflicts" se calculan aquí con la misma regla.
      const connected = list.filter((instance) => instance.connected !== false);
      app.conflicts = {
        connected: connected.map((instance) => instance.id),
        conversing: connected.filter((instance) => instance.mode === "conversation").map((instance) => instance.id),
      };
    }

    // Si la elegida ya no existe (o no había), la que eligió este navegador o la primera conectada.
    if (!findInstance(app.instanceId)) {
      const next = findInstance(app.preferredId) || list.find((instance) => instance.connected !== false) || list[0];
      if (next) switchInstance(next.id, { remember: false });
    }
    renderInstances();
    renderTopbar();
    renderHeroKicker();
    renderDisconnected();
    if (app.status) renderHero(app.status);
    refreshControls();
  }

  /**
   * Cambia la Sonnia que se controla: limpia lo de la anterior y pide la nueva
   * (por el WebSocket si está abierto; si no, por sondeo).
   */
  function switchInstance(id, { remember = true } = {}) {
    if (!id || id === app.instanceId) return;
    const first = app.instanceId === null;
    app.instanceId = id;
    if (remember) {
      app.preferredId = id;
      storeInstance(id);
    }
    clearInstanceView();
    const ws = app.ws;
    if (ws && ws.readyState === WebSocket.OPEN && (!first || ws.instanceId !== id)) sendSelect(ws);
    // Durante el arranque, init() pide el estado y la galería con la Sonnia ya elegida.
    if (app.started) {
      if (!app.wsLive) pollStatus();
      loadGallery();
    }
    renderInstances();
  }

  /** Borra estado, conversación y registro de la Sonnia anterior. */
  function clearInstanceView() {
    app.status = null;
    app.caps = new Set();
    app.capsKnown = false;
    app.notesBase = null;
    app.lastPresence = null;
    resetChat();
    ui.log.replaceChildren();
    ui.notesInput.value = "";
    ui.voiceSelect.dirty = false;
    voicesKey = "";
    sessionKey = "";
    usageKey = "";
    animKey = "";
    animTiles.clear();
    ui.animGroups.replaceChildren();
    healthKeys = "";
    healthRows.clear();
    ui.healthList.replaceChildren(el("li", { class: "muted", text: "Esperando datos…" }));
    setHidden(ui.lastError, true);
    if (ui.hero.dataset.mode !== "") ui.hero.dataset.mode = "";
    setText(ui.heroMode, `Conectando con ${instanceName(selectedInstance())}…`);
    setText(ui.heroActivity, "Esperando datos");
    ui.activityDot.dataset.state = "";
    setHidden(ui.heroMuted, true);
    setHidden(ui.awaySign, true);
    for (const button of ui.modeButtons) button.setAttribute("aria-pressed", "false");
    setText(ui.nowShowing, "No hay ninguna imagen en pantalla.");
    ui.nowShowing.classList.remove("is-showing");
    renderHeroKicker();
    renderNotesState();
    refreshControls();
    updateConnectionUi();
  }

  // Botones de cada Sonnia, por id, para actualizarlos sin rehacerlos (un
  // botón rehecho bajo el dedo puede perder la pulsación).
  const instanceButtons = new Map();

  function makeInstanceButton(id) {
    const parts = {
      button: el("button", { type: "button", class: "instance", "data-instance-id": id }),
      dot: el("span", { class: "instance-dot", "aria-hidden": "true" }),
      name: el("span", { class: "instance-name" }),
      host: el("span", { class: "instance-host" }),
      mode: el("span", { class: "instance-mode" }),
      health: el("span", { class: "instance-health" }),
      check: el("span", { class: "instance-check", text: "La estás controlando" }),
    };
    parts.button.append(
      parts.dot,
      el("span", { class: "instance-title" }, parts.name, parts.host),
      el("span", { class: "instance-detail" }, parts.mode, parts.health, parts.check),
    );
    parts.button.addEventListener("click", () => onInstanceClick(id));
    return parts;
  }

  function renderInstances() {
    const several = hasSeveralInstances();
    setHidden(ui.instances, !several);
    document.body.classList.toggle("has-several", several);
    if (!several) return;

    const ids = app.instances.map((instance) => instance.id);
    for (const [id, parts] of instanceButtons) {
      if (!ids.includes(id)) {
        parts.button.remove();
        instanceButtons.delete(id);
      }
    }
    app.instances.forEach((instance, index) => {
      let parts = instanceButtons.get(instance.id);
      if (!parts) {
        parts = makeInstanceButton(instance.id);
        instanceButtons.set(instance.id, parts);
      }
      // Mantiene el orden de la lista.
      if (ui.instanceList.children[index] !== parts.button) {
        ui.instanceList.insertBefore(parts.button, ui.instanceList.children[index] || null);
      }
      paintInstanceButton(parts, instance);
    });
    renderConflicts();
  }

  function paintInstanceButton(parts, instance) {
    const connected = instance.connected !== false;
    const selected = instance.id === app.instanceId;
    const mode = MODES[instance.mode] ? instance.mode : "";
    const set = (node, attr, value) => {
      if (node.getAttribute(attr) !== value) node.setAttribute(attr, value);
    };
    set(parts.button, "aria-pressed", String(selected));
    set(parts.button, "data-connected", String(connected));
    set(parts.button, "data-mode", mode);
    setText(parts.name, instanceName(instance));
    const host = instance.host && instance.host !== instance.name ? `Equipo: ${instance.host}` : "";
    setText(parts.host, host);
    setText(parts.mode, mode ? MODES[mode].short : "Sin modo");

    let health = "";
    let level = "";
    if (!connected) {
      health = `Desconectada ${lastSeenText(instance)}`.trim();
      level = "off";
    } else if (instance.healthy === true) {
      health = "Todo bien";
      level = "ok";
    } else if (instance.healthy === false) {
      const issues = Array.isArray(instance.issues) ? instance.issues.filter((i) => typeof i === "string") : [];
      health = issues.length ? `Revisar: ${issues.join(", ")}` : "Hay algo que revisar";
      level = "bad";
    }
    setText(parts.health, health);
    set(parts.health, "data-level", level);
    const label = [instanceName(instance), mode ? MODES[mode].short : "", health, selected ? "la estás controlando" : ""]
      .filter(Boolean)
      .join(", ");
    set(parts.button, "aria-label", label);
  }

  /**
   * Nota (informativa, no un error) cuando varias Sonnias conversan a la vez:
   * puede haber una en el stand y otra en otro sitio. Cada una gasta lo suyo y,
   * si dos están en la misma sala, se contestarían entre ellas.
   */
  function renderConflicts() {
    const conversing = app.conflicts.conversing;
    const several = conversing.length >= 2;

    setHidden(ui.dupConversing, !several);
    if (several) {
      setText(ui.dupConversingTitle, `${conversing.length} Sonnias conversando a la vez`);
      const selected = selectedInstance();
      const keepable = selected && conversing.includes(selected.id);
      setText(
        ui.dupConversingText,
        `${joinNames(conversing.map(nameOf))}. Cada una gasta por su cuenta (unos 3 USD por hora). ` +
          "Si dos están en la misma sala, deja solo una conversando para que no se contesten entre ellas.",
      );
      setHidden(ui.keepOneBtn, !keepable);
      if (keepable) setText(ui.keepOneBtn, `Dejar solo «${instanceName(selected)}» conversando`);
    }
  }

  function onInstanceClick(id) {
    if (id === app.instanceId) return;
    switchInstance(id);
    showToast(`Ahora controlas «${nameOf(id)}».`, "info");
  }

  /** Manda a "Fuera" a las demás Sonnias que están conversando (una acción por Sonnia). */
  async function onKeepOne() {
    const keep = selectedInstance();
    if (!keep) return;
    const others = app.conflicts.conversing.filter((id) => id !== keep.id);
    if (others.length === 0) return;
    const names = joinNames(others.map((id) => `«${nameOf(id)}»`));
    const plural = others.length > 1;
    const ok = await confirmAction({
      title: `¿Dejar solo «${instanceName(keep)}» conversando?`,
      text:
        `${names} ${plural ? "pasarán" : "pasará"} a «Fuera»: ${plural ? "saldrán" : "saldrá"} de su pantalla ` +
        `y ${plural ? "dejarán" : "dejará"} el letrero. «${instanceName(keep)}» sigue conversando.`,
      confirmLabel: "Sí, dejar solo esta",
    });
    if (!ok) return;
    setBusy(ui.keepOneBtn, true);
    const results = await Promise.all(
      others.map((id) => sendAction("set_mode", { mode: "away" }, { instance: id, silent: true })),
    );
    setBusy(ui.keepOneBtn, false);
    const failed = others.filter((_, index) => !results[index].ok);
    const done = others.filter((_, index) => results[index].ok);
    if (done.length) {
      const doneNames = joinNames(done.map((id) => `«${nameOf(id)}»`));
      showToast(`${doneNames} ${done.length > 1 ? "pasan" : "pasa"} a «Fuera».`, "ok");
    }
    for (const id of failed) {
      showToast(`«${nameOf(id)}»: ${results[others.indexOf(id)].message}`, "error");
    }
    // La lista nueva llega sola por el WebSocket; sin él, se pide.
    if (!app.wsLive) fetchInstances();
  }

  /** La Sonnia elegida está desconectada: aviso en gris y controles deshabilitados. */
  function renderDisconnected() {
    const instance = selectedInstance();
    const disconnected = Boolean(instance) && instance.connected === false;
    const value = String(disconnected);
    if (ui.hero.dataset.disconnected !== value) ui.hero.dataset.disconnected = value;
    setHidden(ui.heroDisconnected, !disconnected);
    if (disconnected) {
      const name = hasSeveralInstances() ? `«${instanceName(instance)}»` : "Esta Sonnia";
      const since = lastSeenText(instance);
      setText(
        ui.heroDisconnected,
        `${name} está desconectada${since ? ` desde ${since}` : ""}. Los controles no funcionan hasta que ` +
          "vuelva: comprueba que su equipo está encendido y con internet.",
      );
    }
  }

  function renderHeroKicker() {
    const several = hasSeveralInstances();
    setText(ui.heroKicker, several ? `Ahora mismo · ${instanceName(selectedInstance())}` : "Ahora mismo");
  }

  // ------------------------------------------------------------ cabecera y modo

  function activityState(status) {
    const mode = currentMode();
    if (mode === "away") return "away";
    return STATE_TEXT[status.state] ? status.state : "idle";
  }

  function activityText(status) {
    const mode = currentMode();
    if (mode === "away") return "Fuera de la pantalla, con el letrero puesto";
    if (mode === "greeter") {
      return status.state === "speaking" ? "Diciendo una frase" : "Saluda y baila sola de vez en cuando";
    }
    return STATE_TEXT[status.state] || STATE_TEXT.idle;
  }

  function renderTopbar() {
    const level = connectionLevel();
    const status = app.status;
    const several = hasSeveralInstances();
    let text = "Conectando…";
    let detail = "";
    let mode = "";
    setText(ui.topbarName, several ? instanceName(selectedInstance()) : "");
    setHidden(ui.topbarName, !several);
    if (level === "offline" || level === "auth") {
      text = "Sin conexión";
    } else if (!selectedConnected()) {
      text = "Desconectada";
    } else if (status) {
      mode = currentMode();
      text = MODES[mode].short;
      if (mode === "conversation") detail = `· ${STATE_SHORT[status.state] || STATE_SHORT.idle}`;
    }
    if (ui.topbarStatus.dataset.mode !== mode) ui.topbarStatus.dataset.mode = mode;
    setText(ui.topbarText, text);
    setText(ui.topbarState, detail);
  }

  function renderHero(status) {
    const mode = currentMode();
    const connected = selectedConnected();
    if (ui.hero.dataset.mode !== mode) ui.hero.dataset.mode = mode;
    // Desconectada, el estado que se ve es el último conocido: se dice así.
    const sentence = status.debug === true ? "Sonnia en modo debug" : MODES[mode].sentence;
    setText(ui.heroMode, connected ? sentence : "Sonnia desconectada");
    setText(ui.heroActivity, connected ? activityText(status) : `Lo último que se supo: ${MODES[mode].short.toLowerCase()}`);
    const state = activityState(status);
    if (ui.activityDot.dataset.state !== state) ui.activityDot.dataset.state = state;

    const mic = (status.health && status.health.mic) || {};
    setHidden(ui.heroMuted, !(mic.muted && mode === "conversation"));
    setHidden(ui.heroDebug, status.debug !== true);

    setHidden(ui.awaySign, mode !== "away");
    setText(ui.awaySignText, status.away_message || DEFAULT_AWAY_MESSAGE);

    for (const button of ui.modeButtons) {
      const pressed = String(button.dataset.setMode === mode);
      if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
    }
  }

  function healthEntries(status) {
    const health = status && status.health && typeof status.health === "object" ? status.health : {};
    const keys = HEALTH_ORDER.filter((key) => key in health);
    for (const key of Object.keys(health)) if (!keys.includes(key)) keys.push(key);
    return keys.map((key) => [key, health[key] && typeof health[key] === "object" ? health[key] : {}]);
  }

  function renderHealthSummary() {
    const level = connectionLevel();
    let tone = "unknown";
    let text = "Comprobando…";
    if (level === "offline" || level === "auth") {
      text = "Sin datos: no hay conexión";
    } else if (!selectedConnected()) {
      text = "Sin datos: Sonnia desconectada";
    } else if (app.status) {
      const problems = healthEntries(app.status).filter(([, item]) => item.ok === false);
      if (problems.length === 0) {
        tone = "ok";
        text = "Todo funciona bien";
      } else {
        tone = "bad";
        text = `Revisa: ${problems.map(([key]) => HEALTH_NAMES[key] || capitalize(key)).join(", ")}`;
      }
    }
    if (ui.heroHealth.dataset.level !== tone) ui.heroHealth.dataset.level = tone;
    setText(ui.heroHealth, text);
  }

  async function onModeClick(button) {
    const mode = button.dataset.setMode;
    if (!MODES[mode]) return;
    if (app.status && currentMode() === mode) {
      showToast(MODES[mode].already, "info");
      return;
    }
    if (mode === "away") {
      const text = await askAwayMessage("go");
      if (text === null) return;
      const saved = await sendAction("set_away_message", { text }, { button, quiet: true });
      if (!saved.ok) return;
    }
    await sendAction("set_mode", { mode }, { button });
  }

  async function onEditSign() {
    const text = await askAwayMessage("edit");
    if (text === null) return;
    await sendAction("set_away_message", { text }, { button: ui.editSignBtn });
  }

  // ------------------------------------------------------------ diálogos

  const supportsDialog = typeof HTMLDialogElement === "function";

  /** Confirmación sencilla. Devuelve true si el operador acepta. */
  function confirmAction({ title, text, confirmLabel, danger = false }) {
    if (!supportsDialog) return Promise.resolve(window.confirm(`${title}\n\n${text}`));
    ui.confirmTitle.textContent = title;
    ui.confirmText.textContent = text;
    ui.confirmOk.textContent = confirmLabel;
    ui.confirmOk.className = danger ? "btn btn-danger" : "btn btn-primary";
    return runDialog(ui.confirmDialog).then((choice) => choice === "ok");
  }

  /**
   * Abre un diálogo modal y resuelve con el valor del botón pulsado ("ok",
   * "cancel"...). No depende solo del evento close: Chrome lo retrasa hasta el
   * siguiente fotograma, que no llega si la pestaña está en segundo plano.
   */
  function runDialog(dialog) {
    const form = dialog.querySelector("form");
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        form.removeEventListener("submit", onSubmit);
        dialog.removeEventListener("cancel", onCancel);
        dialog.removeEventListener("close", onClose);
        resolve(value || "cancel");
      };
      const onSubmit = (event) => finish(event.submitter ? event.submitter.value : dialog.returnValue);
      const onCancel = () => finish("cancel");
      const onClose = () => finish(dialog.returnValue);
      form.addEventListener("submit", onSubmit);
      dialog.addEventListener("cancel", onCancel);
      dialog.addEventListener("close", onClose);
      dialog.returnValue = "";
      dialog.showModal();
    });
  }

  /**
   * Pide el texto del letrero. kind "go" para mandarla fuera, "edit" para
   * cambiarlo estando fuera. Devuelve el texto o null si se cancela.
   */
  function askAwayMessage(kind) {
    const current = (app.status && app.status.away_message) || DEFAULT_AWAY_MESSAGE;
    if (!supportsDialog) {
      const text = window.prompt("Texto del letrero que se verá en la pantalla:", current);
      return Promise.resolve(text === null ? null : text.trim() || DEFAULT_AWAY_MESSAGE);
    }
    const going = kind === "go";
    ui.awayTitle.textContent = going ? "¿Mandar a Sonnia fuera?" : "Cambiar el letrero";
    ui.awayHelp.textContent = going
      ? "Sonnia saldrá caminando de la pantalla y dejará este letrero. No conversará ni saludará hasta que la traigas de vuelta."
      : "Escribe lo que quieres que diga el letrero que se ve en la pantalla.";
    ui.awayOk.textContent = going ? "Sí, mandarla fuera" : "Guardar letrero";
    ui.awayOk.className = going ? "btn btn-warning" : "btn btn-primary";
    ui.awayText.value = current;
    return runDialog(ui.awayDialog).then((choice) =>
      choice === "ok" ? ui.awayText.value.trim() || DEFAULT_AWAY_MESSAGE : null,
    );
  }

  // ------------------------------------------------------------ acciones rápidas

  function renderQuickActions(status) {
    const mic = (status.health && status.health.mic) || {};
    const muted = Boolean(mic.muted);
    const pressed = String(muted);
    if (ui.muteBtn.getAttribute("aria-pressed") !== pressed) ui.muteBtn.setAttribute("aria-pressed", pressed);
    setText(ui.muteLabel, muted ? "Activar micrófono" : "Silenciar micrófono");
  }

  function renderTrivia(status) {
    const trivia = triviaInfo();
    const playing = Boolean(trivia.active);
    let text = "No hay ninguna trivia en marcha.";
    if (playing) {
      const score = `${trivia.score} acierto${trivia.score === 1 ? "" : "s"}`;
      const phase = trivia.phase === "asking" ? "esperando respuesta" : "mostrando el resultado";
      text = `Pregunta ${trivia.number} de ${trivia.total} · ${score} · ${phase}`;
    } else if (trivia.available === false) {
      text = "No hay preguntas suficientes en assets/trivia/preguntas.md.";
    } else if (trivia.total) {
      text = `Lista: ${trivia.total} preguntas, gana con ${trivia.threshold} aciertos.`;
    }
    setText(ui.triviaState, text);
    ui.triviaState.classList.toggle("is-playing", playing);
    const options = Array.isArray(trivia.options) ? trivia.options : [];
    setHidden(ui.triviaQuestion, !playing || options.length !== 3);
    setText(ui.triviaQ, trivia.question || "");
    setText(ui.triviaOptA, options[0] || "");
    setText(ui.triviaOptB, options[1] || "");
    setText(ui.triviaOptC, options[2] || "");
    setHidden(ui.triviaNote, status.mode === "conversation" || playing);
  }

  function onMuteClick() {
    const mic = (app.status && app.status.health && app.status.health.mic) || {};
    sendAction("mute", { muted: !mic.muted }, { button: ui.muteBtn });
  }

  // ------------------------------------------------------------ galería

  function logoImageId() {
    const ids = app.gallery.map((image) => image.id);
    if (ids.includes("logo-sonnet")) return "logo-sonnet";
    return ids.find((id) => /logo/i.test(id)) || null;
  }

  async function loadGallery() {
    const requested = app.instanceId;
    app.galleryState = "loading";
    app.galleryAttemptAt = Date.now();
    renderGallery();
    let gallery = [];
    let state = "error";
    try {
      const { response, data } = await apiFetch(withInstance(API_GALLERY, requested));
      if (response.ok && data) {
        const images = Array.isArray(data.images) ? data.images : [];
        // La url viene del servidor: /api/gallery/<id> en local, /gallery/<archivo> en
        // Cloudflare. Sin url (imagen que no está en Cloudflare) sale sin miniatura.
        gallery = images
          .filter((image) => image && typeof image.id === "string" && image.id)
          .map((image) => ({ id: image.id, url: typeof image.url === "string" && image.url ? image.url : "" }));
        state = "ready";
      }
    } catch {
      state = "error";
    }
    // Si mientras tanto se cambió de Sonnia, esta respuesta ya no vale.
    if (requested !== app.instanceId) return;
    app.gallery = gallery;
    app.galleryState = state;
    renderGallery();
    refreshControls();
  }

  function missingThumb() {
    return el("span", { class: "thumb-missing", text: "Sin vista previa" });
  }

  function renderGallery() {
    const thumbs = ui.thumbs;
    if (app.galleryState === "loading") {
      thumbs.replaceChildren(el("p", { class: "muted", text: "Cargando imágenes…" }));
      return;
    }
    if (app.galleryState === "error") {
      const retry = el("button", { type: "button", class: "btn btn-small", text: "Reintentar" });
      retry.addEventListener("click", loadGallery);
      thumbs.replaceChildren(
        el("div", { class: "retry" }, el("p", { class: "muted", text: "No se pudieron cargar las imágenes." }), retry),
      );
      return;
    }
    if (app.gallery.length === 0) {
      thumbs.replaceChildren(
        el("p", { class: "muted", text: "No hay imágenes en la galería. Se añaden en la carpeta assets/gallery del equipo del stand." }),
      );
      return;
    }
    thumbs.replaceChildren(
      ...app.gallery.map((image) => {
        const button = el(
          "button",
          {
            type: "button",
            class: "thumb",
            "data-image-id": image.id,
            "data-cap": "images",
            "data-off-modes": "away",
            "aria-label": `Mostrar «${prettyImageName(image.id)}»`,
          },
          image.url ? thumbImage(image.url) : missingThumb(),
          el("span", { class: "thumb-name", text: prettyImageName(image.id) }),
        );
        button.addEventListener("click", () => onShowImage(image.id, button));
        return button;
      }),
    );
    if (app.status) renderImageState(app.status);
  }

  function thumbImage(url) {
    const img = el("img", { src: url, alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("error", () => img.replaceWith(missingThumb()), { once: true });
    return img;
  }

  function currentImage(status) {
    const image = status.image;
    if (!image) return null;
    if (typeof image === "string") return { id: image, caption: "" };
    if (typeof image !== "object") return null;
    const id = image.image_id || image.id || (image.source === "camera" ? "camera" : "") || "imagen";
    return { id: String(id), caption: typeof image.caption === "string" ? image.caption : "" };
  }

  function renderImageState(status) {
    const image = currentImage(status);
    let text = "No hay ninguna imagen en pantalla.";
    if (image) {
      text = image.id === "camera" ? "En pantalla ahora: una foto de la cámara" : `En pantalla ahora: «${prettyImageName(image.id)}»`;
      if (image.caption) text += `, con el texto «${image.caption}»`;
    }
    setText(ui.nowShowing, text);
    ui.nowShowing.classList.toggle("is-showing", Boolean(image));
    for (const thumb of ui.thumbs.querySelectorAll(".thumb")) {
      thumb.classList.toggle("is-current", Boolean(image) && thumb.dataset.imageId === image.id);
    }
  }

  function onShowImage(id, button) {
    const caption = ui.captionInput.value.trim();
    const params = { image_id: id };
    if (caption) params.caption = caption;
    sendAction("show_image", params, { button });
  }

  // ------------------------------------------------------------ avisos del día

  function renderNotes(status) {
    const server = typeof status.notes === "string" ? status.notes : "";
    const input = ui.notesInput;
    if (app.notesBase === null) {
      input.value = server;
      app.notesBase = server;
    } else if (input.value === app.notesBase && document.activeElement !== input && server !== app.notesBase) {
      // Sin cambios locales: se adopta lo que haya guardado otra persona.
      input.value = server;
      app.notesBase = server;
    } else if (input.value === server) {
      app.notesBase = server;
    }
    renderNotesState();
  }

  function renderNotesState() {
    const node = ui.notesState;
    if (ui.notesBtn.classList.contains("is-busy")) {
      node.dataset.state = "saving";
      setText(node, "Guardando…");
    } else if (app.notesBase !== null && ui.notesInput.value !== app.notesBase) {
      node.dataset.state = "dirty";
      setText(node, "Cambios sin guardar");
    } else {
      node.dataset.state = "saved";
      setText(node, ui.notesInput.value.trim() ? "Guardado" : "Sin avisos");
    }
  }

  async function onNotesSubmit(event) {
    event.preventDefault();
    const text = ui.notesInput.value.trim();
    const promise = sendAction("set_notes", { text }, { button: ui.notesBtn });
    renderNotesState();
    const result = await promise;
    if (result.ok) {
      ui.notesInput.value = text;
      app.notesBase = text;
    }
    renderNotesState();
  }

  // ------------------------------------------------------------ que Sonnia diga

  async function onSaySubmit(event) {
    event.preventDefault();
    const text = ui.sayInput.value.trim();
    if (!text) {
      showToast("Escribe primero lo que quieres que diga Sonia.", "info");
      ui.sayInput.focus();
      return;
    }
    const result = await sendAction("say", { text }, { button: ui.sayBtn });
    if (result.ok) ui.sayInput.value = "";
  }

  async function onAskSubmit(event) {
    event.preventDefault();
    const text = ui.askInput.value.trim();
    if (!text) {
      showToast("Escribe primero la pregunta.", "info");
      ui.askInput.focus();
      return;
    }
    const result = await sendAction("ask", { text }, { button: ui.askBtn });
    if (result.ok) ui.askInput.value = "";
  }

  // ------------------------------------------------------------ sonido

  // Mientras el operador mueve un control, el estado que llega no lo pisa.
  function lockControl(input) {
    input.lockUntil = Date.now() + CONTROL_LOCK_MS;
  }

  function isLocked(input) {
    return Boolean(input.dragging) || Date.now() < (input.lockUntil || 0);
  }

  function trackDragging(input) {
    input.addEventListener("pointerdown", () => {
      input.dragging = true;
    });
    const release = () => {
      input.dragging = false;
      lockControl(input);
    };
    input.addEventListener("pointerup", release);
    input.addEventListener("pointercancel", release);
    input.addEventListener("blur", () => {
      input.dragging = false;
    });
  }

  function renderVolumeLabel() {
    const percent = Number(ui.volumeInput.value);
    let text = `${percent} %`;
    if (percent === 100) text += " (normal)";
    else if (percent === 0) text = "Sin voz (0 %)";
    setText(ui.volumeValue, text);
  }

  function renderGateControl() {
    const gate = sliderToGate(Number(ui.gateInput.value));
    setText(ui.gateValue, describeGate(gate));
    ui.gateMeterMark.style.left = `${levelToFraction(gate) * 100}%`;
    return gate;
  }

  function renderSound(status) {
    if (isNumber(status.volume) && !isLocked(ui.volumeInput)) {
      const value = String(Math.round(status.volume * 100));
      if (ui.volumeInput.value !== value) ui.volumeInput.value = value;
    }
    renderVolumeLabel();

    if (isNumber(status.mic_gate) && !isLocked(ui.gateInput)) {
      const value = String(gateToSlider(status.mic_gate));
      if (ui.gateInput.value !== value) ui.gateInput.value = value;
    }
    const gate = renderGateControl();

    const mic = (status.health && status.health.mic) || {};
    const level = isNumber(mic.level) ? mic.level : null;
    const fill = level === null || mic.muted ? 0 : levelToFraction(level);
    ui.gateMeterFill.style.width = `${fill * 100}%`;
    ui.gateMeterFill.classList.toggle("is-below", level !== null && level < gate);
    let caption = "Micrófono: sin datos ahora mismo.";
    if (mic.muted) caption = "Micrófono silenciado: no llega sonido.";
    else if (level !== null) {
      caption = `Nivel del micrófono: ${formatNumber(level, 3)}. `;
      caption += level < gate ? "Por debajo de la raya: Sonnia no lo oye." : "Por encima de la raya: Sonnia lo oye.";
    }
    setText(ui.gateMeterCaption, caption);
  }

  // ------------------------------------------------------------ salud

  const healthRows = new Map();
  let healthKeys = "";

  function renderHealth(status) {
    const entries = healthEntries(status);
    const keys = entries.map(([key]) => key).join(",");
    if (keys !== healthKeys) {
      healthKeys = keys;
      healthRows.clear();
      const items = entries.map(([key]) => {
        const row = {
          li: el("li", { class: "health-item" }),
          icon: el("span", { class: "health-icon", "aria-hidden": "true" }),
          name: el("span", { class: "health-name", text: HEALTH_NAMES[key] || capitalize(key) }),
          label: el("span", { class: "health-label" }),
          hint: el("p", { class: "health-hint", hidden: true }),
          meter: null,
          meterFill: null,
        };
        row.li.append(row.icon, row.name, row.label, row.hint);
        if (key === "mic") {
          row.meterFill = el("div", { class: "meter-fill" });
          row.meter = el("div", { class: "meter health-meter", "aria-hidden": "true" }, row.meterFill);
          row.li.append(row.meter);
        }
        healthRows.set(key, row);
        return row.li;
      });
      if (items.length === 0) items.push(el("li", { class: "muted", text: "Sin datos de salud." }));
      ui.healthList.replaceChildren(...items);
    }

    for (const [key, item] of entries) {
      const row = healthRows.get(key);
      const ok = item.ok === true ? "true" : item.ok === false ? "false" : "null";
      if (row.li.dataset.ok !== ok) row.li.dataset.ok = ok;
      setText(row.icon, ok === "true" ? "✓" : ok === "false" ? "✕" : "–");
      let label = typeof item.label === "string" && item.label ? item.label : "";
      if (!label) label = ok === "true" ? "Bien" : ok === "false" ? "Falla" : "No aplica ahora";
      const watch = cameraWatch(status);
      if (key === "camera" && watch.live) label += ` · En directo: ${watch.viewers} mirando`;
      setText(row.label, label);
      const hint = item.ok !== true && typeof item.hint === "string" ? item.hint.trim() : "";
      setText(row.hint, hint);
      setHidden(row.hint, !hint);
      if (row.meterFill) {
        const level = isNumber(item.level) && !item.muted ? item.level : 0;
        row.meterFill.style.width = `${levelToFraction(level) * 100}%`;
        setHidden(row.meter, item.muted === true || !isNumber(item.level));
      }
    }

    const error = status.last_error;
    let errorText = "";
    if (typeof error === "string") errorText = error;
    else if (error && typeof error === "object") errorText = String(error.message || error.text || JSON.stringify(error));
    setText(ui.lastErrorText, errorText);
    setHidden(ui.lastError, !errorText);
  }

  // ------------------------------------------------------------ avanzado

  let voicesKey = "";
  let sessionKey = "";
  let usageKey = "";
  let animKey = "";

  /** Grupos del bloque de animaciones (los que manda Unity), en este orden. */
  const ANIMATION_GROUPS = [
    ["greeting", "Saludo"],
    ["dance", "Bailes"],
    ["fourth_wall", "Hacia el público"],
    ["soft", "Gestos suaves"],
    ["talking", "Gestos al hablar"],
    ["idle_variation", "En reposo"],
    ["thinking", "Pensando"],
    ["nod", "Escuchando"],
    ["present", "Señalar una imagen"],
  ];

  /** Nombres legibles de los clips conocidos (oficiales de Genies); el resto se deriva del nombre. */
  const ANIMATION_NAMES = {
    WaveGeneric: "Saludar con la mano",
    Wave: "Saludar con la mano (largo)",
    Peace: "Signo de la paz",
    QuickAction_salute: "Saludo militar",
    QuickAction_twoThumbsUp: "Pulgares arriba",
    QuickAction_vibe: "Bailar",
    "actions-presentItem_intro": "Presentar",
    "actions-0224-lookAtObject_Trimmed": "Mirar algo en la mano",
    DefaultIdle: "Reposo",
    "idles-0024-basicIdle": "Reposo atento",
    StillPose: "Quieta",
    Walk: "Caminar",
  };

  /** "Some_Clip_Name" -> "Some clip name". */
  function prettyClipName(clip) {
    if (ANIMATION_NAMES[clip]) return ANIMATION_NAMES[clip];
    return capitalize(clip.replace(/_+/g, " ").trim());
  }

  /** Fichas pintadas: clip → {item, button, toggle}, para actualizarlas sin rehacerlas. */
  const animTiles = new Map();

  /** Botones de cada animación que tiene la app de Unity, por grupos. */
  function renderAnimations(status) {
    const list = Array.isArray(status.animations)
      ? status.animations.filter((a) => a && typeof a.clip === "string" && typeof a.group === "string")
      : [];
    const supported = app.caps.has("animations");
    const toggles = app.caps.has("animation_toggles");
    const key = `${supported}|${toggles}|${JSON.stringify(list)}`;
    if (key !== animKey) {
      animKey = key;
      buildAnimationTiles(supported ? list : null, toggles);
    }
    updateAnimationTiles(status);
  }

  function buildAnimationTiles(list, toggles) {
    animTiles.clear();
    if (!list) {
      ui.animGroups.replaceChildren();
      return;
    }
    if (list.length === 0) {
      ui.animGroups.replaceChildren(
        el("p", { class: "muted", text: "La pantalla de Sonnia no ha mandado su lista de animaciones. Ábrela (o actualízala) y aparecerán aquí." }),
      );
      return;
    }
    const known = ANIMATION_GROUPS.map(([group]) => group);
    const extra = [...new Set(list.map((a) => a.group).filter((group) => !known.includes(group)))];
    const groups = [...ANIMATION_GROUPS, ...extra.map((group) => [group, capitalize(group.replace(/_+/g, " "))])];
    ui.animGroups.replaceChildren(
      ...groups
        .map(([group, label]) => {
          const clips = list.filter((a) => a.group === group);
          if (clips.length === 0) return null;
          return el("div", { class: "anim-group" }, el("h4", { text: label }), el("div", { class: "anim-row" }, ...clips.map(({ clip }) => animationTile(clip, toggles))));
        })
        .filter(Boolean),
    );
  }

  /** Una ficha: el botón que la lanza y, si el orquestador lo admite, «La usa». */
  function animationTile(clip, toggles) {
    const button = el("button", {
      type: "button",
      class: "btn btn-small anim-play",
      "data-cap": "animations",
      "data-off-modes": "away",
      "data-extra": "sonia_here",
      title: clip,
      text: prettyClipName(clip),
    });
    button.addEventListener("click", () => sendAction("animation", { clip }, { button }));
    const item = el("div", { class: "anim-item" }, button);
    let toggle = null;
    if (toggles) {
      toggle = el("input", { type: "checkbox", "data-cap": "animation_toggles", "aria-label": `Sonnia usa «${prettyClipName(clip)}» por su cuenta` });
      toggle.checked = true;
      toggle.addEventListener("change", () => onAnimationToggle(clip, toggle));
      item.append(el("label", { class: "anim-toggle" }, toggle, el("span", { text: "La usa" })));
    }
    animTiles.set(clip, { item, button, toggle });
    return item;
  }

  /** Marca la que está sonando y las que Sonnia no usa por su cuenta. */
  function updateAnimationTiles(status) {
    const disabled = new Set(Array.isArray(status.disabled_animations) ? status.disabled_animations : []);
    const playing = typeof status.current_animation === "string" ? status.current_animation : null;
    for (const [clip, tile] of animTiles) {
      const off = disabled.has(clip);
      const isPlaying = clip === playing;
      if (tile.item.classList.contains("is-off") !== off) tile.item.classList.toggle("is-off", off);
      if (tile.item.classList.contains("is-playing") !== isPlaying) tile.item.classList.toggle("is-playing", isPlaying);
      if (tile.toggle && !isLocked(tile.toggle) && tile.toggle.checked === off) tile.toggle.checked = !off;
    }
  }

  async function onAnimationToggle(clip, input) {
    const enabled = input.checked;
    lockControl(input);
    const tile = animTiles.get(clip);
    if (tile) tile.item.classList.toggle("is-off", !enabled);
    const result = await sendAction("set_animation_enabled", { clip, enabled }, { button: input });
    if (!result.ok) {
      input.checked = !enabled;
      if (tile) tile.item.classList.toggle("is-off", enabled);
    }
    lockControl(input);
  }

  function renderAdvanced(status) {
    // Voz
    const voices = Array.isArray(status.voices) ? status.voices.filter((v) => typeof v === "string") : [];
    if (status.voice && !voices.includes(status.voice)) voices.unshift(status.voice);
    const key = `${voices.join(",")}|${status.voice}`;
    if (key !== voicesKey) {
      voicesKey = key;
      const keep = ui.voiceSelect.dirty ? ui.voiceSelect.value : status.voice;
      ui.voiceSelect.replaceChildren(
        ...voices.map((voice) =>
          el("option", { value: voice, text: voice === status.voice ? `${capitalize(voice)} (la de ahora)` : capitalize(voice) }),
        ),
      );
      if (keep && voices.includes(keep)) ui.voiceSelect.value = keep;
    }
    if (!ui.voiceSelect.dirty && document.activeElement !== ui.voiceSelect && status.voice) {
      if (ui.voiceSelect.value !== status.voice) ui.voiceSelect.value = status.voice;
    }

    // Interruptores
    if (!isLocked(ui.showcaseInput)) ui.showcaseInput.checked = Boolean(status.showcase && status.showcase.enabled);
    if (!isLocked(ui.debugInput)) ui.debugInput.checked = status.debug === true;
    if (!isLocked(ui.subtitlesInput)) ui.subtitlesInput.checked = status.subtitles !== false;

    renderAnimations(status);

    // Caché de voces
    const cache = status.voice_cache;
    if (cache && isNumber(cache.ready) && isNumber(cache.total)) {
      ui.cacheProgress.max = Math.max(cache.total, 1);
      ui.cacheProgress.value = Math.min(cache.ready, cache.total);
      let text = `${cache.ready} de ${cache.total} frases listas`;
      if (cache.busy) text = `Grabando… ${text}`;
      else if (cache.total > 0 && cache.ready >= cache.total) text = `Las ${cache.total} frases están listas`;
      setText(ui.cacheText, text);
      setText(ui.cacheBtn, cache.busy ? "Grabando…" : "Preparar voces");
    } else {
      setText(ui.cacheText, "Sin datos");
    }
    const cacheError = cache && typeof cache.error === "string" ? cache.error.trim() : "";
    setText(ui.cacheError, cacheError ? `Último fallo al grabar: ${cacheError}` : "");
    setHidden(ui.cacheError, !cacheError);

    // Sesión
    const session = status.session && typeof status.session === "object" ? status.session : null;
    const sessionFacts = [["Motor de voz", ENGINE_NAMES[status.engine] || status.engine || "—"]];
    if (session) {
      if (session.id) sessionFacts.push(["Sesión", String(session.id)]);
      sessionFacts.push(["Abierta hace", formatDuration(session.uptime_s)]);
      if (isNumber(session.expires_in_s)) sessionFacts.push(["Se renueva en", formatDuration(session.expires_in_s)]);
      if (isNumber(session.context_ratio)) {
        sessionFacts.push(["Memoria usada", `${Math.round(clamp(session.context_ratio, 0, 1) * 100)} %`]);
      }
    } else {
      sessionFacts.push(["Sesión", "Ninguna abierta"]);
    }
    sessionKey = renderFacts(ui.sessionFacts, sessionFacts, sessionKey);

    // Gasto
    const usage = status.usage && typeof status.usage === "object" ? status.usage : {};
    const usageFacts = [
      ["Tiempo conversando", isNumber(usage.live_seconds) ? `${formatNumber(usage.live_seconds / 60, 1)} min` : "—"],
      ["Gasto aproximado", isNumber(usage.cost_usd) ? `${formatNumber(usage.cost_usd, 2)} USD` : "—"],
    ];
    usageKey = renderFacts(ui.usageFacts, usageFacts, usageKey);
  }

  /** Pinta una lista de datos solo si ha cambiado. Devuelve la nueva clave. */
  function renderFacts(list, facts, previousKey) {
    const key = JSON.stringify(facts);
    if (key === previousKey) return previousKey;
    list.replaceChildren(...facts.flatMap(([term, value]) => [el("dt", { text: term }), el("dd", { text: value })]));
    return key;
  }

  // ------------------------------------------------------------ Developer

  /** Pinta los deslizadores de Developer a partir de TUNING_SPEC (una vez, al arrancar). */
  function buildTuning() {
    const lists = { mouth: ui.tuneMouth, camera: ui.tuneCamera, idle: ui.tuneIdle };
    for (const [group, specs] of Object.entries(TUNING_SPEC)) {
      if (lists[group]) lists[group].replaceChildren(...specs.map((spec) => tuningControl(group, spec)));
    }
    ui.tuningInputs = Array.from(document.querySelectorAll("input[data-tune-group]"));
  }

  function tuningControl(group, spec) {
    const id = `tune-${group}-${spec.key}`;
    const input = el("input", {
      type: "range",
      id,
      min: String(spec.min),
      max: String(spec.max),
      step: String(spec.step),
      value: String(spec.def),
      "data-cap": "tuning",
      "data-tune-group": group,
      "data-tune-key": spec.key,
    });
    input.spec = spec;
    const label = el("label", { class: "control-label", text: spec.label });
    label.htmlFor = id;
    const output = el("output", { class: "control-value", id: `${id}-value`, text: formatTuning(spec, spec.def) });
    output.setAttribute("for", id);
    input.output = output;
    return el(
      "div",
      { class: "control" },
      el("div", { class: "control-head" }, label, output),
      input,
      el("div", { class: "scale" }, el("span", { text: spec.ends[0] }), el("span", { text: spec.ends[1] })),
    );
  }

  function formatTuning(spec, value) {
    let text;
    if (spec.unit === "%") text = `${Math.round(value * 100)} %`;
    else if (spec.unit === "cm") text = `${value > 0 ? "+" : ""}${Math.round(value * 100)} cm`;
    else text = `${value > 0 ? "+" : ""}${formatNumber(value, 1)}°`;
    return Math.abs(value - spec.def) < spec.step / 2 ? `${text} (normal)` : text;
  }

  function renderTuningLabel(input) {
    setText(input.output, formatTuning(input.spec, Number(input.value)));
  }

  function renderTuning(status) {
    const tuning = status.tuning && typeof status.tuning === "object" ? status.tuning : {};
    for (const input of ui.tuningInputs) {
      const group = tuning[input.dataset.tuneGroup];
      const value = group && isNumber(group[input.dataset.tuneKey]) ? group[input.dataset.tuneKey] : null;
      if (value !== null && !isLocked(input) && Number(input.value) !== value) input.value = String(value);
      renderTuningLabel(input);
    }
  }

  /** Mientras se arrastra, manda el valor como mucho cada TUNING_SEND_MS para verlo en directo. */
  function queueTuning(input) {
    if (input.sendTimer) return;
    const wait = Math.max(0, TUNING_SEND_MS - (Date.now() - (input.sentAt || 0)));
    input.sendTimer = setTimeout(() => sendTuning(input), wait);
  }

  /** Un envío a la vez por deslizador: así el último valor siempre llega el último. */
  async function sendTuning(input) {
    clearTimeout(input.sendTimer);
    input.sendTimer = null;
    if (input.inFlight) return;
    const value = Number(input.value);
    input.inFlight = true;
    input.sentAt = Date.now();
    lockControl(input);
    try {
      await sendAction("set_tuning", { [input.dataset.tuneGroup]: { [input.dataset.tuneKey]: value } }, { quiet: true });
    } finally {
      input.inFlight = false;
      lockControl(input);
    }
    if (Number(input.value) !== value) sendTuning(input);
  }

  async function onResetTuning(button) {
    const part = button.dataset.resetTuning;
    const result = await sendAction("reset_tuning", { part }, { button });
    if (!result.ok) return;
    for (const input of ui.tuningInputs) {
      if (input.dataset.tuneGroup !== part) continue;
      input.lockUntil = 0;
      input.value = String(input.spec.def);
      renderTuningLabel(input);
    }
  }

  function renderAvatar() {
    const avatar = avatarInfo();
    const editingGuest = Boolean(avatar.editor_open) && avatar.editor_target === "guest";
    const editingSonia = Boolean(avatar.editor_open) && !editingGuest;
    let text = avatar.custom ? "Sonnia: personaje propio, guardado en la nube." : "Sonnia: personaje de la app.";
    if (editingSonia) text = "Editando el personaje de Sonnia en su pantalla…";
    setAvatarState(ui.avatarState, text, editingSonia);
    let guestText = guestAvatarInfo().custom
      ? "Jean: personaje propio, guardado en la nube."
      : "Jean: avatar de prueba de la app.";
    if (editingGuest) guestText = "Editando el personaje de Jean en la pantalla de Sonnia…";
    setAvatarState(ui.guestAvatarState, guestText, editingGuest);
    setHidden(ui.guestAvatarState, !hasCap("guest_avatar_editor"));
  }

  /** «Ver cámara» y el Modo Jean: ¿sale la cámara del stand ahora? (`camera_watch` del estado). */
  function cameraWatch(status) {
    const watch = status && status.camera_watch;
    if (!watch || typeof watch !== "object") return { live: false, viewers: 0 };
    return { live: watch.live === true, viewers: isNumber(watch.viewers) ? watch.viewers : 0 };
  }

  function renderCameraLive(status) {
    const watch = cameraWatch(status);
    const live = watch.live && selectedConnected();
    setHidden(ui.topbarLive, !live);
    document.body.classList.toggle("camera-live", live);
    if (!live) return;
    const text = `Cámara en directo: ${watch.viewers} mirando`;
    setText(ui.topbarLiveText, text);
    setText(ui.topbarLiveShort, String(watch.viewers));
    if (ui.topbarLive.title !== text) {
      ui.topbarLive.title = text;
      ui.topbarLive.setAttribute("aria-label", text);
    }
  }

  function setAvatarState(node, text, editing) {
    setText(node, text);
    const state = editing ? "editing" : "idle";
    if (node.dataset.state !== state) node.dataset.state = state;
  }

  async function onResetAvatar() {
    const ok = await confirmAction({
      title: "¿Volver al personaje de la app?",
      text: "Sonnia dejará el aspecto guardado en el editor, en todas las Sonnias.",
      confirmLabel: "Sí, volver",
    });
    if (ok) await sendAction("reset_avatar", {}, { button: ui.avatarResetBtn });
  }

  async function onResetGuestAvatar() {
    const ok = await confirmAction({
      title: "¿Volver al avatar de prueba de Jean?",
      text: "El avatar de Jean del Modo Jean dejará el aspecto guardado en el editor, en todas las Sonnias.",
      confirmLabel: "Sí, volver",
    });
    if (ok) await sendAction("reset_avatar", { target: "guest" }, { button: ui.guestAvatarResetBtn });
  }

  // ------------------------------------------------------------ ajustes en la nube

  /** Frase sobre dónde quedan guardados los ajustes (`settings_sync` del estado). */
  function syncNote(sync) {
    if (!sync || typeof sync !== "object") return null;
    const pending = Array.isArray(sync.pending) ? sync.pending.length : 0;
    if (sync.cloud === "off") {
      return {
        state: "info",
        text: "Esta Sonnia no está conectada a la nube (le falta PANEL_CLOUD_TOKEN): los ajustes se guardan solo en su equipo.",
      };
    }
    if (sync.cloud === "offline") {
      const what = pending === 1 ? "1 ajuste guardado" : `${pending} ajustes guardados`;
      return {
        state: "warn",
        text: pending
          ? `Sin conexión con la nube: ${what} en el equipo de Sonnia, se subirán al volver.`
          : "Sin conexión con la nube: lo que cambies se guarda en el equipo de Sonnia y se sube al volver.",
      };
    }
    if (pending) return { state: "info", text: "Guardando en la nube…" };
    if (!sync.synced) return { state: "info", text: "Conectando con la nube…" };
    return { state: "ok", text: "Ajustes guardados en la nube: valen para todas las Sonnias." };
  }

  function renderSyncNotes(status) {
    const note = app.caps.has("cloud_settings") ? syncNote(status.settings_sync) : null;
    for (const node of ui.syncNotes) {
      setHidden(node, !note);
      if (!note) continue;
      setText(node, note.text);
      if (node.dataset.state !== note.state) node.dataset.state = note.state;
    }
  }

  async function onVoiceChange() {
    const voice = ui.voiceSelect.value;
    if (!voice) return;
    const ok = await confirmAction({
      title: `¿Cambiar a la voz ${capitalize(voice)}?`,
      text: "Sonnia empezará una conversación nueva y olvidará lo que estaba hablando.",
      confirmLabel: "Sí, cambiar la voz",
    });
    if (!ok) return;
    const result = await sendAction("set_voice", { voice }, { button: ui.voiceBtn });
    if (result.ok) ui.voiceSelect.dirty = false;
  }

  async function onShowcaseChange() {
    const input = ui.showcaseInput;
    const enabled = input.checked;
    lockControl(input);
    const result = await sendAction("showcase", { enabled }, { button: input });
    if (!result.ok) input.checked = !enabled;
    lockControl(input);
  }

  /** Interruptor sencillo: manda la acción y, si falla, vuelve a como estaba. */
  async function onSwitchChange(input, action) {
    const enabled = input.checked;
    lockControl(input);
    const result = await sendAction(action, { enabled }, { button: input });
    if (!result.ok) input.checked = !enabled;
    lockControl(input);
  }

  async function onRestart() {
    const ok = await confirmAction({
      title: "¿Empezar una conversación nueva?",
      text: "Sonnia olvidará todo lo que se ha hablado hasta ahora.",
      confirmLabel: "Sí, empezar de cero",
    });
    if (ok) sendAction("restart", {}, { button: ui.restartBtn });
  }

  // ------------------------------------------------------------ conversación en vivo

  const chat = {
    lines: [],
    open: { user: null, assistant: null }, // última línea de cada hablante que sigue creciendo
    ambient: null, // frase de la animación de stand en curso
    ambientUid: null,
  };

  function chatIsNearBottom() {
    const box = ui.chat;
    return box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  }

  function chatScrollToBottom() {
    ui.chat.scrollTop = ui.chat.scrollHeight;
  }

  function appendChatNode(line) {
    const stick = chatIsNearBottom();
    chat.lines.push(line);
    ui.chat.append(line.node);
    while (chat.lines.length > MAX_CHAT_LINES) {
      const old = chat.lines.shift();
      old.node.remove();
      if (chat.open.user === old) chat.open.user = null;
      if (chat.open.assistant === old) chat.open.assistant = null;
      if (chat.ambient === old) chat.ambient = null;
    }
    setHidden(ui.chatEmpty, true);
    if (stick) chatScrollToBottom();
  }

  function speakerName(line) {
    if (line.role === "user") return "Visitante";
    return line.ambient ? "Sonnia (sola)" : "Sonnia";
  }

  function addSpeechLine({ role, text, final, ambient = false, time = "" }) {
    const line = { role, text, final, ambient, updatedAt: Date.now() };
    line.textNode = el("span", { class: "line-text" });
    line.node = el("div", { class: `line line--${role}${ambient ? " line--ambient" : ""}` });
    const who = el("span", { class: "line-who" }, el("span", { class: "line-name", text: speakerName(line) }));
    if (shortTime(time)) who.append(el("span", { class: "line-time", text: shortTime(time) }));
    line.node.append(who, line.textNode);
    paintSpeechLine(line);
    appendChatNode(line);
    return line;
  }

  function paintSpeechLine(line) {
    const stick = chatIsNearBottom();
    setText(line.textNode, line.text || "…");
    line.node.classList.toggle("is-partial", !line.final);
    if (stick) chatScrollToBottom();
  }

  function addSystemLine(text, kind = "", time = "") {
    const label = shortTime(time) ? `${shortTime(time)} · ${text}` : text;
    const line = { role: "system", node: el("div", { class: `line line--system${kind ? ` line--${kind}` : ""}`, text: label }) };
    appendChatNode(line);
  }

  function removeChatLine(line) {
    const index = chat.lines.indexOf(line);
    if (index >= 0) chat.lines.splice(index, 1);
    line.node.remove();
    setHidden(ui.chatEmpty, chat.lines.length > 0);
  }

  function onTranscript(message) {
    const role = message.role === "user" ? "user" : "assistant";
    const text = typeof message.text === "string" ? message.text.trim() : "";
    const final = message.final !== false;
    let line = role === "assistant" && chat.ambient ? chat.ambient : chat.open[role];

    // Una línea que lleva mucho sin crecer se da por terminada (turno descartado).
    if (line && line !== chat.ambient && Date.now() - line.updatedAt > PARTIAL_LINE_STALE_MS) {
      line.final = true;
      paintSpeechLine(line);
      chat.open[role] = null;
      line = null;
    }

    if (line) {
      if (text) line.text = text;
      line.updatedAt = Date.now();
      if (final) {
        line.final = true;
        if (line === chat.ambient) chat.ambient = null;
        else chat.open[role] = null;
      }
      paintSpeechLine(line);
    } else if (text) {
      line = addSpeechLine({ role, text, final, time: message.time });
      if (!final) chat.open[role] = line;
    }
  }

  function onSpeechStart(message) {
    // Solo interesan las frases de la animación de stand: el resto llega como transcript.
    if (!message.ambient) return;
    closeAmbient();
    const text = typeof message.text === "string" ? message.text.trim() : "";
    // Algunos motores mandan el transcript de la frase justo antes de su
    // speech_start: esa línea se convierte en la de "Sonnia (sola)" en vez de repetirla.
    const last = chat.lines[chat.lines.length - 1];
    if (
      last && last.role === "assistant" && !last.ambient && text && last.text === text &&
      Date.now() - last.updatedAt < 3000
    ) {
      last.ambient = true;
      last.node.classList.add("line--ambient");
      setText(last.node.querySelector(".line-name"), speakerName(last));
      paintSpeechLine(last);
      return;
    }
    chat.ambient = addSpeechLine({ role: "assistant", text, final: false, ambient: true, time: message.time });
    chat.ambientUid = message.utterance_id;
  }

  function closeAmbient() {
    const line = chat.ambient;
    chat.ambient = null;
    chat.ambientUid = null;
    if (!line) return;
    if (!line.text) removeChatLine(line);
    else {
      line.final = true;
      paintSpeechLine(line);
    }
  }

  /** Sonnia se calla: lo que estuviera diciendo queda cerrado tal cual. */
  function closeSoniaLines() {
    const line = chat.open.assistant;
    if (line) {
      line.final = true;
      paintSpeechLine(line);
      chat.open.assistant = null;
    }
    closeAmbient();
  }

  /** Mensajes que el orquestador manda a Unity: se usan para la conversación en vivo. */
  function handleOrchestratorMessage(message, live) {
    if (!message || typeof message !== "object") return;
    switch (message.type) {
      case "transcript":
        onTranscript(message);
        break;
      case "speech_start":
        onSpeechStart(message);
        break;
      case "speech_end":
        if (chat.ambient && message.utterance_id === chat.ambientUid) closeAmbient();
        break;
      case "stop_speaking":
        closeSoniaLines();
        addSystemLine("Sonnia se calló", "", message.time);
        break;
      case "show_image": {
        const id = message.image_id || (message.source === "camera" ? "camera" : "");
        addSystemLine(
          id === "camera" ? "En pantalla: una foto de la cámara" : `En pantalla: «${prettyImageName(id || "imagen")}»`,
          "",
          message.time,
        );
        break;
      }
      case "hide_image":
        addSystemLine("Imagen retirada de la pantalla", "", message.time);
        break;
      case "presence":
        if (app.lastPresence !== null && app.lastPresence !== message.present) {
          addSystemLine(message.present ? "Sonnia volvió a la pantalla" : "Sonnia salió de la pantalla", "", message.time);
        }
        app.lastPresence = Boolean(message.present);
        break;
      case "error":
        addSystemLine(`Error: ${message.message || "sin detalles"}`, "error", message.time);
        break;
      case "state":
        // Cambia la actividad al momento, sin esperar al siguiente estado completo.
        if (live && app.status && STATE_TEXT[message.state] && app.status.state !== message.state) {
          app.status.state = message.state;
          renderHero(app.status);
          renderTopbar();
        }
        break;
      default:
        break;
    }
  }

  function resetChat() {
    for (const line of chat.lines) line.node.remove();
    chat.lines = [];
    chat.open = { user: null, assistant: null };
    chat.ambient = null;
    chat.ambientUid = null;
    setHidden(ui.chatEmpty, false);
  }

  /** Al conectar llega lo último de la conversación y del registro: se repinta desde cero. */
  function applyHistory(data) {
    resetChat();
    ui.log.replaceChildren();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    for (const item of messages) {
      const message = item && item.type === "message" && item.message ? item.message : item;
      handleOrchestratorMessage(message, false);
    }
    const logs = Array.isArray(data.logs) ? data.logs : [];
    for (const entry of logs) appendLog(entry);
    chatScrollToBottom();
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  // ------------------------------------------------------------ registro

  function appendLog(entry) {
    const data = typeof entry === "string" ? { text: entry } : entry || {};
    const level = String(data.level || "INFO").toUpperCase();
    const box = ui.log;
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const line = el("p", { class: "log-line", "data-level": level });
    if (data.time) line.append(el("span", { class: "log-time", text: `${data.time} ` }));
    if (LOG_LEVELS[level]) line.append(`[${LOG_LEVELS[level]}] `);
    line.append(String(data.text ?? data.message ?? ""));
    box.append(line);
    while (box.childElementCount > MAX_LOG_LINES) box.firstElementChild.remove();
    if (stick) box.scrollTop = box.scrollHeight;
  }

  // ------------------------------------------------------------ eventos de la página

  function bindEvents() {
    ui.reloadBtn.addEventListener("click", () => location.reload());
    ui.keepOneBtn.addEventListener("click", onKeepOne);

    for (const button of ui.modeButtons) button.addEventListener("click", () => onModeClick(button));
    ui.editSignBtn.addEventListener("click", onEditSign);

    ui.stopBtn.addEventListener("click", () => sendAction("stop", {}, { button: ui.stopBtn }));
    ui.greetBtn.addEventListener("click", () => sendAction("greet", {}, { button: ui.greetBtn }));
    ui.triviaStartBtn.addEventListener("click", () =>
      sendAction("trivia_start", {}, { button: ui.triviaStartBtn }),
    );
    ui.triviaRestartBtn.addEventListener("click", () =>
      sendAction("trivia_restart", {}, { button: ui.triviaRestartBtn }),
    );
    ui.triviaStopBtn.addEventListener("click", () =>
      sendAction("trivia_stop", {}, { button: ui.triviaStopBtn }),
    );
    for (const button of ui.triviaAnswerButtons) {
      button.addEventListener("click", () =>
        sendAction("trivia_answer", { option: button.dataset.triviaAnswer }, { button }),
      );
    }
    ui.danceBtn.addEventListener("click", () => sendAction("gesture", { category: "dance" }, { button: ui.danceBtn }));
    ui.logoBtn.addEventListener("click", () =>
      sendAction("show_image", { image_id: logoImageId() || "logo-sonnet" }, { button: ui.logoBtn }),
    );
    ui.hideBtn.addEventListener("click", () => sendAction("hide_image", {}, { button: ui.hideBtn }));
    ui.muteBtn.addEventListener("click", onMuteClick);

    ui.sayForm.addEventListener("submit", onSaySubmit);
    // Ctrl/Cmd + Enter también envía desde la caja de texto.
    ui.sayInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        ui.sayForm.requestSubmit();
      }
    });

    ui.notesForm.addEventListener("submit", onNotesSubmit);
    ui.notesInput.addEventListener("input", renderNotesState);

    trackDragging(ui.volumeInput);
    ui.volumeInput.addEventListener("input", () => {
      lockControl(ui.volumeInput);
      renderVolumeLabel();
    });
    ui.volumeInput.addEventListener("change", () => {
      lockControl(ui.volumeInput);
      const value = Math.round(Number(ui.volumeInput.value)) / 100;
      sendAction("set_volume", { value }, { button: null });
    });

    trackDragging(ui.gateInput);
    ui.gateInput.addEventListener("input", () => {
      lockControl(ui.gateInput);
      renderGateControl();
    });
    ui.gateInput.addEventListener("change", () => {
      lockControl(ui.gateInput);
      const value = sliderToGate(Number(ui.gateInput.value));
      sendAction("set_mic_gate", { value }, { button: null });
    });

    ui.voiceSelect.addEventListener("change", () => {
      ui.voiceSelect.dirty = ui.voiceSelect.value !== (app.status && app.status.voice);
      refreshControls();
    });
    ui.voiceBtn.addEventListener("click", onVoiceChange);
    ui.showcaseInput.addEventListener("change", onShowcaseChange);
    ui.debugInput.addEventListener("change", () => onSwitchChange(ui.debugInput, "set_debug"));
    ui.subtitlesInput.addEventListener("change", () => onSwitchChange(ui.subtitlesInput, "set_subtitles"));
    for (const button of ui.gestureButtons) {
      button.addEventListener("click", () => sendAction("gesture", { category: button.dataset.gesture }, { button }));
    }
    for (const input of ui.tuningInputs) {
      trackDragging(input);
      input.addEventListener("input", () => {
        lockControl(input);
        renderTuningLabel(input);
        queueTuning(input);
      });
      input.addEventListener("change", () => {
        lockControl(input);
        sendTuning(input);
      });
    }
    for (const button of ui.resetTuningButtons) button.addEventListener("click", () => onResetTuning(button));
    ui.avatarEditBtn.addEventListener("click", () => sendAction("open_avatar_editor", {}, { button: ui.avatarEditBtn }));
    ui.avatarCloseBtn.addEventListener("click", () => sendAction("close_avatar_editor", {}, { button: ui.avatarCloseBtn }));
    ui.avatarResetBtn.addEventListener("click", onResetAvatar);
    ui.guestAvatarEditBtn.addEventListener("click", () =>
      sendAction("open_avatar_editor", { target: "guest" }, { button: ui.guestAvatarEditBtn }),
    );
    ui.guestAvatarResetBtn.addEventListener("click", onResetGuestAvatar);
    ui.askForm.addEventListener("submit", onAskSubmit);
    ui.restartBtn.addEventListener("click", onRestart);
    ui.cacheBtn.addEventListener("click", () => sendAction("prepare_voices", {}, { button: ui.cacheBtn }));

    // Al volver a la pestaña o recuperar la red, reconecta sin esperar al reintento.
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && !app.wsLive) reconnectNow();
    });
    window.addEventListener("online", () => {
      if (!app.wsLive) reconnectNow();
    });
  }

  async function init() {
    collectElements();
    buildTuning();
    bindEvents();
    renderVolumeLabel();
    renderGateControl();
    refreshControls();
    setInterval(watchdog, 1000);
    // Primero la lista de Sonnias, para abrir el WebSocket ya con la elegida
    // (sin esperar más de unos segundos: si falla, se sigue igual).
    await fetchInstances({ timeout: INSTANCES_TIMEOUT_MS });
    app.started = true;
    connectWs();
    startPolling();
    loadGallery();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
