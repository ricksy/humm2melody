// The visual half of the app. Everything here mirrors a widget in
// humm2melody/tui.py — same palette, same information, same names — so that
// the two front ends stay recognisably one app.
//
// Where the terminal is limited by the character cell, this is not, and a few
// things are deliberately better: the piano roll can show a gap narrower than
// one cell (a limitation the roadmap lists), and the keyboard is drawn rather
// than approximated with block characters.

export const ACCENT = "#7dd3fc";       // white-key notes
export const ACCENT_SHARP = "#818cf8"; // black-key notes
export const HIGHLIGHT = "#fbbf24";    // playhead, lit keys, active note
export const SELECTED = "#f472b6";     // the note being edited

const WHITE_STEPS = [0, 2, 4, 5, 7, 9, 11];
export const isBlack = (midi) => !WHITE_STEPS.includes(midi % 12);

const svg = (tag, attrs = {}) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

// ------------------------------------------------------------------ dials

// Captions copied from tui.py so a level reads the same in both front ends.
export const DIALS = {
  sensitivity: {
    label: "Pitch", keys: "[ ]",
    captions: ["forgiving — small wobbles read as one note", "balanced",
               "literal — small differences become separate notes"],
  },
  pause: {
    label: "Pauses", keys: "< >",
    captions: ["only real silence separates notes", "balanced",
               "a fresh attack alone starts a new note"],
  },
  mix: {
    label: "Mix", keys: "- +",
    captions: ["mostly your hum, tones underneath", "balanced — favours your voice",
               "mostly tones, hum underneath"],
  },
  tempo: {
    label: "Tempo", keys: "< >",
    captions: ["slower, for learning it", "as recorded", "faster"],
    speeds: true, // caption gains the actual multiplier, as TempoDial does
  },
};

export function renderDial(host, kind, level, speeds = null) {
  const { label, keys, captions } = DIALS[kind];
  let caption = level < 5 ? captions[0] : level === 5 ? captions[1] : captions[2];
  if (DIALS[kind].speeds && speeds && level !== 5) {
    caption += ` — ${speeds[level].toFixed(2)}×`;
  }
  const pips = Array.from({ length: 9 }, (_, i) =>
    `<span class="${i + 1 === level ? "pip on" : "pip"}">${i + 1 === level ? "●" : "·"}</span>`,
  ).join("");
  host.innerHTML =
    `<span class="dial-label">${label}</span><span class="keys">${keys}</span>` +
    `<span class="pips">[${pips}]</span><b>${level}/9</b>` +
    `<span class="caption">${caption}</span>`;
}

// --------------------------------------------------------------- readout

export function renderReadout(host, r) {
  if (!r || !r.note) {
    host.innerHTML = `<span class="big dim">——</span><span class="dim">listening…</span>`;
    return;
  }
  const tuning =
    Math.abs(r.cents) < 12
      ? `<span class="in-tune">in tune</span>`
      : `<span class="off">${r.cents > 0 ? "♯" : "♭"}${Math.abs(r.cents).toFixed(0)}¢</span>`;
  host.innerHTML =
    `<span class="big">${r.note}</span>${tuning}` +
    `<span class="dim">${r.freq.toFixed(1)} Hz</span>` +
    `<span class="dim">·</span><span class="dim">${r.elapsed.toFixed(1)}s</span>`;
}

// A level meter with the same green/yellow/red zones as LevelMeter.
export function renderMeter(host, level) {
  const pct = Math.min(1, Math.max(0, level)) * 100;
  host.style.width = `${pct}%`;
  host.style.background = pct < 70 ? "#4ade80" : pct < 90 ? "#facc15" : "#f87171";
}

// ------------------------------------------------------------ piano roll

export function renderRoll(host, notes, { scheme = "english", spellings = {},
                                          playhead = null, selected = null } = {}) {
  host.innerHTML = "";
  if (!notes.length) return;

  const span = Math.max(...notes.map((n) => n.end)) || 1;
  const lo = Math.min(...notes.map((n) => n.midi));
  const hi = Math.max(...notes.map((n) => n.midi));
  const rows = hi - lo + 1;

  const ROW = 16, LABEL = 46, AXIS = 22, PAD = 8;
  const width = Math.max(320, host.clientWidth - LABEL - PAD);
  const height = rows * ROW + AXIS;
  const board = svg("svg", {
    viewBox: `0 0 ${LABEL + width + PAD} ${height}`,
    width: "100%", height, class: "roll",
  });

  const y = (midi) => (hi - midi) * ROW;
  const x = (t) => LABEL + (t / span) * width;

  for (let midi = lo; midi <= hi; midi++) {
    // Black-key rows sit on a darker band, exactly as the terminal dims them.
    board.appendChild(svg("rect", {
      x: LABEL, y: y(midi), width, height: ROW,
      fill: isBlack(midi) ? "#1b1b1f" : "#202027",
    }));
    const name = spellings[scheme]?.[midi] ?? String(midi);
    const label = svg("text", {
      x: LABEL - 8, y: y(midi) + ROW - 4, "text-anchor": "end",
      class: isBlack(midi) ? "row-label dim" : "row-label",
    });
    label.textContent = name;
    board.appendChild(label);
  }

  notes.forEach((n, i) => {
    // A real minimum width in pixels, not one character cell — so two quick
    // repeated notes stay visibly separate here even where the TUI joins them.
    const left = x(n.start);
    const w = Math.max(2, x(n.end) - left);
    const rect = svg("rect", {
      x: left, y: y(n.midi) + 2, width: w, height: ROW - 4, rx: 2,
      fill: i === selected ? SELECTED : isBlack(n.midi) ? ACCENT_SHARP : ACCENT,
      class: "note-bar", "data-index": i,
    });
    rect.appendChild(svg("title")).textContent =
      `${n.names?.[scheme] ?? n.name} · ${n.start.toFixed(2)}s · ${n.duration.toFixed(2)}s`;
    board.appendChild(rect);
  });

  // Time axis, with the same tick spacing rule as _tick_step().
  const step = [0.5, 1, 2, 5, 10, 30, 60].find((s) => span / s <= 12) ?? 120;
  const axisY = rows * ROW;
  board.appendChild(svg("line", {
    x1: LABEL, y1: axisY, x2: LABEL + width, y2: axisY, class: "axis",
  }));
  for (let t = 0; t <= span; t += step) {
    board.appendChild(svg("line", {
      x1: x(t), y1: axisY, x2: x(t), y2: axisY + 4, class: "axis",
    }));
    const tick = svg("text", { x: x(t), y: axisY + 16, class: "tick" });
    tick.textContent = `${+t.toFixed(2)}s`;
    board.appendChild(tick);
  }

  if (playhead !== null) {
    board.appendChild(svg("line", {
      x1: x(playhead), y1: 0, x2: x(playhead), y2: axisY,
      stroke: HIGHLIGHT, "stroke-width": 2,
    }));
  }
  host.appendChild(board);
}

// ---------------------------------------------------------- piano keys

export function renderKeys(host, notes, { scheme = "english", spellings = {},
                                          lit = new Set() } = {}) {
  host.innerHTML = "";
  // Round outwards to whole octaves, as PianoKeys.set_range does.
  let low = 60, high = 71;
  if (notes.length) {
    low = Math.floor(Math.min(...notes.map((n) => n.midi)) / 12) * 12;
    high = Math.floor(Math.max(...notes.map((n) => n.midi)) / 12) * 12 + 11;
  }

  const whites = [];
  for (let m = low; m <= high; m++) if (!isBlack(m)) whites.push(m);

  const W = 34, H = 104, BW = 20, BH = 64;
  const board = svg("svg", {
    viewBox: `0 0 ${whites.length * W} ${H}`,
    width: "100%", height: H, class: "keys",
  });

  whites.forEach((midi, i) => {
    board.appendChild(svg("rect", {
      x: i * W, y: 0, width: W - 1, height: H, rx: 3,
      fill: lit.has(midi) ? HIGHLIGHT : "#f4f4f5", stroke: "#3f3f46",
    }));
    const name = spellings[scheme]?.[midi] ?? "";
    const label = svg("text", {
      x: i * W + (W - 1) / 2, y: H - 8, "text-anchor": "middle", class: "key-label",
    });
    label.textContent = name;
    board.appendChild(label);
  });

  // Black keys are drawn after, so they overlay the whites they sit between.
  whites.forEach((midi, i) => {
    if (isBlack(midi + 1) && midi + 1 <= high) {
      board.appendChild(svg("rect", {
        x: i * W + W - BW / 2 - 1, y: 0, width: BW, height: BH, rx: 2,
        fill: lit.has(midi + 1) ? HIGHLIGHT : "#18181b", stroke: "#3f3f46",
      }));
    }
  });
  host.appendChild(board);
}

// ------------------------------------------------------------- sequence

export function renderSequence(host, notes, { scheme = "english",
                                              active = null, selected = null } = {}) {
  if (!notes.length) { host.innerHTML = ""; return; }
  const parts = notes.map((n, i) => {
    const gap = i && n.start - notes[i - 1].end > 0.25 ? `<span class="gap">·</span>` : "";
    const name = n.names?.[scheme] ?? n.name;
    const cls = i === active ? "seq active" : i === selected ? "seq chosen" : "seq";
    return `${gap}<span class="${cls}" data-index="${i}">${name}</span>`;
  });
  host.innerHTML = `<span class="dim">Play this:</span> ${parts.join("")}`;
}

// ---------------------------------------------------------------- table

export function renderTable(host, notes, { scheme = "english", selected = null } = {}) {
  if (!notes.length) { host.innerHTML = ""; return; }
  const rows = notes.map((n, i) => {
    const tuning = Math.abs(n.cents) < 12
      ? `<span class="in-tune">on pitch</span>`
      : `<span class="off">${n.cents > 0 ? "+" : "−"}${Math.abs(n.cents).toFixed(0)}¢</span>`;
    return `<tr data-index="${i}" class="${i === selected ? "chosen" : ""}">
      <td class="dim">${i === selected ? "▸" : i + 1}</td>
      <td class="n">${n.names?.[scheme] ?? n.name}</td>
      <td>${n.start.toFixed(2)}s</td><td>${n.duration.toFixed(2)}s</td>
      <td class="dim">${n.freq.toFixed(1)}</td><td>${tuning}</td></tr>`;
  });
  host.innerHTML =
    `<table><thead><tr><th></th><th>Note</th><th>Start</th><th>Length</th>
     <th>Hz</th><th>Tuning</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

export function renderNotation(host, schemes, current) {
  const chips = schemes.map((s) =>
    `<button class="chip ${s.key === current ? "on" : ""}" data-scheme="${s.key}">${s.label}</button>`,
  ).join("");
  const note = schemes.find((s) => s.key === current)?.note ?? "";
  host.innerHTML =
    `<span class="dial-label">Notation</span><span class="keys">n</span>` +
    `<span class="chips">${chips}</span><span class="caption">${note}</span>`;
}
