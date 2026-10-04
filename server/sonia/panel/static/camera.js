/*
 * «Ver cámara»: la cámara del stand en directo desde el panel, sin el Modo Jean.
 *
 * El botón está en «Acciones rápidas» (index.html, id camera-btn). Al abrir el
 * modal se pide la sala con la acción watch_camera y se renueva cada
 * WATCH_KEEPALIVE_MS mientras siga abierto. El visor (room.js) entra con
 * role "watch": solo vídeo, sin el micro del stand. La sala la cierra el
 * orquestador cuando ya no mira nadie (al pulsar «Cerrar», casi al momento).
 * GPT-Live, Unity y el micro no se tocan.
 *
 * Privacidad: los fotogramas se pintan y se descartan; no se graba nada.
 */
"use strict";

(() => {
  const Room = window.SoniaRoom;
  const WATCH_KEEPALIVE_MS = 10000;

  const state = {
    ui: {},
    open: false,
    viewer: null,
    keepalive: null,
    viewers: 0,
  };

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("data-") || key.startsWith("aria-") || key === "role") node.setAttribute(key, value);
      else node[key] = value;
    }
    for (const child of children) if (child !== null && child !== undefined) node.append(child);
    return node;
  }

  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  function mount() {
    const button = document.getElementById("camera-btn");
    if (!button || !Room || state.ui.dialog) return;
    const ui = state.ui;
    ui.canvas = el("canvas", { class: "camera-video", width: 640, height: 360, "aria-label": "Cámara del stand en directo" });
    ui.empty = el("p", { class: "camera-empty", text: "Esperando la cámara del stand…" });
    ui.live = el("p", { class: "camera-live", "data-live": "false", role: "status", text: "Conectando…" });
    ui.stats = el("p", { class: "camera-stats", text: "—" });
    ui.conn = el("p", { class: "camera-conn", "data-state": "connecting", text: "Conectando con el stand…" });
    ui.error = el("p", { class: "camera-error", role: "alert", hidden: true });
    ui.close = el("button", { type: "button", class: "btn btn-small", text: "Cerrar" });
    ui.dialog = el(
      "dialog",
      { class: "dialog camera-dialog", id: "camera-dialog", "aria-labelledby": "camera-title" },
      el("div", { class: "camera-head" }, el("h2", { id: "camera-title", text: "Cámara del stand" }), ui.close),
      ui.live,
      el("div", { class: "camera-frame" }, ui.canvas, ui.empty),
      ui.stats,
      ui.conn,
      ui.error,
      el("p", {
        class: "camera-privacy",
        text: "Solo sale del stand mientras alguien la mira, sin sonido. No se graba nada.",
      }),
    );
    document.body.append(ui.dialog);
    state.viewer = Room.createViewer({
      role: "watch",
      canvas: ui.canvas,
      empty: ui.empty,
      stats: ui.stats,
      conn: ui.conn,
      onStats: (stats) => {
        if (typeof stats.viewers === "number") renderLive(stats.viewers);
      },
    });
    button.addEventListener("click", openDialog);
    // Se limpia al momento: Chrome retrasa el evento close hasta el siguiente
    // fotograma, que no llega con la pestaña en segundo plano.
    ui.close.addEventListener("click", () => {
      ui.dialog.close();
      onClosed();
    });
    ui.dialog.addEventListener("cancel", onClosed);
    ui.dialog.addEventListener("close", onClosed);
  }

  async function openDialog() {
    const ui = state.ui;
    if (state.open) return;
    state.open = true;
    state.viewers = 0;
    ui.error.hidden = true;
    renderLive(0);
    state.viewer.reset();
    ui.dialog.showModal();
    if (Room.isLocalPanel()) {
      state.viewer.setConn("off", "La cámara en directo va por el panel de la nube (sonia.sonnetcode.com): desde aquí no se ve.");
      setText(ui.live, "Sin directo en el panel local");
      return;
    }
    const result = await Room.action("watch_camera", { active: true });
    if (!state.open) return;
    if (!result.ok) {
      setText(ui.error, result.message);
      ui.error.hidden = false;
      setText(ui.live, "Sin directo");
      return;
    }
    state.keepalive = setInterval(() => Room.action("watch_camera", { active: true, keepalive: true }), WATCH_KEEPALIVE_MS);
    state.viewer.start();
  }

  function onClosed() {
    if (!state.open) return;
    state.open = false;
    if (state.keepalive) {
      clearInterval(state.keepalive);
      state.keepalive = null;
      Room.action("watch_camera", { active: false });
    }
    state.viewer.stop();
  }

  function renderLive(viewers) {
    state.viewers = viewers;
    const live = viewers > 0;
    state.ui.live.dataset.live = live ? "true" : "false";
    setText(state.ui.live, live ? `Cámara en directo: ${viewers} mirando` : "Conectando…");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
