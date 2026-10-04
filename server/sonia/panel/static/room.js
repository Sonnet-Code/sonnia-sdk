/*
 * Sala de vídeo del stand en el panel: lo que comparten el modal del Modo Jean
 * (jean.js) y el de «Ver cámara» (camera.js).
 *
 *   - La conexión con /api/guest y sus reintentos. Con role "watch" la sala
 *     solo manda vídeo; con "guest" (Jean) también el micro del stand.
 *   - El vídeo: un JPEG por fotograma, pintado en un canvas y confirmado con un
 *     ack, con el que el stand ajusta tamaño, calidad y fps a la red.
 *   - Las estadísticas (fps, kbit/s, RTT y cuántos miran) y el envío de acciones.
 *
 * Nada se guarda: cada fotograma se pinta y se descarta. Formato de los frames
 * en docs/modo-jean.md.
 */
"use strict";

(() => {
  const STORAGE_KEY = "sonia-panel.instance";
  const HEADER_BYTES = 16;
  const KIND_VIDEO = 1;
  const KIND_STAND_AUDIO = 2;
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 10000;
  const ACTION_TIMEOUT_MS = 15000;

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

  /** Manda una acción a la Sonia elegida. Devuelve {ok, message}; nunca lanza. */
  async function action(name, params = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
    try {
      const body = { action: name, ...params };
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
      const ok = response.ok && Boolean(data) && data.ok !== false;
      const message = (data && typeof data.message === "string" && data.message) || (ok ? "Hecho." : "No se pudo.");
      return { ok, message };
    } catch {
      return { ok: false, message: "No se pudo enviar: revisa la conexión." };
    } finally {
      clearTimeout(timer);
    }
  }

  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  /**
   * Un visor de la sala. Opciones:
   *   role: "guest" (modal del Modo Jean) o "watch" (solo vídeo);
   *   canvas, empty, stats, conn: dónde pintar el vídeo, el aviso de «esperando
   *     la cámara», las estadísticas y el estado de la conexión;
   *   onStandAudio(pcm, rate): micro del stand (solo le llega a role "guest");
   *   onStats(stats): estadísticas del stand, una vez por segundo;
   *   extraStats(): texto que se añade a la línea de estadísticas.
   */
  function createViewer(options) {
    const state = {
      running: false,
      ws: null,
      retryMs: RETRY_MIN_MS,
      retryTimer: null,
      failedConnects: 0,
      agentConnected: false,
      framesShown: 0,
      fpsShown: 0,
      lastFpsAt: 0,
      remoteStats: null,
    };

    function setConn(kind, text) {
      if (!options.conn) return;
      options.conn.dataset.state = kind;
      setText(options.conn, text);
    }

    function start() {
      if (state.running) return;
      state.running = true;
      state.retryMs = RETRY_MIN_MS;
      state.failedConnects = 0;
      connect();
    }

    function stop() {
      state.running = false;
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
      const ws = state.ws;
      state.ws = null;
      state.agentConnected = false;
      if (ws) ws.close(1000, "Visor cerrado");
    }

    function connect() {
      if (!state.running || state.ws) return;
      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      const role = options.role === "watch" ? "?role=watch" : "";
      const ws = new WebSocket(withInstance(`${scheme}//${location.host}/api/guest${role}`));
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
        if (!state.running) return;
        const delay = state.retryMs;
        state.retryMs = Math.min(RETRY_MAX_MS, state.retryMs * 2);
        setConn(
          "retry",
          state.failedConnects >= 3 && !opened
            ? "No hay sala de vídeo aquí. La cámara en directo va desde sonia.sonnetcode.com con la Sonia conectada."
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
          if (!state.agentConnected) {
            state.agentConnected = true;
            setConn("live", "Conectado al stand.");
          }
          if (options.onStats) options.onStats(message);
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
      else if (kind === KIND_STAND_AUDIO && rate && options.onStandAudio) {
        options.onStandAudio(new Int16Array(data.slice(HEADER_BYTES)), rate);
      }
    }

    async function showFrame(ws, data, seq, t) {
      const canvas = options.canvas;
      try {
        const bitmap = await createImageBitmap(new Blob([new Uint8Array(data, HEADER_BYTES)], { type: "image/jpeg" }));
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
        }
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
        bitmap.close();
        if (options.empty) options.empty.hidden = true;
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
      if (!options.stats) return;
      const remote = state.remoteStats;
      const video = remote && remote.video ? remote.video : null;
      const parts = [`${state.fpsShown.toFixed(0)} fps`];
      if (video) {
        parts.push(`${Math.round(video.kbps || 0)} kbit/s`, `${video.width || "?"} px · calidad ${video.quality || "?"}`);
        if (typeof video.rtt_ms === "number") parts.push(`ida y vuelta ${Math.round(video.rtt_ms)} ms`);
      }
      const extra = options.extraStats ? options.extraStats() : "";
      if (extra) parts.push(extra);
      setText(options.stats, parts.join(" · "));
    }

    /** Vuelve a «esperando la cámara» (al reabrir el modal). */
    function reset() {
      state.remoteStats = null;
      state.fpsShown = 0;
      state.framesShown = 0;
      if (options.empty) options.empty.hidden = false;
      if (options.canvas) {
        const context = options.canvas.getContext("2d");
        if (context) context.clearRect(0, 0, options.canvas.width, options.canvas.height);
      }
      renderStats();
    }

    return {
      start,
      stop,
      reset,
      renderStats,
      setConn,
      /** El WebSocket si está abierto (para mandar la voz de Jean). */
      get socket() {
        return state.ws && state.ws.readyState === WebSocket.OPEN ? state.ws : null;
      },
    };
  }

  window.SoniaRoom = { instanceId, withInstance, isLocalPanel, action, createViewer, HEADER_BYTES };
})();
