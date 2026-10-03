/** Utilidades HTTP comunes: respuestas JSON y cabeceras de seguridad. */

/** Política de contenido, la misma que el panel local: nada de terceros ni scripts en línea. */
export const CSP =
  "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; " +
  "script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'";

/** Cabeceras de seguridad de todas las respuestas HTTP (iguales a las del panel local). */
const SECURITY_HEADERS: ReadonlyArray<readonly [string, string]> = [
  ["content-security-policy", CSP],
  ["x-frame-options", "DENY"],
  ["x-content-type-options", "nosniff"],
  ["referrer-policy", "same-origin"],
];

/** Añade las cabeceras de seguridad (salvo a la respuesta de un WebSocket). */
export function withSecurityHeaders(response: Response): Response {
  if (response.status === 101 || response.webSocket) return response;
  const out = new Response(response.body, response);
  for (const [name, value] of SECURITY_HEADERS) {
    if (!out.headers.has(name)) out.headers.set(name, value);
  }
  return out;
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return rawJson(JSON.stringify(body), status, headers);
}

/** Respuesta JSON con el cuerpo ya serializado. */
export function rawJson(body: string, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

export function html(body: string, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

export function text(body: string, status: number): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}

export function redirect(location: string, status = 302, headers: Record<string, string> = {}): Response {
  return new Response(null, {
    status,
    headers: { location, "cache-control": "no-store", ...headers },
  });
}

/** Escapa texto para meterlo en HTML (contenido o atributos entre comillas dobles). */
export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Lee una cookie de la petición (vacío si no está). */
export function getCookie(request: Request, name: string): string {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const index = part.indexOf("=");
    if (index < 0) continue;
    if (part.slice(0, index).trim() === name) return part.slice(index + 1).trim();
  }
  return "";
}

/** ¿El `Origin` del navegador es el propio host (o no viene)? Igual que el panel local. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const host = request.headers.get("host") ?? new URL(request.url).host;
    return new URL(origin).host.toLowerCase() === host.toLowerCase();
  } catch {
    return false;
  }
}
