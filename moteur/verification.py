"""Contrôle de l'installation réelle : clés, boîtes, accès au web. N'envoie rien, ne montre aucune clé."""
import imaplib
import smtplib
import ssl

from . import sgai, sourcing, verif
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
    l.append(f"- Clé Claude : {'présente' if sec['anthropic'] else 'ABSENTE'}")
    for role in ("extraction", "redaction"):
        l.append(f"  - modèle de {role} ({DEFAUTS['ia'][role]}) : {_essai(lambda r=role: _claude(sec, DEFAUTS['ia'][r]))}")
    l.append(f"- Clé ScrapeGraphAI : {'présente' if sec['scrapegraph'] else 'absente'}")
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
    l += ["", "## Boîtes d'envoi", ""]
    for c in lister_clients():
        if c == "exemple":
            continue
        f = charger_fiche(c)
        etat = "actif" if f["actif"] else "inactif"
        l.append(f"- {f['nom'] or c} ({etat}{'' if f['envoi'] else ', préparation'}) : {_essai(lambda: _boite(f, secrets(c)['mdp']))}")
    texte = "\n".join(l) + "\n"
    (RACINE / "verification.md").write_text(texte, encoding="utf-8")
    return texte
