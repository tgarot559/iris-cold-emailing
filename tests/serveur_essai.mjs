// Faux Cloudflare + faux GitHub pour l'essai : sert site/ et fait tourner les vraies fonctions,
// en remplaçant l'API GitHub par le dossier d'essai.   node tests/serveur_essai.mjs <racine d'essai> <port>
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ici = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [racine, port] = [process.argv[2], Number(process.argv[3])];
const copie = path.join(racine, "espace-fn.mjs");
fs.copyFileSync(path.join(ici, "functions/api/espace.js"), copie);
const fn = await import(pathToFileURL(copie));
const env = { GITHUB_TOKEN: "jeton-essai", GITHUB_REPO: "essai/depot", CLE_CONSOLE: "cle-essai" };

globalThis.fetch = async (url, opt = {}) => {
  const m = String(url).match(/^https:\/\/api\.github\.com\/repos\/essai\/depot\/contents\/(.+)$/);
  if (!m || opt.headers.authorization !== "Bearer jeton-essai") return new Response("", { status: 401 });
  const cible = path.join(racine, decodeURIComponent(m[1]));
  if (!cible.startsWith(racine + path.sep)) return new Response("", { status: 400 });
  if ((opt.method || "GET") === "GET") return fs.existsSync(cible) ? new Response(fs.readFileSync(cible, "utf8")) : new Response("", { status: 404 });
  fs.mkdirSync(path.dirname(cible), { recursive: true });
  fs.writeFileSync(cible, Buffer.from(JSON.parse(opt.body).content, "base64"));
  return new Response("{}", { status: 201 });
};

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost:" + port);
  if (url.pathname === "/api/espace") {
    const corps = await new Promise(r => { let d = ""; req.on("data", c => d += c); req.on("end", () => r(d)); });
    const request = new Request(url, { method: req.method, headers: req.headers, body: req.method === "POST" ? corps : undefined });
    const rep = await (req.method === "POST" ? fn.onRequestPost : fn.onRequestGet)({ request, env });
    res.writeHead(rep.status, Object.fromEntries(rep.headers)); res.end(await rep.text()); return;
  }
  const fichier = url.pathname.startsWith("/e/") ? "espace.html" : url.pathname === "/console/" ? "console/index.html" : null;
  if (!fichier) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); res.end(fs.readFileSync(path.join(ici, "site", fichier)));
}).listen(port, "127.0.0.1", () => console.log("pret"));
