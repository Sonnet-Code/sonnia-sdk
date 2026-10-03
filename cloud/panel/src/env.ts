/**
 * Bindings y secretos del Worker.
 *
 * Los secretos se ponen con `wrangler secret put` (en local, en `.dev.vars`).
 * Se declaran a mano en vez de generarlos con `wrangler types` para que el
 * tipado no dependa de tener un `.dev.vars` en el equipo.
 */

import type { ControlRoom } from "./control-room";

export interface Env {
  /** Estáticos de `public/` (página del panel y galería). */
  ASSETS: Fetcher;
  /** El Durable Object con el estado de todas las Sonias. */
  CONTROL_ROOM: DurableObjectNamespace<ControlRoom>;

  /** Token compartido con las Sonias (`PANEL_CLOUD_TOKEN` en su `.env`). */
  AGENT_TOKEN?: string;
  /** Contraseña del panel para el personal del stand. */
  PANEL_PASSWORD?: string;
  /** Dominio del equipo de Cloudflare Access (`<equipo>.cloudflareaccess.com`). */
  ACCESS_TEAM_DOMAIN?: string;
  /** Audiencia (AUD) de la aplicación de Access de `sonia.sonnetcode.com`. */
  ACCESS_AUD?: string;
}
