// The service worker (add-web-application, Stage 4b). It caches only the static app shell, from the
// fixed list below, when it installs. It never stores a response at runtime and never answers for
// anything else, so /api responses, drafts, and query results cannot end up in a cache.
//
// The server fills in VERSION with a hash of the shell's files, so a new build is a new worker. A new
// worker installs and waits; the page tells it to take over only when no note is being typed.
"use strict";

const VERSION = "__SHELL_VERSION__";
const PREFIX = "outreach-shell-";
const CACHE = `${PREFIX}${VERSION}`;
const SHELL = ["./", "index.html", "offline.html", "style.css", "app.js", "screens.js", "device.js", "queue.js", "seal.js", "ssn.js", "manifest.webmanifest", "fonts/inter-latin-wght-normal.woff2", "icons/icon-192.png", "icons/icon-512.png"];

const SCOPE = new URL("./", self.location);
const PATHS = new Set(SHELL.map((path) => new URL(path, SCOPE).pathname));
const OFFLINE_PAGE = new URL("offline.html", SCOPE).href;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL.map((path) => new Request(new URL(path, SCOPE).href, { cache: "reload" })))));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((names) => Promise.all(names.filter((name) => name.startsWith(PREFIX) && name !== CACHE).map((name) => caches.delete(name))))
    .then(() => self.clients.claim()));
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "activate") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (PATHS.has(url.pathname)) {
    event.respondWith(caches.open(CACHE).then((cache) => cache.match(url.href, { ignoreSearch: true })).then((hit) => hit || fetch(request)));
    return;
  }
  if (request.mode === "navigate" && url.pathname.startsWith(SCOPE.pathname)) {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_PAGE)));
  }
});
