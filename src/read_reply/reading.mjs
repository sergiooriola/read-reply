// The reading behind player.html: speaks the chunks one after another, and
// lets the listener pause, change the speed, go to another sentence and stop.
//
// Edge's online voices, such as Álvaro, ignore speechSynthesis.pause(), so a
// pause cancels the utterance, and resuming speaks again from the start of the
// sentence in progress. A new speed restarts at the word in progress, which
// the "boundary" events report; a jump, at the start of a sentence. No DOM
// here: the tests run it in Node.

export const RATE_MIN = 0.5;
export const RATE_MAX = 2;
export const RATE_STEP = 0.1;
// A restart, for a new speed or a jump, waits for the clicks to stop: each
// one is a new request to the online voice, and quick ones make it fail more.
export const SETTLE_MS = 400;
// Microsoft's service fails now and then for a moment ("synthesis-failed"):
// the same voice is tried again after these waits before a local one.
export const RETRY_DELAYS_MS = [500, 1500];
// The text itself is refused: no retry nor voice would say that chunk.
const TEXT_TOO_LONG = "text-too-long";
// Edge loads its online voices after the page, and announces them.
export const VOICE_WAIT_MS = 5000;

const voiceNamed = (synth, name) =>
  synth.getVoices().find((voice) => voice.name === name);

// The first preferred voice once Edge offers it, or after waitMs the first
// preferred one available, or null.
export function pickVoice(synth, preferred, waitMs = VOICE_WAIT_MS) {
  return new Promise((resolve) => {
    const done = (voice) => {
      synth.removeEventListener("voiceschanged", tryFirst);
      clearTimeout(timer);
      resolve(voice);
    };
    const tryFirst = () => {
      const voice = voiceNamed(synth, preferred[0]);
      if (voice) done(voice);
    };
    const timer = setTimeout(
      () => done(preferred.map((name) => voiceNamed(synth, name)).find(Boolean) ?? null),
      waitMs,
    );
    synth.addEventListener("voiceschanged", tryFirst);
    tryFirst();
  });
}

// A voice that works without internet: the first local one preferred, then
// any local voice of Spain, then any local Spanish one.
export function localVoice(synth, preferred) {
  const local = (voice) => voice?.localService;
  const voices = synth.getVoices().filter(local);
  return (
    preferred.map((name) => voiceNamed(synth, name)).find(local) ??
    voices.find((voice) => voice.lang === "es-ES") ??
    voices.find((voice) => voice.lang.startsWith("es")) ??
    null
  );
}

// Where each sentence of the text starts. A sentence ends at . ! ? … : or ;
// and a space, with any closing quotes or brackets between them.
export function sentenceStarts(text) {
  const ends = [...text.matchAll(/[.!?…:;][»”’"')\]]*\s+/g)];
  const starts = ends.map((end) => end.index + end[0].length);
  return [0, ...starts.filter((start) => start < text.length)];
}

// Where the sentence that holds text[index] starts.
export function sentenceStart(text, index) {
  return sentenceStarts(text).findLast((start) => start <= index);
}

export class Reading {
  voice;
  rate;
  #synth;
  #Utterance;
  #chunks;
  #preferred;
  #onProgress;
  #onSkip;
  #onFinish;
  #starts; // where each chunk starts in the whole reply
  #total;
  #sentences; // where each sentence starts in the whole reply
  #index = 0; // the chunk being read
  #offset = 0; // where in it the utterance in progress starts
  #word = 0; // where in it the word being spoken starts
  #current = null; // the utterance in progress; any other was cancelled
  #failures = 0; // in a row, without getting past where the last one was
  #failedAt = -1; // where in the chunk the last failure was
  #started = false; // the controls work before, while the voice loads
  #held = false; // the slider is held: the end waits, it may go back
  #paused = false;
  #finished = false;
  #waiting = null; // a retry, or a new speed waiting for the clicks to stop

  // synth and Utterance: speechSynthesis and SpeechSynthesisUtterance.
  // preferred: voice names, for a local voice when the online one fails.
  // onSkip(error): a chunk left out because of its text.
  // onFinish(error): once, with null unless no voice could go on.
  constructor({
    synth,
    Utterance,
    chunks,
    voice,
    preferred,
    rate,
    onProgress,
    onSkip,
    onFinish,
  }) {
    this.#synth = synth;
    this.#Utterance = Utterance;
    this.#chunks = chunks;
    this.voice = voice;
    this.#preferred = preferred;
    this.rate = rate;
    this.#onProgress = onProgress;
    this.#onSkip = onSkip;
    this.#onFinish = onFinish;
    this.#starts = [];
    this.#total = 0;
    for (const chunk of chunks) {
      this.#starts.push(this.#total);
      this.#total += chunk.length;
    }
    this.#sentences = chunks.flatMap((chunk, index) =>
      sentenceStarts(chunk).map((start) => this.#starts[index] + start),
    );
  }

  get paused() {
    return this.#paused;
  }

  start() {
    this.#started = true;
    if (!this.#paused && !this.#finished) this.#speak();
  }

  togglePause() {
    if (this.#finished) return;
    this.#paused = !this.#paused;
    if (this.#paused) {
      this.#cancelWait();
      this.#interrupt(sentenceStart(this.#chunks[this.#index], this.#word));
    } else if (this.#started) {
      this.#speak();
    }
  }

  setRate(rate) {
    this.rate = rate;
    if (!this.#started || this.#paused || this.#finished) return; // used later
    this.#wait(SETTLE_MS, () => {
      // A chunk that started meanwhile already has it.
      if (this.#current?.rate === this.rate) return;
      this.#interrupt(this.#word);
      this.#speak();
    });
  }

  // Goes to the sentence at that point of the reply, from 0 to 1.
  seek(fraction) {
    const at = fraction * this.#total;
    this.#jump(this.#sentences.findLast((start) => start <= at) ?? 0);
  }

  // Goes to the sentence before (-1) or after (1) the one in progress; after
  // the last one there is none.
  skip(direction) {
    const ended = this.#index >= this.#chunks.length; // the slider held at the end
    const at = ended ? this.#total : this.#starts[this.#index] + this.#word;
    const current = this.#sentences.findLastIndex((start) => start <= at);
    const target = this.#sentences[Math.max(current + direction, 0)];
    if (target !== undefined) this.#jump(target);
  }

  // While the slider is held, the reading does not end: the listener may be
  // about to go back.
  hold(held) {
    this.#held = held;
    if (!held && this.#index >= this.#chunks.length) this.#finish(null);
  }

  stop() {
    this.#finish(null);
  }

  #speak() {
    if (this.#index >= this.#chunks.length) {
      if (!this.#held) this.#finish(null);
      return;
    }
    const offset = this.#offset;
    const utterance = new this.#Utterance(this.#chunks[this.#index].slice(offset));
    utterance.voice = this.voice;
    utterance.lang = this.voice?.lang ?? "es-ES";
    utterance.rate = this.rate;
    utterance.onboundary = (event) => {
      if (utterance !== this.#current || event.name !== "word") return;
      this.#word = offset + event.charIndex;
      if (this.#word > this.#failedAt) this.#failures = 0; // it got past it
      this.#onProgress((this.#starts[this.#index] + this.#word) / this.#total);
    };
    utterance.onend = () => {
      if (utterance === this.#current) this.#next();
    };
    utterance.onerror = (event) => {
      if (utterance !== this.#current) return; // cancelled on purpose
      this.#recover(event.error);
    };
    this.#current = utterance;
    this.#word = offset;
    this.#synth.speak(utterance);
  }

  #next() {
    this.#index += 1;
    this.#offset = 0;
    this.#failures = 0;
    this.#failedAt = -1;
    this.#speak();
  }

  // The same voice again from the word in progress after a moment, then a
  // local voice for the rest, then the end.
  #recover(error) {
    this.#current = null;
    if (error === TEXT_TOO_LONG) {
      this.#onSkip(error);
      return this.#next();
    }
    this.#offset = this.#word;
    this.#failedAt = this.#word;
    if (this.#failures < RETRY_DELAYS_MS.length) {
      this.#wait(RETRY_DELAYS_MS[this.#failures++], () => this.#speak());
      return;
    }
    const local = !this.voice?.localService && localVoice(this.#synth, this.#preferred);
    if (local) {
      this.voice = local;
      this.#failures = 0;
      return this.#speak();
    }
    this.#finish(error);
  }

  // Moves to a place in the whole reply: silence at once, and the voice there
  // once the clicks stop.
  #jump(at) {
    if (this.#finished) return;
    this.#index = this.#starts.findLastIndex((start) => start <= at);
    this.#offset = this.#word = at - this.#starts[this.#index];
    this.#failures = 0;
    this.#failedAt = -1;
    this.#onProgress(at / this.#total);
    if (!this.#started || this.#paused) return; // starting or resuming goes there
    this.#current = null;
    this.#synth.cancel();
    this.#wait(SETTLE_MS, () => this.#speak());
  }

  // Cancels the utterance in progress; the next one starts at "from".
  #interrupt(from) {
    this.#offset = from;
    this.#current = null;
    this.#synth.cancel();
  }

  // Runs "then" after "ms", instead of whatever was waiting: a new speed
  // replaces a retry, since both speak again.
  #wait(ms, then) {
    this.#cancelWait();
    this.#waiting = setTimeout(() => {
      this.#waiting = null;
      then();
    }, ms);
  }

  #cancelWait() {
    clearTimeout(this.#waiting);
    this.#waiting = null;
  }

  #finish(error) {
    if (this.#finished) return;
    this.#finished = true;
    this.#cancelWait();
    this.#current = null;
    this.#synth.cancel();
    this.#onFinish(error);
  }
}
