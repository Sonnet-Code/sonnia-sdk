/*
 * Modo Jean en el panel: bloque en «Developer» y modal para que Jean (CTO de
 * Sonnet Code) entre en el stand como invitado sorpresa desde donde esté.
 *
 * Se monta solo al cargar: index.html únicamente incluye este script (después
 * de panel.js) y jean.css. El modal:
 *   - activa y termina el Modo Jean (acción set_guest_mode) y muestra la fase;
 *   - pinta la cámara del stand (JPEG por /api/guest) y confirma cada fotograma
 *     (ack), con lo que el stand ajusta tamaño, calidad y fps a la red;
 *   - reproduce el micro del stand y manda el de Jean (AudioWorklet en
 *     jean-worklet.js), con micro abierto o pulsar para hablar;
 *   - lanza animaciones del avatar de Jean (acción guest_animation);
 *   - pasa la pantalla de Sonia al editor del personaje de Jean (acción
 *     open_avatar_editor con target "guest"), antes de activar el modo.
 * Formato de los frames y decisiones en docs/modo-jean.md.
 */
"use strict";

(() => {
  const STORAGE_KEY = "sonia-panel.instance";
  const KIND_VIDEO = 1;
  const KIND_STAND_AUDIO = 2;
  const KIND_GUEST_AUDIO = 3;
  const HEADER_BYTES = 16;
  const MAX_BUFFERED = 64 * 1024; // más que esto pendiente de enviar y se tira la voz
  const STATUS_POLL_MS = 1000;
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 10000;
  const ACTION_TIMEOUT_MS = 15000;

  const PHASES = {
    off: "Sonia está sola en el stand.",
    intro: "Sonia anuncia al invitado sorpresa…",
    entering: "Tu avatar está entrando…",
    live: "En directo: el stand te oye.",
    leaving: "Te estás despidiendo…",
  };

  const state = {
    ui: {},
    open: false,
    ws: null,
    retryMs: RETRY_MIN_MS,
    retryTimer: null,
    failedConnects: 0,
    statusTimer: null,
    status: null,
    phase: "off",
    agentConnected: false,
    audio: null, // { ctx, player, playerGain, capture, stream, sink }
    micMode: "open", // "open" | "ptt"
    micOn: false,
    pttHeld: false,
    seqOut: 0,
    sentBlocks: 0,
    droppedBlocks: 0,
    framesShown: 0,
    fpsShown: 0,
    lastFpsAt: 0,
    remoteStats: null,
    animationsKey: null, // null: aún no se ha pintado ninguna lista
  };

  // ------------------------------------------------------------ utilidades

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("data-") || key.startsWith("aria-") || key === "role" || key === "for") node.setAttribute(key, value);
      else node[key] = value;
    }
    for (const child of children) if (child !== null && child !== undefined) node.append(child);
    return node;
  }

  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  function instanceId() {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  }

  function withInstance(url) {
    const id = instanceId();
    if (!id) return url;
    return `${url}${url.includes("?") ? "&" : "?"}instance=${encodeURIComponent(id)}`;
  }

  /** El panel local del orquestador (127.0.0.1:8780) no tiene sala de vídeo. */
  function isLocalPanel() {
    return /^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname) && location.port === "8780";
  }

  async function sendAction(action, params = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
    try {
      const body = { action, ...params };
      const id = instanceId();
      if (id) body.instance = id;
      const response = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Sonia-Panel": "1" },
        body: JSON.stringify(body),
        credentials: "same-origin",
        signal: controller.signal,
      });
      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      const ok = response.ok && data && data.ok !== false;
      const message = (data && typeof data.message === "string" && data.message) || (ok ? "Hecho." : "No se pudo.");
      note(message, ok ? "ok" : "error");
      return ok;
    } catch {
      note("No se pudo enviar: revisa la conexión.", "error");
      return false;
    } finally {
      clearTimeout(timer);
      pollStatus();
    }
  }

  function note(message, kind = "info") {
    const ui = state.ui;
    setText(ui.note, message);
    ui.note.dataset.kind = kind;
    ui.note.hidden = !message;
  }

  // ------------------------------------------------------------ montaje

  function mount() {
    const grid = document.querySelector("#developer .adv-grid");
    if (!grid || document.getElementById("jean-block")) return;
    const openButton = el("button", {
      type: "button",
      class: "btn btn-primary",
      id: "jean-open-btn",
      "data-cap": "guest_mode",
      text: "Abrir Modo Jean",
    });
    grid.append(
      el(
        "section",
        { class: "adv-block", id: "jean-block", "aria-labelledby": "jean-block-title" },
        el("h3", { id: "jean-block-title", text: "Modo Jean" }),
        el("p", {
          class: "help",
          text: "Jean entra en el stand como invitado sorpresa: Sonia lo presenta, se dan la mano y le deja hablar. Desde aquí ves la cámara del stand, hablas por tu micro y lanzas tus gestos.",
        }),
        openButton,
        el("p", {
          class: "cap-note",
          "data-cap-note": "guest_mode",
          hidden: true,
          text: "Esta Sonia no tiene aún el Modo Jean: hay que actualizar el orquestador.",
        }),
      ),
    );
    buildDialog();
    openButton.addEventListener("click", openDialog);
  }

  function buildDialog() {
    const ui = state.ui;
    ui.canvas = el("canvas", { id: "jean-video", width: 640, height: 360, "aria-label": "Cámara del stand" });
    ui.videoEmpty = el("p", { class: "jean-video-empty", text: "Esperando la cámara del stand…" });
    ui.stats = el("p", { class: "jean-stats", text: "—" });
    ui.phase = el("p", { class: "jean-phase", "data-phase": "off", text: PHASES.off });
    ui.conn = el("p", { class: "jean-conn", "data-state": "connecting", text: "Conectando con el stand…" });
    ui.note = el("p", { class: "jean-note", role: "status", hidden: true });
    ui.start = el("button", { type: "button", class: "btn btn-primary", text: "Activar Modo Jean" });
    ui.stop = el("button", { type: "button", class: "btn btn-danger", text: "Terminar" });
    ui.mic = el("button", { type: "button", class: "btn", text: "Activar mi micrófono" });
    ui.modeOpen = el("input", { type: "radio", name: "jean-mic-mode", value: "open", checked: true });
    ui.modePtt = el("input", { type: "radio", name: "jean-mic-mode", value: "ptt" });
    ui.ptt = el("button", { type: "button", class: "btn jean-ptt", text: "Mantén pulsado para hablar (o la barra espaciadora)" });
    ui.meterFill = el("div", { class: "meter-fill jean-meter-fill" });
    ui.micState = el("p", { class: "help jean-mic-state", text: "Micrófono apagado." });
    ui.volume = el("input", { type: "range", min: 0, max: 200, step: 5, value: 100, id: "jean-volume" });
    ui.volumeValue = el("output", { class: "control-value", for: "jean-volume", text: "100 %" });
    ui.animations = el("div", { class: "jean-anims" }, el("p", { class: "muted", text: "Cargando animaciones…" }));
    ui.avatarState = el("p", { class: "jean-avatar-state", text: "—" });
    ui.avatarEdit = el("button", { type: "button", class: "btn", text: "Editar mi personaje" });
    ui.avatarClose = el("button", { type: "button", class: "btn", text: "Cerrar el editor" });
    ui.close = el("button", { type: "button", class: "btn btn-small", text: "Cerrar" });

    ui.dialog = el(
      "dialog",
      { class: "dialog jean-dialog", id: "jean-dialog", "aria-labelledby": "jean-title" },
      el("div", { class: "jean-head" }, el("h2", { id: "jean-title", text: "Modo Jean" }), ui.close),
      ui.phase,
      el(
        "div",
        { class: "jean-layout" },
        el("div", { class: "jean-video-wrap" }, ui.canvas, ui.videoEmpty, ui.stats, ui.conn),
        el(
          "div",
          { class: "jean-side" },
          el("div", { class: "button-row" }, ui.start, ui.stop),
          ui.note,
          el(
            "section",
            { class: "jean-section" },
            el("h3", { text: "Tu micrófono" }),
            el("p", { class: "help warn-text", text: "Usa auriculares: si no, el stand se oye a sí mismo con retraso." }),
            ui.mic,
            el(
              "div",
              { class: "jean-modes", role: "radiogroup", "aria-label": "Cómo hablas" },
              el("label", {}, ui.modeOpen, " Micro abierto"),
              el("label", {}, ui.modePtt, " Pulsar para hablar"),
            ),
            ui.ptt,
            el("div", { class: "meter jean-meter", "aria-hidden": "true" }, ui.meterFill),
            ui.micState,
          ),
          el(
            "section",
            { class: "jean-section" },
            el("div", { class: "control-head" }, el("label", { class: "control-label", for: "jean-volume", text: "Sonido del stand" }), ui.volumeValue),
            ui.volume,
          ),
          el("section", { class: "jean-section" }, el("h3", { text: "Tus gestos" }), ui.animations),
          el(
            "section",
            { class: "jean-section" },
            el("h3", { text: "Tu avatar" }),
            el("p", {
              class: "help",
              text: "Se edita en la pantalla de Sonia, con su ratón, con el Modo Jean apagado. Al guardar queda en la nube para todas las Sonias.",
            }),
            ui.avatarState,
            el("div", { class: "button-row" }, ui.avatarEdit, ui.avatarClose),
          ),
        ),
      ),
    );
    document.body.append(ui.dialog);

    ui.close.addEventListener("click", closeDialog);
    ui.dialog.addEventListener("close", onDialogClosed);
    ui.start.addEventListener("click", () => sendAction("set_guest_mode", { active: true }));
    ui.stop.addEventListener("click", () => sendAction("set_guest_mode", { active: false }));
    ui.avatarEdit.addEventListener("click", () => sendAction("open_avatar_editor", { target: "guest" }));
    ui.avatarClose.addEventListener("click", () => sendAction("close_avatar_editor"));
    ui.mic.addEventListener("click", toggleMic);
    for (const radio of [ui.modeOpen, ui.modePtt]) {
      radio.addEventListener("change", () => {
        state.micMode = ui.modePtt.checked ? "ptt" : "open";
        renderMic();
      });
    }
    const press = (held) => {
      state.pttHeld = held;
      renderMic();
    };
    ui.ptt.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      press(true);
    });
    for (const name of ["pointerup", "pointercancel", "pointerleave"]) ui.ptt.addEventListener(name, () => press(false));
    window.addEventListener("keydown", (event) => {
      if (!state.open || event.code !== "Space" || event.repeat || isTyping(event.target)) return;
      event.preventDefault();
      press(true);
    });
    window.addEventListener("keyup", (event) => {
      if (!state.open || event.code !== "Space") return;
      press(false);
    });
    ui.volume.addEventListener("input", () => {
      const value = Number(ui.volume.value);
      setText(ui.volumeValue, `${value} %`);
      if (state.audio) state.audio.player.port.postMessage({ volume: value / 100 });
    });
  }

  function isTyping(target) {
    return target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) && target.type !== "radio" && target.type !== "range";
  }

  // ------------------------------------------------------------ abrir y cerrar

  async function openDialog() {
    const ui = state.ui;
    if (state.open) return;
    state.open = true;
    ui.dialog.showModal();
    note("");
    renderMic();
    pollStatus();
    state.statusTimer = setInterval(pollStatus, STATUS_POLL_MS);
    if (isLocalPanel()) {
      setConn("off", "La cámara y el micro solo van desde el panel de la nube (sonia.sonnetcode.com). Aquí puedes probar la entrada y los gestos.");
      return;
    }
    // Abrir el modal es un gesto del usuario: el audio del stand puede empezar ya.
    try {
      await ensureAudio();
    } catch {
      note("Este navegador no deja reproducir el sonido del stand.", "error");
    }
    connect();
  }

  function closeDialog() {
    state.ui.dialog.close();
  }

  function onDialogClosed() {
    state.open = false;
    clearInterval(state.statusTimer);
    state.statusTimer = null;
    clearTimeout(state.retryTimer);
    state.retryTimer = null;
    stopMic();
    if (state.ws) {
      const ws = state.ws;
      state.ws = null;
      ws.close(1000, "Modal cerrado");
    }
    if (state.audio) state.audio.player.port.postMessage({ reset: true });
  }

  // ------------------------------------------------------------ estado de Sonia

  async function pollStatus() {
    if (!state.open) return;
    try {
      const response = await fetch(withInstance("/api/status"), { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) return;
      const status = await response.json();
      state.status = status;
      const guest = status && typeof status.guest === "object" && status.guest ? status.guest : {};
      state.phase = typeof guest.phase === "string" ? guest.phase : "off";
      renderPhase();
      renderAnimations(Array.isArray(status.animations) ? status.animations : []);
    } catch {
      // El panel ya avisa de la conexión; aquí se reintenta en el siguiente sondeo.
    }
  }

  function renderPhase() {
    const ui = state.ui;
    const phase = PHASES[state.phase] ? state.phase : "off";
    setText(ui.phase, PHASES[phase]);
    ui.phase.dataset.phase = phase;
    const caps = new Set(Array.isArray(state.status && state.status.capabilities) ? state.status.capabilities : []);
    const supported = caps.has("guest_mode");
    const avatar = objectOf(state.status && state.status.avatar);
    const editorOpen = Boolean(avatar.editor_open);
    ui.start.disabled = !supported || phase !== "off" || editorOpen;
    ui.stop.disabled = !supported || phase === "off" || phase === "leaving";
    for (const button of ui.animations.querySelectorAll("button")) button.disabled = !supported || phase !== "live";
    renderAvatar(caps, phase, avatar);
    renderMic();
  }

  /** Estado del personaje de Jean y del editor (`avatar` y `guest_avatar` del estado). */
  function renderAvatar(caps, phase, avatar) {
    const ui = state.ui;
    const status = state.status || {};
    const editing = Boolean(avatar.editor_open);
    const editingMine = editing && avatar.editor_target === "guest";
    let text = objectOf(status.guest_avatar).custom ? "Tu personaje, guardado en la nube." : "Avatar de prueba de la app.";
    if (editingMine) text = "Editando tu personaje en la pantalla de Sonia…";
    else if (editing) text = "La pantalla de Sonia está en el editor del personaje de Sonia.";
    setText(ui.avatarState, text);
    ui.avatarState.dataset.state = editing ? "editing" : "idle";
    const supported = caps.has("guest_avatar_editor");
    ui.avatarEdit.disabled = !supported || editing || phase !== "off" || status.mode === "away";
    ui.avatarClose.disabled = !supported || !editing;
  }

  function objectOf(value) {
    return value && typeof value === "object" ? value : {};
  }

  function renderAnimations(list) {
    const ui = state.ui;
    const clips = list.filter((item) => item && typeof item.clip === "string").map((item) => item.clip);
    const key = clips.join("|");
    if (key === state.animationsKey) return;
    state.animationsKey = key;
    if (clips.length === 0) {
      ui.animations.replaceChildren(el("p", { class: "muted", text: "La app de Sonia no ha mandado su lista de animaciones." }));
      return;
    }
    ui.animations.replaceChildren(
      ...clips.map((clip) => {
        const button = el("button", { type: "button", class: "btn btn-small", text: prettyClip(clip) });
        button.addEventListener("click", () => sendAction("guest_animation", { clip }));
        return button;
      }),
    );
    renderPhase();
  }

  function prettyClip(clip) {
    return clip
      .replace(/^QuickAction_/, "")
      .replace(/^actions-(\d+-)?/, "")
      .replace(/_Trimmed$/, "")
      .replace(/[_-]+/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .trim();
  }

  // ------------------------------------------------------------ conexión con la sala

  function setConn(kind, text) {
    const ui = state.ui;
    ui.conn.dataset.state = kind;
    setText(ui.conn, text);
  }

  function connect() {
    if (!state.open || state.ws) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(withInstance(`${scheme}//${location.host}/api/guest`));
    ws.binaryType = "arraybuffer";
    state.ws = ws;
    let opened = false;
    setConn("connecting", "Conectando con el stand…");
    ws.addEventListener("open", () => {
      opened = true;
      state.retryMs = RETRY_MIN_MS;
      state.failedConnects = 0;
      setConn(state.agentConnected ? "live" : "waiting", state.agentConnected ? "Conectado al stand." : "Esperando a que Sonia se conecte…");
    });
    ws.addEventListener("message", (event) => onMessage(ws, event.data));
    ws.addEventListener("close", () => {
      if (state.ws !== ws) return;
      state.ws = null;
      state.agentConnected = false;
      if (!opened) state.failedConnects += 1;
      if (!state.open) return;
      const delay = state.retryMs;
      state.retryMs = Math.min(RETRY_MAX_MS, state.retryMs * 2);
      setConn(
        "retry",
        state.failedConnects >= 3 && !opened
          ? "No hay sala de vídeo aquí. El Modo Jean va desde sonia.sonnetcode.com con la Sonia conectada."
          : `Conexión cortada. Reintento en ${Math.round(delay / 1000)} s…`,
      );
      state.retryTimer = setTimeout(connect, delay);
    });
  }

  function onMessage(ws, data) {
    if (typeof data === "string") {
      let message = null;
      try {
        message = JSON.parse(data);
      } catch {
        return;
      }
      if (!message || typeof message !== "object") return;
      if (message.type === "agent") {
        state.agentConnected = message.connected === true;
        setConn(state.agentConnected ? "live" : "waiting", state.agentConnected ? "Conectado al stand." : "La Sonia del stand no está conectada a la sala.");
      } else if (message.type === "stats") {
        state.remoteStats = message;
        renderStats();
      }
      return;
    }
    if (!(data instanceof ArrayBuffer) || data.byteLength < HEADER_BYTES) return;
    const view = new DataView(data);
    if (view.getUint8(0) !== 0x53 || view.getUint8(1) !== 0x47 || view.getUint8(2) !== 1) return;
    const kind = view.getUint8(3);
    const seq = view.getUint32(4, true);
    const t = view.getUint32(8, true);
    const rate = view.getUint16(12, true);
    if (kind === KIND_VIDEO) showFrame(ws, data, seq, t);
    else if (kind === KIND_STAND_AUDIO && state.audio && rate) {
      const pcm = new Int16Array(data.slice(HEADER_BYTES));
      state.audio.player.port.postMessage({ pcm, rate }, [pcm.buffer]);
    }
  }

  async function showFrame(ws, data, seq, t) {
    const ui = state.ui;
    try {
      const bitmap = await createImageBitmap(new Blob([new Uint8Array(data, HEADER_BYTES)], { type: "image/jpeg" }));
      if (ui.canvas.width !== bitmap.width || ui.canvas.height !== bitmap.height) {
        ui.canvas.width = bitmap.width;
        ui.canvas.height = bitmap.height;
      }
      ui.canvas.getContext("2d").drawImage(bitmap, 0, 0);
      bitmap.close();
      ui.videoEmpty.hidden = true;
      countFrame();
    } catch {
      // Un fotograma roto no para el vídeo: se confirma igual para no atascar la ventana.
    }
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ack", seq, t }));
  }

  function countFrame() {
    const now = performance.now();
    state.framesShown += 1;
    if (now - state.lastFpsAt >= 1000) {
      state.fpsShown = (state.framesShown * 1000) / Math.max(1, now - state.lastFpsAt);
      state.framesShown = 0;
      state.lastFpsAt = now;
      renderStats();
    }
  }

  function renderStats() {
    const remote = state.remoteStats;
    const video = remote && remote.video ? remote.video : null;
    const parts = [`${state.fpsShown.toFixed(0)} fps`];
    if (video) {
      parts.push(`${Math.round(video.kbps || 0)} kbit/s`, `${video.width || "?"} px · calidad ${video.quality || "?"}`);
      if (typeof video.rtt_ms === "number") parts.push(`ida y vuelta ${Math.round(video.rtt_ms)} ms`);
    }
    if (state.droppedBlocks) parts.push(`voz perdida: ${state.droppedBlocks}`);
    setText(state.ui.stats, parts.join(" · "));
  }

  // ------------------------------------------------------------ audio

  async function ensureAudio() {
    if (state.audio) {
      await state.audio.ctx.resume();
      return state.audio;
    }
    const ctx = new AudioContext({ latencyHint: "interactive" });
    await ctx.audioWorklet.addModule("/static/jean-worklet.js");
    const player = new AudioWorkletNode(ctx, "jean-player", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2] });
    player.connect(ctx.destination);
    player.port.postMessage({ volume: Number(state.ui.volume.value) / 100 });
    // La captura no suena: va a un nodo mudo para que el gráfico la procese.
    const sink = ctx.createGain();
    sink.gain.value = 0;
    sink.connect(ctx.destination);
    state.audio = { ctx, player, sink, capture: null, stream: null, source: null };
    await ctx.resume();
    return state.audio;
  }

  async function toggleMic() {
    if (state.micOn) {
      stopMic();
      return;
    }
    try {
      const audio = await ensureAudio();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      const source = audio.ctx.createMediaStreamSource(stream);
      const capture = new AudioWorkletNode(audio.ctx, "jean-capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      capture.port.onmessage = (event) => onMicBlock(event.data || {});
      source.connect(capture);
      capture.connect(audio.sink);
      Object.assign(audio, { stream, source, capture });
      state.micOn = true;
    } catch {
      note("No se pudo abrir el micrófono: revisa el permiso del navegador.", "error");
    }
    renderMic();
  }

  function stopMic() {
    const audio = state.audio;
    if (audio && audio.stream) {
      for (const track of audio.stream.getTracks()) track.stop();
      audio.source.disconnect();
      audio.capture.disconnect();
      audio.capture.port.onmessage = null;
      Object.assign(audio, { stream: null, source: null, capture: null });
    }
    state.micOn = false;
    state.pttHeld = false;
    state.ui.meterFill.style.width = "0%";
    renderMic();
  }

  function transmitting() {
    return state.micOn && state.phase === "live" && (state.micMode === "open" || state.pttHeld);
  }

  function onMicBlock(data) {
    const level = typeof data.level === "number" ? data.level : 0;
    state.ui.meterFill.style.width = `${Math.min(100, Math.sqrt(level) * 220)}%`;
    if (!transmitting() || !data.pcm) return;
    const ws = state.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (ws.bufferedAmount > MAX_BUFFERED) {
      // La red no da abasto: mejor un hueco que un retraso que crece.
      state.droppedBlocks += 1;
      return;
    }
    const pcm = data.pcm;
    const frame = new ArrayBuffer(HEADER_BYTES + pcm.byteLength);
    const view = new DataView(frame);
    view.setUint8(0, 0x53);
    view.setUint8(1, 0x47);
    view.setUint8(2, 1);
    view.setUint8(3, KIND_GUEST_AUDIO);
    state.seqOut = (state.seqOut + 1) >>> 0;
    view.setUint32(4, state.seqOut, true);
    view.setUint32(8, Math.round(performance.now()) >>> 0, true);
    view.setUint16(12, data.rate || 24000, true);
    new Uint8Array(frame, HEADER_BYTES).set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength));
    ws.send(frame);
    state.sentBlocks += 1;
  }

  function renderMic() {
    const ui = state.ui;
    if (!ui.mic) return;
    setText(ui.mic, state.micOn ? "Apagar mi micrófono" : "Activar mi micrófono");
    ui.ptt.hidden = state.micMode !== "ptt";
    ui.ptt.disabled = !state.micOn;
    ui.ptt.classList.toggle("is-held", state.pttHeld);
    let text = "Micrófono apagado.";
    if (state.micOn) {
      if (state.phase !== "live") text = "Micrófono listo: se abre al stand cuando tu avatar ya está dentro.";
      else if (transmitting()) text = "Te están oyendo en el stand.";
      else text = "Mantén pulsado el botón o la barra espaciadora para hablar.";
    }
    setText(ui.micState, text);
    ui.micState.dataset.live = transmitting() ? "true" : "false";
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
