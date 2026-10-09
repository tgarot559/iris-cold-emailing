"""Appels à l'API Claude, sans dépendance autre que requests."""
import json
import re
import time

import requests

URL = "https://api.anthropic.com/v1/messages"


class ErreurIA(Exception):
    pass


def fabriquer(cle, espace=""):
    """Renvoie une fonction ia(systeme, message, modele, max_tokens) -> texte.
    OPENAI_API_KEY, if configured, takes priority over the Anthropic provider.
    """
    import os
    openai_key=(os.environ.get("OPENAI_API_KEY") or "").strip()
    if openai_key:
        def ia_openai(systeme, message, modele, max_tokens=2000):
            # The existing model IDs are Claude-specific. Use a dedicated OpenAI model.
            selected=(os.environ.get("OPENAI_COLDMAIL_MODEL") or "gpt-4.1-mini").strip()
            payload={"model":selected,"messages":[
                {"role":"system","content":systeme},
                {"role":"user","content":message}
            ],"max_tokens":max_tokens,"temperature":0.2}
            for essai in range(4):
                try:
                    response=requests.post("https://api.openai.com/v1/chat/completions",
                        headers={"Authorization":"Bearer "+openai_key,"Content-Type":"application/json"},
                        json=payload,timeout=120)
                except requests.RequestException as exc:
                    raise ErreurIA("API OpenAI inaccessible : "+str(exc)[:150]) from exc
                if response.status_code in (429,500,502,503):
                    time.sleep(4*(essai+1))
                    continue
                if response.status_code!=200:
                    raise ErreurIA(f"API OpenAI {response.status_code} : {response.text[:220]}")
                try:
                    result=response.json()
                    return result["choices"][0]["message"]["content"] or ""
                except (KeyError,IndexError,TypeError,ValueError) as exc:
                    raise ErreurIA("Réponse OpenAI invalide.") from exc
            raise ErreurIA("API OpenAI indisponible après plusieurs essais.")
        return ia_openai
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
