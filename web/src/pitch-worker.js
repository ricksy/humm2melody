// Pyodide lives here, off both the audio thread and the UI thread — the same
// three-way split the desktop app uses (PortAudio callback / worker thread /
// Textual). A module worker is required: pyodide.asm.mjs is an ES module and
// classic importScripts() workers cannot load it.

// Vendored, not a CDN: an installed PWA must be able to launch with no
// network at all, and the service worker can only cache what it serves.
// web/scripts/vendor-pyodide.sh puts it there.
const PYODIDE = new URL("../public/pyodide/", import.meta.url).href;

let pyodide = null;
let bridge = null;

async function boot(bridgeUrl, wheelUrl) {
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  pyodide = await loadPyodide({ indexURL: PYODIDE });

  await pyodide.loadPackage(["numpy", "micropip"]);

  // deps=False is load-bearing. The wheel declares sounddevice, soundfile and
  // textual as hard requirements; the first two are C bindings with no wasm
  // build and micropip would fail resolving them. The code paths that use them
  // are all lazily imported, so nothing here needs them. See docs/pwa.md.
  await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheelUrl)}, deps=False)
`);

  const source = await (await fetch(bridgeUrl)).text();
  pyodide.FS.mkdirTree("/web");
  pyodide.FS.writeFile("/web/bridge.py", source);
  pyodide.runPython("import sys; sys.path.insert(0, '/web'); import bridge");
  bridge = pyodide.globals.get("bridge");

  const version = pyodide.runPython("import humm2melody; humm2melody.__version__");
  return {
    version,
    python: pyodide.runPython("import sys; sys.version.split()[0]"),
    // Sent once. Note spelling and the tempo curve stay defined in Python;
    // the browser only renders what it is told.
    schemes: JSON.parse(bridge.schemes()),
    tempo: JSON.parse(bridge.tempo_table()),
  };
}

self.onmessage = async ({ data }) => {
  try {
    switch (data.type) {
      case "boot": {
        const info = await boot(data.bridgeUrl, data.wheelUrl);
        self.postMessage({ type: "ready", ...info });
        break;
      }
      case "start": {
        const config = JSON.parse(bridge.start(data.inputRate));
        self.postMessage({ type: "started", config });
        break;
      }
      case "block": {
        // Returns a JSON string, or None until the first window is full.
        const reading = bridge.push(data.block);
        if (reading) {
          self.postMessage({ type: "reading", reading: JSON.parse(reading) });
        }
        break;
      }
      case "transcribe": {
        const notes = JSON.parse(bridge.transcribe(data.level, data.pauseLevel));
        // Row and key labels need every pitch in range, not just the sounded
        // ones, and the roll rounds outwards to whole octaves.
        let spellings = {};
        if (notes.length) {
          const midis = notes.map((n) => n.midi);
          const low = Math.floor(Math.min(...midis) / 12) * 12;
          const high = Math.floor(Math.max(...midis) / 12) * 12 + 11;
          spellings = JSON.parse(bridge.spell_range(low, high));
        }
        self.postMessage({ type: "notes", notes, spellings });
        break;
      }
      case "playback": {
        // render() and mix_hum_with_tones() reused verbatim from the desktop
        // app; only the sink differs.
        const buffer = bridge.playback(data.rate, data.mixLevel).toJs();
        self.postMessage({ type: "audio", buffer, rate: data.rate }, [buffer.buffer]);
        break;
      }
    }
  } catch (error) {
    self.postMessage({ type: "error", message: String(error) });
  }
};
