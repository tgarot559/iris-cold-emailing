// Page de suivi en direct (Cloudflare Pages Functions), même mécanique que les espaces IRIS.
//   GET  /api/espace?code=<code>          données d'un client, lues dans espaces/<code>.json du dépôt
//   GET  /api/espace?console=1            liste des clients (en-tête x-cle = secret CLE_CONSOLE)
//   POST /api/espace {code, decisions}    dépose clients/<dossier>/decisions/<date>.json, appliqué au passage suivant
// Secrets Cloudflare : GITHUB_TOKEN (jeton limité à ce dépôt, Contents lecture et écriture), CLE_CONSOLE.
// Variable : GITHUB_REPO ("compte/depot").
const RE_CODE = /^[a-z0-9]{12}$/;
const RE_ID = /^[0-9a-f]{10}$/;

function json(body, status) {
  return new Response(JSON.stringify(body), { status: status || 200, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" } });
}
function entetes(env, brut) {
  return { authorization: "Bearer " + env.GITHUB_TOKEN, accept: brut ? "application/vnd.github.raw+json" : "application/vnd.github+json", "user-agent": "prospection-email", "x-github-api-version": "2022-11-28", "content-type": "application/json" };
}
async function lire(env, chemin) {
  const r = await fetch("https://api.github.com/repos/" + env.GITHUB_REPO + "/contents/" + chemin, { headers: entetes(env, true) });
  if (!r.ok) return null;
  try { return JSON.parse(await r.text()); } catch (e) { return null; }
}
function base64(texte) {
  const octets = new TextEncoder().encode(texte);
  let s = "";
  for (let i = 0; i < octets.length; i++) s += String.fromCharCode(octets[i]);
  return btoa(s);
}
function couper(v, max) { return String(v === undefined || v === null ? "" : v).slice(0, max); }

// Ne laisse passer que les décisions qu'un client peut prendre depuis sa page.
export function trier(liste) {
  const propres = [];
  for (const d of Array.isArray(liste) ? liste.slice(0, 60) : []) {
    if (!d || typeof d !== "object") continue;
    if (d.action === "pause") propres.push({ action: "pause", motif: couper(d.motif, 120) || "demandée depuis l'espace" });
    else if (d.action === "reprise") propres.push({ action: "reprise" });
    else if ((d.action === "valider" || d.action === "refuser") && RE_ID.test(d.prospect || "")) {
      const x = { action: d.action, prospect: d.prospect };
      if (d.action === "refuser") x.motif = couper(d.motif, 200);
      propres.push(x);
    } else if (d.action === "modifier" && RE_ID.test(d.prospect || "") && [1, 2, 3, 4, 5].includes(d.etape) && couper(d.corps, 2000).trim()) {
      const x = { action: "modifier", prospect: d.prospect, etape: d.etape, corps: couper(d.corps, 2000).trim() };
      if (d.etape === 1 && couper(d.objet, 120).trim()) x.objet = couper(d.objet, 120).trim();
      propres.push(x);
    }
  }
  return propres;
}

export async function onRequestGet({ request, env }) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return json({ erreur: "configuration" }, 500);
  const url = new URL(request.url);
  if (url.searchParams.get("console")) {
    if (!env.CLE_CONSOLE || request.headers.get("x-cle") !== env.CLE_CONSOLE) return json({ erreur: "cle" }, 403);
    return json((await lire(env, "espaces/_index.json")) || {});
  }
  const code = url.searchParams.get("code") || "";
  if (!RE_CODE.test(code)) return json({ erreur: "code" }, 404);
  const d = await lire(env, "espaces/" + code + ".json");
  if (!d) return json({ erreur: "code" }, 404);
  delete d.dossier;
  return json(d);
}

export async function onRequestPost({ request, env }) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return json({ erreur: "configuration" }, 500);
  let b;
  try { b = JSON.parse(couper(await request.text(), 200000)); } catch (e) { return json({ erreur: "format" }, 400); }
  const code = (b && b.code) || "";
  if (!RE_CODE.test(code)) return json({ erreur: "code" }, 404);
  const d = await lire(env, "espaces/" + code + ".json");
  if (!d || !/^[A-Za-z0-9_-]{1,60}$/.test(d.dossier || "")) return json({ erreur: "code" }, 404);
  const decisions = trier(b.decisions);
  if (!decisions.length) return json({ erreur: "vide" }, 400);
  const date = new Date().toISOString();
  const nom = date.replace(/[-:.TZ]/g, "").slice(0, 17) + "-" + Math.random().toString(36).slice(2, 6) + ".json";
  const r = await fetch("https://api.github.com/repos/" + env.GITHUB_REPO + "/contents/clients/" + d.dossier + "/decisions/" + nom, {
    method: "PUT", headers: entetes(env),
    // Le préfixe évite un redéploiement du site à chaque décision.
    body: JSON.stringify({ message: "[CF-Pages-Skip] décision " + d.dossier, content: base64(JSON.stringify({ par: "espace", date, decisions }, null, 1)), branch: env.GITHUB_BRANCH || "main" })
  });
  if (!r.ok) return json({ erreur: "depot" }, 502);
  return json({ ok: true, enregistrees: decisions.length });
}
