"""API ScrapeGraphAI, tenue dans la limite du compte gratuit.

Le compte gratuit donne 500 crédits par mois et 10 appels par minute. On ne s'en sert que là où le moteur
ne peut pas faire seul, et jamais sans avoir vérifié qu'il reste de quoi payer l'appel :
  - lire une page    1 crédit   (seulement quand la lecture directe échoue : page faite en JavaScript)
  - chercher         2 crédits par résultat (trouver le site d'une entreprise, ou des entreprises sur une requête)
L'extraction, elle, reste confiée à la clé Claude : l'« extract » de ScrapeGraphAI coûte 5 crédits la page.

Le compteur est tenu dans credits.json, à la racine, commun à tous les clients qui partagent la clé.
"""
import json
import time

import requests

from .socle import RACINE, maintenant

BASE = "https://v2-api.scrapegraphai.com/api"
COUT_PAGE, COUT_RESULTAT = 1, 2
REGLAGES = {"credits_par_mois": 480, "credits_par_client": 160}   # marge de 20 sous les 500 du compte gratuit
http = requests           # remplaçable dans les essais
dormir = time.sleep


def reglages():
    f = RACINE / "reglages.json"
    perso = json.loads(f.read_text(encoding="utf-8")).get("scrapegraph", {}) if f.exists() else {}
    return {**REGLAGES, **perso}


class Compte:
    def __init__(self, cle, client, propre=False):
        self.cle, self.client = cle, client
        self.porteur = client if propre else "commun"      # une clé propre au client a son propre compteur
        self.regles = reglages()
        self.fichier = RACINE / "credits.json"
        self._dernier = 0.0

    # ------------------------------------------------------------ compteur
    def _lire(self):
        tout = json.loads(self.fichier.read_text(encoding="utf-8")) if self.fichier.exists() else {}
        mois = maintenant().strftime("%Y-%m")
        c = tout.get(self.porteur) or {}
        if c.get("mois") != mois:
            c = {"mois": mois, "utilises": 0, "par_client": {}, "epuise": False}
        tout[self.porteur] = c
        return tout, c

    def utilises(self):
        _, c = self._lire()
        return c["utilises"], c["par_client"].get(self.client, 0)

    def disponible(self, cout):
        _, c = self._lire()
        if c.get("epuise"):
            return False
        plafond_client = self.regles["credits_par_mois"] if self.porteur != "commun" else self.regles["credits_par_client"]
        return (c["utilises"] + cout <= self.regles["credits_par_mois"]
                and c["par_client"].get(self.client, 0) + cout <= plafond_client)

    def _debiter(self, cout, epuise=False):
        tout, c = self._lire()
        c["utilises"] += cout
        c["par_client"][self.client] = c["par_client"].get(self.client, 0) + cout
        c["epuise"] = c.get("epuise") or epuise
        self.fichier.write_text(json.dumps(tout, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ appels
    def _appel(self, chemin, corps, cout_max):
        """Renvoie la réponse JSON, ou None. Ne lance jamais d'appel qui pourrait dépasser le budget."""
        if not self.disponible(cout_max):
            return None
        attente = 6.5 - (time.time() - self._dernier)      # 10 appels par minute au plus
        if attente > 0:
            dormir(attente)
        self._dernier = time.time()
        try:
            r = http.post(BASE + chemin, headers={"SGAI-APIKEY": self.cle, "Content-Type": "application/json"},
                          json=corps, timeout=90)
        except Exception:
            return None                                     # un appel en erreur n'est pas facturé
        if r.status_code in (402, 429):                     # crédits épuisés ou débit dépassé côté ScrapeGraphAI
            self._debiter(0, epuise=r.status_code == 402)
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def lire(self, url):
        """Une page rendue (JavaScript compris), en markdown. 1 crédit."""
        d = self._appel("/scrape", {"url": url, "formats": [{"type": "markdown"}], "fetchConfig": {"mode": "js"}}, COUT_PAGE)
        if d is None:
            return None
        self._debiter(COUT_PAGE)
        data = (((d.get("results") or {}).get("markdown") or {}).get("data")) or []
        texte = "\n".join(data) if isinstance(data, list) else str(data)
        return texte or None

    def chercher(self, requete, n=3):
        """Recherche web. 2 crédits par résultat rendu. Renvoie [{url, title, content}]."""
        d = self._appel("/search", {"query": requete, "numResults": n, "locationGeoCode": "fr",
                                    "allowedTypes": ["text/html"]}, COUT_RESULTAT * n)
        if d is None:
            return None
        res = [x for x in (d.get("results") or []) if isinstance(x, dict) and x.get("url")]
        self._debiter(COUT_RESULTAT * max(len(res), 1))
        return res

    def solde(self):
        """Ce que ScrapeGraphAI dit lui-même du compte (appel gratuit)."""
        try:
            r = http.get(BASE + "/credits", headers={"SGAI-APIKEY": self.cle}, timeout=30)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None


def ouvrir(fiche, secrets_client):
    """Renvoie un Compte si le client y a droit et qu'une clé existe, sinon None : le moteur fait alors sans."""
    if not fiche["ia"].get("scrapegraph_api", True):
        return None
    propre = secrets_client.get("scrapegraph_client")
    cle = propre or secrets_client.get("scrapegraph")
    return Compte(cle, fiche["_id"], bool(propre)) if cle else None
