#!/usr/bin/env node
/**
 * Prepara `public/` para el Worker (sin dependencias, solo Node):
 *
 * - `server/sonia/panel/static/*` → `public/` (la página del panel; el Worker
 *   la sirve también en `/static/...`, como el panel local).
 * - `assets/gallery/*` (solo PNG y JPEG, como `server/sonia/actions/gallery.py`)
 *   → `public/gallery/`, más `public/gallery.json` con `id → archivo`, que usa
 *   `/api/gallery`.
 */

import { copyFile, mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, extname, join, parse, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const panelDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(panelDir, "..", "..");
const staticDir = join(repoDir, "server", "sonia", "panel", "static");
const galleryDir = join(repoDir, "assets", "gallery");
const outDir = join(panelDir, "public");

/** Extensiones de la galería por orden de preferencia (igual que en Python). */
const GALLERY_EXTENSIONS = [".png", ".jpg", ".jpeg"];

/** Copia un directorio recursivamente, sin archivos ocultos. Devuelve cuántos copió. */
async function copyTree(from, to) {
  await mkdir(to, { recursive: true });
  let count = 0;
  for (const entry of await readdir(from, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const source = join(from, entry.name);
    const target = join(to, entry.name);
    if (entry.isDirectory()) count += await copyTree(source, target);
    else if (entry.isFile()) {
      await copyFile(source, target);
      count += 1;
    }
  }
  return count;
}

/** `id → archivo` con las mismas reglas que `Gallery._entries` en Python. */
async function galleryEntries() {
  const entries = new Map();
  let names;
  try {
    names = (await readdir(galleryDir, { withFileTypes: true }))
      .filter((entry) => entry.isFile() && !entry.name.startsWith("."))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return entries;
  }
  for (const name of names) {
    const rank = GALLERY_EXTENSIONS.indexOf(extname(name).toLowerCase());
    if (rank < 0) continue;
    const id = parse(name).name;
    const current = entries.get(id);
    if (!current || rank < GALLERY_EXTENSIONS.indexOf(extname(current).toLowerCase())) {
      entries.set(id, name);
    }
  }
  return entries;
}

async function main() {
  await rm(outDir, { recursive: true, force: true });
  const staticCount = await copyTree(staticDir, outDir);
  if (staticCount === 0) throw new Error(`No hay estáticos del panel en ${staticDir}`);

  const galleryOut = join(outDir, "gallery");
  await mkdir(galleryOut, { recursive: true });
  const entries = await galleryEntries();
  const map = {};
  for (const [id, name] of [...entries].sort(([a], [b]) => a.localeCompare(b))) {
    await copyFile(join(galleryDir, name), join(galleryOut, name));
    map[id] = name;
  }
  await writeFile(join(outDir, "gallery.json"), `${JSON.stringify(map, null, 2)}\n`);

  console.log(`public/: ${staticCount} archivos del panel y ${entries.size} imágenes de la galería.`);
}

main().catch((error) => {
  console.error(`Error preparando public/: ${error.message}`);
  process.exit(1);
});
