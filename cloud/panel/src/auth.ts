/**
 * Autenticación del panel.
 *
 * Dos vías, cualquiera de las dos vale:
 *
 * - JWT de Cloudflare Access (`Cf-Access-Jwt-Assertion` o la cookie
 *   `CF_Authorization`), si `ACCESS_TEAM_DOMAIN` y `ACCESS_AUD` están puestos.
 *   Se verifica la firma RS256 con WebCrypto contra las claves públicas del
 *   equipo (cacheadas una hora), `aud`, `iss` y `exp`.
 * - Sesión de la contraseña del panel (`PANEL_PASSWORD`): cookie
 *   `sonia_session` con valor `exp.firma`, firmada con HMAC-SHA256 y una clave
 *   derivada (HKDF) de `PANEL_PASSWORD` y `AGENT_TOKEN`. Cambiar cualquiera de
 *   los dos secretos cierra todas las sesiones.
 *
 * Si no hay ni Access ni contraseña configurados, nadie entra.
 */

import type { Env } from "./env";
import { getCookie } from "./http";

export const SESSION_COOKIE = "sonia_session";
export const SESSION_TTL_S = 12 * 60 * 60;

/** Margen para relojes desajustados al comprobar caducidades. */
const CLOCK_SKEW_S = 60;
/** Cuánto valen las claves públicas de Access descargadas. */
const ACCESS_KEYS_TTL_MS = 60 * 60 * 1000;
/** Como mucho una descarga de claves cada este tiempo si aparece un `kid` desconocido. */
const ACCESS_KEYS_MIN_REFRESH_MS = 30 * 1000;

const encoder = new TextEncoder();

export type AuthKind = "access" | "session";

export function accessConfigured(env: Env): boolean {
  return Boolean(teamDomain(env) && env.ACCESS_AUD?.trim());
}

export function passwordConfigured(env: Env): boolean {
  return Boolean(env.PANEL_PASSWORD);
}

/** ¿Quién hace la petición? `null` si no trae una sesión válida. */
export async function authenticate(request: Request, env: Env): Promise<AuthKind | null> {
  if (accessConfigured(env)) {
    const token =
      request.headers.get("cf-access-jwt-assertion") ?? getCookie(request, "CF_Authorization");
    if (token && (await verifyAccessJwt(token, env))) return "access";
  }
  if (passwordConfigured(env)) {
    const cookie = getCookie(request, SESSION_COOKIE);
    if (cookie && (await verifySession(cookie, env))) return "session";
  }
  return null;
}

// ------------------------------------------------------------ comparaciones

async function sha256(value: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", encoder.encode(value));
}

/**
 * Compara dos secretos en tiempo constante.
 *
 * Se comparan sus SHA-256 (misma longitud siempre) con `timingSafeEqual`, así
 * que ni el contenido ni la longitud del secreto se filtran por el tiempo.
 */
export async function constantTimeEqual(a: string, b: string): Promise<boolean> {
  const [hashA, hashB] = await Promise.all([sha256(a), sha256(b)]);
  return crypto.subtle.timingSafeEqual(hashA, hashB);
}

// ------------------------------------------------------------ base64url

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToBase64Url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

// ------------------------------------------------------------ sesión de contraseña

/** Clave HMAC derivada de los secretos (cacheada mientras no cambien). */
let sessionKeyCache: { material: string; key: CryptoKey } | null = null;

async function sessionKey(env: Env): Promise<CryptoKey> {
  const material = `${env.PANEL_PASSWORD ?? ""}\u0000${env.AGENT_TOKEN ?? ""}`;
  if (sessionKeyCache?.material === material) return sessionKeyCache.key;
  const base = await crypto.subtle.importKey("raw", encoder.encode(material), "HKDF", false, [
    "deriveKey",
  ]);
  const key = await crypto.subtle.deriveKey(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: encoder.encode("sonia-panel"),
      info: encoder.encode("sonia_session v1"),
    },
    base,
    { name: "HMAC", hash: "SHA-256", length: 256 },
    false,
    ["sign", "verify"],
  );
  sessionKeyCache = { material, key };
  return key;
}

function sessionPayload(exp: number): Uint8Array {
  return encoder.encode(`sonia_session.v1.${exp}`);
}

/** Valor nuevo de la cookie de sesión (`exp.firma`), válido 12 horas. */
export async function createSession(env: Env): Promise<string> {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_S;
  const signature = await crypto.subtle.sign("HMAC", await sessionKey(env), sessionPayload(exp));
  return `${exp}.${bytesToBase64Url(signature)}`;
}

async function verifySession(value: string, env: Env): Promise<boolean> {
  const match = /^(\d{1,12})\.([A-Za-z0-9_-]{43})$/.exec(value);
  if (!match) return false;
  const exp = Number(match[1]);
  const now = Math.floor(Date.now() / 1000);
  if (exp <= now || exp > now + SESSION_TTL_S + CLOCK_SKEW_S) return false;
  try {
    // `verify` de HMAC compara en tiempo constante.
    return await crypto.subtle.verify(
      "HMAC",
      await sessionKey(env),
      base64UrlToBytes(match[2]!),
      sessionPayload(exp),
    );
  } catch {
    return false;
  }
}

/** Cabecera `Set-Cookie` de la sesión. */
export function sessionCookie(value: string): string {
  return `${SESSION_COOKIE}=${value}; Path=/; Max-Age=${SESSION_TTL_S}; HttpOnly; Secure; SameSite=Strict`;
}

/** Cabecera `Set-Cookie` que borra la sesión. */
export function clearSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}

// ------------------------------------------------------------ Cloudflare Access

function teamDomain(env: Env): string {
  return (env.ACCESS_TEAM_DOMAIN ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
}

interface AccessJwk {
  kid?: string;
  kty?: string;
  alg?: string;
  n?: string;
  e?: string;
}

/** Claves públicas de Access por `kid` (caché del isolate). */
let accessKeys: { team: string; keys: Map<string, CryptoKey>; fetchedAt: number } | null = null;
let accessKeysAttemptAt = 0;

async function fetchAccessKeys(team: string): Promise<Map<string, CryptoKey>> {
  accessKeysAttemptAt = Date.now();
  const response = await fetch(`https://${team}/cdn-cgi/access/certs`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`certs de Access: HTTP ${response.status}`);
  const body: { keys?: AccessJwk[] } = await response.json();
  const keys = new Map<string, CryptoKey>();
  for (const jwk of body.keys ?? []) {
    if (!jwk.kid || jwk.kty !== "RSA" || !jwk.n || !jwk.e) continue;
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    keys.set(jwk.kid, key);
  }
  accessKeys = { team, keys, fetchedAt: Date.now() };
  return keys;
}

async function accessKey(team: string, kid: string): Promise<CryptoKey | null> {
  const now = Date.now();
  const cached = accessKeys?.team === team ? accessKeys : null;
  if (cached && now - cached.fetchedAt < ACCESS_KEYS_TTL_MS) {
    const key = cached.keys.get(kid);
    if (key) return key;
    // `kid` desconocido: Access pudo rotar las claves. Descarga otra vez, sin abusar.
    if (now - accessKeysAttemptAt < ACCESS_KEYS_MIN_REFRESH_MS) return null;
  }
  const keys = await fetchAccessKeys(team);
  return keys.get(kid) ?? null;
}

function decodeJsonPart(part: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(new TextDecoder().decode(base64UrlToBytes(part)));
    return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Verifica un JWT de Cloudflare Access: firma RS256, `aud`, `iss`, `exp` y `nbf`. */
export async function verifyAccessJwt(token: string, env: Env): Promise<boolean> {
  const team = teamDomain(env);
  const audience = env.ACCESS_AUD?.trim();
  if (!team || !audience) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [headerPart, payloadPart, signaturePart] = parts as [string, string, string];
  const header = decodeJsonPart(headerPart);
  const claims = decodeJsonPart(payloadPart);
  if (!header || !claims || header.alg !== "RS256" || typeof header.kid !== "string") return false;

  const now = Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp + CLOCK_SKEW_S < now) return false;
  if (typeof claims.nbf === "number" && claims.nbf - CLOCK_SKEW_S > now) return false;
  if (claims.iss !== `https://${team}`) return false;
  const aud = claims.aud;
  const audiences = Array.isArray(aud) ? aud : [aud];
  if (!audiences.includes(audience)) return false;

  try {
    const key = await accessKey(team, header.kid);
    if (!key) return false;
    return await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      base64UrlToBytes(signaturePart),
      encoder.encode(`${headerPart}.${payloadPart}`),
    );
  } catch (error) {
    console.warn("No se pudo verificar el JWT de Access:", String(error));
    return false;
  }
}
