// The reading engine of player.html, with a speechSynthesis that the tests
// drive by hand: no sound, no browser.
import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import {
  SETTLE_MS,
  RETRY_DELAYS_MS,
  Reading,
  VOICE_WAIT_MS,
  localVoice,
  pickVoice,
  sentenceStart,
  sentenceStarts,
} from "../../src/read_reply/reading.mjs";

const ALVARO = { name: "Álvaro", lang: "es-ES", localService: false };
const PABLO = { name: "Pablo", lang: "es-ES", localService: true };

class Utterance {
  constructor(text) {
    this.text = text;
  }
}

// What speechSynthesis does, as far as the reading can tell.
class FakeSynth extends EventTarget {
  voices = [ALVARO, PABLO];
  spoken = [];
  current = null;

  getVoices() {
    return this.voices;
  }

  speak(utterance) {
    this.spoken.push(utterance);
    this.current = utterance;
  }

  // Like Edge, the cancelled utterance reports "interrupted" afterwards.
  cancel() {
    const cancelled = this.current;
    this.current = null;
    if (cancelled) queueMicrotask(() => cancelled.onerror({ error: "interrupted" }));
  }

  word(charIndex) {
    this.current.onboundary({ name: "word", charIndex });
  }

  end() {
    const utterance = this.current;
    this.current = null;
    utterance.onend();
  }

  fail(error = "synthesis-failed") {
    const utterance = this.current;
    this.current = null;
    utterance.onerror({ error });
  }

  get last() {
    return this.spoken.at(-1);
  }
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

function reading(synth, chunks, options = {}, { start = true } = {}) {
  const finished = [];
  const progress = [];
  const skipped = [];
  const instance = new Reading({
    synth,
    Utterance,
    chunks,
    voice: ALVARO,
    preferred: ["Álvaro", "Pablo"],
    rate: 1,
    onProgress: (fraction) => progress.push(fraction),
    onSkip: (error) => skipped.push(error),
    onFinish: (error) => finished.push(error),
    ...options,
  });
  if (start) instance.start();
  return { reading: instance, finished, progress, skipped };
}

describe("Reading", () => {
  let synth;
  beforeEach(() => {
    synth = new FakeSynth();
  });

  test("speaks the chunks in order and then finishes", () => {
    const { finished } = reading(synth, ["Uno.", "Dos."]);

    assert.equal(synth.last.text, "Uno.");
    assert.equal(synth.last.voice, ALVARO);
    synth.end();
    assert.equal(synth.last.text, "Dos.");
    synth.end();

    assert.deepEqual(finished, [null]);
  });

  test("reports how far it has read", () => {
    const { progress } = reading(synth, ["Uno dos.", "Tres."]);

    synth.word(4);
    synth.end();
    synth.word(0);

    assert.deepEqual(progress, [4 / 13, 8 / 13]);
  });

  test("a pause cuts the voice and resuming starts the sentence again", async () => {
    const { reading: r } = reading(synth, ["Primera frase. Segunda frase larga."]);
    synth.word(15);
    synth.word(23);

    r.togglePause();
    await settle();
    assert.equal(r.paused, true);
    assert.equal(synth.current, null);
    assert.equal(synth.spoken.length, 1); // the cut is not taken for a failure

    r.togglePause();
    assert.equal(r.paused, false);
    assert.equal(synth.last.text, "Segunda frase larga.");
  });

  test("a new speed waits for the clicks to stop, then goes on from the word", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, ["Una frase bastante larga."]);
    synth.word(10);

    r.setRate(1.1);
    r.setRate(1.2);
    t.mock.timers.tick(SETTLE_MS - 1);
    assert.equal(synth.spoken.length, 1);
    t.mock.timers.tick(1);

    assert.equal(synth.spoken.length, 2);
    assert.equal(synth.last.text, "bastante larga.");
    assert.equal(synth.last.rate, 1.2);
  });

  test("a new speed is not forced on a chunk that started with it", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, ["Uno.", "Dos."]);

    r.setRate(1.2);
    synth.end();
    t.mock.timers.tick(SETTLE_MS);

    assert.equal(synth.spoken.length, 2);
    assert.equal(synth.last.rate, 1.2);
  });

  test("a new speed while paused is used on resuming", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, ["Uno."]);
    r.togglePause();

    r.setRate(1.5);
    t.mock.timers.tick(SETTLE_MS);
    assert.equal(synth.spoken.length, 1);
    r.togglePause();

    assert.equal(synth.last.rate, 1.5);
  });

  test("a failure is tried again after a moment, then with a local voice", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { finished } = reading(synth, ["Una frase que falla."]);
    synth.word(4);

    for (const delay of RETRY_DELAYS_MS) {
      synth.fail();
      t.mock.timers.tick(delay - 1);
      assert.equal(synth.current, null);
      t.mock.timers.tick(1);
      assert.equal(synth.last.text, "frase que falla.");
      assert.equal(synth.last.voice, ALVARO);
    }
    synth.fail();
    assert.equal(synth.last.text, "frase que falla.");
    assert.equal(synth.last.voice, PABLO);
    synth.end();

    assert.deepEqual(finished, [null]);
  });

  test("a voice that speaks again after a failure gets its retries back", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    reading(synth, ["Uno dos tres."]);

    synth.fail();
    t.mock.timers.tick(RETRY_DELAYS_MS[0]);
    synth.word(4);
    synth.fail();
    t.mock.timers.tick(RETRY_DELAYS_MS[0]);

    assert.equal(synth.spoken.length, 3);
    assert.equal(synth.last.voice, ALVARO);
  });

  test("failing again on the same word uses up the retries", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    reading(synth, ["Uno dos tres."]);
    synth.word(4);

    for (const delay of RETRY_DELAYS_MS) {
      synth.fail();
      t.mock.timers.tick(delay);
      synth.word(0); // the restart says the same word, and fails
    }
    synth.fail();

    assert.equal(synth.last.voice, PABLO);
  });

  test("a chunk rejected for its text is left out, and the rest read", () => {
    const { finished, skipped } = reading(synth, ["Uno.", "Dos."]);

    synth.fail("text-too-long");
    assert.equal(synth.last.text, "Dos.");
    synth.end();

    assert.deepEqual(skipped, ["text-too-long"]);
    assert.deepEqual(finished, [null]);
  });

  test("a refused speed is a failure like any other, not a refused text", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { skipped } = reading(synth, ["Uno.", "Dos."]);

    synth.fail("invalid-argument");
    t.mock.timers.tick(RETRY_DELAYS_MS[0]);

    assert.equal(synth.last.text, "Uno.");
    assert.deepEqual(skipped, []);
  });

  test("when no voice can go on, it finishes with the error", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    synth.voices = [ALVARO];
    const { finished } = reading(synth, ["Uno.", "Dos."]);

    for (const delay of RETRY_DELAYS_MS) {
      synth.fail("network");
      t.mock.timers.tick(delay);
    }
    synth.fail("network");

    assert.deepEqual(finished, ["network"]);
    assert.equal(synth.spoken.length, 1 + RETRY_DELAYS_MS.length);
  });

  test("a pause while a retry waits holds it until resuming", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, ["Uno. Dos tres."]);
    synth.word(5);
    synth.fail();

    r.togglePause();
    t.mock.timers.tick(RETRY_DELAYS_MS.at(-1));
    assert.equal(synth.spoken.length, 1);
    r.togglePause();

    assert.equal(synth.last.text, "Dos tres.");
  });

  test("stop cuts the voice and finishes once", async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r, finished } = reading(synth, ["Uno.", "Dos."]);
    r.setRate(1.3);

    r.stop();
    r.stop();
    r.togglePause();
    t.mock.timers.tick(SETTLE_MS);
    await settle();

    assert.equal(synth.current, null);
    assert.equal(synth.spoken.length, 1);
    assert.deepEqual(finished, [null]);
  });
});

describe("Reading, going to another sentence", () => {
  // Sentences start at 0, 9 and 21 of 32 characters.
  const CHUNKS = ["Uno dos. Tres cuatro.", "Cinco seis."];
  let synth;
  beforeEach(() => {
    synth = new FakeSynth();
  });

  test("the slider goes to the start of the sentence at that point", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r, progress } = reading(synth, CHUNKS);

    r.seek(0.5);
    assert.equal(synth.current, null); // silence at once
    t.mock.timers.tick(SETTLE_MS);

    assert.equal(synth.last.text, "Tres cuatro.");
    assert.deepEqual(progress, [9 / 32]);
  });

  test("the voice goes on after the clicks stop, at the last sentence asked", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, CHUNKS);

    r.skip(1);
    r.skip(1);
    t.mock.timers.tick(SETTLE_MS);
    assert.equal(synth.last.text, "Cinco seis.");
    r.skip(-1);
    t.mock.timers.tick(SETTLE_MS);

    assert.equal(synth.last.text, "Tres cuatro.");
    assert.equal(synth.spoken.length, 3);
  });

  test("before the first sentence is its start, after the last there is none", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, CHUNKS);
    synth.word(4);

    r.skip(-1);
    t.mock.timers.tick(SETTLE_MS);
    assert.equal(synth.last.text, "Uno dos. Tres cuatro.");
    synth.end();
    r.skip(1);
    t.mock.timers.tick(SETTLE_MS);

    assert.equal(synth.last.text, "Cinco seis.");
    assert.notEqual(synth.current, null);
    assert.equal(synth.spoken.length, 3);
  });

  test("held, the slider keeps the end from closing the reading", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r, finished } = reading(synth, CHUNKS);
    r.hold(true);
    synth.end();
    synth.end();
    assert.deepEqual(finished, []);

    r.seek(0.5);
    r.hold(false);
    t.mock.timers.tick(SETTLE_MS);

    assert.equal(synth.last.text, "Tres cuatro.");
    assert.deepEqual(finished, []);
  });

  test("a pause with the slider held at the end is ignored", () => {
    const { reading: r } = reading(synth, CHUNKS);
    r.hold(true);
    synth.end();
    synth.end();

    r.togglePause();

    assert.equal(r.paused, false);
  });

  test("let go without a jump, the slider lets the reading end", () => {
    const { reading: r, finished } = reading(synth, CHUNKS);
    r.hold(true);
    synth.end();
    synth.end();

    r.hold(false);

    assert.deepEqual(finished, [null]);
  });

  test("a jump while paused is where resuming starts", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, CHUNKS);
    r.togglePause();

    r.skip(1);
    t.mock.timers.tick(SETTLE_MS);
    assert.equal(synth.spoken.length, 1);
    r.togglePause();

    assert.equal(synth.last.text, "Tres cuatro.");
  });

  test("a jump before the start is where it starts", () => {
    const { reading: r } = reading(synth, CHUNKS, {}, { start: false });

    r.seek(0.9);
    r.start();

    assert.equal(synth.last.text, "Cinco seis.");
  });
});

describe("Reading before it starts", () => {
  let synth;
  beforeEach(() => {
    synth = new FakeSynth();
  });

  test("a stop means it never speaks", () => {
    const { reading: r, finished } = reading(synth, ["Uno."], {}, { start: false });

    r.stop();
    r.start();

    assert.equal(synth.spoken.length, 0);
    assert.deepEqual(finished, [null]);
  });

  test("a new speed waits for the start", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { reading: r } = reading(synth, ["Uno."], {}, { start: false });

    r.setRate(1.4);
    t.mock.timers.tick(SETTLE_MS);
    assert.equal(synth.spoken.length, 0);
    r.start();

    assert.equal(synth.last.rate, 1.4);
  });

  test("a pause holds the start until resuming", () => {
    const { reading: r } = reading(synth, ["Uno."], {}, { start: false });

    r.togglePause();
    r.start();
    assert.equal(synth.spoken.length, 0);
    r.togglePause();

    assert.equal(synth.last.text, "Uno.");
  });
});

describe("sentenceStarts", () => {
  test("lists where each sentence starts, the first at 0", () => {
    assert.deepEqual(sentenceStarts("Uno. Dos: Tres… Cuatro"), [0, 5, 10, 16]);
  });

  test("a lowercase letter after the space goes on with the sentence", () => {
    const text = "Haz clic en «¿La has olvidado?» para entrar, etc. y sigue: ahí. Fin";

    assert.deepEqual(sentenceStarts(text), [0, 64]);
  });

  test("closing quotes or brackets may come before the space", () => {
    assert.deepEqual(sentenceStarts("«¡Hecho!» Ahora. (Ver abajo.) Fin"), [0, 10, 17, 30]);
  });

  test("an ending at the very end starts nothing", () => {
    assert.deepEqual(sentenceStarts("Uno. "), [0]);
  });
});

describe("sentenceStart", () => {
  test("finds the start of the sentence that holds the index", () => {
    const text = "Uno. Dos: Tres; Cuatro… Cinco";

    assert.equal(sentenceStart(text, 2), 0);
    assert.equal(sentenceStart(text, 5), 5);
    assert.equal(sentenceStart(text, 7), 5);
    assert.equal(sentenceStart(text, 12), 10);
    assert.equal(sentenceStart(text, 26), 24);
  });

  test("a full stop without a space after it ends no sentence", () => {
    assert.equal(sentenceStart("Versión 1.5 de algo", 15), 0);
  });
});

describe("voices", () => {
  test("waits for Edge to offer the preferred voice", async () => {
    const synth = new FakeSynth();
    synth.voices = [PABLO];

    const picked = pickVoice(synth, ["Álvaro", "Pablo"]);
    synth.voices = [ALVARO, PABLO];
    synth.dispatchEvent(new Event("voiceschanged"));

    assert.equal(await picked, ALVARO);
  });

  test("falls back to the next preferred voice in time", async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const synth = new FakeSynth();
    synth.voices = [PABLO];

    const picked = pickVoice(synth, ["Álvaro", "Pablo"]);
    t.mock.timers.tick(VOICE_WAIT_MS);

    assert.equal(await picked, PABLO);
  });

  test("a local voice is the preferred one, or any of Spain, or any Spanish", () => {
    const synth = new FakeSynth();
    const helena = { name: "Helena", lang: "es-ES", localService: true };
    const sabina = { name: "Sabina", lang: "es-MX", localService: true };

    assert.equal(localVoice(synth, ["Álvaro", "Pablo"]), PABLO);
    synth.voices = [ALVARO, sabina, helena];
    assert.equal(localVoice(synth, ["Álvaro", "Pablo"]), helena);
    synth.voices = [ALVARO, sabina];
    assert.equal(localVoice(synth, ["Álvaro", "Pablo"]), sabina);
    synth.voices = [ALVARO];
    assert.equal(localVoice(synth, ["Álvaro", "Pablo"]), null);
  });
});
