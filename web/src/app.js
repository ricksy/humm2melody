// Main thread: microphone, tabs, and the message plumbing to the worker.
// No analysis happens here, and no drawing — that is views.js.

import {
  renderDial, renderKeys, renderMeter, renderNotation, renderReadout,
  renderRoll, renderSequence, renderTable,
} from "./views.js";

const SAMPLE_RATE = 22050;      // matches humm2melody/audio.py
const TARGET_FPS = SAMPLE_RATE / 512;

const el = (id) => document.getElementById(id);
const worker = new Worker(new URL("./pitch-worker.js", import.meta.url), {
  type: "module",
});

// Everything the views draw from. One object so a redraw is always consistent.
const state = {
  notes: [], schemes: [], scheme: "english", spellings: {},
  selected: null, active: null, playhead: null,
  levels: { sensitivity: 5, pause: 5, mix: 5, tempo: 5 },
  tempo: {},
};

let context = null;
let stream = null;
let capturing = false;
const recent = [];

const status = (text, kind = "") => {
  el("status").textContent = text;
  el("status").className = kind;
};

// --------------------------------------------------------------- drawing

function drawDials() {
  for (const kind of ["sensitivity", "pause", "mix", "tempo"]) {
    renderDial(el(`dial-${kind}`), kind, state.levels[kind], state.tempo);
  }
  renderNotation(el("notation"), state.schemes, state.scheme);
}

function drawMelody() {
  const opts = {
    scheme: state.scheme, spellings: state.spellings,
    selected: state.selected, active: state.active, playhead: state.playhead,
    lit: new Set(state.active !== null ? [state.notes[state.active].midi] : []),
  };
  renderSequence(el("sequence"), state.notes, opts);
  renderKeys(el("keys"), state.notes, opts);
  renderRoll(el("roll"), state.notes, opts);
  renderTable(el("table"), state.notes, opts);
  const has = state.notes.length > 0;
  el("play").disabled = !has;
  el("playmix").disabled = !has;
}

// Redraw the roll on resize: its width is measured, not fixed.
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawMelody, 120);
});

// ------------------------------------------------------------------ boot

status("Loading Pyodide, numpy and the humm2melody wheel…");
fetch("./public/wheel.json")
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error("no wheel.json"))))
  .then(({ wheel, built }) => {
    el("build").textContent = `${wheel} · built ${built}`;
    registerWorker(built);
    worker.postMessage({
      type: "boot",
      bridgeUrl: new URL("../py/bridge.py", import.meta.url).href,
      wheelUrl: new URL(`../public/${wheel}`, import.meta.url).href,
    });
  })
  .catch(() =>
    status("No wheel found — run ./web/scripts/build-wheel.sh first.", "bad"),
  );

// ------------------------------------------------------------------- PWA

// Versioned by the build stamp from wheel.json, so a deploy produces a
// genuinely new worker without the build having to rewrite sw.js.
function registerWorker(build) {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker
      .register(`./sw.js?v=${encodeURIComponent(build)}`)
      .then(async (reg) => {
        el("offline").textContent = "caching runtime…";
        // Wait for a controller before asking: a worker that is not yet in
        // control cannot be messaged, and on a first visit it never is.
        await navigator.serviceWorker.ready;
        navigator.serviceWorker.addEventListener("message", ({ data }) => {
          if (data?.type !== "warm") return;
          if (data.state === "progress") {
            el("offline").textContent =
              `caching runtime ${data.done}/${data.total}`;
          } else if (data.state === "ready") {
            el("offline").textContent = "offline ready";
          } else {
            el("offline").textContent = "offline unavailable";
          }
        });
        // `controller` is still null on a first visit — the page that
        // registered a worker is not controlled by it until a navigation.
        // `reg.active` is the worker either way, so message that.
        (reg.active ?? navigator.serviceWorker.controller)?.postMessage({
          type: "warm",
        });
        // A waiting worker means a newer build is installed but the old one
        // still controls this tab; say so rather than silently serving stale.
        reg.addEventListener("updatefound", () => {
          const fresh = reg.installing;
          fresh?.addEventListener("statechange", () => {
            if (fresh.state === "installed" && navigator.serviceWorker.controller) {
              el("offline").textContent = "update ready — reload";
            }
          });
        });
      })
      .catch(() => { el("offline").textContent = "offline unavailable"; });
}

// Chrome fires this instead of showing its own prompt; Safari never does, and
// installs through the share sheet, so the button simply stays hidden there.
let installPrompt = null;
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  el("install").hidden = false;
});
el("install").onclick = async () => {
  if (!installPrompt) return;
  el("install").hidden = true;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
};
addEventListener("appinstalled", () => { el("install").hidden = true; });

// --------------------------------------------------------------- capture

async function start() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // The detector wants the raw voice; browser speech processing fights it.
        echoCancellation: false, noiseSuppression: false, autoGainControl: false,
      },
    });
  } catch (error) {
    status(`Microphone refused: ${error.name}`, "bad");
    return;
  }

  context = new AudioContext({ sampleRate: SAMPLE_RATE });
  await context.audioWorklet.addModule(
    new URL("./capture-worklet.js", import.meta.url),
  );

  const source = context.createMediaStreamSource(stream);
  const capture = new AudioWorkletNode(context, "capture");
  capture.port.onmessage = ({ data }) =>
    worker.postMessage({ type: "block", block: data }, [data.buffer]);
  source.connect(capture);
  // Some browsers do not pull a worklet with nothing downstream; a muted gain
  // keeps the graph alive without routing the microphone to the speakers.
  const silence = context.createGain();
  silence.gain.value = 0;
  capture.connect(silence).connect(context.destination);

  worker.postMessage({ type: "start", inputRate: context.sampleRate });
  capturing = true;
  recent.length = 0;
  state.notes = [];
  state.selected = state.active = state.playhead = null;
  drawMelody();
  el("start").disabled = true;
  el("stop").disabled = false;
}

async function stop() {
  capturing = false;
  el("stop").disabled = true;
  el("start").disabled = false;
  stream?.getTracks().forEach((t) => t.stop());
  await context?.close();
  context = null;
  status("Segmenting…");
  retranscribe();
}

const retranscribe = () =>
  worker.postMessage({
    type: "transcribe",
    level: state.levels.sensitivity,
    pauseLevel: state.levels.pause,
  });

// -------------------------------------------------------------- playback

let playbackTimer = null;

function play(buffer, rate) {
  const ctx = new AudioContext();
  const audio = ctx.createBuffer(1, buffer.length, rate);
  audio.getChannelData(0).set(buffer);
  const source = ctx.createBufferSource();
  source.buffer = audio;
  source.connect(ctx.destination);

  // Drive the playhead and the lit keys off the clock, as the TUI does.
  const started = ctx.currentTime;
  clearInterval(playbackTimer);
  playbackTimer = setInterval(() => {
    const at = (ctx.currentTime - started) * speed();
    state.playhead = at;
    const i = state.notes.findIndex((n) => at >= n.start && at < n.end);
    state.active = i === -1 ? null : i;
    drawMelody();
    if (at > (state.notes.at(-1)?.end ?? 0) + 0.4) {
      clearInterval(playbackTimer);
      state.playhead = state.active = null;
      drawMelody();
      ctx.close();
    }
  }, 40);

  source.playbackRate.value = speed();
  source.start();
}

// From playback.tempo_speed(), sent at boot — not reimplemented here.
const speed = () => state.tempo[state.levels.tempo] ?? 1.0;

// ---------------------------------------------------------------- events

worker.onmessage = ({ data }) => {
  switch (data.type) {
    case "ready":
      status(`Ready — humm2melody ${data.version} on Python ${data.python}`, "good");
      state.schemes = data.schemes;
      state.tempo = data.tempo;
      drawDials();
      el("start").disabled = false;
      break;
    case "started":
      status(
        data.config.resampling
          ? `Recording — ${data.config.inputRate} Hz input, resampled to ${data.config.sampleRate}`
          : "Recording",
        data.config.resampling ? "warn" : "",
      );
      break;
    case "reading":
      if (!capturing) break;
      renderReadout(el("readout"), data.reading);
      renderMeter(el("meter"), data.reading.level);
      showRate(data.reading);
      break;
    case "notes":
      state.notes = data.notes;
      state.spellings = data.spellings;
      state.selected = null;
      status(data.notes.length ? `${data.notes.length} notes` : "Nothing detected");
      drawMelody();
      break;
    case "audio":
      play(data.buffer, data.rate);
      break;
    case "error":
      status(data.message, "bad");
      break;
  }
};

function showRate(r) {
  const now = performance.now();
  recent.push(now);
  while (recent.length && now - recent[0] > 2000) recent.shift();
  const fps =
    recent.length > 1 ? (recent.length - 1) / ((now - recent[0]) / 1000) : 0;
  el("fps").textContent = fps.toFixed(1);
  el("fps").style.color = fps >= TARGET_FPS * 0.95 ? "var(--green)" : "#f87171";
  el("cost").textContent = `${r.meanAnalysisMs.toFixed(2)} ms`;
  el("budget").textContent = `${(1000 / TARGET_FPS / r.meanAnalysisMs).toFixed(0)}×`;
}

el("start").onclick = start;
el("stop").onclick = stop;
el("play").onclick = () =>
  worker.postMessage({ type: "playback", rate: 44100, mixLevel: 0 });
el("playmix").onclick = () =>
  worker.postMessage({ type: "playback", rate: 44100, mixLevel: state.levels.mix });

// Click a pip to set a dial; the two that change detection re-segment.
el("tabs").onclick = (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("on", t === tab);
  for (const name of ["record", "calibrate", "train"]) {
    el(`pane-${name}`).hidden = name !== tab.dataset.tab;
  }
};

document.querySelector(".dials").onclick = (e) => {
  const scheme = e.target.closest(".chip")?.dataset.scheme;
  if (scheme) {
    state.scheme = scheme;
    drawDials();
    drawMelody();
    return;
  }
  const pip = e.target.closest(".pip");
  if (!pip) return;
  const kind = pip.closest(".dial")?.id.replace("dial-", "");
  // The notation row shares the .dial class but has no level, so guard rather
  // than writing a junk key into state.levels.
  if (!(kind in state.levels)) return;
  const level = [...pip.parentElement.querySelectorAll(".pip")].indexOf(pip) + 1;
  state.levels[kind] = level;
  drawDials();
  // Pitch and pause change what the notes *are*; mix and tempo only affect
  // playback, so they must not trigger a re-segmentation.
  if (state.notes.length && (kind === "sensitivity" || kind === "pause")) {
    retranscribe();
  }
};

// Selecting a note from either the roll or the table, as the TUI allows.
const select = (index) => {
  state.selected = state.selected === index ? null : index;
  drawMelody();
};
el("roll").onclick = (e) => {
  const bar = e.target.closest(".note-bar");
  if (bar) select(Number(bar.dataset.index));
};
el("table").onclick = (e) => {
  const row = e.target.closest("tr[data-index]");
  if (row) select(Number(row.dataset.index));
};
el("sequence").onclick = (e) => {
  const chip = e.target.closest(".seq");
  if (chip) select(Number(chip.dataset.index));
};

// Keyboard shortcuts, matching tui.py where they make sense in a browser.
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const bump = (kind, by) => {
    state.levels[kind] = Math.min(9, Math.max(1, state.levels[kind] + by));
    drawDials();
    if (kind === "sensitivity" || kind === "pause") retranscribe();
  };
  const keys = {
    "[": () => bump("sensitivity", -1), "]": () => bump("sensitivity", 1),
    "<": () => bump("pause", -1), ">": () => bump("pause", 1),
    ",": () => bump("pause", -1), ".": () => bump("pause", 1),
    "-": () => bump("mix", -1), "=": () => bump("mix", 1),
    n: () => {
      const i = state.schemes.findIndex((s) => s.key === state.scheme);
      state.scheme = state.schemes[(i + 1) % state.schemes.length].key;
      drawDials();
      drawMelody();
    },
    r: () => !el("start").disabled && start(),
    s: () => !el("stop").disabled && stop(),
    p: () => !el("play").disabled && el("play").click(),
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});
