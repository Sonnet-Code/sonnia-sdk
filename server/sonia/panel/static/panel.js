/*
 * Sonnia control panel: page logic.
 *
 * No dependencies and no build step. The orchestrator serves this page locally
 * and it controls a single Sonnia. API:
 *   GET  /api/status     full status snapshot
 *   GET  /api/gallery    images Sonnia can show
 *   POST /api/action     actions (header X-Sonia-Panel: 1, JSON body {"action", ...params})
 *   WS   /api/events     history on connect, then status, messages for the avatar
 *                        client and log lines
 *
 * If the WebSocket drops, it is retried with a growing delay and meanwhile
 * /api/status is polled so the page does not freeze.
 */
"use strict";

(() => {
  // ------------------------------------------------------------ constants

  const API_STATUS = "/api/status";
  const API_GALLERY = "/api/gallery";
  const API_ACTION = "/api/action";
  const API_EVENTS = "/api/events";

  const MIC_GATE_MAX = 0.2;
  const GATE_SLIDER_MAX = 1000;

  const STATUS_STALE_MS = 8000; // nothing on the WebSocket for this long: reconnect
  const WS_CONNECT_TIMEOUT_MS = 10000;
  const POLL_INTERVAL_MS = 3000; // /api/status polling while there is no WebSocket
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 15000;
  const STARTUP_GRACE_MS = 4000; // do not raise alarms while the page starts
  const ACTION_TIMEOUT_MS = 15000;
  const CONTROL_LOCK_MS = 2500; // after touching a control, the server status does not overwrite it
  const PARTIAL_LINE_STALE_MS = 20000;
  const MAX_CHAT_LINES = 200;
  const MAX_LOG_LINES = 400;
  const MAX_DEV_LOG_LINES = 500; // as many as the orchestrator keeps (LogBuffer)
  const MAX_TOASTS = 3;
  const TUNING_SEND_MS = 150; // a Developer slider sends at most this often

  // "Developer" settings. Same limits as TUNING_LIMITS in control.py: mouth and
  // motion as multipliers of what the scene brings, and the camera relative to
  // its base shot.
  const TUNING_SPEC = {
    mouth: [
      { key: "open", label: "Mouth opening", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Closed", "Wide open"] },
      { key: "jaw", label: "Jaw on stressed syllables", min: 0, max: 3, step: 0.1, def: 1, unit: "%", ends: ["None", "A lot"] },
      { key: "closure", label: "Lip closure (p, b, m)", min: 0, max: 1.5, step: 0.05, def: 1, unit: "%", ends: ["No closure", "Very marked"] },
      { key: "speed", label: "Mouth speed", min: 0.5, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Soft", "Crisp"] },
    ],
    camera: [
      { key: "zoom", label: "Zoom", min: 0.5, max: 2, step: 0.05, def: 1, unit: "%", ends: ["Farther", "Closer"] },
      { key: "height", label: "Height", min: -0.5, max: 0.5, step: 0.01, def: 0, unit: "cm", ends: ["Lower", "Higher"] },
      { key: "distance", label: "Distance", min: -0.6, max: 1, step: 0.02, def: 0, unit: "cm", ends: ["Closer", "Farther"] },
      { key: "side", label: "Side", min: -0.4, max: 0.4, step: 0.01, def: 0, unit: "cm", ends: ["Left", "Right"] },
      { key: "tilt", label: "Tilt", min: -15, max: 15, step: 0.5, def: 0, unit: "°", ends: ["Looks up", "Looks down"] },
    ],
    idle: [
      { key: "breath", label: "Breathing", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["No breathing", "Very marked"] },
      { key: "accents", label: "Accents while speaking", min: 0, max: 2, step: 0.05, def: 1, unit: "%", ends: ["No accents", "Very marked"] },
      { key: "speed", label: "Idle pace", min: 0.5, max: 1.5, step: 0.05, def: 1, unit: "%", ends: ["Slower", "Faster"] },
    ],
  };

  const MODES = {
    conversation: { short: "Conversing", sentence: "Sonnia is conversing", already: "Sonnia is already conversing." },
    greeter: { short: "Greeter only", sentence: "Sonnia only greets", already: "Sonnia is already in “Greeter only”." },
    away: { short: "Away", sentence: "Sonnia is away", already: "Sonnia is already away." },
  };

  const STATE_TEXT = {
    idle: "Waiting for someone to talk to her",
    listening: "Listening",
    thinking: "Thinking what to say",
    speaking: "Speaking",
  };

  const STATE_SHORT = {
    idle: "Waiting",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
  };

  const HEALTH_ORDER = ["internet", "screen", "mic", "camera"];
  const HEALTH_NAMES = { internet: "Internet", screen: "Screen", mic: "Microphone", camera: "Camera" };
  const LOG_LEVELS = { DEBUG: "debug", WARNING: "warning", ERROR: "error", CRITICAL: "critical" };
  const PROBLEM_LEVELS = new Set(["WARNING", "ERROR", "CRITICAL"]);

  // How numbers are shown.
  const LOCALE = "en-US";

  // ------------------------------------------------------------ utilities

  const byId = (id) => document.getElementById(id);

  /** Creates an element with simple properties and attributes. Never uses innerHTML. */
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

  /** Changes the text only if it differs, so the DOM is not touched twice a second for nothing. */
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
    if (seconds < 60) return "less than 1 min";
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

  /** What the ids of the images uploaded from the panel (the ones with "×") start with.
   * Same as `UPLOAD_PREFIX` in `server/sonia/actions/gallery.py`. */
  const UPLOAD_PREFIX = "upload-";

  /** "upload-team-photo-0731" -> "Team photo 0731". */
  function prettyImageName(id) {
    let name = String(id);
    if (name.startsWith(UPLOAD_PREFIX) && name.length > UPLOAD_PREFIX.length) name = name.slice(UPLOAD_PREFIX.length);
    return capitalize(name.replace(/[-_]+/g, " ").trim());
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  /** "12:03:04" -> "12:03". */
  function shortTime(time) {
    return typeof time === "string" ? time.slice(0, 5) : "";
  }

  // The noise control and the meter use a square-root scale: voice levels are
  // small (0.01-0.1) and would not be visible on a linear scale.
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
    if (gate <= 0) return "Off";
    let word = "High";
    if (gate < 0.015) word = "Low";
    else if (gate < 0.05) word = "Medium";
    return `${word} (${formatNumber(gate, 3)})`;
  }

  // ------------------------------------------------------------ page state

  const app = {
    status: null,
    caps: new Set(),
    capsKnown: false,
    lastContactAt: 0, // last answer from the panel (WebSocket or HTTP)
    lastWsMessageAt: 0,
    startedAt: Date.now(),
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
    gallery: [],
    galleryState: "loading", // loading | ready | error
    galleryAttemptAt: 0,
    gallerySig: "", // ids of `status.gallery` already drawn
    galleryPreviews: new Map(), // id -> local preview of what this browser uploaded
    pendingUpload: null, // image picked and already reduced, waiting for "Upload to the gallery"
    notesBase: null, // last notes text that came from the server and is in the box
    lastPresence: null,
  };

  // References to the fixed elements of the page.
  const ui = {};

  function collectElements() {
    const ids = [
      "topbar-status", "topbar-text", "topbar-state", "offline-banner", "offline-detail", "slow-banner",
      "hero", "hero-mode", "hero-activity", "activity-dot", "hero-health", "hero-muted", "hero-debug",
      "away-sign", "away-sign-text", "edit-sign-btn", "stop-btn", "greet-btn", "dance-btn",
      "hide-btn", "mute-btn", "mute-label", "now-showing", "thumbs", "caption-input", "say-form",
      "say-input", "say-btn", "notes-form", "notes-input", "notes-btn", "notes-state", "volume-input",
      "volume-value", "gate-input", "gate-value", "gate-meter-fill", "gate-meter-mark",
      "gate-meter-caption", "health-list", "last-error", "last-error-text", "chat", "chat-empty",
      "voice-select", "voice-btn", "showcase-input", "anim-groups", "anim-count", "debug-input", "subtitles-input",
      "ask-form", "ask-input", "ask-btn", "tune-mouth", "tune-camera", "tune-idle",
      "avatar-state", "avatar-input", "avatar-save-btn", "avatar-default-btn",
      "restart-btn", "cache-progress", "cache-text", "cache-error", "cache-btn", "session-facts", "usage-facts", "log",
      "dev-log", "dev-log-copy-btn", "dev-log-count",
      "toasts", "confirm-dialog", "confirm-title", "confirm-text", "confirm-ok", "away-dialog",
      "away-title", "away-help", "away-text", "away-ok",
      "trivia-state", "trivia-question", "trivia-q", "trivia-opt-a", "trivia-opt-b", "trivia-opt-c",
      "trivia-start-btn", "trivia-restart-btn", "trivia-stop-btn", "trivia-note", "trivia-next-btn", "trivia-level",
      "trivia-bank-info",
      "gallery-add-btn", "gallery-file", "gallery-upload", "gallery-upload-preview", "gallery-upload-name",
      "gallery-upload-btn", "gallery-upload-cancel", "gallery-upload-state",
    ];
    for (const id of ids) {
      // "topbar-status" -> ui.topbarStatus
      ui[id.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = byId(id);
    }
    ui.modeButtons = Array.from(document.querySelectorAll("[data-set-mode]"));
    ui.gestureButtons = Array.from(document.querySelectorAll("[data-gesture]"));
    ui.triviaAnswerButtons = Array.from(document.querySelectorAll("[data-trivia-answer]"));
    ui.resetTuningButtons = Array.from(document.querySelectorAll("[data-reset-tuning]"));
    ui.logFilterButtons = Array.from(document.querySelectorAll("[data-log-filter]"));
    ui.tuningInputs = [];
  }

  // ------------------------------------------------------------ floating notices

  function showToast(message, kind = "info") {
    const titles = { ok: "Done", error: "Could not do it", info: "Note" };
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

  // ------------------------------------------------------------ HTTP requests

  /** Reads the body as JSON only if it is JSON; otherwise (an error page, for example) null. */
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

  /** fetch with the usual options. Returns {response, data} (data is the JSON or null). */
  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      ...options,
    });
    const data = await readJson(response);
    return { response, data };
  }

  /** Message for the operator when the answer does not bring its own. */
  function defaultActionError(status) {
    if (status === 503) return "Sonnia is not ready yet. Try again in a few seconds.";
    if (status === 504) return "Sonnia did not answer in time. Check whether she did it before trying again.";
    return `The panel answered with an error (code ${status}). Try again.`;
  }

  /**
   * Sends an action to Sonnia and shows her answer to the operator. Returns
   * {ok, message}. With quiet it only warns when it fails; with silent it never
   * warns (the caller handles the result).
   */
  async function sendAction(action, params = {}, { button = null, quiet = false, silent = false } = {}) {
    const notify = (message, kind) => {
      if (!silent && (kind === "error" || !quiet)) showToast(message, kind);
    };
    setBusy(button, true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
    try {
      const body = { action, ...params };
      const { response, data } = await apiFetch(API_ACTION, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Sonia-Panel": "1" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!data) {
        const message = defaultActionError(response.status);
        notify(message, "error");
        return { ok: false, message };
      }
      markContact();
      const ok = response.ok && data.ok !== false;
      const serverMessage = typeof data.message === "string" ? data.message.trim() : "";
      const message = serverMessage || (ok ? "Done." : defaultActionError(response.status));
      notify(message, ok ? "ok" : "error");
      // Without WebSocket, refresh now so the change shows without waiting for the poll.
      if (ok && !app.wsLive) pollStatus();
      return { ok, message };
    } catch (error) {
      const message =
        error && error.name === "AbortError"
          ? "Sonnia took too long to answer. Check whether she did it before trying again."
          : "Could not send it: there is no connection to the panel. Try again in a few seconds.";
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

  // ------------------------------------------------------------ connection

  function markContact() {
    app.lastContactAt = Date.now();
  }

  function eventsUrl() {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${location.host}${API_EVENTS}`;
  }

  function connectWs() {
    clearTimeout(app.retryTimer);
    app.retryTimer = 0;
    app.nextRetryAt = 0;
    if (app.ws) return;
    let ws;
    try {
      ws = new WebSocket(eventsUrl());
    } catch {
      scheduleReconnect();
      return;
    }
    app.ws = ws;
    app.wsCreatedAt = Date.now();
    ws.addEventListener("open", () => {
      if (app.ws === ws) app.wsOpenedAt = Date.now();
    });
    ws.addEventListener("message", (event) => {
      if (app.ws === ws) onWsMessage(event);
    });
    ws.addEventListener("close", () => {
      if (app.ws === ws) dropWs();
    });
    // An error is always followed by close: it is handled there.
    updateConnectionUi();
  }

  /** Abandons the current WebSocket and switches to polling with a retry. */
  function dropWs() {
    const ws = app.ws;
    app.ws = null;
    app.wsLive = false;
    app.wsOpenedAt = 0;
    if (ws && ws.readyState <= WebSocket.OPEN) {
      try {
        ws.close();
      } catch {
        // It was already closing.
      }
    }
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

  /** Retries right away (the network is back, the phone was unlocked...). */
  function reconnectNow() {
    if (app.ws) return;
    app.retryDelay = RETRY_MIN_MS;
    clearTimeout(app.retryTimer);
    app.retryTimer = 0;
    connectWs();
    pollStatus();
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
    switch (data.type) {
      case "history":
        applyHistory(data);
        break;
      case "status":
        applyStatus(data.status);
        break;
      case "message":
        handleOrchestratorMessage(data.message, true);
        break;
      case "log":
        appendLog(data);
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

  /** Polling while there is no WebSocket: Sonnia's status. */
  async function pollStatus() {
    if (app.polling) return;
    app.polling = true;
    try {
      const { response, data } = await apiFetch(API_STATUS);
      if (response.ok && data) {
        const wasOffline = connectionLevel() === "offline";
        app.pollOk = true;
        markContact();
        applyStatus(data);
        // The server is back: do not wait for the next WebSocket retry.
        if (wasOffline && !app.ws) connectWs();
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

  /** Checks every second that the WebSocket is still alive and refreshes warnings and times. */
  function watchdog() {
    const now = Date.now();
    const ws = app.ws;
    if (ws) {
      const stuckConnecting = ws.readyState === WebSocket.CONNECTING && now - app.wsCreatedAt > WS_CONNECT_TIMEOUT_MS;
      const silentAfterOpen = !app.wsLive && app.wsOpenedAt && now - app.wsOpenedAt > STATUS_STALE_MS;
      const staleLive = app.wsLive && now - app.lastWsMessageAt > STATUS_STALE_MS;
      if (stuckConnecting || silentAfterOpen || staleLive) dropWs();
    }
    // If the gallery failed at startup, it is retried when the connection is back.
    if (app.galleryState === "error" && app.lastContactAt && now - app.galleryAttemptAt > 10000) loadGallery();
    updateConnectionUi();
  }

  function connectionLevel() {
    if (app.wsLive) return "live";
    const age = Date.now() - app.lastContactAt;
    if (app.lastContactAt && app.pollOk && age < POLL_INTERVAL_MS * 3) return "slow";
    if (!app.lastContactAt && Date.now() - app.startedAt < STARTUP_GRACE_MS) return "connecting";
    return "offline";
  }

  function updateConnectionUi() {
    const level = connectionLevel();
    setHidden(ui.slowBanner, level !== "slow");
    setHidden(ui.offlineBanner, level !== "offline");
    document.body.classList.toggle("is-offline", level === "offline");
    if (level === "offline") {
      const parts = [];
      if (app.ws && app.ws.readyState === WebSocket.CONNECTING) parts.push("Retrying now…");
      else if (app.nextRetryAt) {
        const seconds = Math.max(1, Math.ceil((app.nextRetryAt - Date.now()) / 1000));
        parts.push(`Retrying in ${seconds} s.`);
      }
      if (app.lastContactAt) parts.push(`Last data ${formatAgo(Date.now() - app.lastContactAt)} ago.`);
      parts.push("Check that Sonnia's orchestrator is still running.");
      setText(ui.offlineDetail, parts.join(" "));
    }
    renderTopbar();
    renderHealthSummary();
  }

  // ------------------------------------------------------------ status

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
    syncGallery(status);
    renderSound(status);
    renderHealth(status);
    renderNotes(status);
    renderAdvanced(status);
    renderTuning(status);
    renderAvatar();
    refreshControls();
    updateConnectionUi();
  }

  // Extra rules to enable controls, on top of capabilities and mode.
  const EXTRA_RULES = {
    cache: () => {
      const cache = app.status && app.status.voice_cache;
      return !cache || (!cache.busy && cache.ready < cache.total);
    },
    voice: () => Boolean(ui.voiceSelect.value) && ui.voiceSelect.value !== (app.status && app.status.voice),
    avatar_typed: () => Boolean(ui.avatarInput.value.trim()),
    avatar_custom: () => Boolean(avatarInfo().custom),
    trivia_idle: () => triviaInfo().available !== false && !triviaInfo().active,
    trivia_active: () => Boolean(triviaInfo().active),
    trivia_asking: () => triviaInfo().phase === "asking",
    trivia_revealing: () => triviaInfo().phase === "revealing",
  };

  /** Trivia in progress (`trivia` in the status). */
  function triviaInfo() {
    const trivia = app.status && app.status.trivia;
    return trivia && typeof trivia === "object" ? trivia : {};
  }

  function avatarInfo() {
    const avatar = app.status && app.status.avatar;
    return avatar && typeof avatar === "object" ? avatar : {};
  }

  /**
   * Enables or disables each control according to the engine capabilities,
   * the current mode, its own rules and whether one of its actions is running.
   */
  function refreshControls() {
    const mode = app.status ? currentMode() : null;
    // Without Sonnia's status the actions would not get through.
    const reachable = Boolean(app.status);
    for (const node of document.querySelectorAll("[data-cap]")) {
      const capOk = !app.capsKnown || hasCap(node.dataset.cap);
      const offModes = node.dataset.offModes ? node.dataset.offModes.split(" ") : [];
      const modeOk = !mode || !offModes.includes(mode);
      const rule = node.dataset.extra && EXTRA_RULES[node.dataset.extra];
      const extraOk = !rule || rule(node);
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

  // ------------------------------------------------------------ header and mode

  function activityState(status) {
    const mode = currentMode();
    if (mode === "away") return "away";
    return STATE_TEXT[status.state] ? status.state : "idle";
  }

  function activityText(status) {
    const mode = currentMode();
    if (mode === "away") return "Off the screen, with the sign up";
    if (mode === "greeter") {
      return status.state === "speaking" ? "Saying a line" : "Greets and dances on her own now and then";
    }
    return STATE_TEXT[status.state] || STATE_TEXT.idle;
  }

  function renderTopbar() {
    const level = connectionLevel();
    const status = app.status;
    let text = "Connecting…";
    let detail = "";
    let mode = "";
    if (level === "offline") {
      text = "No connection";
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
    if (ui.hero.dataset.mode !== mode) ui.hero.dataset.mode = mode;
    setText(ui.heroMode, status.debug === true ? "Sonnia in debug mode" : MODES[mode].sentence);
    setText(ui.heroActivity, activityText(status));
    const state = activityState(status);
    if (ui.activityDot.dataset.state !== state) ui.activityDot.dataset.state = state;

    const mic = (status.health && status.health.mic) || {};
    setHidden(ui.heroMuted, !(mic.muted && mode === "conversation"));
    setHidden(ui.heroDebug, status.debug !== true);

    const sign = typeof status.away_message === "string" ? status.away_message.trim() : "";
    setHidden(ui.awaySign, mode !== "away");
    setText(ui.awaySignText, sign);

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
    let text = "Checking…";
    if (level === "offline") {
      text = "No data: no connection";
    } else if (app.status) {
      const problems = healthEntries(app.status).filter(([, item]) => item.ok === false);
      if (problems.length === 0) {
        tone = "ok";
        text = "Everything works";
      } else {
        tone = "bad";
        text = `Check: ${problems.map(([key]) => HEALTH_NAMES[key] || capitalize(key)).join(", ")}`;
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

  // ------------------------------------------------------------ dialogs

  const supportsDialog = typeof HTMLDialogElement === "function";

  /** Simple confirmation. Returns true if the operator accepts. */
  function confirmAction({ title, text, confirmLabel, danger = false }) {
    if (!supportsDialog) return Promise.resolve(window.confirm(`${title}\n\n${text}`));
    ui.confirmTitle.textContent = title;
    ui.confirmText.textContent = text;
    ui.confirmOk.textContent = confirmLabel;
    ui.confirmOk.className = danger ? "btn btn-danger" : "btn btn-primary";
    return runDialog(ui.confirmDialog).then((choice) => choice === "ok");
  }

  /**
   * Opens a modal dialog and resolves with the value of the pressed button
   * ("ok", "cancel"...). It does not rely only on the close event: Chrome
   * delays it until the next frame, which never comes if the tab is in the
   * background.
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
   * Asks for the sign text. kind "go" to send her away, "edit" to change it
   * while she is away. Returns the text (empty: the default sign) or null if
   * cancelled.
   */
  function askAwayMessage(kind) {
    const current = (app.status && typeof app.status.away_message === "string" && app.status.away_message) || "";
    if (!supportsDialog) {
      const text = window.prompt("Sign text shown on the screen (empty for the default one):", current);
      return Promise.resolve(text === null ? null : text.trim());
    }
    const going = kind === "go";
    ui.awayTitle.textContent = going ? "Send Sonnia away?" : "Change the sign";
    ui.awayHelp.textContent = going
      ? "Sonnia will walk off the screen and leave this sign. She will not talk or greet anyone until you bring her back."
      : "Write what the sign on the screen should say.";
    ui.awayOk.textContent = going ? "Yes, send her away" : "Save the sign";
    ui.awayOk.className = going ? "btn btn-warning" : "btn btn-primary";
    ui.awayText.value = current;
    return runDialog(ui.awayDialog).then((choice) => (choice === "ok" ? ui.awayText.value.trim() : null));
  }

  // ------------------------------------------------------------ quick actions

  function renderQuickActions(status) {
    const mic = (status.health && status.health.mic) || {};
    const muted = Boolean(mic.muted);
    const pressed = String(muted);
    if (ui.muteBtn.getAttribute("aria-pressed") !== pressed) ui.muteBtn.setAttribute("aria-pressed", pressed);
    setText(ui.muteLabel, muted ? "Unmute microphone" : "Mute microphone");
  }

  function onMuteClick() {
    const mic = (app.status && app.status.health && app.status.health.mic) || {};
    sendAction("mute", { muted: !mic.muted }, { button: ui.muteBtn });
  }

  // ------------------------------------------------------------ trivia

  function renderTrivia(status) {
    const trivia = triviaInfo();
    const playing = Boolean(trivia.active);
    let text = "No trivia running right now.";
    if (playing) {
      const score = `${trivia.score} correct`;
      const phase = trivia.phase === "asking" ? "waiting for an answer" : "result on screen, waiting for the next question";
      const level = trivia.level ? ` · level ${trivia.level}` : "";
      text = `Question ${trivia.number} of ${trivia.total}${level} · ${score} · ${phase}`;
    } else if (trivia.available === false) {
      text = "There are not enough questions in the trivia bank.";
    } else if (trivia.total) {
      text = `Ready: ${trivia.total} questions, wins with ${trivia.threshold} correct.`;
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
    renderTriviaBankInfo(trivia);
  }

  /** Summary of the question bank in use. */
  function renderTriviaBankInfo(trivia) {
    let text = "";
    if (isNumber(trivia.bank)) {
      const levels = trivia.bank_levels && typeof trivia.bank_levels === "object" ? trivia.bank_levels : {};
      text = `Question bank: ${trivia.bank} question${trivia.bank === 1 ? "" : "s"} (${levels.easy || 0} easy, ` +
        `${levels.medium || 0} medium, ${levels.hard || 0} hard).`;
    }
    setText(ui.triviaBankInfo, text);
  }

  // ------------------------------------------------------------ gallery

  /**
   * Fetches the gallery. With quiet (after uploading or removing an image, or
   * when the status list changed) it does not show "Loading…" and, if it fails,
   * keeps the one it had.
   */
  async function loadGallery({ quiet = false } = {}) {
    if (!quiet || app.galleryState !== "ready") {
      app.galleryState = "loading";
      renderGallery();
    }
    app.galleryAttemptAt = Date.now();
    let gallery = [];
    let state = "error";
    try {
      const { response, data } = await apiFetch(API_GALLERY);
      if (response.ok && data) {
        const images = Array.isArray(data.images) ? data.images : [];
        // The url comes from the server (/api/gallery/<id>). Without a url the
        // image shows without a thumbnail.
        gallery = images
          .filter((image) => image && typeof image.id === "string" && image.id)
          .map((image) => ({ id: image.id, url: typeof image.url === "string" && image.url ? image.url : "" }));
        state = "ready";
      }
    } catch {
      state = "error";
    }
    if (quiet && state === "error" && app.galleryState === "ready") return;
    app.gallery = gallery;
    app.galleryState = state;
    renderGallery();
    refreshControls();
  }

  function missingThumb() {
    return el("span", { class: "thumb-missing", text: "No preview" });
  }

  function renderGallery() {
    const thumbs = ui.thumbs;
    if (app.galleryState === "loading") {
      thumbs.replaceChildren(el("p", { class: "muted", text: "Loading images…" }));
      return;
    }
    if (app.galleryState === "error") {
      const retry = el("button", { type: "button", class: "btn btn-small", text: "Retry" });
      retry.addEventListener("click", () => loadGallery());
      thumbs.replaceChildren(
        el("div", { class: "retry" }, el("p", { class: "muted", text: "Could not load the images." }), retry),
      );
      return;
    }
    const images = galleryItems();
    if (images.length === 0) {
      const text = app.caps.has("gallery_upload")
        ? "There are no images in the gallery. Add one with “Add image”."
        : "There are no images in the gallery. Add them to the assets/gallery folder.";
      thumbs.replaceChildren(el("p", { class: "muted", text }));
      return;
    }
    thumbs.replaceChildren(
      ...images.map((image) => {
        const button = el(
          "button",
          {
            type: "button",
            class: "thumb",
            "data-image-id": image.id,
            "data-cap": "images",
            "data-off-modes": "away",
            "aria-label": `Show “${prettyImageName(image.id)}”`,
          },
          image.url ? thumbImage(image.url) : missingThumb(),
          el("span", { class: "thumb-name", text: prettyImageName(image.id) }),
        );
        button.addEventListener("click", () => onShowImage(image.id, button));
        if (!image.upload) return button;
        // Only the images uploaded from the panel can be removed; the bundled ones cannot.
        const remove = el("button", {
          type: "button",
          class: "thumb-remove",
          "data-cap": "gallery_upload",
          "aria-label": `Remove “${prettyImageName(image.id)}” from the gallery`,
          title: "Remove from the gallery",
          text: "×",
        });
        remove.addEventListener("click", () => onRemoveImage(image.id, remove));
        return el("div", { class: "thumb-wrap" }, button, remove);
      }),
    );
    if (app.status) renderImageState(app.status);
    refreshControls();
  }

  /**
   * The images shown: the ids of `status.gallery` (always up to date) or, if it
   * is missing, the list from `/api/gallery`. Images uploaded from the panel are
   * recognised by their id (`upload-...`) and get a "×". The thumbnail is the
   * local preview of what was uploaded from here or the server url.
   */
  function galleryItems() {
    const info = app.status && app.status.gallery;
    const fetched = new Map(app.gallery.map((image) => [image.id, image]));
    let ids = app.gallery.map((image) => image.id);
    if (info && typeof info === "object" && Array.isArray(info.ids)) {
      ids = info.ids.filter((id) => typeof id === "string" && id);
    }
    return ids.map((id) => {
      const known = fetched.get(id);
      return { id, url: app.galleryPreviews.get(id) || (known && known.url) || "", upload: id.startsWith(UPLOAD_PREFIX) };
    });
  }

  /** Redraws the gallery if the status list changed (and fetches it again if it has new ids). */
  function syncGallery(status) {
    const info = status.gallery;
    if (!info || typeof info !== "object" || !Array.isArray(info.ids)) return;
    const sig = JSON.stringify(info.ids);
    if (sig === app.gallerySig) return;
    app.gallerySig = sig;
    if (app.galleryState !== "ready") return;
    renderGallery();
    const fetched = new Set(app.gallery.map((image) => image.id));
    if (info.ids.some((id) => !fetched.has(id))) loadGallery({ quiet: true });
  }

  async function onRemoveImage(id, button) {
    const ok = await confirmAction({
      title: "Remove the image?",
      text: `“${prettyImageName(id)}” leaves the gallery and Sonnia can no longer show it.`,
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    const result = await sendAction("remove_gallery_image", { id }, { button });
    if (!result.ok) return;
    const preview = app.galleryPreviews.get(id);
    if (preview) {
      URL.revokeObjectURL(preview);
      app.galleryPreviews.delete(id);
    }
    loadGallery({ quiet: true });
  }

  // ------------------------------------------------------------ image upload

  // The image is reduced here before sending it: 1280 px on the long side and
  // ~220 KB, so the action stays small even in base64 inside the JSON.
  const UPLOAD_MAX_SIDE = 1280;
  const UPLOAD_MIN_SIDE = 16;
  const UPLOAD_TARGET_BYTES = 220 * 1024;
  const UPLOAD_BAD_FORMAT = "Use a JPG or PNG photo: this browser cannot open that image.";

  /** Upload error with a text for the operator (the others show as UPLOAD_BAD_FORMAT). */
  class UploadError extends Error {}

  async function onGalleryFile() {
    const file = ui.galleryFile.files && ui.galleryFile.files[0];
    ui.galleryFile.value = ""; // so the same file can be picked again
    if (!file) return;
    discardPendingUpload();
    setUploadState("Preparing the image…");
    let prepared;
    try {
      prepared = await prepareUpload(file);
    } catch (error) {
      setUploadState(error instanceof UploadError ? error.message : UPLOAD_BAD_FORMAT, "error");
      return;
    }
    app.pendingUpload = prepared;
    ui.galleryUploadPreview.src = prepared.previewUrl;
    ui.galleryUploadName.value = uploadName(file.name);
    setHidden(ui.galleryUpload, false);
    setUploadState(`Ready to upload (${Math.max(1, Math.round(prepared.blob.size / 1024))} KB). Check the name.`);
    ui.galleryUploadName.focus();
    ui.galleryUploadName.select();
  }

  /** "IMG_4521.jpg" -> "IMG 4521": the photo name, without extension, to edit it. */
  function uploadName(fileName) {
    const base = String(fileName || "").replace(/\.[a-z0-9]{2,5}$/i, "");
    return base.replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 60);
  }

  /**
   * Decodes the image in the browser and reduces it. PNGs that fit stay PNG
   * (logos with transparency); the rest go to JPEG on white, lowering the
   * quality (and, if needed, the size) until it takes ~220 KB at most.
   */
  async function prepareUpload(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      try {
        await img.decode();
      } catch {
        throw new UploadError(UPLOAD_BAD_FORMAT);
      }
      const width = img.naturalWidth;
      const height = img.naturalHeight;
      if (!width || !height) throw new UploadError(UPLOAD_BAD_FORMAT);
      if (Math.min(width, height) < UPLOAD_MIN_SIDE) {
        throw new UploadError(`The image is too small: it must be at least ${UPLOAD_MIN_SIDE} pixels per side.`);
      }
      let scale = Math.min(1, UPLOAD_MAX_SIDE / Math.max(width, height));
      if (file.type === "image/png") {
        const blob = await drawToBlob(img, width * scale, height * scale, "image/png");
        if (blob && blob.size <= UPLOAD_TARGET_BYTES) return finishUpload(blob);
      }
      for (let attempt = 0; attempt < 6; attempt += 1) {
        for (const quality of [0.86, 0.78, 0.7, 0.62, 0.54, 0.46]) {
          const blob = await drawToBlob(img, width * scale, height * scale, "image/jpeg", quality);
          if (!blob) throw new UploadError(UPLOAD_BAD_FORMAT);
          if (blob.size <= UPLOAD_TARGET_BYTES) return finishUpload(blob);
        }
        scale *= 0.75;
      }
      throw new UploadError("The image is too heavy even when reduced: try another one.");
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function finishUpload(blob) {
    return { blob, previewUrl: URL.createObjectURL(blob) };
  }

  /** Draws the image on a canvas of the requested size and exports it as PNG or JPEG. */
  function drawToBlob(img, width, height, type, quality) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    const context = canvas.getContext("2d");
    if (!context) return Promise.resolve(null);
    if (type === "image/jpeg") {
      // Without a background, the transparent parts of a PNG turn black in the JPEG.
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
    }
    context.imageSmoothingQuality = "high";
    context.drawImage(img, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  async function onGalleryUpload() {
    const pending = app.pendingUpload;
    if (!pending) return;
    const name = ui.galleryUploadName.value.trim();
    if (!/[a-z0-9]/i.test(name.normalize("NFKD"))) {
      setUploadState("Give the image a name with letters or numbers.", "error");
      ui.galleryUploadName.focus();
      return;
    }
    setUploadState("Uploading…");
    let data;
    try {
      data = await blobToBase64(pending.blob);
    } catch {
      setUploadState(UPLOAD_BAD_FORMAT, "error");
      return;
    }
    const result = await sendAction(
      "add_gallery_image",
      { name, data_base64: data },
      { button: ui.galleryUploadBtn, silent: true },
    );
    if (!result.ok) {
      setUploadState(result.message, "error");
      return;
    }
    // "Image added: upload-team-photo-0731": the id Sonnia will use.
    const match = /:\s*(\S+)\s*$/.exec(result.message);
    const id = match ? match[1] : "";
    if (pending === app.pendingUpload) {
      if (id) {
        app.galleryPreviews.set(id, pending.previewUrl);
        app.pendingUpload = null; // the preview stays for the thumbnail
      }
      discardPendingUpload();
    }
    setUploadState(id ? `Added as “${id}”. Sonnia can show it now.` : result.message, "ok");
    renderGallery();
    loadGallery({ quiet: true });
  }

  /** Forgets the picked image that was not uploaded yet (and its preview). */
  function discardPendingUpload() {
    const pending = app.pendingUpload;
    app.pendingUpload = null;
    if (pending) URL.revokeObjectURL(pending.previewUrl);
    if (!ui.galleryUpload) return;
    setHidden(ui.galleryUpload, true);
    ui.galleryUploadPreview.removeAttribute("src");
    ui.galleryUploadName.value = "";
  }

  /** The upload status line: empty, "Uploading…", "Added…" or the error. */
  function setUploadState(text, kind = "") {
    const node = ui.galleryUploadState;
    if (!node) return;
    setText(node, text);
    node.dataset.kind = kind;
    setHidden(node, !text);
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
    const id = image.image_id || image.id || "image";
    return { id: String(id), caption: typeof image.caption === "string" ? image.caption : "" };
  }

  function renderImageState(status) {
    const image = currentImage(status);
    let text = "No image on screen.";
    if (image) {
      text = `On screen now: “${prettyImageName(image.id)}”`;
      if (image.caption) text += `, with the caption “${image.caption}”`;
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

  // ------------------------------------------------------------ today's notes

  function renderNotes(status) {
    const server = typeof status.notes === "string" ? status.notes : "";
    const input = ui.notesInput;
    if (app.notesBase === null) {
      input.value = server;
      app.notesBase = server;
    } else if (input.value === app.notesBase && document.activeElement !== input && server !== app.notesBase) {
      // No local changes: adopt what someone else saved.
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
      setText(node, "Saving…");
    } else if (app.notesBase !== null && ui.notesInput.value !== app.notesBase) {
      node.dataset.state = "dirty";
      setText(node, "Unsaved changes");
    } else {
      node.dataset.state = "saved";
      setText(node, ui.notesInput.value.trim() ? "Saved" : "No notes");
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

  // ------------------------------------------------------------ have Sonnia say

  async function onSaySubmit(event) {
    event.preventDefault();
    const text = ui.sayInput.value.trim();
    if (!text) {
      showToast("Write what you want Sonnia to say first.", "info");
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
      showToast("Write the question first.", "info");
      ui.askInput.focus();
      return;
    }
    const result = await sendAction("ask", { text }, { button: ui.askBtn });
    if (result.ok) ui.askInput.value = "";
  }

  // ------------------------------------------------------------ sound

  // While the operator moves a control, the incoming status does not overwrite it.
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
    let text = `${percent}%`;
    if (percent === 100) text += " (normal)";
    else if (percent === 0) text = "Muted (0%)";
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
    let caption = "Microphone: no data right now.";
    if (mic.muted) caption = "Microphone muted: no sound gets through.";
    else if (level !== null) {
      caption = `Microphone level: ${formatNumber(level, 3)}. `;
      caption += level < gate ? "Below the line: Sonnia does not hear it." : "Above the line: Sonnia hears it.";
    }
    setText(ui.gateMeterCaption, caption);
  }

  // ------------------------------------------------------------ health

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
      if (items.length === 0) items.push(el("li", { class: "muted", text: "No health data." }));
      ui.healthList.replaceChildren(...items);
    }

    for (const [key, item] of entries) {
      const row = healthRows.get(key);
      const ok = item.ok === true ? "true" : item.ok === false ? "false" : "null";
      if (row.li.dataset.ok !== ok) row.li.dataset.ok = ok;
      setText(row.icon, ok === "true" ? "✓" : ok === "false" ? "✕" : "–");
      let label = typeof item.label === "string" && item.label ? item.label : "";
      if (!label) label = ok === "true" ? "OK" : ok === "false" ? "Failing" : "Not used right now";
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

  // ------------------------------------------------------------ advanced

  let voicesKey = "";
  let sessionKey = "";
  let usageKey = "";
  let animKey = "";

  /** Groups of the animations block (the ones the avatar client sends), in this order. */
  const ANIMATION_GROUPS = [
    ["greeting", "Greeting"],
    ["dance", "Dances"],
    ["fourth_wall", "Toward the audience"],
    ["soft", "Soft gestures"],
    ["talking", "Talking gestures"],
    ["idle_variation", "Idle"],
    ["thinking", "Thinking"],
    ["nod", "Listening"],
    ["present", "Pointing at an image"],
    ["trivia", "Trivia"],
  ];

  /** Readable names of some known clips; the rest are derived from the clip name. */
  const ANIMATION_NAMES = {
    WaveGeneric: "Wave",
    Wave: "Wave (long)",
    Peace: "Peace sign",
    QuickAction_salute: "Salute",
    QuickAction_twoThumbsUp: "Thumbs up",
    QuickAction_vibe: "Dance",
    "actions-presentItem_intro": "Present",
    "actions-0224-lookAtObject_Trimmed": "Look at something in her hand",
    DefaultIdle: "Idle",
    "idles-0024-basicIdle": "Attentive idle",
    StillPose: "Still",
    Walk: "Walk",
  };

  /** "Some_Clip_Name" -> "Some clip name". */
  function prettyClipName(clip) {
    if (ANIMATION_NAMES[clip]) return ANIMATION_NAMES[clip];
    return capitalize(clip.replace(/_+/g, " ").trim());
  }

  /** Drawn tiles: clip → {item, button, toggle}, to update them without rebuilding them. */
  const animTiles = new Map();

  /** One button per animation the avatar client has, by group. */
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
    setText(ui.animCount, list && list.length > 0 ? `${list.length} animations` : "");
    if (!list) {
      ui.animGroups.replaceChildren();
      return;
    }
    if (list.length === 0) {
      ui.animGroups.replaceChildren(
        el("p", { class: "muted", text: "The avatar client has not sent its list of animations. Open it and they will show up here." }),
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

  /** A tile: the button that plays it and, if the orchestrator supports it, "Auto". */
  function animationTile(clip, toggles) {
    const button = el("button", {
      type: "button",
      class: "btn btn-small anim-play",
      "data-cap": "animations",
      "data-off-modes": "away",
      title: clip,
      text: prettyClipName(clip),
    });
    button.addEventListener("click", () => sendAction("animation", { clip }, { button }));
    const item = el("div", { class: "anim-item" }, button);
    let toggle = null;
    if (toggles) {
      toggle = el("input", { type: "checkbox", "data-cap": "animation_toggles", "aria-label": `Sonnia plays “${prettyClipName(clip)}” on her own` });
      toggle.checked = true;
      toggle.addEventListener("change", () => onAnimationToggle(clip, toggle));
      item.append(el("label", { class: "anim-toggle" }, toggle, el("span", { text: "Auto" })));
    }
    animTiles.set(clip, { item, button, toggle });
    return item;
  }

  /** Marks the one playing and the ones Sonnia does not play on her own. */
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
    // Voice
    const voices = Array.isArray(status.voices) ? status.voices.filter((v) => typeof v === "string") : [];
    if (status.voice && !voices.includes(status.voice)) voices.unshift(status.voice);
    const key = `${voices.join(",")}|${status.voice}`;
    if (key !== voicesKey) {
      voicesKey = key;
      const keep = ui.voiceSelect.dirty ? ui.voiceSelect.value : status.voice;
      ui.voiceSelect.replaceChildren(
        ...voices.map((voice) =>
          el("option", { value: voice, text: voice === status.voice ? `${capitalize(voice)} (current)` : capitalize(voice) }),
        ),
      );
      if (keep && voices.includes(keep)) ui.voiceSelect.value = keep;
    }
    if (!ui.voiceSelect.dirty && document.activeElement !== ui.voiceSelect && status.voice) {
      if (ui.voiceSelect.value !== status.voice) ui.voiceSelect.value = status.voice;
    }

    // Switches
    if (!isLocked(ui.showcaseInput)) ui.showcaseInput.checked = Boolean(status.showcase && status.showcase.enabled);
    if (!isLocked(ui.debugInput)) ui.debugInput.checked = status.debug === true;
    if (!isLocked(ui.subtitlesInput)) ui.subtitlesInput.checked = status.subtitles !== false;

    renderAnimations(status);

    // Recorded lines
    const cache = status.voice_cache;
    if (cache && isNumber(cache.ready) && isNumber(cache.total)) {
      ui.cacheProgress.max = Math.max(cache.total, 1);
      ui.cacheProgress.value = Math.min(cache.ready, cache.total);
      let text = `${cache.ready} of ${cache.total} lines ready`;
      if (cache.busy) text = `Recording… ${text}`;
      else if (cache.total > 0 && cache.ready >= cache.total) text = `All ${cache.total} lines are ready`;
      setText(ui.cacheText, text);
      setText(ui.cacheBtn, cache.busy ? "Recording…" : "Prepare voices");
    } else {
      setText(ui.cacheText, "No data");
    }
    const cacheError = cache && typeof cache.error === "string" ? cache.error.trim() : "";
    setText(ui.cacheError, cacheError ? `Last recording error: ${cacheError}` : "");
    setHidden(ui.cacheError, !cacheError);

    // Session
    const session = status.session && typeof status.session === "object" ? status.session : null;
    const sessionFacts = [];
    if (session && session.id) {
      sessionFacts.push(["Session", String(session.id)]);
      sessionFacts.push(["Open for", formatDuration(session.uptime_s)]);
      if (isNumber(session.expires_in_s)) sessionFacts.push(["Renews in", formatDuration(session.expires_in_s)]);
      if (isNumber(session.context_ratio)) {
        sessionFacts.push(["Memory used", `${Math.round(clamp(session.context_ratio, 0, 1) * 100)}%`]);
      }
    } else {
      sessionFacts.push(["Session", "None open"]);
    }
    sessionKey = renderFacts(ui.sessionFacts, sessionFacts, sessionKey);

    // Usage
    const usage = status.usage && typeof status.usage === "object" ? status.usage : {};
    const usageFacts = [
      ["Time conversing", isNumber(usage.live_seconds) ? `${formatNumber(usage.live_seconds / 60, 1)} min` : "—"],
      ["Approximate cost", isNumber(usage.cost_usd) ? `${formatNumber(usage.cost_usd, 2)} USD` : "—"],
    ];
    usageKey = renderFacts(ui.usageFacts, usageFacts, usageKey);
  }

  /** Draws a list of facts only if it changed. Returns the new key. */
  function renderFacts(list, facts, previousKey) {
    const key = JSON.stringify(facts);
    if (key === previousKey) return previousKey;
    list.replaceChildren(...facts.flatMap(([term, value]) => [el("dt", { text: term }), el("dd", { text: value })]));
    return key;
  }

  // ------------------------------------------------------------ Developer

  /** Draws the Developer sliders from TUNING_SPEC (once, at startup). */
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
    if (spec.unit === "%") text = `${Math.round(value * 100)}%`;
    else if (spec.unit === "cm") text = `${value > 0 ? "+" : ""}${Math.round(value * 100)} cm`;
    else text = `${value > 0 ? "+" : ""}${formatNumber(value, 1)}°`;
    return Math.abs(value - spec.def) < spec.step / 2 ? `${text} (default)` : text;
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

  /** While dragging, sends the value at most every TUNING_SEND_MS to see it live. */
  function queueTuning(input) {
    if (input.sendTimer) return;
    const wait = Math.max(0, TUNING_SEND_MS - (Date.now() - (input.sentAt || 0)));
    input.sendTimer = setTimeout(() => sendTuning(input), wait);
  }

  /** One request at a time per slider: that way the last value always arrives last. */
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

  // ------------------------------------------------------------ avatar (Developer)

  /** Whether a custom avatar definition is set (`avatar.custom`); the panel never gets its text back. */
  function renderAvatar() {
    const custom = Boolean(avatarInfo().custom);
    setText(ui.avatarState, custom ? "In use: a custom avatar definition." : "In use: the default avatar.");
    const state = custom ? "custom" : "default";
    if (ui.avatarState.dataset.state !== state) ui.avatarState.dataset.state = state;
  }

  /** "Save": sends the definition as text, after checking that it is JSON. */
  async function onAvatarSave() {
    const definition = ui.avatarInput.value.trim();
    if (!definition) return;
    try {
      JSON.parse(definition);
    } catch {
      showToast("The avatar definition is not valid JSON.", "error");
      ui.avatarInput.focus();
      return;
    }
    await sendAction("set_avatar", { definition }, { button: ui.avatarSaveBtn });
  }

  async function onAvatarDefault() {
    const ok = await confirmAction({
      title: "Use the default avatar?",
      text: "Sonnia goes back to the avatar that comes with the avatar client. The saved definition is deleted.",
      confirmLabel: "Yes, use the default",
    });
    if (ok) await sendAction("set_avatar", { definition: null }, { button: ui.avatarDefaultBtn });
  }

  // ------------------------------------------------------------ switches and voice

  async function onVoiceChange() {
    const voice = ui.voiceSelect.value;
    if (!voice) return;
    const ok = await confirmAction({
      title: `Switch to the ${capitalize(voice)} voice?`,
      text: "Sonnia will start a new conversation and forget what she was talking about.",
      confirmLabel: "Yes, change the voice",
    });
    if (!ok) return;
    const result = await sendAction("set_voice", { voice }, { button: ui.voiceBtn });
    if (result.ok) ui.voiceSelect.dirty = false;
  }

  /** Simple switch: sends the action and, if it fails, goes back to how it was. */
  async function onSwitchChange(input, action) {
    const enabled = input.checked;
    lockControl(input);
    const result = await sendAction(action, { enabled }, { button: input });
    if (!result.ok) input.checked = !enabled;
    lockControl(input);
  }

  async function onRestart() {
    const ok = await confirmAction({
      title: "Start a new conversation?",
      text: "Sonnia will forget everything that was said so far.",
      confirmLabel: "Yes, start over",
    });
    if (ok) sendAction("restart", {}, { button: ui.restartBtn });
  }

  // ------------------------------------------------------------ live conversation

  const chat = {
    lines: [],
    open: { user: null, assistant: null }, // last line of each speaker that is still growing
    ambient: null, // idle show line in progress
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
    if (line.role === "user") return "Visitor";
    return line.ambient ? "Sonnia (on her own)" : "Sonnia";
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

    // A line that has not grown for a long time is considered finished (dropped turn).
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
    // Only the idle show lines matter here: the rest arrive as transcript.
    if (!message.ambient) return;
    closeAmbient();
    const text = typeof message.text === "string" ? message.text.trim() : "";
    // Some engines send the line's transcript right before its speech_start:
    // that line becomes the "Sonnia (on her own)" one instead of repeating it.
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

  /** Sonnia goes quiet: whatever she was saying is closed as it is. */
  function closeSonniaLines() {
    const line = chat.open.assistant;
    if (line) {
      line.final = true;
      paintSpeechLine(line);
      chat.open.assistant = null;
    }
    closeAmbient();
  }

  /** Messages the orchestrator sends to the avatar client: used for the live conversation. */
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
        closeSonniaLines();
        addSystemLine("Sonnia went quiet", "", message.time);
        break;
      case "show_image": {
        addSystemLine(`On screen: “${prettyImageName(message.image_id || "image")}”`, "", message.time);
        break;
      }
      case "hide_image":
        addSystemLine("Image removed from the screen", "", message.time);
        break;
      case "presence":
        if (app.lastPresence !== null && app.lastPresence !== message.present) {
          addSystemLine(message.present ? "Sonnia came back to the screen" : "Sonnia left the screen", "", message.time);
        }
        app.lastPresence = Boolean(message.present);
        break;
      case "error":
        addSystemLine(`Error: ${message.message || "no details"}`, "error", message.time);
        break;
      case "state":
        // Updates the activity right away, without waiting for the next full status.
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

  /** On connect the latest conversation and log arrive: everything is redrawn from scratch. */
  function applyHistory(data) {
    resetChat();
    ui.log.replaceChildren();
    clearDevLog();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    for (const item of messages) {
      const message = item && item.type === "message" && item.message ? item.message : item;
      handleOrchestratorMessage(message, false);
    }
    const logs = Array.isArray(data.logs) ? data.logs : [];
    for (const entry of logs) appendLog(entry);
    chatScrollToBottom();
    ui.log.scrollTop = ui.log.scrollHeight;
    ui.devLog.scrollTop = ui.devLog.scrollHeight;
  }

  // ------------------------------------------------------------ log

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
    appendDevLog(data, level);
  }

  // ------------------------------------------------------------ Developer log

  const devLog = { filter: "all" };

  /** Tags of a line, set by the orchestrator (`log_tags()` in `server/sonia/panel/logs.py`). */
  function logTags(data) {
    return Array.isArray(data.tags) ? data.tags.filter((tag) => typeof tag === "string") : [];
  }

  function devLogMatches(line) {
    const filter = devLog.filter;
    if (filter === "all") return true;
    if (filter === "problems") return PROBLEM_LEVELS.has(line.dataset.level);
    return line.dataset.tags.split(" ").includes(filter);
  }

  function appendDevLog(data, level) {
    const box = ui.devLog;
    if (!box) return;
    const text = String(data.text ?? data.message ?? "");
    const tags = logTags(data);
    const logger = typeof data.logger === "string" ? data.logger : "";
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const line = el("p", { class: "log-line", "data-level": level, "data-tags": tags.join(" ") });
    if (data.time) line.append(el("span", { class: "log-time", text: `${data.time} ` }));
    if (LOG_LEVELS[level]) line.append(`[${LOG_LEVELS[level]}] `);
    if (logger) line.append(el("span", { class: "log-logger", text: `${logger} · ` }));
    line.append(text);
    line.hidden = !devLogMatches(line);
    box.append(line);
    while (box.childElementCount > MAX_DEV_LOG_LINES) box.firstElementChild.remove();
    if (stick) box.scrollTop = box.scrollHeight;
    updateDevLogCount();
  }

  function clearDevLog() {
    ui.devLog.replaceChildren();
    updateDevLogCount();
  }

  function setDevLogFilter(filter) {
    devLog.filter = filter;
    for (const button of ui.logFilterButtons) {
      button.setAttribute("aria-pressed", String(button.dataset.logFilter === filter));
    }
    for (const line of ui.devLog.children) line.hidden = !devLogMatches(line);
    ui.devLog.scrollTop = ui.devLog.scrollHeight;
    updateDevLogCount();
  }

  function visibleDevLogLines() {
    return Array.from(ui.devLog.children).filter((line) => !line.hidden);
  }

  function updateDevLogCount() {
    const total = ui.devLog.childElementCount;
    const shown = devLog.filter === "all" ? total : visibleDevLogLines().length;
    const text = total === 0
      ? "No lines yet."
      : devLog.filter === "all"
        ? `${total} ${total === 1 ? "line" : "lines"}`
        : `${shown} of ${total} lines`;
    setText(ui.devLogCount, text);
  }

  async function copyDevLog() {
    const text = visibleDevLogLines().map((line) => line.textContent).join("\n");
    if (!text) {
      showToast("There are no lines to copy with this filter.", "info");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // No clipboard permission (or no secure context): the old method.
      const area = el("textarea", { class: "visually-hidden", value: text, readOnly: true });
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      if (!ok) {
        showToast("The browser does not allow copying: select the lines by hand.", "error");
        return;
      }
    }
    const count = text.split("\n").length;
    showToast(`${count} ${count === 1 ? "line" : "lines"} copied from the log.`, "ok");
  }

  // ------------------------------------------------------------ page events

  function bindEvents() {
    for (const button of ui.logFilterButtons) {
      button.addEventListener("click", () => setDevLogFilter(button.dataset.logFilter));
    }
    ui.devLogCopyBtn.addEventListener("click", copyDevLog);

    for (const button of ui.modeButtons) button.addEventListener("click", () => onModeClick(button));
    ui.editSignBtn.addEventListener("click", onEditSign);

    ui.stopBtn.addEventListener("click", () => sendAction("stop", {}, { button: ui.stopBtn }));
    ui.greetBtn.addEventListener("click", () => sendAction("greet", {}, { button: ui.greetBtn }));
    ui.triviaStartBtn.addEventListener("click", () =>
      sendAction("trivia_start", { level: ui.triviaLevel.value }, { button: ui.triviaStartBtn }),
    );
    ui.triviaRestartBtn.addEventListener("click", () =>
      sendAction("trivia_restart", { level: ui.triviaLevel.value }, { button: ui.triviaRestartBtn }),
    );
    ui.triviaNextBtn.addEventListener("click", () =>
      sendAction("trivia_next", {}, { button: ui.triviaNextBtn }),
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
    ui.hideBtn.addEventListener("click", () => sendAction("hide_image", {}, { button: ui.hideBtn }));
    ui.galleryAddBtn.addEventListener("click", () => ui.galleryFile.click());
    ui.galleryFile.addEventListener("change", onGalleryFile);
    ui.galleryUploadBtn.addEventListener("click", onGalleryUpload);
    ui.galleryUploadCancel.addEventListener("click", () => {
      discardPendingUpload();
      setUploadState("");
    });
    ui.muteBtn.addEventListener("click", onMuteClick);

    ui.sayForm.addEventListener("submit", onSaySubmit);
    // Ctrl/Cmd + Enter also sends from the text box.
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
    ui.showcaseInput.addEventListener("change", () => onSwitchChange(ui.showcaseInput, "showcase"));
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
    ui.avatarInput.addEventListener("input", refreshControls);
    ui.avatarSaveBtn.addEventListener("click", onAvatarSave);
    ui.avatarDefaultBtn.addEventListener("click", onAvatarDefault);
    ui.askForm.addEventListener("submit", onAskSubmit);
    ui.restartBtn.addEventListener("click", onRestart);
    ui.cacheBtn.addEventListener("click", () => sendAction("prepare_voices", {}, { button: ui.cacheBtn }));

    // When the tab comes back or the network returns, reconnect without waiting for the retry.
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && !app.wsLive) reconnectNow();
    });
    window.addEventListener("online", () => {
      if (!app.wsLive) reconnectNow();
    });
  }

  function init() {
    collectElements();
    buildTuning();
    bindEvents();
    renderVolumeLabel();
    renderGateControl();
    refreshControls();
    setInterval(watchdog, 1000);
    connectWs();
    startPolling();
    loadGallery();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
