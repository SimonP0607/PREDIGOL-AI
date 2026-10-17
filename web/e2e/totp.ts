/**
 * Codes for the second factor (RFC 6238: HMAC-SHA1, 6 digits, 30 s), computed here from a QA account's secret the
 * way an authenticator app would. The server accepts each code once, so `nextCode` never repeats a step.
 */
import { createHmac } from "node:crypto";

const PERIOD = 30;

export function base32Decode(text: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = text.replace(/[\s=]/g, "").toUpperCase();
  let bits = "";
  for (const ch of clean) {
    const v = alphabet.indexOf(ch);
    if (v < 0) throw new Error("not base32");
    bits += v.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export function stepNow(): number {
  return Math.floor(Date.now() / 1000 / PERIOD);
}

export function codeAt(secret: Buffer, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", secret).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return value.toString().padStart(6, "0");
}

const used = new Map<string, number>();

/** A code for a step this process has not used yet for this secret (the current one, or the next). */
export function nextCode(secretB32: string): string {
  const last = used.get(secretB32) ?? -1;
  const step = Math.max(stepNow(), last + 1);
  if (step > stepNow() + 1)
    throw new Error("two codes already used this half-minute: wait for the next one");
  used.set(secretB32, step);
  return codeAt(base32Decode(secretB32), step);
}
