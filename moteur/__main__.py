"""Ligne de commande.   python -m moteur <commande> ...

  nouveau <client>              crée le dossier et une fiche à remplir
  passage <client>|--tous       un tour complet : décisions, relève, recherche, rédaction, envoi, page de suivi
          [--a-blanc]           ... sans rien envoyer ni relever : les messages sont écrits dans sorties/
          [--sans-recherche]    ... sans aller chercher de nouveaux prospects
  etat <client>                 où en est le client
  importer <client> <csv>       charge une liste de prospects
  decider <client> '<json>'     applique une décision tout de suite
  verifier                      contrôle les clés, les boîtes et l'accès au web, sans rien envoyer ; écrit verification.md
  site                          réécrit site/espace.html (après une modification du gabarit)
  diagnostic <url> [...]        lit des pages réelles et contrôle les adresses trouvées, sans rien envoyer
  tester-boite <client>         vérifie la connexion à la boîte, sans rien envoyer
  (un CSV déposé dans clients/<client>/imports/ est chargé au passage suivant)
  effacer <client> <email>      supprime les données d'une personne et bloque toute reprise de contact
"""
import json
import sys
import os
import requests
from collections import Counter

from . import envoi, espace, redaction, reponses, sgai, sourcing
from .ia import fabriquer
from .socle import (effacer, charger_etat, charger_fiche, controler_fiche, dossier, enregistrer_etat, identifiant,
                    iso, lister_clients, maintenant, noter, opposer, secrets)
from .ia import en_json, ErreurIA

SYS_OPTIMISATION_CIBLE = """Tu es un expert de prospection B2B. À partir de la cible, de l'offre et des preuves fournies,
propose une version plus précise et exploitable de l'ICP sans inventer de faits.
Réponds uniquement en JSON :
{"description":"...", "fonctions":["..."], "secteurs":["..."], "signaux":["..."],
 "priorites":["..."], "a_eviter":["..."], "raison":"..."}"""


def _decisions_distantes(fiche):
    code=fiche.get("code") or ""
    if len(code)!=12:return [],[]
    base=os.environ.get("COLDMAIL_ONBOARDING_API","https://new-app-i5ds.onrender.com").rstrip("/")
    try:
        r=requests.get(f"{base}/api/coldmail/client/{code}/decisions",timeout=15)
        if not r.ok:return [],[]
        items=r.json().get("items") or []
        ids=[]; out=[]
        for item in items:
            ids.append(item.get("id"))
            out.extend(item.get("decisions") or [])
        return out,[x for x in ids if x is not None]
    except Exception:
        return [],[]

def _accuser_decisions(fiche,ids):
    if not ids:return
    code=fiche.get("code") or ""
    base=os.environ.get("COLDMAIL_ONBOARDING_API","https://new-app-i5ds.onrender.com").rstrip("/")
    try: requests.post(f"{base}/api/coldmail/client/{code}/decisions/ack",json={"ids":ids},timeout=15)
    except Exception: pass

def _decisions_en_attente(client):
    d = dossier(client) / "decisions"
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.json"))


def passage(client, a_blanc=False, recherche=True, ia=None, transport=None, releve=None, dormir=None):
    """Un tour complet pour un client. Les paramètres ia/transport/releve servent aux essais."""
    fiche, etat, sec = charger_fiche(client), charger_etat(client), secrets(client)
    bilan = {"client": client}
    ia = ia or fabriquer(sec["anthropic"], sec["anthropic_espace"])

    distantes, ids_distants = _decisions_distantes(fiche)
    force_recherche, limite_force, demande_optimisation = False, 10, False
    if distantes:
        ordinaires=[]
        for d in distantes:
            if d.get("action")=="trouver_prospects":
                force_recherche=True
                limite_force=max(1,min(20,int(d.get("quantite") or 10)))
                bilan.setdefault("decisions", []).append(f"recherche forcée de {limite_force} prospects")
            elif d.get("action")=="ameliorer_cible":
                demande_optimisation=True
                bilan.setdefault("decisions", []).append("optimisation de cible demandée")
            else:
                ordinaires.append(d)
        try:
            if ordinaires:
                bilan.setdefault("decisions", []).extend(redaction.appliquer_decisions(fiche, etat, ordinaires))
            _accuser_decisions(fiche, ids_distants)
        except (ValueError, KeyError, TypeError) as e:
            noter(etat, "erreur", f"décision distante illisible : {e}")

    if demande_optimisation:
        try:
            c=f"""CIBLE ACTUELLE : {fiche['cible']['description']}
FONCTIONS : {', '.join(fiche['cible']['fonctions'])}
OFFRE : {fiche['offre']['proposition']}
PREUVES : {' | '.join(fiche['offre']['preuves']) or 'aucune'}"""
            reco=en_json(ia(SYS_OPTIMISATION_CIBLE,c,fiche["ia"]["redaction"],1400))
            etat["optimisation_cible"]={**reco,"date":iso()}
            noter(etat,"optimisation","proposition d'amélioration de la cible générée")
        except ErreurIA as e:
            noter(etat,"erreur",f"optimisation cible : {e}")

    for f in _decisions_en_attente(client):
        try:
            contenu = json.loads(f.read_text(encoding="utf-8"))
            liste = contenu.get("decisions", contenu) if isinstance(contenu, dict) else contenu
            bilan.setdefault("decisions", []).extend(redaction.appliquer_decisions(fiche, etat, liste))
        except (ValueError, KeyError, TypeError) as e:
            noter(etat, "erreur", f"décision illisible {f.name} : {e}")
        rangement = f.parent / "appliquees"
        rangement.mkdir(exist_ok=True)
        f.replace(rangement / f.name)

    depot = dossier(client) / "imports"
    for f in sorted(depot.glob("*.csv")) if depot.exists() else []:
        try:
            origine = "l'annuaire professionnel Apollo" if "apollo" in f.name.lower() else ""
            bilan["importes"] = bilan.get("importes", 0) + sourcing.importer(fiche, etat, f, origine=origine)[0]
        except Exception as e:
            noter(etat, "erreur", f"import {f.name} : {type(e).__name__} {e}")
        (depot / "faits").mkdir(exist_ok=True)
        f.replace(depot / "faits" / f.name)

    manques = controler_fiche(fiche)
    if manques:
        bilan["bloque"] = manques
        espace.produire(fiche, etat)
        enregistrer_etat(client, etat)
        return bilan

    if etat["demarrage"] and not a_blanc and fiche["envoi"] and (releve or sec["linkup"]):
        try:
            recus = releve(fiche, etat) if releve else reponses.par_linkup(fiche, sec["linkup"], etat)
            bilan["releve"] = reponses.traiter(fiche, etat, recus, ia if sec["anthropic"] or releve else None)
        except Exception as e:
            noter(etat, "erreur", f"relève LinkupAPI : {type(e).__name__} {e}")
    elif releve:
        bilan["releve"] = reponses.traiter(fiche, etat, releve(fiche, etat), ia)

    envoi.cloturer(fiche, etat)
    if envoi.coupe_circuit(fiche, etat):
        bilan["alerte"] = etat["motif_pause"]

    if fiche["actif"] and not etat["pause"]:
        mois = maintenant().strftime("%Y-%m")
        crees = sum(1 for p in etat["prospects"].values() if p["cree"][:7] == mois and p["statut"] != "ecarte")
        stock = sum(1 for p in etat["prospects"].values() if p["statut"] in ("nouveau", "a_valider", "pret"))
        if recherche and ((stock < 15 and crees < fiche["cible"]["prospects_par_mois"]) or force_recherche):
            try:
                sg = sgai.ouvrir(fiche, sec)
                sourcing.registre(fiche, etat)
                sourcing.recherches(fiche, etat, sg)
                sourcing.trouver_sites(fiche, etat, sg)
                sourcing.decouvrir(fiche, etat, ia, sg=sg)
                bilan["trouves"] = sourcing.explorer(fiche, etat, ia, limite=limite_force if force_recherche else 15, sg=sg)
                if sg:
                    bilan["credits_scrapegraph"] = sg.utilises()[0]
            except Exception as e:
                noter(etat, "erreur", f"recherche : {type(e).__name__} {e}")
        bilan["rediges"] = redaction.rediger(fiche, etat, ia)

        if a_blanc:
            sortie = dossier(client) / "sorties"
            sortie.mkdir(exist_ok=True)

            def transport(msg, _d=sortie):
                nom = f"{maintenant():%Y%m%d-%H%M%S}-{msg['To'].replace('@', '_')}.eml"
                (_d / nom).write_bytes(bytes(msg))
        elif not transport:
            if fiche.get("envoi") and (fiche.get("linkup") or {}).get("status") == "connected" and sec["linkup"]:
                transport = envoi.par_linkup(fiche, sec["linkup"])
            else:
                transport = None if fiche["envoi"] else (lambda m: None)
        if transport:
            kw = {"dormir": dormir} if dormir else ({"dormir": lambda s: None} if a_blanc else {})
            bilan["envoyes"], bilan["raison"] = envoi.envoyer(fiche, etat, transport, force=a_blanc, **kw)
        else:
            bilan["envoyes"], bilan["raison"] = 0, "boîte LinkupAPI non connectée ou clé LinkupAPI absente"

    espace.produire(fiche, etat)
    enregistrer_etat(client, etat)
    return bilan


def _afficher_etat(client):
    fiche, etat = charger_fiche(client), charger_etat(client)
    c = Counter(p["statut"] for p in etat["prospects"].values())
    env = [m for m in etat["messages"] if m["statut"] == "envoye"]
    print(f"{fiche['nom'] or client}  |  mode {fiche['mode']}  |  "
          + ("EN PAUSE : " + etat["motif_pause"] if etat["pause"] else "actif" if fiche["actif"] else "inactif"))
    for m in controler_fiche(fiche):
        print("  à compléter :", m)
    print(f"  entreprises repérées : {len(etat['entreprises'])}   prospects : {len(etat['prospects'])}")
    for s in ("nouveau", "a_valider", "pret", "en_sequence", "repondu", "termine", "stop", "rebond", "ecarte"):
        if c[s]:
            print(f"    {s:12} {c[s]}")
    sg = sgai.ouvrir(fiche, secrets(client))
    if sg:
        tout, lui = sg.utilises()
        print(f"  crédits ScrapeGraphAI ce mois : {tout} sur {sg.regles['credits_par_mois']} (dont {lui} pour ce client)")
    print(f"  messages envoyés : {len(env)}   plafond du jour : {envoi.plafond_du_jour(fiche, etat, maintenant().date())}")
    for p in etat["prospects"].values():
        if p["statut"] == "repondu":
            r = p["reponse"]
            print(f"  RÉPONSE {p['email']} [{r['intention']}] {r.get('resume') or r['extrait'][:90]}")
    for j in etat["journal"][-6:]:
        print(f"  {j['date'][5:16]} {j['type']:10} {j['detail'][:110]}")


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "aide"):
        print(__doc__)
        return 0
    cmd, reste = a[0], a[1:]
    options = {x for x in reste if x.startswith("--")}
    args = [x for x in reste if not x.startswith("--")]

    if cmd == "nouveau":
        d = dossier(args[0])
        (d / "decisions").mkdir(parents=True, exist_ok=True)
        if not (d / "client.json").exists():
            modele = (dossier("exemple") / "client.json")
            base = json.loads(modele.read_text(encoding="utf-8")) if modele.exists() else {}
            import secrets as alea
            base.update({"nom": args[0], "actif": False,
                         "code": "".join(alea.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(12))})
            (d / "client.json").write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Dossier prêt : {d}\nRemplissez client.json, puis passez \"actif\" à true.")
    elif cmd == "passage":
        clients = lister_clients() if "--tous" in options else args[:1]
        for c in clients:
            if "--tous" in options and (c == "exemple" or not (charger_fiche(c)["actif"] or _decisions_en_attente(c))):
                continue        # un client inactif et sans décision en attente ne produit aucun enregistrement
            try:
                print(json.dumps(passage(c, "--a-blanc" in options, "--sans-recherche" not in options),
                                 ensure_ascii=False))
            except Exception as e:      # un client en panne ne bloque pas les autres
                print(json.dumps({"client": c, "erreur": f"{type(e).__name__} {e}"}, ensure_ascii=False))
    elif cmd == "verifier":
        from . import verification
        print(verification.rapport())
    elif cmd == "site":
        print("Page écrite :", espace.site())
    elif cmd == "diagnostic":
        from . import verif
        for url in args:
            html = sourcing.recuperer(url)
            if not html:
                print(f"{url} : illisible (absente, interdite par robots.txt ou réseau fermé)")
                continue
            texte, liens, adresses = sourcing.lire_page(html, url)
            print(f"{url} : {len(texte)} caractères, {len(liens)} liens, adresses : {sorted(adresses) or 'aucune'}")
            for adr in sorted(adresses):
                print("   ", adr, "->", verif.controler(adr))
    elif cmd == "etat":
        _afficher_etat(args[0])
    elif cmd == "importer":
        fiche, etat = charger_fiche(args[0]), charger_etat(args[0])
        print("%d prospect(s) chargé(s), %d ligne(s) écartée(s)" % sourcing.importer(fiche, etat, args[1]))
        enregistrer_etat(args[0], etat)
    elif cmd == "decider":
        fiche, etat = charger_fiche(args[0]), charger_etat(args[0])
        d = json.loads(args[1])
        print(redaction.appliquer_decisions(fiche, etat, d if isinstance(d, list) else [d]))
        espace.produire(fiche, etat)
        enregistrer_etat(args[0], etat)
    elif cmd == "tester-boite":
        import imaplib
        import smtplib
        import ssl
        fiche, sec = charger_fiche(args[0]), secrets(args[0])
        b = fiche["boite"]
        ident = b.get("identifiant") or b["adresse"]
        try:
            port = int(b["smtp"]["port"])
            s = smtplib.SMTP_SSL(b["smtp"]["hote"], port, timeout=20) if port == 465 else smtplib.SMTP(b["smtp"]["hote"], port, timeout=20)
            if port != 465:
                s.starttls(context=ssl.create_default_context())
            s.login(ident, sec["mdp"])
            s.quit()
            print("Envoi : connexion acceptée")
        except Exception as e:
            print("Envoi : refusé -", type(e).__name__, e)
        try:
            i = imaplib.IMAP4_SSL(b["imap"]["hote"], int(b["imap"]["port"]))
            i.login(ident, sec["mdp"])
            i.logout()
            print("Relève : connexion acceptée")
        except Exception as e:
            print("Relève : refusée -", type(e).__name__, e)
    elif cmd == "effacer":
        fiche, etat = charger_fiche(args[0]), charger_etat(args[0])
        e = args[1].strip().lower()
        effacer(etat, e)
        espace.produire(fiche, etat)
        enregistrer_etat(args[0], etat)
        print(f"{e} : données supprimées, adresse conservée seule en liste d'opposition.")
    else:
        print("Commande inconnue.\n" + __doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
