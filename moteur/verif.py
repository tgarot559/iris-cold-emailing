"""Contrôle des adresses avant tout envoi."""
import re

import requests

RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
WEBMAILS = {
    "gmail.com", "googlemail.com", "yahoo.fr", "yahoo.com", "hotmail.fr", "hotmail.com", "outlook.fr",
    "outlook.com", "live.fr", "live.com", "msn.com", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr",
    "neuf.fr", "laposte.net", "bbox.fr", "icloud.com", "me.com", "aol.com", "gmx.fr", "gmx.com",
    "protonmail.com", "proton.me", "numericable.fr", "club-internet.fr", "aliceadsl.fr", "cegetel.net",
}
GENERIQUES = {"contact", "info", "infos", "bonjour", "hello", "accueil", "commercial", "direction",
              "secretariat", "administration", "admin", "agence", "bureau", "office", "mail", "courrier"}
REFUSEES = {"noreply", "no-reply", "ne-pas-repondre", "nepasrepondre", "donotreply", "abuse", "postmaster",
            "webmaster", "dpo", "rgpd", "privacy", "recrutement", "rh", "jobs", "presse", "press",
            "mailer-daemon", "support", "sav", "comptabilite", "facturation"}
_cache = {}


def syntaxe(email):
    e = (email or "").strip()
    return bool(RE.fullmatch(e)) and len(e) <= 254 and not e.lower().endswith((".png", ".jpg", ".gif", ".webp", ".svg"))


def est_generique(email):
    return email.split("@")[0].lower() in GENERIQUES


def a_un_mx(dom):
    """Le domaine reçoit-il du courrier ? Interroge le DNS par HTTPS (aucune bibliothèque à installer).
    En cas de doute (résolveur injoignable), renvoie None : l'adresse est alors gardée et signalée."""
    if dom in _cache:
        return _cache[dom]
    res = None
    for url in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        try:
            r = requests.get(url, params={"name": dom, "type": "MX"},
                             headers={"accept": "application/dns-json"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                res = any(a.get("type") == 15 for a in data.get("Answer", []))
                break
        except (requests.RequestException, ValueError):
            continue
    _cache[dom] = res
    return res


def controler(email, accepter_webmails=False, mx=a_un_mx):
    """Renvoie (acceptée, motif)."""
    if not syntaxe(email):
        return False, "adresse mal formée"
    local, dom = email.lower().rsplit("@", 1)
    if local in REFUSEES:
        return False, "boîte qui n'est pas faite pour la prospection"
    if dom in WEBMAILS and not accepter_webmails:
        return False, "adresse de messagerie grand public (possible particulier)"
    if mx(dom) is False:
        return False, "le domaine ne reçoit pas de courrier"
    return True, ""
