"""Page de suivi du client : une photographie de l'état, lisible sans explication."""
import html
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from . import envoi
import re

from .socle import RACINE, dossier, iso, lire_date, maintenant, messages_de

GABARIT = Path(__file__).with_name("gabarit_espace.html")
ENTETE = ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
          '<meta name="robots" content="noindex,nofollow">'
          '<style>body{margin:0}[hidden]{display:none!important}</style></head><body>')


def donnees(fiche, etat):
    now = maintenant()
    jour = now.date().isoformat()
    envoyes = [m for m in etat["messages"] if m["statut"] == "envoye"]
    statuts = Counter(p["statut"] for p in etat["prospects"].values())
    contactes = {m["prospect"] for m in envoyes}
    delais = fiche["sequence"]["delais_jours"]
    contacts, attente, reponses, prevu = [], [], [], Counter()
    for p in etat["prospects"].values():
        ms = messages_de(etat, p["id"])
        partis = [m for m in ms if m["statut"] == "envoye"]
        suivant = next((m for m in ms if m["statut"] == "valide"), None)
        echeance = None
        if p["statut"] == "en_sequence" and suivant and partis:
            d = lire_date(ms[0]["envoye_le"]).date() + timedelta(days=delais[suivant["etape"] - 1])
            while d.weekday() not in fiche["cadence"]["jours"] or d < now.date():
                d += timedelta(days=1)
            echeance = d.isoformat()
            prevu[echeance] += 1
        contacts.append({
            "nom": (p["prenom"] + " " + p["nom"]).strip() or "Adresse générale",
            "fonction": p["fonction"], "entreprise": p["entreprise"], "email": p["email"], "site": p["site"],
            "statut": p["statut"], "etape": len(partis), "sur": len(delais),
            "dernier": max((m["envoye_le"] for m in partis), default=None), "prochain": echeance,
        })
        if p["statut"] == "a_valider":
            attente.append({
                "id": p["id"], "nom": (p["prenom"] + " " + p["nom"]).strip() or p["email"],
                "fonction": p["fonction"], "entreprise": p["entreprise"], "email": p["email"],
                "source": p["source_url"], "accroche": p["citation"], "alertes": p.get("alertes", []),
                "messages": [{"etape": m["etape"], "objet": m["objet"], "corps": m["corps"],
                              "jour": delais[m["etape"] - 1]} for m in ms if m["statut"] == "brouillon"],
            })
        if p.get("reponse") and p["statut"] in ("repondu", "stop"):
            r = p["reponse"]
            reponses.append({"nom": (p["prenom"] + " " + p["nom"]).strip() or p["email"],
                             "entreprise": p["entreprise"], "email": p["email"], "date": r["date"],
                             "intention": r["intention"], "resume": r.get("resume", ""), "extrait": r["extrait"]})
    ordre = {"repondu": 0, "a_valider": 1, "en_sequence": 2, "pret": 3, "nouveau": 4}
    contacts.sort(key=lambda c: (ordre.get(c["statut"], 9), c["entreprise"].lower()))
    reponses.sort(key=lambda r: r["date"], reverse=True)
    e = fiche["expediteur"]
    return {
        "client": fiche["nom"] or fiche["_id"], "signataire": f"{e['prenom']} {e['nom']}".strip(),
        "boite": fiche["boite"]["adresse"], "mode": fiche["mode"], "maj": iso(now),
        "etat": "pause" if etat["pause"] else "arret" if not fiche["actif"] else "marche" if fiche.get("envoi", True) else "preparation",
        "motif": etat["motif_pause"], "demarrage": etat["demarrage"],
        "jour": {"partis": sum(1 for m in envoyes if m["envoye_le"][:10] == jour),
                 "plafond": envoi.plafond_du_jour(fiche, etat, now.date()),
                 "max": fiche["cadence"]["plafond_par_jour"]},
        "parcours": {"trouves": len(etat["prospects"]), "contactes": len(contactes),
                     "messages": len(envoyes), "reponses": statuts["repondu"],
                     "interesses": sum(1 for p in etat["prospects"].values() if p["statut"] == "repondu"
                                       and p.get("reponse", {}).get("intention") in ("interesse", "question")),
                     "arrets": statuts["stop"], "invalides": statuts["rebond"]},
        "prets": statuts["pret"], "attente": attente, "reponses": reponses, "contacts": contacts,
        "prevu": [{"jour": j, "relances": n} for j, n in sorted(prevu.items())[:6]],
        "journal": [j for j in etat["journal"] if j["type"] != "decision"][-12:][::-1],
        "cible": fiche["cible"]["description"], "sequence": delais,
    }


def produire(fiche, etat, exemple=False):
    """Écrit espace/page.html (à publier tel quel) et espace/index.html (à héberger où l'on veut)."""
    d = donnees(fiche, etat)
    d["exemple"] = exemple
    charge = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    page = GABARIT.read_text(encoding="utf-8").replace("/*DONNEES*/null", charge)
    page = page.replace("<title>IRIS Prospection cold emailing</title>", "<title>" + html.escape(d["client"]) + " · IRIS cold emailing</title>")
    _publier(fiche, d)
    sortie = dossier(fiche["_id"]) / "espace"
    sortie.mkdir(exist_ok=True)
    (sortie / "page.html").write_text(page, encoding="utf-8")
    (sortie / "index.html").write_text(ENTETE + page + "</body></html>", encoding="utf-8")
    return sortie / "page.html"


def _publier(fiche, d):
    """Dépose les données de la page dans espaces/<code>.json : c'est ce que lit le site en direct."""
    code = fiche.get("code") or ""
    if not re.fullmatch(r"[a-z0-9]{12}", code):
        return
    base = RACINE / "espaces"
    base.mkdir(exist_ok=True)
    (base / f"{code}.json").write_text(json.dumps({**d, "dossier": fiche["_id"]}, ensure_ascii=False), encoding="utf-8")
    index = base / "_index.json"
    tout = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    tout[code] = {"dossier": fiche["_id"], "client": d["client"], "etat": d["etat"], "motif": d["motif"],
                  "attente": len(d["attente"]), "reponses": d["parcours"]["reponses"],
                  "contactes": d["parcours"]["contactes"], "jour": d["jour"], "maj": d["maj"]}
    index.write_text(json.dumps(tout, ensure_ascii=False, indent=1), encoding="utf-8")


def site():
    """Écrit site/espace.html : la page commune à tous les clients, qui lit ses données en direct."""
    cible = RACINE / "site"
    cible.mkdir(exist_ok=True)
    page = GABARIT.read_text(encoding="utf-8")
    (cible / "espace.html").write_text(ENTETE + page + "</body></html>", encoding="utf-8")
    return cible / "espace.html"
