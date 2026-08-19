// Service worker: what makes this installable and usable offline.
//
// Two caches, deliberately, because the two halves of this app have opposite
// lifetimes:
//
//   shell   — index.html, the modules, the CSS, bridge.py. Kilobytes, changes
//             constantly. Wiped and refetched on every deploy.
//   runtime — Pyodide, numpy, the humm2melody wheel. ~19 MB, changes rarely.
//             Keyed by content, never wiped by an app-code deploy.
//
// One cache for both would mean re-downloading 19 MB every time a CSS colour
// changes, which on a phone is the difference between usable and not.

// The build stamp arrives in the registration URL (`sw.js?v=…`), taken from
// wheel.json. That is deliberate: the browser decides a worker is new by
// comparing the script *bytes*, so a version baked into this file would have
// to be rewritten by the build — churn in git for every deploy. A changing
// query string makes it a different script without editing anything.
const BUILD = new URL(location.href).searchParams.get("v") || "dev";
const SHELL = `h2m-shell-${BUILD}`;
const RUNTIME = "h2m-runtime-v1";

// Everything needed to start. Pyodide is not here on purpose: 19 MB in the
// install event is slow and fails atomically, so it is cached on first use
// instead — which happens on the first load anyway, since the app boots it.
const SHELL_FILES = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./src/app.js",
  "./src/app.css",
  "./src/views.js",
  "./src/pitch-worker.js",
  "./src/capture-worklet.js",
  "./py/bridge.py",
  // Both are fetched by the app before this worker controls the page on a
  // first visit, so they would never reach the cache on their own. They are
  // safe to precache because SHELL is keyed by the build stamp: a new build
  // is a new cache, and these are refetched with it.
  "./public/wheel.json",
  "./public/precache.json",
  "./public/icons/icon-192.png",
  "./public/icons/icon-512.png",
];

const isRuntime = (url) =>
  url.pathname.includes("/public/pyodide/") || url.pathname.endsWith(".whl");

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(SHELL_FILES)).then(() =>
      self.skipWaiting(),
    ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          // Keep the runtime cache; drop shells from earlier builds.
          names
            .filter((n) => n !== SHELL && n !== RUNTIME)
            .map((n) => caches.delete(n)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

// Warming the runtime cache on demand.
//
// The app asks for this once it is up. It cannot happen earlier: on a first
// visit Pyodide is already downloading before this worker controls anything,
// so those 16 MB never pass through the fetch handler and an install followed
// by going offline would fail. Fetching them again here is the price of one
// visit being enough.
async function warm(client) {
  // A client that is not yet controlled is not a usable postMessage target,
  // so fall back to every client in scope.
  const tell = async (message) => {
    if (client) return client.postMessage(message);
    for (const c of await self.clients.matchAll({ includeUncontrolled: true })) {
      c.postMessage(message);
    }
  };

  const cache = await caches.open(RUNTIME);
  let files = [];
  try {
    files = (await (await fetch("./public/precache.json")).json()).files;
  } catch {
    await tell({ type: "warm", state: "unavailable" });
    return;
  }

  let done = 0;
  for (const file of files) {
    const request = new Request(new URL(file, location.href));
    if (!(await cache.match(request))) {
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response);
      } catch {
        await tell({ type: "warm", state: "failed", file });
        return;
      }
    }
    await tell({
      type: "warm", state: "progress", done: ++done, total: files.length,
    });
  }
  await tell({ type: "warm", state: "ready", total: files.length });
}

self.addEventListener("message", (event) => {
  if (event.data?.type === "warm") event.waitUntil(warm(event.source));
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== location.origin) return; // nothing external is expected

  // Large and immutable: serve from cache, populate on first miss.
  if (isRuntime(url)) {
    event.respondWith(
      caches.open(RUNTIME).then(async (cache) => {
        const hit = await cache.match(request);
        if (hit) return hit;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  // wheel.json names the current wheel, so a stale copy would pin the app to
  // an old build: try the network first, fall back to cache when offline.
  if (url.pathname.endsWith("wheel.json")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL).then((c) => c.put(request, copy));
          return response;
        })
        // A cache miss here resolves to undefined, which respondWith turns
        // into a network error — so be explicit about the failure instead.
        .catch(async () => (await caches.match(request)) ?? Response.error()),
    );
    return;
  }

  // The shell: cache first, since the build stamp already guarantees freshness.
  event.respondWith(
    caches.match(request).then((hit) => hit || fetch(request)),
  );
});
