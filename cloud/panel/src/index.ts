/**
 * Worker `sonia-panel`: panel de control de Sonnia en Cloudflare.
 *
 * - `sonnia.sonnetcode.com` (con doble n): todo redirige a `sonia.sonnetcode.com`.
 * - `/agent`: WebSocket de cada Sonnia, solo con `AGENT_TOKEN`.
 * - `/guest/agent`: WebSocket del Modo Jean de cada Sonnia (cámara, micro y voz
 *   del invitado), también con `AGENT_TOKEN`; el navegador entra por `/api/guest`.
 * - `/login`, `/logout`: entrada con la contraseña del panel.
 * - Todo lo demás (página, estáticos, API y WebSocket del navegador) exige un
 *   JWT de Cloudflare Access o la sesión de la contraseña.
 *
 * El estado vive en el Durable Object `ControlRoom` (una sola instancia).
 */

import { authenticate, constantTimeEqual } from "./auth";
import type { Env } from "./env";
import { json, rawJson, redirect, sameOrigin, text, withSecurityHeaders } from "./http";
import { bouncePage, handleLoginGet, handleLoginPost, handleLogout } from "./login";

export { ControlRoom } from "./control-room";
export { GuestRoom } from "./guest-room";

/** Dominio del panel. */
const PANEL_HOST = "sonia.sonnetcode.com";
/** Con doble n, como se escribe Sonnia: solo redirige al dominio del panel (por si alguien lo teclea así). */
const ALIAS_HOSTS = new Set(["sonnia.sonnetcode.com"]);
/** Estáticos que se ven sin sesión (los usa la página de entrada). */
const PUBLIC_PATHS = new Set(["/static/sonnet-code-logo.svg", "/static/favicon.svg", "/favicon.ico"]);
/** Tamaño máximo del cuerpo de `POST /api/action`: cabe el banco de preguntas de la trivia (`set_trivia_bank`). */
const MAX_ACTION_BYTES = 320 * 1024;
/** Ids de Sonnia válidos (el agente los manda en `[a-z0-9-]`; se admite algo más). */
const INSTANCE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;

export default {
  async fetch(request, env): Promise<Response> {
    try {
      return withSecurityHeaders(await route(request, env));
    } catch (error) {
      console.error("Error en el panel:", error instanceof Error ? error.stack ?? error.message : String(error));
      return withSecurityHeaders(json({ ok: false, message: "Error interno del panel. Inténtalo de nuevo." }, 500));
    }
  },
} satisfies ExportedHandler<Env>;

/**
 * La sala del Modo Jean de una Sonia. Vive en el este de Norteamérica: casi de
 * camino entre España (Jean) y Santo Domingo (el stand).
 */
function guestRoom(env: Env, instance: string): DurableObjectStub<import("./guest-room").GuestRoom> {
  return env.GUEST_ROOM.get(env.GUEST_ROOM.idFromName(instance), { locationHint: "enam" });
}

function controlRoom(env: Env): DurableObjectStub<import("./control-room").ControlRoom> {
  return env.CONTROL_ROOM.get(env.CONTROL_ROOM.idFromName("control"));
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  // Antes que nada: la sesión y las cookies son las del dominio del panel.
  if (ALIAS_HOSTS.has(url.hostname)) return redirect(`https://${PANEL_HOST}${path}${url.search}`, 301);
  if (path === "/agent") return handleAgent(request, env);
  if (path === "/guest/agent") return handleGuestAgent(request, env);
  if (path === "/login") {
    if (method === "POST") return handleLoginPost(request, env);
    if (method === "GET" || method === "HEAD") return handleLoginGet(request, env);
    return text("Método no permitido.", 405);
  }
  if (path === "/logout") return handleLogout(request, env);
  if (PUBLIC_PATHS.has(path) && (method === "GET" || method === "HEAD")) {
    return serveAsset(request, env, path === "/favicon.ico" ? "/static/favicon.svg" : path);
  }

  if (!(await authenticate(request, env))) return unauthorized(request, url);

  if (path.startsWith("/api/")) return handleApi(request, env, url);
  if (method !== "GET" && method !== "HEAD") return text("Método no permitido.", 405);
  return serveAsset(request, env, path);
}

/** Sin sesión: la API responde 401 y las páginas mandan a `/login`. */
function unauthorized(request: Request, url: URL): Response {
  if (url.pathname.startsWith("/api/")) {
    return json({ ok: false, message: "Inicia sesión de nuevo." }, 401);
  }
  const next = url.pathname + url.search;
  const login = next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
  // Desde otra web la cookie SameSite=Strict no viaja: se reintenta desde aquí.
  if (request.method === "GET" && request.headers.get("sec-fetch-site") === "cross-site") {
    return bouncePage(login);
  }
  return redirect(login, 302);
}

// ------------------------------------------------------------ Sonnias (agentes)

/** Decodifica texto codificado como URL; si está mal codificado, lo deja tal cual. */
function decodeHeader(value: string | null): string {
  if (!value) return "";
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/** Comprueba el WebSocket de una Sonnia (token e id). Devuelve su id y nombre, o la respuesta de error. */
async function checkAgent(request: Request, env: Env): Promise<{ id: string; name: string } | Response> {
  if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
    return text("Se esperaba un WebSocket.", 426);
  }
  const header = request.headers.get("authorization") ?? "";
  const token = /^Bearer\s+(.+)$/i.exec(header)?.[1]?.trim() ?? "";
  const expected = env.AGENT_TOKEN ?? "";
  if (!expected) {
    console.warn("Conexión de una Sonnia rechazada: falta el secreto AGENT_TOKEN.");
    return text("Token no válido.", 401);
  }
  if (!token || !(await constantTimeEqual(token, expected))) return text("Token no válido.", 401);

  const id = decodeHeader(request.headers.get("x-sonia-instance")).trim();
  if (!INSTANCE_ID.test(id)) return text("Falta X-Sonia-Instance o no es válido.", 400);
  // Sin caracteres de control; el nombre bueno llega después en el `hello`.
  const name = decodeHeader(request.headers.get("x-sonia-name"))
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .trim()
    .slice(0, 80);
  return { id, name };
}

async function handleAgent(request: Request, env: Env): Promise<Response> {
  const agent = await checkAgent(request, env);
  if (agent instanceof Response) return agent;
  const { id, name } = agent;

  const target = new URL("https://control/agent");
  target.searchParams.set("id", id);
  target.searchParams.set("name", name || id);
  return controlRoom(env).fetch(target.toString(), { headers: { upgrade: "websocket" } });
}

/** Modo Jean: la Sonnia sube cámara y micro y baja la voz del invitado. */
async function handleGuestAgent(request: Request, env: Env): Promise<Response> {
  const agent = await checkAgent(request, env);
  if (agent instanceof Response) return agent;
  return guestRoom(env, agent.id).fetch("https://guest/agent", { headers: { upgrade: "websocket" } });
}

// ------------------------------------------------------------ API del navegador

function instanceParam(url: URL): string | null {
  const value = url.searchParams.get("instance")?.trim();
  return value && INSTANCE_ID.test(value) ? value : null;
}

async function handleApi(request: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname;
  const method = request.method;
  const isRead = method === "GET" || method === "HEAD";

  if (path === "/api/events") {
    if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
      return json({ ok: false, message: "Se esperaba un WebSocket." }, 426);
    }
    if (!sameOrigin(request)) return json({ ok: false, message: "Origen no permitido." }, 403);
    const target = new URL("https://control/events");
    const instance = instanceParam(url);
    if (instance) target.searchParams.set("instance", instance);
    return controlRoom(env).fetch(target.toString(), { headers: { upgrade: "websocket" } });
  }

  if (path === "/api/guest") {
    // Sala de vídeo: el modal del Modo Jean ve la cámara, oye el micro del stand y
    // manda su voz; con `role=watch` («Ver cámara») solo ve la cámara.
    if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
      return json({ ok: false, message: "Se esperaba un WebSocket." }, 426);
    }
    if (!sameOrigin(request)) return json({ ok: false, message: "Origen no permitido." }, 403);
    let instance = instanceParam(url);
    if (!instance) {
      const { instances } = await controlRoom(env).getInstances();
      instance = instances.find((item) => item.connected)?.id ?? null;
    }
    if (!instance) return json({ ok: false, message: "No hay ninguna Sonnia conectada." }, 503);
    const viewer = url.searchParams.get("role") === "watch" ? "https://guest/viewer?role=watch" : "https://guest/viewer";
    return guestRoom(env, instance).fetch(viewer, { headers: { upgrade: "websocket" } });
  }

  if (path === "/api/action") {
    if (method !== "POST") return json({ ok: false, message: "Método no permitido." }, 405);
    return handleAction(request, env, url);
  }

  if (!isRead) return json({ ok: false, message: "Método no permitido." }, 405);

  if (path === "/api/instances") {
    return json(await controlRoom(env).getInstances());
  }
  if (path === "/api/status") {
    const result = await controlRoom(env).getStatus(instanceParam(url));
    return rawJson(result.body, result.status);
  }
  if (path === "/api/gallery") {
    return handleGallery(request, env, url);
  }
  if (path.startsWith("/api/gallery/")) {
    return handleGalleryImage(request, env, decodeHeader(path.slice("/api/gallery/".length)));
  }
  return json({ ok: false, message: "No existe." }, 404);
}

async function handleAction(request: Request, env: Env, url: URL): Promise<Response> {
  if (request.headers.get("x-sonia-panel") !== "1") {
    return json({ ok: false, message: "Petición no permitida." }, 403);
  }
  if (Number(request.headers.get("content-length") ?? "0") > MAX_ACTION_BYTES) {
    return json({ ok: false, message: "Petición demasiado grande." }, 413);
  }
  let body: unknown = null;
  try {
    const raw = await request.text();
    if (raw.length <= MAX_ACTION_BYTES) body = JSON.parse(raw);
  } catch {
    body = null;
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return json({ ok: false, message: "Petición mal formada." }, 400);
  }
  const { action, instance, ...params } = body as Record<string, unknown>;
  if (typeof action !== "string" || !action) {
    return json({ ok: false, message: "Petición mal formada." }, 400);
  }
  let target = instanceParam(url);
  if (typeof instance === "string" && instance) {
    if (!INSTANCE_ID.test(instance)) return json({ ok: false, message: "No conozco esa Sonia." }, 404);
    target = instance;
  }
  const result = await controlRoom(env).runAction(target, action, params);
  return rawJson(result.body, result.status);
}

// ------------------------------------------------------------ galería

/** `id → archivo` de `public/gallery.json` (cambia solo al desplegar). */
let galleryMapCache: Record<string, string> | null = null;

async function galleryMap(request: Request, env: Env): Promise<Record<string, string>> {
  if (galleryMapCache) return galleryMapCache;
  const response = await env.ASSETS.fetch(new URL("/gallery.json", request.url));
  if (!response.ok) return {};
  const data: unknown = await response.json();
  const map: Record<string, string> = {};
  if (data && typeof data === "object" && !Array.isArray(data)) {
    for (const [id, file] of Object.entries(data)) {
      if (typeof file === "string") map[id] = file;
    }
  }
  galleryMapCache = map;
  return map;
}

async function handleGallery(request: Request, env: Env, url: URL): Promise<Response> {
  const map = await galleryMap(request, env);
  // Los ids que mandó esa Sonnia; si todavía no se saben, los de la galería desplegada.
  const ids = (await controlRoom(env).getGalleryIds(instanceParam(url))) ?? Object.keys(map).sort();
  const images = ids.map((id) => ({
    id,
    // Un id sin archivo en Cloudflare sale sin miniatura.
    url: map[id] ? `/gallery/${encodeURIComponent(map[id])}` : null,
  }));
  return json({ images });
}

async function handleGalleryImage(request: Request, env: Env, id: string): Promise<Response> {
  const file = (await galleryMap(request, env))[id];
  if (!file) return json({ ok: false, message: "No existe esa imagen." }, 404);
  return serveAsset(request, env, `/gallery/${encodeURIComponent(file)}`);
}

// ------------------------------------------------------------ estáticos

/**
 * Sirve un archivo de `public/`. La página pide sus recursos en `/static/...`
 * (igual que en el panel local) y en `public/` están en la raíz.
 */
async function serveAsset(request: Request, env: Env, path: string): Promise<Response> {
  let assetPath = path;
  if (assetPath.startsWith("/static/")) assetPath = assetPath.slice("/static".length);
  if (assetPath === "/gallery.json") return json({ ok: false, message: "No existe." }, 404);
  const assetUrl = new URL(assetPath, request.url);
  const response = await env.ASSETS.fetch(new Request(assetUrl, { method: request.method, headers: request.headers }));
  if (assetPath === "/" || assetPath === "/index.html") {
    const page = new Response(response.body, response);
    page.headers.set("cache-control", "no-store");
    return page;
  }
  return response;
}
