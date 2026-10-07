"""Rédaction des séquences, puis contrôle avant qu'elles puissent partir."""
import json
import re

from .ia import ErreurIA, en_json
from .socle import iso, messages_de, noter

SYS = """Tu écris de courts emails de premier contact entre professionnels, en français, signés par une personne réelle.
Ils doivent se lire comme écrits à la main par quelqu'un d'occupé et de poli.

Règles :
- Texte brut. Pas de mise en forme, pas de liste, pas d'émoji, pas de lien, pas de pièce jointe.
- Premier message : 50 à 90 mots. Relances : 25 à 60 mots, elles apportent un angle nouveau et ne culpabilisent jamais.
- Une seule demande par message, simple à accepter ou à refuser.
- Tu n'affirmes QUE ce qui figure dans les blocs OFFRE et PREUVES. Aucun chiffre, client, résultat ou délai qui n'y soit pas.
- Sur le destinataire, tu n'utilises QUE le bloc PROSPECT. Si une ACCROCHE est fournie, tu peux t'y référer sobrement ; sinon tu n'inventes aucun détail sur son entreprise.
- Pas de formule creuse ("j'espère que vous allez bien", "je me permets de", "n'hésitez pas"), pas de superlatif, pas de fausse familiarité, pas de "Re:" mensonger, pas d'urgence artificielle.
- Si le prénom est inconnu, commence par "Bonjour," sans rien d'autre.
- N'écris ni signature ni mention de désinscription : elles sont ajoutées ensuite.
- L'objet : 2 à 6 mots, en minuscules sauf la première lettre, sans ponctuation finale. Les relances reprennent le fil du premier message, leur champ "objet" reste vide.

Réponds uniquement en JSON : {"messages": [{"objet": "...", "corps": "..."}, ...]} avec exactement le nombre de messages demandé."""

RE_NOMBRE = re.compile(r"\d[\d\s.,]*\d|\d")
RE_GABARIT = re.compile(r"\{\{|\}\}|\[[A-ZÉ][^\]]{0,30}\]|<[a-zé_ ]{2,30}>|XX+|lorem", re.I)
RE_LIEN = re.compile(r"https?://|www\.", re.I)


def _chiffres(texte):
    return {re.sub(r"[\s.,]", "", n) for n in RE_NOMBRE.findall(texte or "")}


def controler(messages, fiche, prospect):
    """Relit ce que le modèle a écrit. Renvoie la liste des alertes (vide = rien à signaler).
    Une alerte force la validation humaine, même en mode autonome."""
    alertes = []
    permis = _chiffres(json.dumps(fiche["offre"], ensure_ascii=False)) | _chiffres(
        " ".join(str(prospect.get(k, "")) for k in ("accroche", "citation", "entreprise", "activite")))
    for i, m in enumerate(messages, 1):
        corps, objet = m.get("corps", ""), m.get("objet", "")
        mots = len(corps.split())
        if not corps.strip() or (i == 1 and not objet.strip()):
            alertes.append(f"message {i} : vide")
        if mots > (130 if i == 1 else 90):
            alertes.append(f"message {i} : trop long ({mots} mots)")
        if RE_GABARIT.search(corps + " " + objet):
            alertes.append(f"message {i} : champ non rempli")
        if RE_LIEN.search(corps):
            alertes.append(f"message {i} : contient un lien")
        inconnus = _chiffres(corps) - permis
        if inconnus:
            alertes.append(f"message {i} : chiffre absent de la fiche ({', '.join(sorted(inconnus))})")
        for interdit in fiche["offre"]["interdits"]:
            if interdit and interdit.lower() in corps.lower():
                alertes.append(f"message {i} : contient « {interdit} »")
        if prospect.get("prenom") and i == 1 and prospect["prenom"].lower() not in corps.lower()[:60]:
            pass    # ne pas saluer par le prénom est un choix admis
    return alertes


def rediger(fiche, etat, ia, limite=20):
    """Écrit la séquence des prospects nouveaux. Renvoie le nombre de séquences écrites."""
    exp, offre, n = fiche["expediteur"], fiche["offre"], len(fiche["sequence"]["delais_jours"])
    faits = 0
    for p in etat["prospects"].values():
        if p["statut"] != "nouveau" or faits >= limite:
            continue
        message = (
            f"EXPÉDITEUR : {exp['prenom']} {exp['nom']}, {exp['fonction']}, {exp['societe']}\n"
            f"OFFRE : {offre['proposition']}\n"
            f"PREUVES : {' | '.join(offre['preuves']) or 'aucune, ne rien affirmer de chiffré'}\n"
            f"DEMANDE FINALE : {offre['appel']}\nTON : {offre['ton']}\n\n"
            f"PROSPECT : prénom « {p['prenom']} », fonction « {p['fonction']} », entreprise « {p['entreprise']} », "
            f"activité « {p['activite']} »\n"
            f"ACCROCHE : {p['accroche'] or 'aucune'}"
            + (f" (lu sur son site : « {p['citation']} »)" if p["citation"] else "")
            + f"\n\nÉcris {n} messages : le premier contact puis {n - 1} relance(s).")
        try:
            msgs = en_json(ia(SYS, message, fiche["ia"]["redaction"], 1800)).get("messages", [])[:n]
        except ErreurIA as e:
            noter(etat, "erreur", f"rédaction {p['email']} : {e}")
            continue
        if len(msgs) != n:
            noter(etat, "erreur", f"rédaction {p['email']} : {len(msgs)} message(s) au lieu de {n}")
            continue
        alertes = controler(msgs, fiche, p)
        direct = fiche["mode"] == "autonome" and not alertes
        for i, m in enumerate(msgs, 1):
            etat["messages"].append({
                "id": f"{p['id']}-{i}", "prospect": p["id"], "etape": i,
                "objet": (m.get("objet") or "").strip() if i == 1 else "",
                "corps": (m.get("corps") or "").strip(),
                "statut": "valide" if direct else "brouillon", "cree": iso(),
                "envoye_le": None, "message_id": None,
            })
        p["alertes"] = alertes
        p["statut"] = "pret" if direct else "a_valider"
        faits += 1
    if faits:
        noter(etat, "redaction", f"{faits} séquence(s) écrite(s)")
    return faits


def appliquer_decisions(fiche, etat, decisions):
    """Applique les décisions du pilote ou du client.
    Formes acceptées :
      {"action": "valider", "prospect": "<id|email|tous>"}
      {"action": "refuser", "prospect": "<id|email>", "motif": "..."}
      {"action": "modifier", "prospect": "<id|email>", "etape": 1, "objet": "...", "corps": "..."}
      {"action": "effacer", "email": "x@y.fr"}   (supprime ses données, garde le blocage)
      {"action": "opposer", "email": "x@y.fr"}  |  {"action": "pause", "motif": "..."}  |  {"action": "reprise"}
    """
    from .socle import annuler_messages, effacer, opposer
    faits = []
    par_email = {p["email"]: p for p in etat["prospects"].values()}
    for d in decisions:
        act, ref = d.get("action"), (d.get("prospect") or "").strip().lower()
        if act == "pause":
            etat["pause"], etat["motif_pause"] = True, d.get("motif", "demandée")
        elif act == "reprise":
            etat["pause"], etat["motif_pause"] = False, ""
        elif act == "opposer":
            opposer(etat, d["email"], d.get("motif", "demande"))
        elif act == "effacer":
            effacer(etat, d["email"])
        elif act in ("valider", "refuser", "modifier"):
            if ref == "tous" and act == "valider":
                cibles = [p for p in etat["prospects"].values() if p["statut"] == "a_valider"]
            else:
                cibles = [x for x in (etat["prospects"].get(ref), par_email.get(ref)) if x]
            if not cibles and ref != "tous":
                faits.append(f"ignorée : prospect inconnu ({ref})")
                continue
            for p in cibles:
                if act == "valider" and p["statut"] == "a_valider":
                    for m in messages_de(etat, p["id"]):
                        if m["statut"] == "brouillon":
                            m["statut"] = "valide"
                    p["statut"], p["alertes"] = "pret", []
                elif act == "refuser" and p["statut"] in ("a_valider", "pret", "nouveau"):
                    annuler_messages(etat, p["id"])
                    p["statut"], p["motif"] = "ecarte", d.get("motif", "")
                elif act == "modifier":
                    for m in messages_de(etat, p["id"]):
                        if m["etape"] == int(d.get("etape", 1)) and m["statut"] in ("brouillon", "valide"):
                            if "objet" in d and m["etape"] == 1:
                                m["objet"] = d["objet"].strip()
                            if "corps" in d:
                                m["corps"] = d["corps"].strip()
                            reste = controler([{"objet": x["objet"], "corps": x["corps"]}
                                               for x in messages_de(etat, p["id"])], fiche, p)
                            p["alertes"] = [a for a in reste if "chiffre" not in a]  # un humain a relu
        else:
            faits.append(f"ignorée : action inconnue ({act})")
            continue
        faits.append("effacer une adresse" if act == "effacer" else f"{act} {ref or d.get('email', '')}".strip())
    if faits:
        noter(etat, "decision", " ; ".join(faits))
    return faits
