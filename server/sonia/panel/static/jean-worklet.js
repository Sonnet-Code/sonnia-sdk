/*
 * AudioWorklet del Modo Jean (lo carga jean.js; formato en docs/modo-jean.md).
 *
 * - "jean-capture": baja el micro de Jean a 24 kHz mono y manda al hilo
 *   principal bloques Int16 de 60 ms, más el nivel para el medidor.
 * - "jean-player": reproduce el micro del stand (PCM16 a la tasa de cada
 *   bloque) con un colchón de unos 200 ms; si se acumula más de 600 ms, tira
 *   lo viejo para no ir con retraso.
 */
"use strict";

const CAPTURE_RATE = 24000;
const CAPTURE_BLOCK_MS = 60;
const PLAYER_TARGET_S = 0.2;
const PLAYER_MAX_S = 0.6;

/** Remuestreo lineal con estado: los bloques encadenan sin saltos. */
class Resampler {
  constructor(srcRate, dstRate) {
    this.step = srcRate / dstRate;
    this.t = 0; // posición fraccionaria de la siguiente salida dentro del bloque actual
    this.prev = 0;
    // Paso bajo de un polo antes de bajar de tasa (corte a ~0,4 de la nueva tasa).
    this.lowpass = dstRate < srcRate ? 1 - Math.exp((-2 * Math.PI * 0.4 * dstRate) / srcRate) : 0;
    this.lp = 0;
  }

  /** Remuestrea `input` dentro de `output` desde `outOffset`; devuelve cuántas muestras escribió. */
  process(input, output, outOffset) {
    const n = input.length;
    if (n === 0) return 0;
    let samples = input;
    if (this.lowpass) {
      samples = new Float32Array(n);
      let y = this.lp;
      for (let i = 0; i < n; i++) {
        y += this.lowpass * (input[i] - y);
        samples[i] = y;
      }
      this.lp = y;
    }
    // Posiciones sobre [anterior, ...samples]: la 0 es la última muestra del bloque previo.
    let produced = 0;
    while (this.t <= n - 1 && outOffset + produced < output.length) {
      const position = this.t + 1;
      const index = Math.floor(position);
      const frac = position - index;
      const left = index === 0 ? this.prev : samples[index - 1];
      const right = index < n ? samples[index] : samples[n - 1];
      output[outOffset + produced] = left + (right - left) * frac;
      produced += 1;
      this.t += this.step;
    }
    this.t -= n;
    this.prev = samples[n - 1];
    return produced;
  }
}

class JeanCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.resampler = new Resampler(sampleRate, CAPTURE_RATE);
    this.blockSize = Math.round((CAPTURE_RATE * CAPTURE_BLOCK_MS) / 1000);
    this.block = new Float32Array(this.blockSize);
    this.filled = 0;
    this.scratch = new Float32Array(256);
    this.peak = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;
    const channel = input[0];
    let sum = 0;
    for (let i = 0; i < channel.length; i++) sum += channel[i] * channel[i];
    this.peak = Math.max(Math.sqrt(sum / channel.length), this.peak * 0.95);

    if (this.scratch.length < channel.length) this.scratch = new Float32Array(channel.length * 2);
    const produced = this.resampler.process(channel, this.scratch, 0);
    for (let i = 0; i < produced; i++) {
      this.block[this.filled++] = this.scratch[i];
      if (this.filled === this.blockSize) this.flush();
    }
    return true;
  }

  flush() {
    const pcm = new Int16Array(this.blockSize);
    for (let i = 0; i < this.blockSize; i++) {
      const value = Math.max(-1, Math.min(1, this.block[i]));
      pcm[i] = value < 0 ? value * 32768 : value * 32767;
    }
    this.filled = 0;
    this.port.postMessage({ pcm, rate: CAPTURE_RATE, level: this.peak }, [pcm.buffer]);
  }
}

class JeanPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = [];
    this.queued = 0;
    this.offset = 0; // muestras ya leídas del primer trozo
    this.playing = false;
    this.volume = 1;
    this.resampler = null;
    this.resamplerRate = 0;
    this.target = Math.round(sampleRate * PLAYER_TARGET_S);
    this.max = Math.round(sampleRate * PLAYER_MAX_S);
    this.underruns = 0;
    this.dropped = 0;
    this.port.onmessage = (event) => this.onMessage(event.data || {});
  }

  onMessage(data) {
    if (typeof data.volume === "number") this.volume = Math.max(0, Math.min(2, data.volume));
    if (data.reset) {
      this.chunks = [];
      this.queued = 0;
      this.offset = 0;
      this.playing = false;
    }
    if (!data.pcm || !data.rate) return;
    if (!this.resampler || this.resamplerRate !== data.rate) {
      this.resampler = new Resampler(data.rate, sampleRate);
      this.resamplerRate = data.rate;
    }
    const pcm = data.pcm;
    const input = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) input[i] = pcm[i] / 32768;
    const output = new Float32Array(Math.ceil((pcm.length * sampleRate) / data.rate) + 4);
    const produced = this.resampler.process(input, output, 0);
    if (produced === 0) return;
    this.chunks.push(output.subarray(0, produced));
    this.queued += produced;
    // Demasiado retraso: fuera lo viejo hasta quedar en el objetivo.
    while (this.queued - this.offset > this.max && this.chunks.length > 1) {
      const head = this.chunks.shift();
      const remaining = head.length - this.offset;
      this.queued -= head.length;
      this.offset = 0;
      this.dropped += remaining;
      if (this.queued <= this.target) break;
    }
  }

  process(_inputs, outputs) {
    const output = outputs[0];
    if (!output || output.length === 0) return true;
    const out = output[0];
    const available = this.queued - this.offset;
    if (!this.playing) {
      if (available >= this.target) this.playing = true;
      else {
        out.fill(0);
        for (let c = 1; c < output.length; c++) output[c].fill(0);
        return true;
      }
    }
    let written = 0;
    while (written < out.length && this.chunks.length > 0) {
      const head = this.chunks[0];
      const take = Math.min(out.length - written, head.length - this.offset);
      for (let i = 0; i < take; i++) out[written + i] = head[this.offset + i] * this.volume;
      written += take;
      this.offset += take;
      if (this.offset >= head.length) {
        this.chunks.shift();
        this.queued -= head.length;
        this.offset = 0;
      }
    }
    if (written < out.length) {
      // Se acabó el colchón: silencio y a esperar a que se rellene.
      out.fill(0, written);
      this.playing = false;
      this.underruns += 1;
    }
    for (let c = 1; c < output.length; c++) output[c].set(out);
    return true;
  }
}

registerProcessor("jean-capture", JeanCapture);
registerProcessor("jean-player", JeanPlayer);
