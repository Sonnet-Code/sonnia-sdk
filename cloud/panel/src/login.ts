/**
 * Entrada al panel con contraseña (`/login`, `/logout`).
 *
 * Página pensada para el personal del stand, no técnico: un solo campo y
 * mensajes claros. Sin JavaScript (la CSP no lo permite en línea y no hace
 * falta); el estilo va en línea porque la CSP admite estilos en línea y así la
 * página no depende de estáticos protegidos.
 */

import {
  accessConfigured,
  authenticate,
  clearSessionCookie,
  constantTimeEqual,
  createSession,
  passwordConfigured,
  sessionCookie,
} from "./auth";
import type { Env } from "./env";
import { escapeHtml, html, redirect, sameOrigin } from "./http";

/** Tamaño máximo del formulario de entrada. */
const MAX_FORM_BYTES = 4096;

/** Destino seguro tras entrar: solo rutas del propio panel. */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  if (value.startsWith("/login") || value.startsWith("/logout")) return "/";
  return value;
}

type Notice = { kind: "error" | "info"; text: string } | null;

const STYLE = `
  :root {
    --navy: #142752; --blue: #0371f5; --blue-strong: #0356c2;
    --bg: #e9edf4; --surface: #ffffff; --ink: #0b1631; --ink-2: #3c4864; --line: #c7cfdd;
    --bad: #b3261e; --bad-bg: #fde6e3; --info: #0356c2; --info-bg: #e1ecfd;
    --font: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0; min-height: 100vh; min-height: 100dvh;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 24px 16px; background: var(--bg); color: var(--ink);
    font: 17px/1.5 var(--font);
  }
  .card {
    width: 100%; max-width: 420px; background: var(--surface); overflow: hidden;
    border: 1px solid var(--line); border-radius: 16px;
    box-shadow: 0 10px 30px rgba(20, 39, 82, 0.10);
  }
  .card-head { background: var(--navy); padding: 20px 28px; }
  .card-body { padding: 28px 28px 26px; }
  .logo { display: block; width: 190px; max-width: 75%; height: auto; }
  h1 { margin: 0 0 6px; font-size: 26px; line-height: 1.2; color: var(--navy); }
  .lead { margin: 0 0 22px; color: var(--ink-2); }
  .notice { margin: 0 0 18px; padding: 12px 14px; border-radius: 10px; font-weight: 600; }
  .notice--error { background: var(--bad-bg); color: var(--bad); }
  .notice--info { background: var(--info-bg); color: var(--info); }
  label { display: block; margin: 0 0 8px; font-weight: 600; }
  input[type="password"] {
    display: block; width: 100%; min-height: 56px; padding: 12px 14px;
    font: inherit; font-size: 20px; color: var(--ink);
    border: 2px solid var(--line); border-radius: 10px; background: #fff;
  }
  input[type="password"]:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px rgba(3, 113, 245, 0.25); }
  button {
    display: block; width: 100%; min-height: 56px; margin: 18px 0 0; padding: 12px 16px;
    font: inherit; font-size: 19px; font-weight: 700; color: #fff;
    background: var(--blue); border: 0; border-radius: 10px; cursor: pointer;
  }
  button:hover { background: var(--blue-strong); }
  button:focus-visible { outline: 3px solid var(--navy); outline-offset: 3px; }
  .help { margin: 20px 0 0; font-size: 15px; color: var(--ink-2); }
  .link { color: var(--blue-strong); font-weight: 600; }
  .foot { margin: 20px 0 0; font-size: 14px; color: var(--ink-2); text-align: center; }
`;

function page(title: string, body: string, extraHead = ""): string {
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#142752">
<meta name="robots" content="noindex, nofollow">
<title>${escapeHtml(title)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
${extraHead}<style>${STYLE}</style>
</head>
<body>
<main class="card">
<div class="card-head"><img class="logo" src="/static/sonnet-code-logo.svg" alt="Sonnet Code" width="190" height="29"></div>
<div class="card-body">
${body}
</div>
</main>
<p class="foot">Sonia · stand de Sonnet Code · DevFest Santo Domingo</p>
</body>
</html>`;
}

function noticeHtml(notice: Notice): string {
  if (!notice) return "";
  const role = notice.kind === "error" ? "alert" : "status";
  return `<p class="notice notice--${notice.kind}" role="${role}">${escapeHtml(notice.text)}</p>`;
}

function loginPage(env: Env, next: string, notice: Notice): string {
  if (passwordConfigured(env)) {
    return page(
      "Entrar · Panel de Sonia",
      `<h1>Panel de Sonia</h1>
<p class="lead">Escribe la contraseña del panel para entrar.</p>
${noticeHtml(notice)}<form method="post" action="/login">
<input type="hidden" name="next" value="${escapeHtml(next)}">
<label for="password">Contraseña</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrar</button>
</form>
<p class="help">¿No tienes la contraseña? Pídela a la persona responsable del stand de Sonnet Code.</p>`,
    );
  }
  if (accessConfigured(env)) {
    return page(
      "Entrar · Panel de Sonia",
      `<h1>Panel de Sonia</h1>
${noticeHtml(notice)}<p class="lead">Este panel se abre con tu cuenta autorizada. Si ves esta página, tu acceso no se pudo comprobar.</p>
<p><a class="link" href="/">Volver a intentarlo</a></p>
<p class="help">Si sigue sin funcionar, pide ayuda a la persona responsable del stand de Sonnet Code.</p>`,
    );
  }
  return page(
    "Panel de Sonia",
    `<h1>Panel de Sonia</h1>
<p class="lead">El panel todavía no tiene ningún acceso configurado, así que nadie puede entrar.</p>
<p class="help">Avisa a la persona que administra el panel: falta configurar la contraseña.</p>`,
  );
}

/**
 * Página intermedia para quien llega desde otra web (un enlace en un chat o un
 * correo): la cookie `SameSite=Strict` no viaja en esa primera navegación, así
 * que se recarga desde el propio panel, donde sí viaja, en vez de pedir la
 * contraseña a quien ya había entrado.
 */
export function bouncePage(target: string): Response {
  const safe = escapeHtml(target);
  return html(
    page(
      "Abriendo el panel de Sonia",
      `<h1>Panel de Sonia</h1>
<p class="lead">Abriendo el panel…</p>
<p><a class="link" href="${safe}">Si no se abre solo, toca aquí.</a></p>`,
      `<meta http-equiv="refresh" content="0;url=${safe}">\n`,
    ),
  );
}

export async function handleLoginGet(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const next = safeNext(url.searchParams.get("next"));
  // Quien ya tiene sesión no necesita el formulario.
  if (await authenticate(request, env)) return redirect(next);
  let notice: Notice = null;
  if (url.searchParams.has("salida")) notice = { kind: "info", text: "Has salido del panel." };
  return html(loginPage(env, next, notice));
}

export async function handleLoginPost(request: Request, env: Env): Promise<Response> {
  if (!sameOrigin(request)) return html(loginPage(env, "/", null), 403);
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_FORM_BYTES) return html(loginPage(env, "/", null), 413);

  let password = "";
  let next = "/";
  try {
    const raw = await request.text();
    if (raw.length > MAX_FORM_BYTES) return html(loginPage(env, "/", null), 413);
    const form = new URLSearchParams(raw);
    password = form.get("password") ?? "";
    next = safeNext(form.get("next"));
  } catch {
    // Formulario ilegible: se trata como contraseña incorrecta.
  }

  const expected = env.PANEL_PASSWORD;
  const ok = Boolean(expected) && password.length > 0 && (await constantTimeEqual(password, expected ?? ""));
  if (!ok) {
    // Pequeño retardo para que probar contraseñas a ciegas sea lento.
    await new Promise((resolve) => setTimeout(resolve, 700 + Math.floor(Math.random() * 500)));
    const notice: Notice = expected
      ? { kind: "error", text: "La contraseña no es correcta. Revísala e inténtalo otra vez." }
      : null;
    return html(loginPage(env, next, notice), 401);
  }
  return redirect(next, 303, { "set-cookie": sessionCookie(await createSession(env)) });
}

export async function handleLogout(request: Request, env: Env): Promise<Response> {
  const kind = await authenticate(request, env);
  // Con Cloudflare Access, cerrar también su sesión; si no, volver al formulario.
  const target = kind === "access" ? "/cdn-cgi/access/logout" : "/login?salida=1";
  return redirect(target, 302, { "set-cookie": clearSessionCookie() });
}
