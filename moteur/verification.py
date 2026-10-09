"""Contrôle de l'installation réelle : clés, boîtes, accès au web. N'envoie rien, ne montre aucune clé."""
import imaplib
import smtplib
import ssl
import requests
import os

from . import sgai, sourcing, verif, oidc
from .ia import ErreurIA, fabriquer
from .socle import DEFAUTS, RACINE, charger_fiche, iso, lister_clients, secrets


def _essai(fonction):
    try:
        return fonction()
    except Exception as e:                      # le rapport doit toujours sortir
        return f"ÉCHEC : {type(e).__name__} {str(e)[:220]}"


def _claude(sec, modele):
    if not sec["anthropic"]:
        return "clé absente"
    try:
        r = fabriquer(sec["anthropic"], sec["anthropic_espace"])("Réponds par le seul mot : ok", "Test", modele, 10)
        return "OK (réponse : " + r.strip()[:20] + ")"
    except ErreurIA as e:
        return "ÉCHEC : " + str(e)[:260]



def _proxy_linkup_status():
    h=oidc.headers()
    if not h:
        return "jeton OIDC GitHub indisponible"
    r=requests.get("https://new-app-i5ds.onrender.com/api/coldmail/engine/status",headers=h,timeout=25)
    try:d=r.json()
    except Exception:d={}
    if r.status_code==200 and d.get("ok"):
        return "OK (clé LinkupAPI présente sur Render)" if d.get("linkup_configured") else "ÉCHEC : clé LinkupAPI absente sur Render"
    return "ÉCHEC : "+str(d.get("detail") or r.status_code)

def _linkup(fiche, cle):
    lu=fiche.get("linkup") or {}
    aid=lu.get("account_id") or ""
    if not cle:
        return "clé LinkupAPI absente"
    if not aid:
        return "boîte non connectée"
    try:
        r=requests.get(f"https://api.linkupapi.com/v2/accounts/{aid}",
                       headers={"x-api-key":cle},timeout=25)
        d=r.json() if r.content else {}
        if r.status_code==200 and d.get("success"):
            data=d.get("data") or {}
            return f"OK ({data.get('status','inconnu')}, {data.get('platform','email')})"
        return "REFUSÉ ("+str((d.get("error") or {}).get("message") or r.status_code)+")"
    except Exception as e:
        return f"ÉCHEC ({type(e).__name__} {str(e)[:120]})"

def _boite(fiche, mdp):
    b = fiche["boite"]
    if not b["adresse"]:
        return "pas d'adresse d'envoi dans la fiche"
    if not mdp:
        return "mot de passe absent des secrets"
    ident, res = b.get("identifiant") or b["adresse"], []
    try:
        port = int(b["smtp"]["port"])
        s = smtplib.SMTP_SSL(b["smtp"]["hote"], port, timeout=25) if port == 465 else smtplib.SMTP(b["smtp"]["hote"], port, timeout=25)
        if port != 465:
            s.starttls(context=ssl.create_default_context())
        s.login(ident, mdp)
        s.quit()
        res.append("envoi OK")
    except Exception as e:
        res.append(f"envoi REFUSÉ ({type(e).__name__} {str(e)[:120]})")
    try:
        i = imaplib.IMAP4_SSL(b["imap"]["hote"], int(b["imap"]["port"]))
        i.login(ident, mdp)
        i.logout()
        res.append("relève OK")
    except Exception as e:
        res.append(f"relève REFUSÉE ({type(e).__name__} {str(e)[:120]})")
    return ", ".join(res)


def rapport():
    sec = secrets("")
    l = [f"# Vérification du {iso()[:16].replace('T', ' à ')}", "",
         "Aucun message n'a été envoyé. Aucune clé n'apparaît dans ce fichier.", "", "## Clés", ""]
    openai_present=bool((os.environ.get("OPENAI_API_KEY") or "").strip())
    l.append(f"- Clé OpenAI : {'présente' if openai_present else 'ABSENTE'}")
    if openai_present:
        try:
            result=fabriquer(sec["anthropic"],sec["anthropic_espace"])("Réponds uniquement ok", "Test de connexion sans email", "gpt-4.1-mini", 12)
            l.append("- Test de génération OpenAI : "+("OK" if result.strip().lower().startswith("ok") else "réponse obtenue, à vérifier"))
        except ErreurIA as e:
            l.append("- Test de génération OpenAI : ÉCHEC : "+str(e)[:220])
    l.append(f"- Clé Claude : {'présente' if sec['anthropic'] else 'ABSENTE'}")
    if not openai_present:
        for role in ("extraction", "redaction"):
            l.append(f"  - modèle de {role} ({DEFAUTS['ia'][role]}) : {_essai(lambda r=role: _claude(sec, DEFAUTS['ia'][r]))}")
    l.append(f"- Clé ScrapeGraphAI : {'présente' if sec['scrapegraph'] else 'absente'}")
    l.append(f"- Accès LinkupAPI via IRIS/OIDC : {_essai(_proxy_linkup_status)}")
    if sec["scrapegraph"]:
        s = _essai(lambda: sgai.Compte(sec["scrapegraph"], "verification").solde())
        l.append(f"  - compte : {'plan ' + str(s.get('plan')) + ', ' + str(s.get('remaining')) + ' crédits restants' if isinstance(s, dict) else (s or 'ÉCHEC : pas de réponse')}")
    l += ["", "## Accès au web", ""]

    def registre():
        r = sourcing.http.get(sourcing.REGISTRE, params={"activite_principale": "49.41A", "per_page": 1}, timeout=20)
        return f"OK ({r.json().get('total_results')} entreprises pour un code d'activité)" if r.status_code == 200 else f"ÉCHEC : {r.status_code}"

    def page():
        h = sourcing.recuperer("https://verifamende.fr/flottes/")
        if not h:
            return "ÉCHEC : page illisible"
        t, liens, adr = sourcing.lire_page(h, "https://verifamende.fr/flottes/")
        return f"OK ({len(t)} caractères, {len(liens)} liens, adresses : {', '.join(sorted(adr)) or 'aucune'})"

    l.append(f"- Registre public des entreprises : {_essai(registre)}")
    l.append(f"- Lecture d'une page (verifamende.fr/flottes) : {_essai(page)}")
    l.append(f"- Contrôle d'un domaine email (verifamende.fr) : {_essai(lambda: {True: 'OK, reçoit du courrier', False: 'ne reçoit pas de courrier', None: 'ÉCHEC : résolveur injoignable'}[verif.a_un_mx('verifamende.fr')])}")
    l += ["", "## Boîtes d'envoi LinkupAPI", ""]
    for c in lister_clients():
        if c == "exemple":
            continue
        f = charger_fiche(c)
        etat = "actif" if f["actif"] else "inactif"
        lu=f.get("linkup") or {}
        l.append(f"- {f['nom'] or c} ({etat}{'' if f['envoi'] else ', préparation'}) : "
                 + (f"boîte {lu.get('status','non connectée')} ({lu.get('provider') or 'fournisseur inconnu'})"
                    if lu.get("account_id") else "boîte non connectée"))
    texte = "\n".join(l) + "\n"
    (RACINE / "verification.md").write_text(texte, encoding="utf-8")
    return texte
