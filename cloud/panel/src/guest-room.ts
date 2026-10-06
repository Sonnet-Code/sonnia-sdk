/**
 * Durable Object `GuestRoom`: la sala de vídeo de una Sonnia (una por id de
 * Sonnia, `idFromName(<id>)`), para el Modo Jean y para «Ver cámara». Solo
 * reenvía media entre el orquestador del stand (el agente, `/guest/agent`) y
 * los navegadores que miran (`/api/guest`). Hay dos clases de navegador:
 *
 * - El modal del Modo Jean (Jean): ve la cámara, oye el micro del stand y
 *   manda su voz.
 * - «Ver cámara» (`role=watch`): solo ve la cámara. No recibe el micro del
 *   stand y lo que mande en binario se descarta.
 *
 * Reglas:
 * - Binario del agente: la cámara JPEG va a todos; el micro del stand, solo a
 *   los del Modo Jean.
 * - Binario de un navegador del Modo Jean (voz de Jean, frames de tipo 3) → al agente.
 * - Texto de un navegador (`ack` de cada fotograma) → al agente; texto del
 *   agente (`stats`) → a los navegadores.
 * - Avisos propios: `viewers` {count, listeners} al agente cuando cambia quién
 *   mira (`listeners`: los que oyen el micro), y `agent` {connected} a los
 *   navegadores cuando entra o sale.
 *
 * No guarda nada (ni fotogramas ni audio), así que no le afecta hibernar; con
 * media fluyendo no llega a dormir. Formato de los frames en
 * `docs/modo-jean.md`. Va aparte de `ControlRoom` para que el vídeo no comparta
 * cola con el estado y las acciones.
 */

import { DurableObject } from "cloudflare:workers";
import type { Env } from "./env";

const AGENT_TAG = "agent";
const VIEWER_TAG = "viewer";
/** Navegador de «Ver cámara»: solo vídeo. */
const WATCH_TAG = "watch";
/** `WebSocket.readyState` abierto. */
const WS_OPEN = 1;
/** Tope de un mensaje binario (un JPEG grande ronda 100 KB). */
const MAX_BINARY_BYTES = 4 * 1024 * 1024;
/** Tope de un mensaje de texto (acks y estadísticas son diminutos). */
const MAX_TEXT_CHARS = 16 * 1024;
/** Tipo de frame del micro del stand (solo para el modal del Modo Jean). */
const KIND_STAND_AUDIO = 2;
/** Tipo de frame de la voz del invitado (lo único que un navegador puede mandar en binario). */
const KIND_GUEST_AUDIO = 3;

export class GuestRoom extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    // Latido opcional sin despertar al objeto.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('{"type":"ping"}', '{"type":"pong"}'));
  }

  override async fetch(request: Request): Promise<Response> {
    if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
      return new Response("Se esperaba un WebSocket.", { status: 426 });
    }
    const url = new URL(request.url);
    if (url.pathname === "/agent") return this.accept(AGENT_TAG);
    if (url.pathname === "/viewer") return this.accept(VIEWER_TAG, url.searchParams.get("role") === "watch");
    return new Response("No encontrado.", { status: 404 });
  }

  private accept(tag: string, watchOnly = false): Response {
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    if (tag === AGENT_TAG) {
      // Un agente nuevo de la misma Sonnia es ella reconectando: fuera el viejo.
      for (const old of this.ctx.getWebSockets(AGENT_TAG)) {
        try {
          old.close(4000, "Reemplazada por una conexión nueva");
        } catch {
          // Ya cerrada.
        }
      }
    }
    this.ctx.acceptWebSocket(server, watchOnly ? [tag, WATCH_TAG] : [tag]);
    if (tag === AGENT_TAG) {
      this.send(server, this.viewersMessage());
      this.broadcast(this.viewers(), JSON.stringify({ type: "agent", connected: true }));
    } else {
      this.send(server, JSON.stringify({ type: "agent", connected: this.agents().length > 0 }));
      this.notifyViewers();
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  override async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const fromAgent = this.ctx.getTags(ws).includes(AGENT_TAG);
    if (typeof message === "string") {
      if (message.length > MAX_TEXT_CHARS) return;
      if (fromAgent) this.broadcast(this.viewers(), message);
      else this.broadcast(this.agents(), message);
      return;
    }
    if (message.byteLength > MAX_BINARY_BYTES) return;
    if (fromAgent) {
      // El micro del stand solo va al modal del Modo Jean; la cámara, a todos.
      const kind = message.byteLength >= 4 ? new Uint8Array(message, 0, 4)[3] : 0;
      this.broadcast(kind === KIND_STAND_AUDIO ? this.listeners() : this.viewers(), message);
      return;
    }
    // «Ver cámara» no manda nada; del modal de Jean solo pasa su voz ("SG", versión, tipo 3).
    if (this.ctx.getTags(ws).includes(WATCH_TAG) || message.byteLength < 16) return;
    const head = new Uint8Array(message, 0, 4);
    if (head[0] !== 0x53 || head[1] !== 0x47 || head[3] !== KIND_GUEST_AUDIO) return;
    this.broadcast(this.agents(), message);
  }

  override async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    try {
      ws.close(code === 1005 || code === 1006 ? 1000 : code, reason);
    } catch {
      // El runtime ya respondió al cierre.
    }
    this.onGone(ws);
  }

  override async webSocketError(ws: WebSocket): Promise<void> {
    this.onGone(ws);
  }

  private onGone(ws: WebSocket): void {
    if (this.ctx.getTags(ws).includes(AGENT_TAG)) {
      if (this.agents(ws).length === 0) {
        this.broadcast(this.viewers(), JSON.stringify({ type: "agent", connected: false }));
      }
    } else {
      this.notifyViewers(ws);
    }
  }

  private notifyViewers(exclude?: WebSocket): void {
    this.broadcast(this.agents(), this.viewersMessage(exclude));
  }

  /** Cuántos miran y cuántos de ellos oyen el micro del stand. */
  private viewersMessage(exclude?: WebSocket): string {
    return JSON.stringify({
      type: "viewers",
      count: this.viewers(exclude).length,
      listeners: this.listeners(exclude).length,
    });
  }

  private agents(exclude?: WebSocket): WebSocket[] {
    return this.open(AGENT_TAG, exclude);
  }

  private viewers(exclude?: WebSocket): WebSocket[] {
    return this.open(VIEWER_TAG, exclude);
  }

  /** Navegadores del Modo Jean (los que no son de «Ver cámara»). */
  private listeners(exclude?: WebSocket): WebSocket[] {
    return this.viewers(exclude).filter((ws) => !this.ctx.getTags(ws).includes(WATCH_TAG));
  }

  private open(tag: string, exclude?: WebSocket): WebSocket[] {
    return this.ctx.getWebSockets(tag).filter((ws) => ws !== exclude && ws.readyState === WS_OPEN);
  }

  private broadcast(targets: WebSocket[], payload: string | ArrayBuffer): void {
    for (const ws of targets) this.send(ws, payload);
  }

  private send(ws: WebSocket, payload: string | ArrayBuffer): void {
    try {
      ws.send(payload);
    } catch {
      // Conexión cerrándose: ya llegará `webSocketClose`.
    }
  }
}
