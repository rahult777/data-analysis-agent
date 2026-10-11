// A dependency-free static server for the public e2e
// (playwright.public.config.ts). It serves a Next static export (out/) on
// 127.0.0.1 the way Vercel serves one:
//   - extensionless HTML: /x serves x.html, and / serves index.html;
//   - a URL ending in .html is a 404 (Vercel strips .html from exported files);
//   - a missing page gets 404.html with status 404;
//   - query strings are ignored;
//   - .txt is text/plain; charset=utf-8: Next's exported router fetches
//     <path>.txt?_rsc=… and accepts only text/x-component or text/plain.
// Usage: node e2e-public/serve-static.mjs <root dir> <port>

import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const [rootArg, portArg] = process.argv.slice(2);
const port = Number.parseInt(portArg ?? "", 10);
if (!rootArg || !Number.isInteger(port)) {
  console.error("usage: node e2e-public/serve-static.mjs <root dir> <port>");
  process.exit(2);
}
const root = path.resolve(rootArg);

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

// A regular file under root, or null. Never anything outside root.
function fileAt(urlPath) {
  const target = path.join(root, urlPath);
  if (target !== root && !target.startsWith(`${root}${path.sep}`)) return null;
  try {
    return fs.statSync(target).isFile() ? target : null;
  } catch {
    return null;
  }
}

function resolvePage(pathname) {
  if (pathname.endsWith(".html")) return null;
  if (pathname === "/") return fileAt("/index.html");
  return fileAt(pathname) ?? fileAt(`${pathname}.html`);
}

const server = http.createServer((request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { allow: "GET, HEAD" }).end();
    return;
  }
  let pathname = null;
  try {
    pathname = decodeURIComponent(new URL(request.url ?? "/", "http://127.0.0.1").pathname);
  } catch {
    pathname = null;
  }
  const found = pathname === null ? null : resolvePage(pathname);
  const file = found ?? fileAt("/404.html");
  if (file === null) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("Not found");
    return;
  }
  const type = CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream";
  response.writeHead(found ? 200 : 404, { "content-type": type, "content-length": fs.statSync(file).size });
  if (request.method === "HEAD") response.end();
  else fs.createReadStream(file).pipe(response);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Serving ${root} at http://127.0.0.1:${port}`);
});
