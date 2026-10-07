"""Socle : horloge, fiche client, secrets, état sur disque."""
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(os.environ.get("COLDMAIL_RACINE", Path(__file__).resolve().parent.parent))
PARIS = ZoneInfo("Europe/Paris")

DEFAUTS = {
    "nom": "",
    "code": "",                    # code secret de la page de suivi (12 caractères), créé par "nouveau"
    "mode": "validation",          # "validation" : rien ne part sans accord / "autonome"
    "actif": True,
    "envoi": True,                 # False : on cherche, on rédige, on fait valider, mais rien ne part (boîte pas encore prête)
    "expediteur": {                # la personne qui signe, toujours réelle
        "prenom": "", "nom": "", "fonction": "", "societe": "",
        "site": "", "telephone": "", "mentions": "",
    },
    "boite": {
        "adresse": "",
        "smtp": {"hote": "smtp.gmail.com", "port": 587},
        "imap": {"hote": "imap.gmail.com", "port": 993},
    },
    "cible": {
        "description": "",          # l'ICP en clair
        "fonctions": [],            # ex. ["gérant", "responsable de flotte"]
        "sources": [],              # pages d'annuaire ou de listes à explorer
        "sites": [],                # sites d'entreprises déjà connus
        "recherches": [],           # requêtes web, ex. "transporteur routier La Rochelle" (20 crédits ScrapeGraphAI l'une)
        "registre": {},             # registre public : {"naf": ["49.41A"], "departements": ["17"], "effectifs": ["11", "12"]}
        "accepter_generiques": True,   # contact@, info@...
        "accepter_webmails": False,    # gmail.com, orange.fr... (souvent des particuliers)
        "max_par_entreprise": 1,
        "prospects_par_mois": 100,
    },
    "offre": {
        "proposition": "",          # ce que le client apporte, en une ou deux phrases
        "preuves": [],              # faits vérifiables uniquement ; rien d'autre ne sera affirmé
        "appel": "un échange de dix minutes au téléphone",
        "ton": "simple, direct, respectueux, vouvoiement",
        "interdits": [],
    },
    "sequence": {"delais_jours": [0, 3, 7], "cloture_jours": 7},
    "cadence": {
        "depart_par_jour": 5,       # premier jour d'envoi
        "pas_par_semaine": 5,       # montée progressive
        "plafond_par_jour": 30,
        "par_passage": 2,
        "ecart_minutes": [9, 26],
        "heures": [8.5, 17.5],      # fenêtre d'envoi, heure de Paris
        "jours": [0, 1, 2, 3, 4],   # lundi à vendredi
        "seuil_rebonds": 0.05,
    },
    "ia": {
        "extraction": "claude-haiku-4-5-20251001",
        "redaction": "claude-sonnet-5-5",
        "scrapegraph": False,       # True : passer par la bibliothèque ScrapeGraphAI si elle est installée
        "scrapegraph_api": True,    # se servir de l'API ScrapeGraphAI si une clé figure dans les secrets
    },
}

ETAT_VIDE = {
    "version": 1, "demarrage": None, "pause": False, "motif_pause": "",
    "entreprises": {}, "prospects": {}, "messages": [], "opposition": {},
    "journal": [], "boite": {"dernier_uid": None, "prochain_envoi_apres": None},
}


def maintenant():
    """Heure de Paris. COLDMAIL_MAINTENANT permet de rejouer une date dans les essais."""
    force = os.environ.get("COLDMAIL_MAINTENANT")
    if force:
        d = datetime.fromisoformat(force)
        return d if d.tzinfo else d.replace(tzinfo=PARIS)
    return datetime.now(PARIS)


def iso(d=None):
    return (d or maintenant()).isoformat(timespec="seconds")


def lire_date(texte):
    d = datetime.fromisoformat(texte)
    return d if d.tzinfo else d.replace(tzinfo=PARIS)


def _fusion(base, ajout):
    res = copy.deepcopy(base)
    for cle, val in (ajout or {}).items():
        if isinstance(val, dict) and isinstance(res.get(cle), dict):
            res[cle] = _fusion(res[cle], val)
        else:
            res[cle] = val
    return res


def dossier(client):
    return RACINE / "clients" / client


def lister_clients():
    base = RACINE / "clients"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "client.json").exists())


def charger_fiche(client):
    brut = json.loads((dossier(client) / "client.json").read_text(encoding="utf-8"))
    fiche = _fusion(DEFAUTS, brut)
    fiche["_id"] = client
    return fiche


def controler_fiche(fiche):
    """Renvoie la liste de ce qui manque pour pouvoir envoyer. Vide = prêt."""
    manques = []
    e, b, o = fiche["expediteur"], fiche["boite"], fiche["offre"]
    if not (e["prenom"] and e["nom"]):
        manques.append("expediteur.prenom et expediteur.nom : la personne réelle qui signe")
    if not e["societe"]:
        manques.append("expediteur.societe")
    if fiche.get("envoi", True) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", b["adresse"] or ""):
        manques.append("boite.adresse : l'adresse d'envoi")
    if not o["proposition"]:
        manques.append("offre.proposition")
    if not fiche["cible"]["description"]:
        manques.append("cible.description")
    return manques


def _nom_secret_client(client):
    """Nom stable du secret GitHub du client, ex. verifamende-flottes -> COLDMAIL_PASSWORD_VERIFAMENDE_FLOTTES."""
    propre = re.sub(r"[^A-Za-z0-9]+", "_", client or "").strip("_").upper()
    return "COLDMAIL_PASSWORD_" + propre if propre else ""


def secrets(client):
    """Secrets : jamais dans les fichiers du dépôt.
    - ANTHROPIC_API_KEY et SGAI_API_KEY sont communs.
    - Chaque client peut avoir son propre secret COLDMAIL_PASSWORD_<CLIENT>.
    - L'ancien JSON COLDMAIL_SECRETS et COLDMAIL_CLIENT_PASSWORD restent compatibles."""
    brut = os.environ.get("COLDMAIL_SECRETS")
    chemin = RACINE / "secrets.json"
    data = {}
    mot_de_passe_legacy = ""
    if brut:
        try:
            data = json.loads(brut)
        except json.JSONDecodeError:
            mot_de_passe_legacy = brut
    elif chemin.exists():
        data = json.loads(chemin.read_text(encoding="utf-8"))
    mdp_json = (data.get("clients", {}).get(client, {}) or {}).get("mdp", "")
    nom_env = _nom_secret_client(client)
    mdp_client = os.environ.get(nom_env, "") if nom_env else ""
    mdp_compat = os.environ.get("COLDMAIL_CLIENT_PASSWORD", "")
    return {
        "anthropic": data.get("anthropic") or os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic_espace": data.get("anthropic_espace", ""),
        "mdp": mdp_client or mdp_json or mdp_compat or mot_de_passe_legacy,
        "scrapegraph": data.get("scrapegraph") or os.environ.get("SGAI_API_KEY", ""),
        "scrapegraph_client": (data.get("clients", {}).get(client, {}) or {}).get("scrapegraph", ""),
        "secret_boite": nom_env,
    }


def charger_etat(client):
    chemin = dossier(client) / "etat.json"
    if not chemin.exists():
        return copy.deepcopy(ETAT_VIDE)
    return _fusion(ETAT_VIDE, json.loads(chemin.read_text(encoding="utf-8")))


def enregistrer_etat(client, etat):
    """Écriture atomique : le fichier n'est jamais à moitié écrit."""
    etat["journal"] = etat["journal"][-800:]
    cible = dossier(client) / "etat.json"
    fd, tmp = tempfile.mkstemp(dir=cible.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cible)


def noter(etat, genre, detail):
    etat["journal"].append({"date": iso(), "type": genre, "detail": detail})


def identifiant(email):
    return hashlib.sha1(email.strip().lower().encode()).hexdigest()[:10]


def domaine(email_ou_url):
    t = email_ou_url.strip().lower()
    if "@" in t and "://" not in t:
        return t.rsplit("@", 1)[1]
    t = re.sub(r"^[a-z]+://", "", t).split("/")[0].split(":")[0]
    return t[4:] if t.startswith("www.") else t


def est_oppose(etat, email):
    e = email.strip().lower()
    opp = etat["opposition"]
    return e in opp or ("@" + domaine(e)) in opp


def opposer(etat, email, motif):
    """Inscrit une adresse (ou un domaine entier : "@exemple.fr") en liste d'opposition
    et arrête tout ce qui était prévu pour elle. Irréversible par le moteur."""
    e = email.strip().lower()
    etat["opposition"].setdefault(e, {"date": iso(), "motif": motif})
    for p in etat["prospects"].values():
        if p["email"] == e or (e.startswith("@") and p["email"].endswith(e)):
            if p["statut"] not in ("rebond",):
                p["statut"] = "rebond" if motif == "rebond" else "stop"
            annuler_messages(etat, p["id"])
    noter(etat, "opposition", f"{e} ({motif})")


def annuler_messages(etat, pid):
    for m in etat["messages"]:
        if m["prospect"] == pid and m["statut"] in ("brouillon", "valide"):
            m["statut"] = "annule"


def messages_de(etat, pid):
    return sorted((m for m in etat["messages"] if m["prospect"] == pid), key=lambda m: m["etape"])


def effacer(etat, email):
    """Supprime toutes les données d'une personne ; seule son adresse reste, en liste d'opposition."""
    e = email.strip().lower()
    opposer(etat, e, "effacement demandé")
    pid = identifiant(e)
    etat["prospects"].pop(pid, None)
    etat["messages"] = [m for m in etat["messages"] if m["prospect"] != pid]
    etat["journal"] = [j for j in etat["journal"] if e not in j["detail"]]
    etat["opposition"][e] = {"date": iso(), "motif": "effacement demandé"}
