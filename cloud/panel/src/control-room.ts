/**
 * Durable Object `ControlRoom`: una única instancia (`idFromName("control")`)
 * que conoce a todas las Sonias conectadas y a todos los navegadores del panel.
 *
 * - Cada Sonia (agente) mantiene un WebSocket saliente hacia `/agent`. Manda
 *   `hello`, `status`, `message`, `log` y `result`; recibe `action`, `viewers`
 *   y `sync` (ver `docs/panel.md`).
 * - Cada navegador abre `/api/events` y recibe `instances`, `history`,
 *   `status`, `message` y `log` de la Sonia que mira; puede mandar `select`.
 * - La API HTTP del navegador llega por RPC desde el Worker (`getInstances`,
 *   `getStatus`, `getGalleryIds`, `runAction`).
 *
 * Consumo (plan free): todo usa la API de hibernación de WebSockets; no hay
 * `setInterval` ni alarmas, así que el objeto duerme en cuanto nadie le habla.
 * Al hibernar se pierde lo que hay en memoria (estado, conversación y
 * registro de cada Sonia); se pide de nuevo con `sync` solo cuando algún
 * navegador lo necesita. En el almacenamiento (SQLite, API kv) solo se guarda
 * un resumen pequeño de cada Sonia, con pocas escrituras, para que las
 * desconectadas de las últimas 2 horas sobrevivan a la hibernación.
 */

import { DurableObject } from "cloudflare:workers";
import type { Env } from "./env";

/** Mensajes de conversación que se guardan para el historial. */
const MAX_MESSAGES = 80;
/** Líneas de registro que se guardan para el historial. */
const MAX_LOGS = 200;
/** Las desconectadas se siguen listando durante este tiempo. */
const KEEP_DISCONNECTED_MS = 2 * 60 * 60 * 1000;
/** Tiempo máximo de espera del `result` de una acción. */
const ACTION_TIMEOUT_MS = 15_000;
/**
 * Sin ningún mensaje de una Sonia en este tiempo, su conexión se da por
 * muerta (manda `status` al menos cada 15 s).
 */
const AGENT_STALE_MS = 75_000;
/** No repetir `sync` a la misma Sonia antes de este tiempo. */
const SYNC_RETRY_MS = 10_000;
/** `GET /api/status` espera como mucho esto a que llegue el estado tras un `sync`. */
const STATUS_WAIT_MS = 3_000;
/** Guardar el resumen como mucho cada este tiempo si ha cambiado algo importante. */
const PERSIST_CHANGED_MS = 10_000;
/** Y como mucho cada este tiempo aunque no cambie (para `last_seen`). */
const PERSIST_IDLE_MS = 60_000;
/** Tipos de mensaje que entran en el historial (igual que el panel local). */
const HISTORY_TYPES = new Set(["transcript", "show_image", "hide_image", "presence", "error"]);
/** Prefijo de las claves de los resúmenes en el almacenamiento. */
const KV_PREFIX = "instance:";
/** Etiqueta de los WebSocket de navegadores. */
const BROWSER_TAG = "browser";
/** Etiqueta común de los WebSocket de agentes. */
const AGENT_TAG = "agent";
/** `WebSocket.readyState` abierto. */
const WS_OPEN = 1;

type Json = Record<string, unknown>;

/** Resumen de una Sonia, como sale en `GET /api/instances`. */
export interface InstanceSummary {
  id: string;
  name: string;
  host: string;
  connected: boolean;
  last_seen: number;
  mode: string | null;
  state: string | null;
  engine: string | null;
  version: string | null;
  healthy: boolean;
  issues: string[];
  cost_usd: number | null;
}

export interface InstancesPayload {
  instances: InstanceSummary[];
  conflicts: { connected: string[]; conversing: string[] };
}

/** Respuesta interna de la API (código HTTP y cuerpo JSON). */
interface ApiResult {
  status: number;
  body: Json;
}

/** Respuesta de la API por RPC: el cuerpo ya serializado en JSON. */
export interface ApiResponse {
  status: number;
  body: string;
}

function toResponse(result: ApiResult): ApiResponse {
  return { status: result.status, body: JSON.stringify(result.body) };
}

/** Lo que se guarda de cada Sonia (sobrevive a la hibernación). */
interface StoredInstance {
  id: string;
  name: string;
  host: string;
  engine: string | null;
  version: string | null;
  mode: string | null;
  state: string | null;
  healthy: boolean;
  issues: string[];
  cost_usd: number | null;
  gallery: string[] | null;
  last_seen: number;
}

/** Lo que solo vive en memoria (se pierde al hibernar). */
interface LiveState {
  status: Json | null;
  messages: Json[];
  logs: Json[];
  /** ¿Tenemos el historial completo (llegó un `hello` desde que despertamos)? */
  synced: boolean;
  syncRequestedAt: number;
  /** Peticiones de `/api/status` esperando a que llegue el estado. */
  statusWaiters: Array<() => void>;
}

interface AgentAttachment {
  kind: "agent";
  id: string;
  connectedAt: number;
  lastSeen: number;
  /** Último `viewers` mandado (-1: ninguno todavía). */
  viewersSent: number;
}

interface BrowserAttachment {
  kind: "browser";
  /** Sonia que mira este navegador (o ninguna si no hay). */
  instance: string | null;
  /** ¿La eligió el navegador? Si no, sigue a la primera conectada. */
  explicit: boolean;
}

type Attachment = AgentAttachment | BrowserAttachment;

interface PendingAction {
  instance: string;
  finish: (result: ApiResult) => void;
}

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function agentTag(id: string): string {
  return `agent:${id}`;
}

/** Hora local de Santo Domingo (`HH:MM:SS`) para mensajes sin hora. */
function clock(): string {
  return new Date().toLocaleTimeString("es-DO", {
    hourCycle: "h23",
    timeZone: "America/Santo_Domingo",
  });
}

/** Copia para el panel: sin imágenes en base64 y con hora. */
function cleanMessage(message: Json): Json {
  const { data_base64: _omit, ...rest } = message;
  if (typeof rest.time !== "string") rest.time = clock();
  return rest;
}

/** ¿Está bien según su salud? Frases cortas de lo que falla. */
function healthOf(status: Json): { healthy: boolean; issues: string[] } {
  const issues: string[] = [];
  const health = status.health;
  if (isObject(health)) {
    for (const entry of Object.values(health)) {
      if (isObject(entry) && entry.ok === false) {
        issues.push(typeof entry.label === "string" && entry.label ? entry.label : "Algo falla");
      }
    }
  }
  return { healthy: issues.length === 0, issues };
}

function persistSignature(record: StoredInstance): string {
  return JSON.stringify([
    record.name,
    record.host,
    record.engine,
    record.version,
    record.mode,
    record.healthy,
    record.issues,
    record.gallery,
  ]);
}

export class ControlRoom extends DurableObject<Env> {
  /** Resumen de cada Sonia conocida (memoria + almacenamiento). */
  private readonly known = new Map<string, StoredInstance>();
  /** Estado en memoria de cada Sonia. */
  private readonly live = new Map<string, LiveState>();
  /** Cuándo y con qué contenido se guardó por última vez cada resumen. */
  private readonly persisted = new Map<string, { at: number; signature: string }>();
  /** Acciones esperando su `result`. */
  private readonly pending = new Map<string, PendingAction>();
  /** Última lista de instancias repartida a los navegadores (para no repetirla). */
  private lastInstancesSignature = "";

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    const now = Date.now();
    for (const [, value] of ctx.storage.kv.list<StoredInstance>({ prefix: KV_PREFIX })) {
      if (!isObject(value) || typeof value.id !== "string") continue;
      this.known.set(value.id, value);
      this.persisted.set(value.id, { at: now, signature: persistSignature(value) });
    }
    // Latido opcional sin despertar al objeto: `{"type":"ping"}` → `{"type":"pong"}`.
    ctx.setWebSocketAutoResponse(
      new WebSocketRequestResponsePair('{"type":"ping"}', '{"type":"pong"}'),
    );
  }

  // ================================================================ conexiones

  override async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
      return new Response("Se esperaba un WebSocket.", { status: 426 });
    }
    if (url.pathname === "/agent") {
      const id = url.searchParams.get("id") ?? "";
      const name = url.searchParams.get("name") ?? "";
      if (!id) return new Response("Falta el id.", { status: 400 });
      return this.acceptAgent(id, name || id);
    }
    if (url.pathname === "/events") {
      return this.acceptBrowser(url.searchParams.get("instance"));
    }
    return new Response("No encontrado.", { status: 404 });
  }

  private acceptAgent(id: string, name: string): Response {
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    const now = Date.now();

    // Una conexión anterior con el mismo id es la misma Sonia reconectando.
    for (const old of this.ctx.getWebSockets(agentTag(id))) {
      try {
        old.close(4000, "Reemplazada por una conexión nueva");
      } catch {
        // Ya estaba cerrada.
      }
    }
    this.failPending(id, 503, "Sonia se reconectó antes de responder. Inténtalo de nuevo.");

    this.ctx.acceptWebSocket(server, [AGENT_TAG, agentTag(id)]);
    const attachment: AgentAttachment = {
      kind: "agent",
      id,
      connectedAt: now,
      lastSeen: now,
      viewersSent: -1,
    };
    server.serializeAttachment(attachment);

    const record = this.known.get(id) ?? this.newRecord(id, name);
    record.name = name;
    record.last_seen = now;
    this.known.set(id, record);
    this.persist(id, true);
    // Lo de antes en memoria ya no vale: el `hello` que la Sonia manda al
    // conectar trae el historial nuevo, así que no hace falta pedir `sync`.
    const live = this.newLive();
    live.syncRequestedAt = now;
    this.live.set(id, live);

    this.adoptOrphanBrowsers();
    this.updateViewers();
    this.broadcastInstances(true);
    return new Response(null, { status: 101, webSocket: client });
  }

  private acceptBrowser(requested: string | null): Response {
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    const listed = new Set(this.list().instances.map((item) => item.id));
    const explicit = Boolean(requested && listed.has(requested));
    const attachment: BrowserAttachment = {
      kind: "browser",
      instance: explicit ? requested : this.defaultInstance(),
      explicit,
    };
    this.ctx.acceptWebSocket(server, [BROWSER_TAG]);
    server.serializeAttachment(attachment);

    this.sendInstances(server, attachment);
    this.sendHistoryAndStatus(server, attachment.instance);
    this.updateViewers();
    return new Response(null, { status: 101, webSocket: client });
  }

  override async webSocketMessage(ws: WebSocket, data: string | ArrayBuffer): Promise<void> {
    if (typeof data !== "string" || data.length > 4 * 1024 * 1024) return;
    let message: unknown;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    if (!isObject(message)) return;
    const attachment = ws.deserializeAttachment() as Attachment | null;
    if (attachment?.kind === "agent") this.onAgentMessage(ws, attachment, message);
    else if (attachment?.kind === "browser") this.onBrowserMessage(ws, attachment, message);
  }

  override async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    try {
      // 1005/1006 no se pueden mandar: se cierra con un código normal.
      ws.close(code === 1005 || code === 1006 ? 1000 : code, reason);
    } catch {
      // El runtime ya respondió al cierre.
    }
    this.onSocketGone(ws);
  }

  override async webSocketError(ws: WebSocket): Promise<void> {
    this.onSocketGone(ws);
  }

  private onSocketGone(ws: WebSocket): void {
    const attachment = ws.deserializeAttachment() as Attachment | null;
    if (attachment?.kind === "agent") this.onAgentGone(ws, attachment);
    else if (attachment?.kind === "browser") this.updateViewers(ws);
  }

  // ================================================================ agentes

  private onAgentMessage(ws: WebSocket, attachment: AgentAttachment, message: Json): void {
    const id = attachment.id;
    const now = Date.now();
    attachment.lastSeen = now;
    ws.serializeAttachment(attachment);

    let record = this.known.get(id);
    if (!record) {
      // Recién despertado y sin resumen guardado (no debería pasar): se rehace.
      record = this.newRecord(id, id);
      this.known.set(id, record);
    }
    record.last_seen = now;
    let live = this.live.get(id);
    if (!live) {
      // Despertamos de la hibernación: no hay historial en memoria.
      live = this.newLive();
      this.live.set(id, live);
    }

    switch (message.type) {
      case "hello":
        this.onHello(id, record, live, message);
        break;
      case "status":
        if (isObject(message.status)) this.onStatus(id, record, live, message.status);
        break;
      case "message":
        if (isObject(message.message)) this.onConversation(id, record, live, message.message);
        break;
      case "log":
        this.onLog(id, live, message);
        break;
      case "result":
        this.onResult(id, message);
        break;
      default:
        break;
    }
    this.persist(id);

    // Si alguien mira esta Sonia y no tenemos su historial, se le pide.
    if (!live.synced && this.viewerCount(id) > 0) this.requestSync(ws, live);
  }

  private onHello(id: string, record: StoredInstance, live: LiveState, message: Json): void {
    const instance = isObject(message.instance) ? message.instance : {};
    const name = str(instance.name)?.trim();
    if (name) record.name = name.slice(0, 80);
    const host = str(instance.host);
    if (host !== null) record.host = host.slice(0, 120);
    const engine = str(instance.engine);
    if (engine !== null) record.engine = engine;
    const version = str(instance.version);
    if (version !== null) record.version = version;

    const history = isObject(message.history) ? message.history : {};
    const messages = Array.isArray(history.messages) ? history.messages : [];
    const logs = Array.isArray(history.logs) ? history.logs : [];
    live.messages = messages.filter(isObject).map(cleanMessage).slice(-MAX_MESSAGES);
    live.logs = logs.filter(isObject).slice(-MAX_LOGS);
    if (Array.isArray(message.gallery)) {
      record.gallery = message.gallery
        .filter((item): item is string => typeof item === "string" && item.length > 0)
        .slice(0, 500);
    }
    if (isObject(message.status)) this.applyStatus(record, live, message.status);
    live.synced = true;
    this.persist(id, true);

    for (const browser of this.browsersWatching(id)) this.sendHistoryAndStatus(browser, id);
    this.wakeStatusWaiters(live);
    this.broadcastInstances();
  }

  private onStatus(id: string, record: StoredInstance, live: LiveState, status: Json): void {
    this.applyStatus(record, live, status);
    const watchers = this.browsersWatching(id);
    if (watchers.length > 0) {
      const payload = JSON.stringify({ type: "status", instance: id, status: this.statusFor(id) });
      for (const browser of watchers) this.send(browser, payload);
    }
    this.wakeStatusWaiters(live);
    this.broadcastInstances();
  }

  private applyStatus(record: StoredInstance, live: LiveState, status: Json): void {
    live.status = status;
    record.mode = str(status.mode);
    record.state = str(status.state);
    record.engine = str(status.engine) ?? record.engine;
    const { healthy, issues } = healthOf(status);
    record.healthy = healthy;
    record.issues = issues;
    const usage = status.usage;
    const cost = isObject(usage) ? usage.cost_usd : null;
    record.cost_usd = typeof cost === "number" && Number.isFinite(cost) ? cost : null;
  }

  private onConversation(id: string, record: StoredInstance, live: LiveState, raw: Json): void {
    const message = cleanMessage(raw);
    const kind = message.type;
    if (typeof kind === "string" && HISTORY_TYPES.has(kind) && (kind !== "transcript" || message.final)) {
      live.messages.push(message);
      if (live.messages.length > MAX_MESSAGES) live.messages.splice(0, live.messages.length - MAX_MESSAGES);
    }
    if (kind === "state" && typeof message.state === "string") {
      record.state = message.state;
      if (live.status) live.status = { ...live.status, state: message.state };
    }
    const watchers = this.browsersWatching(id);
    if (watchers.length > 0) {
      const payload = JSON.stringify({ type: "message", instance: id, message });
      for (const browser of watchers) this.send(browser, payload);
    }
  }

  private onLog(id: string, live: LiveState, message: Json): void {
    const line: Json = {
      level: str(message.level) ?? "INFO",
      time: str(message.time) ?? clock(),
      text: str(message.text) ?? "",
    };
    live.logs.push(line);
    if (live.logs.length > MAX_LOGS) live.logs.splice(0, live.logs.length - MAX_LOGS);
    const watchers = this.browsersWatching(id);
    if (watchers.length > 0) {
      const payload = JSON.stringify({ type: "log", instance: id, ...line });
      for (const browser of watchers) this.send(browser, payload);
    }
  }

  private onResult(id: string, message: Json): void {
    const requestId = str(message.request_id);
    if (!requestId) return;
    const pending = this.pending.get(requestId);
    if (!pending || pending.instance !== id) return;
    const ok = message.ok === true;
    const text = str(message.message) ?? (ok ? "Listo." : "Sonia no pudo hacerlo.");
    pending.finish({ status: ok ? 200 : 400, body: { ok, message: text } });
  }

  private onAgentGone(ws: WebSocket, attachment: AgentAttachment): void {
    const id = attachment.id;
    // Si ya hay otra conexión más nueva de la misma Sonia, no se ha ido.
    if (this.agentSocket(id, ws)) return;
    const record = this.known.get(id);
    if (record) {
      // Desconectada ahora; si el cierre llega muy tarde (conexión muerta), poco
      // después de su último mensaje.
      record.last_seen = Math.min(Date.now(), attachment.lastSeen + AGENT_STALE_MS);
      this.persist(id, true);
    }
    this.failPending(id, 503, "Sonia se desconectó antes de responder.");

    // Los navegadores que no eligieron Sonia pasan a otra conectada, si la hay.
    const fallback = this.firstConnected(ws);
    for (const browser of this.browsers()) {
      const browserAttachment = browser.deserializeAttachment() as BrowserAttachment;
      if (browserAttachment.instance !== id) continue;
      if (!browserAttachment.explicit && fallback) {
        browserAttachment.instance = fallback;
        browser.serializeAttachment(browserAttachment);
        this.sendHistoryAndStatus(browser, fallback, ws);
      } else if (this.live.get(id)?.status) {
        // Se queda mirándola: que vea que está desconectada.
        this.send(browser, JSON.stringify({ type: "status", instance: id, status: this.statusFor(id, ws) }));
      }
    }
    this.updateViewers(undefined, ws);
    this.broadcastInstances(true, ws);
  }

  /** Pide a la Sonia que repita su `hello` (sin repetirlo demasiado). */
  private requestSync(ws: WebSocket, live: LiveState): void {
    const now = Date.now();
    if (now - live.syncRequestedAt < SYNC_RETRY_MS) return;
    live.syncRequestedAt = now;
    this.send(ws, '{"type":"sync"}');
  }

  /**
   * El WebSocket abierto de una Sonia (el más reciente), o `null`.
   *
   * Si lleva demasiado sin decir nada, su conexión se da por muerta y se
   * cierra (la Sonia, si sigue viva, reconecta sola).
   */
  private agentSocket(id: string, exclude?: WebSocket): WebSocket | null {
    let best: WebSocket | null = null;
    let bestAt = -1;
    const now = Date.now();
    for (const ws of this.ctx.getWebSockets(agentTag(id))) {
      if (ws === exclude || ws.readyState !== WS_OPEN) continue;
      const attachment = ws.deserializeAttachment() as AgentAttachment;
      // Un `{"type":"ping"}` respondido sin despertar al objeto también cuenta como señal de vida.
      const pinged = this.ctx.getWebSocketAutoResponseTimestamp(ws)?.getTime() ?? 0;
      if (now - Math.max(attachment.lastSeen, pinged) > AGENT_STALE_MS) {
        try {
          ws.close(4001, "Sin noticias de esta Sonia");
        } catch {
          // Ya cerrada.
        }
        continue;
      }
      if (attachment.connectedAt > bestAt) {
        best = ws;
        bestAt = attachment.connectedAt;
      }
    }
    return best;
  }

  private agentAttachment(id: string, exclude?: WebSocket): AgentAttachment | null {
    const ws = this.agentSocket(id, exclude);
    return ws ? (ws.deserializeAttachment() as AgentAttachment) : null;
  }

  /** Id de la primera Sonia conectada (la que lleva más tiempo). */
  private firstConnected(exclude?: WebSocket): string | null {
    return this.list(exclude).instances.find((item) => item.connected)?.id ?? null;
  }

  /** Sonia por defecto: la primera conectada o, si no hay, la última vista. */
  private defaultInstance(exclude?: WebSocket): string | null {
    const { instances } = this.list(exclude);
    return (instances.find((item) => item.connected) ?? instances[0])?.id ?? null;
  }

  private failPending(id: string, status: number, message: string): void {
    for (const pending of [...this.pending.values()]) {
      if (pending.instance === id) pending.finish({ status, body: { ok: false, message } });
    }
  }

  // ================================================================ navegadores

  private onBrowserMessage(ws: WebSocket, attachment: BrowserAttachment, message: Json): void {
    if (message.type !== "select") return;
    const requested = str(message.instance);
    const listed = new Set(this.list().instances.map((item) => item.id));
    if (requested && listed.has(requested)) {
      attachment.instance = requested;
      attachment.explicit = true;
      ws.serializeAttachment(attachment);
      this.updateViewers();
    }
    this.sendInstances(ws, attachment);
    this.sendHistoryAndStatus(ws, attachment.instance);
  }

  private browsers(exclude?: WebSocket): WebSocket[] {
    return this.ctx
      .getWebSockets(BROWSER_TAG)
      .filter((ws) => ws !== exclude && ws.readyState === WS_OPEN);
  }

  private browsersWatching(id: string): WebSocket[] {
    return this.browsers().filter(
      (ws) => (ws.deserializeAttachment() as BrowserAttachment).instance === id,
    );
  }

  private viewerCount(id: string): number {
    return this.browsersWatching(id).length;
  }

  /** Navegadores que no miraban ninguna Sonia (no había) pasan a la primera conectada. */
  private adoptOrphanBrowsers(): void {
    const target = this.firstConnected();
    if (!target) return;
    const listed = new Set(this.list().instances.map((item) => item.id));
    for (const ws of this.browsers()) {
      const attachment = ws.deserializeAttachment() as BrowserAttachment;
      const orphan = attachment.instance === null || !listed.has(attachment.instance);
      // Quien no eligió y miraba una desconectada también pasa a la conectada.
      const follower =
        !attachment.explicit && attachment.instance !== target && !this.agentSocket(attachment.instance ?? "");
      if (!orphan && !follower) continue;
      attachment.instance = target;
      attachment.explicit = false;
      ws.serializeAttachment(attachment);
      this.sendHistoryAndStatus(ws, target);
    }
  }

  /** Manda `viewers` a cada Sonia cuyo número de navegadores mirándola ha cambiado. */
  private updateViewers(excludeBrowser?: WebSocket, excludeAgent?: WebSocket): void {
    const counts = new Map<string, number>();
    for (const ws of this.browsers(excludeBrowser)) {
      const id = (ws.deserializeAttachment() as BrowserAttachment).instance;
      if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    for (const ws of this.ctx.getWebSockets(AGENT_TAG)) {
      if (ws === excludeAgent || ws.readyState !== WS_OPEN) continue;
      const attachment = ws.deserializeAttachment() as AgentAttachment;
      const count = counts.get(attachment.id) ?? 0;
      if (attachment.viewersSent === count) continue;
      attachment.viewersSent = count;
      ws.serializeAttachment(attachment);
      this.send(ws, JSON.stringify({ type: "viewers", count }));
      // Alguien empieza a mirar una Sonia de la que no tenemos historial.
      const live = this.live.get(attachment.id);
      if (count > 0 && (!live || !live.synced)) {
        const state = live ?? this.newLive();
        this.live.set(attachment.id, state);
        this.requestSync(ws, state);
      }
    }
  }

  private sendInstances(ws: WebSocket, attachment: BrowserAttachment, exclude?: WebSocket): void {
    this.send(
      ws,
      JSON.stringify({ type: "instances", ...this.list(exclude), selected: attachment.instance }),
    );
  }

  /**
   * Historial y último estado de una Sonia para un navegador.
   *
   * Siempre va un `history` (vacío si no hay nada, por ejemplo una Sonia
   * desconectada tras hibernar) y después su `status` si lo tenemos. Si está
   * conectada pero no tenemos su historial (el objeto hibernó), se le pide
   * `sync`: su `hello` volverá a mandar `history` y `status` a quien la mire.
   */
  private sendHistoryAndStatus(ws: WebSocket, id: string | null, excludeAgent?: WebSocket): void {
    if (!id) return;
    let live = this.live.get(id);
    const agent = this.agentSocket(id, excludeAgent);
    if (agent && !live?.synced) {
      live ??= this.newLive();
      this.live.set(id, live);
      this.requestSync(agent, live);
    }
    this.send(
      ws,
      JSON.stringify({
        type: "history",
        instance: id,
        messages: live?.messages ?? [],
        logs: live?.logs ?? [],
      }),
    );
    if (live?.status) {
      this.send(
        ws,
        JSON.stringify({ type: "status", instance: id, status: this.statusFor(id, excludeAgent) }),
      );
    }
  }

  /** Reparte `instances` a todos los navegadores si ha cambiado la lista o el modo de alguna. */
  private broadcastInstances(force = false, exclude?: WebSocket): void {
    const payload = this.list(exclude);
    const signature = JSON.stringify([
      payload.instances.map((item) => [
        item.id,
        item.name,
        item.connected,
        item.mode,
        item.engine,
        item.healthy,
        item.issues,
      ]),
      payload.conflicts,
    ]);
    if (!force && signature === this.lastInstancesSignature) return;
    this.lastInstancesSignature = signature;
    for (const ws of this.browsers()) {
      const attachment = ws.deserializeAttachment() as BrowserAttachment;
      this.send(ws, JSON.stringify({ type: "instances", ...payload, selected: attachment.instance }));
    }
  }

  private send(ws: WebSocket, payload: string): void {
    try {
      ws.send(payload);
    } catch {
      // Conexión cerrándose: ya llegará `webSocketClose`.
    }
  }

  // ================================================================ estado

  private newRecord(id: string, name: string): StoredInstance {
    return {
      id,
      name,
      host: "",
      engine: null,
      version: null,
      mode: null,
      state: null,
      healthy: false,
      issues: [],
      cost_usd: null,
      gallery: null,
      last_seen: Date.now(),
    };
  }

  private newLive(): LiveState {
    return {
      status: null,
      messages: [],
      logs: [],
      synced: false,
      syncRequestedAt: 0,
      statusWaiters: [],
    };
  }

  /**
   * Guarda el resumen de una Sonia, con pocas escrituras: al conectar y
   * desconectar (`force`), si cambia algo importante (como mucho cada 10 s) y
   * al menos cada minuto para que `last_seen` no quede muy atrás.
   */
  private persist(id: string, force = false): void {
    const record = this.known.get(id);
    if (!record) return;
    const now = Date.now();
    const signature = persistSignature(record);
    const previous = this.persisted.get(id);
    if (!force && previous) {
      const elapsed = now - previous.at;
      const changed = signature !== previous.signature;
      if (!(changed && elapsed >= PERSIST_CHANGED_MS) && elapsed < PERSIST_IDLE_MS) return;
    }
    this.ctx.storage.kv.put(KV_PREFIX + id, record);
    this.persisted.set(id, { at: now, signature });
  }

  private summary(id: string, exclude?: WebSocket): InstanceSummary | null {
    const record = this.known.get(id);
    if (!record) return null;
    const attachment = this.agentAttachment(id, exclude);
    return {
      id,
      name: record.name,
      host: record.host,
      connected: attachment !== null,
      last_seen: attachment ? Math.max(attachment.lastSeen, record.last_seen) : record.last_seen,
      mode: record.mode,
      state: record.state,
      engine: record.engine,
      version: record.version,
      healthy: record.healthy,
      issues: record.issues,
      cost_usd: record.cost_usd,
    };
  }

  /** La instantánea de `/api/status` de una Sonia, con `instance`. */
  private statusFor(id: string, exclude?: WebSocket): Json {
    const instance = this.summary(id, exclude);
    const status = this.live.get(id)?.status;
    if (status) return { ...status, instance };
    // Sin estado en memoria (desconectada y tras hibernar): lo que sabemos.
    return {
      engine: instance?.engine ?? null,
      mode: instance?.mode ?? null,
      state: instance?.state ?? null,
      health: {},
      capabilities: [],
      instance,
    };
  }

  private wakeStatusWaiters(live: LiveState): void {
    if (!live.status) return;
    const waiters = live.statusWaiters.splice(0);
    for (const wake of waiters) wake();
  }

  /** Lista de Sonias: conectadas primero (la más antigua delante) y luego desconectadas recientes. */
  private list(exclude?: WebSocket): InstancesPayload {
    const now = Date.now();
    const connected: Array<{ summary: InstanceSummary; since: number }> = [];
    const disconnected: InstanceSummary[] = [];
    for (const id of [...this.known.keys()]) {
      const summary = this.summary(id, exclude);
      if (!summary) continue;
      if (summary.connected) {
        const since = this.agentAttachment(id, exclude)?.connectedAt ?? summary.last_seen;
        connected.push({ summary, since });
      } else if (now - summary.last_seen <= KEEP_DISCONNECTED_MS) {
        disconnected.push(summary);
      } else {
        // Desconectada hace más de 2 horas: se olvida.
        this.known.delete(id);
        this.live.delete(id);
        this.persisted.delete(id);
        this.ctx.storage.kv.delete(KV_PREFIX + id);
      }
    }
    connected.sort((a, b) => a.since - b.since || a.summary.name.localeCompare(b.summary.name));
    disconnected.sort((a, b) => b.last_seen - a.last_seen);
    const instances = [...connected.map((item) => item.summary), ...disconnected];
    const online = instances.filter((item) => item.connected);
    const conversing = online.filter((item) => item.mode === "conversation");
    return {
      instances,
      conflicts: {
        connected: online.length > 1 ? online.map((item) => item.id) : [],
        conversing: conversing.length > 1 ? conversing.map((item) => item.id) : [],
      },
    };
  }

  // ================================================================ RPC (API HTTP del navegador)

  /** `GET /api/instances`. */
  async getInstances(): Promise<InstancesPayload> {
    return this.list();
  }

  /** Resuelve el parámetro `instance` (si falta, la Sonia por defecto). */
  private resolveInstance(instance: string | null): string | null {
    return instance || this.defaultInstance();
  }

  async getStatus(instance: string | null): Promise<ApiResponse> {
    return toResponse(await this.statusResult(instance));
  }

  private async statusResult(instance: string | null): Promise<ApiResult> {
    const id = this.resolveInstance(instance);
    if (!id) return { status: 404, body: { ok: false, message: "No hay ninguna Sonia conectada." } };
    if (!this.list().instances.some((item) => item.id === id)) {
      return { status: 404, body: { ok: false, message: "No conozco esa Sonia." } };
    }
    const agent = this.agentSocket(id);
    let live = this.live.get(id);
    if (agent && !live?.status) {
      // Recién despertado: se pide el `hello` y se espera un poco.
      if (!live) {
        live = this.newLive();
        this.live.set(id, live);
      }
      this.requestSync(agent, live);
      const state = live;
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, STATUS_WAIT_MS);
        state.statusWaiters.push(() => {
          clearTimeout(timer);
          resolve();
        });
      });
      if (!state.status) {
        return {
          status: 503,
          body: { ok: false, message: "Sonia todavía no ha mandado su estado. Inténtalo en unos segundos." },
        };
      }
    }
    return { status: 200, body: this.statusFor(id) };
  }

  /** Ids de la galería que mandó esa Sonia (`null` si no se sabe). */
  async getGalleryIds(instance: string | null): Promise<string[] | null> {
    const id = this.resolveInstance(instance);
    if (!id) return null;
    return this.known.get(id)?.gallery ?? null;
  }

  async runAction(instance: string | null, action: string, params: Json): Promise<ApiResponse> {
    return toResponse(await this.actionResult(instance, action, params));
  }

  private async actionResult(instance: string | null, action: string, params: Json): Promise<ApiResult> {
    const id = this.resolveInstance(instance);
    if (!id) return { status: 503, body: { ok: false, message: "No hay ninguna Sonia conectada." } };
    if (!this.known.has(id)) return { status: 404, body: { ok: false, message: "No conozco esa Sonia." } };
    const ws = this.agentSocket(id);
    if (!ws) {
      return { status: 503, body: { ok: false, message: "Esa Sonia no está conectada ahora mismo." } };
    }
    const requestId = crypto.randomUUID();
    return new Promise<ApiResult>((resolve) => {
      const timer = setTimeout(() => {
        finish({
          status: 504,
          body: { ok: false, message: "Sonia no contestó a tiempo. Mira si lo hizo antes de repetirlo." },
        });
      }, ACTION_TIMEOUT_MS);
      const finish = (result: ApiResult): void => {
        if (!this.pending.delete(requestId)) return;
        clearTimeout(timer);
        resolve(result);
      };
      this.pending.set(requestId, { instance: id, finish });
      try {
        ws.send(JSON.stringify({ type: "action", request_id: requestId, action, params }));
      } catch {
        finish({ status: 503, body: { ok: false, message: "Esa Sonia no está conectada ahora mismo." } });
      }
    });
  }
}
