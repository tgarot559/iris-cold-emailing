"""Appels à l'API Claude, sans dépendance autre que requests."""
import json
import re
import time

import requests

URL = "https://api.anthropic.com/v1/messages"


class ErreurIA(Exception):
    pass


def fabriquer(cle, espace=""):
    """Renvoie une fonction ia(systeme, message, modele, max_tokens) -> texte."""
    if not cle:
        def absente(*a, **k):
            raise ErreurIA("Clé API Claude absente (secrets : champ 'anthropic').")
        return absente

    def ia(systeme, message, modele, max_tokens=2000):
        corps = {"model": modele, "max_tokens": max_tokens, "system": systeme,
                 "messages": [{"role": "user", "content": message}]}
        entetes = {"x-api-key": cle, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        if espace:                      # clé non rattachée à un espace de travail : il faut le nommer
            entetes["anthropic-workspace-id"] = espace
        for essai in range(4):
            r = requests.post(URL, headers=entetes, json=corps, timeout=120)
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(4 * (essai + 1))
                continue
            if r.status_code != 200:
                raise ErreurIA(f"API Claude {r.status_code} : {r.text[:300]}")
            blocs = r.json().get("content", [])
            return "".join(b.get("text", "") for b in blocs if b.get("type") == "text")
        raise ErreurIA("API Claude indisponible après plusieurs essais.")
    return ia


def en_json(texte):
    """Extrait le premier objet ou tableau JSON d'une réponse."""
    t = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.M).strip()
    for ouvre, ferme in (("{", "}"), ("[", "]")):
        i, j = t.find(ouvre), t.rfind(ferme)
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ErreurIA("Réponse non exploitable : " + texte[:200])
