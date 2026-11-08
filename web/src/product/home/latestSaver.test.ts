/// <reference types="bun" />
/**
 * «Editar favoritos» saves each change at once (plan de Inicio, 3.4): one request at a time, the last change winning over the
 * ones made while a save was going, and a failure keeps what was not saved for a retry.
 */
import { describe, expect, test } from "bun:test";
import { createSaver } from "./latestSaver";

function harness(send: (v: string) => Promise<string>) {
  const log: string[] = [];
  const saver = createSaver(send, {
    onStart: () => log.push("start"),
    onSaved: (a) => log.push(`saved:${a}`),
    onIdle: () => log.push("idle"),
    onFail: () => log.push("fail"),
  });
  return { saver, log };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("createSaver", () => {
  test("a change is sent at once and reported idle when saved", async () => {
    const sent: string[] = [];
    const { saver, log } = harness((v) => (sent.push(v), Promise.resolve(v.toUpperCase())));
    saver.push("a");
    await tick();
    expect(sent).toEqual(["a"]);
    expect(log).toEqual(["start", "saved:A", "idle"]);
  });

  test("changes made while a save goes are sent after it - only the last", async () => {
    const sent: string[] = [];
    const release: Array<() => void> = [];
    const { saver, log } = harness(
      (v) =>
        new Promise((resolve) => {
          sent.push(v);
          release.push(() => resolve(v));
        }),
    );
    saver.push("a");
    saver.push("b");
    saver.push("c");
    expect(sent).toEqual(["a"]);
    release[0]!();
    await tick();
    expect(sent).toEqual(["a", "c"]);
    release[1]!();
    await tick();
    expect(log).toEqual(["start", "saved:a", "saved:c", "idle"]);
  });

  test("a failure keeps what was not saved, and a retry sends it", async () => {
    let fail = true;
    const sent: string[] = [];
    const { saver, log } = harness((v) => {
      sent.push(v);
      return fail ? Promise.reject(new Error("down")) : Promise.resolve(v);
    });
    saver.push("a");
    await tick();
    expect(log).toEqual(["start", "fail"]);
    fail = false;
    saver.retry();
    await tick();
    expect(sent).toEqual(["a", "a"]);
    expect(log.slice(-3)).toEqual(["start", "saved:a", "idle"]);
  });

  test("a retry with nothing unsaved sends nothing new", async () => {
    const sent: string[] = [];
    const { saver } = harness((v) => (sent.push(v), Promise.resolve(v)));
    saver.push("a");
    await tick();
    saver.retry();
    await tick();
    expect(sent).toEqual(["a"]);
  });
});
