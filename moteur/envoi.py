"""Envoi : construction des messages, cadence, coupe-circuit."""
import random
import smtplib
import ssl
import time
from datetime import timedelta
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid

from .socle import domaine, est_oppose, iso, lire_date, maintenant, messages_de, noter


def pied(fiche, prospect, etape):
    """Signature et mentions. Écrites par le code : identiques pour tous, jamais oubliées."""
    e = fiche["expediteur"]
    lignes = [f"{e['prenom']} {e['nom']}"]
    lignes.append(", ".join(x for x in (e["fonction"], e["societe"]) if x))
    if e["telephone"]:
        lignes.append(e["telephone"])
    if etape == 1:
        if e["site"]:
            lignes.append(e["site"])
        if e["mentions"]:
            lignes.append(e["mentions"])
        ou = prospect.get("source_url") or prospect.get("site") or "le site de votre entreprise"
        lignes.append("")
        lignes.append(f"J'ai trouvé votre adresse sur {ou}. Si ce message ne vous concerne pas, "
                      "répondez simplement STOP et je ne vous écrirai plus.")
    else:
        lignes.append("")
        lignes.append("Répondez STOP pour ne plus recevoir de message de ma part.")
    return "\n".join(l for l in lignes if l is not None)


def construire(fiche, prospect, m, premier):
    """Fabrique l'email. `premier` = le message d'étape 1 déjà parti (None pour l'étape 1)."""
    exp, adresse = fiche["expediteur"], fiche["boite"]["adresse"]
    msg = EmailMessage()
    msg["From"] = formataddr((f"{exp['prenom']} {exp['nom']}", adresse))
    msg["To"] = prospect["email"]
    msg["Subject"] = m["objet"] if not premier else "Re: " + premier["objet"]
    msg["Date"] = format_datetime(maintenant())
    msg["Message-ID"] = make_msgid(domain=domaine(adresse))
    msg["List-Unsubscribe"] = f"<mailto:{adresse}?subject=STOP>"
    if premier and premier.get("message_id"):
        msg["In-Reply-To"] = premier["message_id"]
        msg["References"] = premier["message_id"]
    msg.set_content(m["corps"].rstrip() + "\n\n" + pied(fiche, prospect, m["etape"]) + "\n", charset="utf-8")
    return msg


def par_smtp(fiche, mdp):
    """Transport réel. Fonctionne avec Gmail (mot de passe d'application) comme avec tout autre hébergeur."""
    def envoyer(msg):
        b = fiche["boite"]
        hote, port = b["smtp"]["hote"], int(b["smtp"]["port"])
        ctx = ssl.create_default_context()
        if port == 465:
            srv = smtplib.SMTP_SSL(hote, port, context=ctx, timeout=30)
        else:
            srv = smtplib.SMTP(hote, port, timeout=30)
            srv.starttls(context=ctx)
        try:
            srv.login(b.get("identifiant") or b["adresse"], mdp)
            srv.send_message(msg)
        finally:
            srv.quit()
    return envoyer


def plafond_du_jour(fiche, etat, jour):
    c = fiche["cadence"]
    if not etat["demarrage"]:
        return c["depart_par_jour"]
    semaines = max(0, (jour - lire_date(etat["demarrage"]).date()).days // 7)
    return min(c["plafond_par_jour"], c["depart_par_jour"] + semaines * c["pas_par_semaine"])


def _envoyes(etat):
    return [m for m in etat["messages"] if m["statut"] == "envoye"]


def a_envoyer(fiche, etat, now):
    """Liste ordonnée (prospect, message, premier) de ce qui est dû maintenant : relances d'abord."""
    delais = fiche["sequence"]["delais_jours"]
    mois = now.strftime("%Y-%m")
    engages = sum(1 for m in _envoyes(etat) if m["etape"] == 1 and m["envoye_le"][:7] == mois)
    relances, premiers = [], []
    for p in etat["prospects"].values():
        if p["statut"] not in ("pret", "en_sequence") or est_oppose(etat, p["email"]):
            continue
        ms = messages_de(etat, p["id"])
        if not ms:
            continue
        un = ms[0]
        if p["statut"] == "pret":
            if un["statut"] == "valide":
                premiers.append((p, un, None))
            continue
        suivant = next((m for m in ms if m["statut"] == "valide"), None)
        if not suivant or un["statut"] != "envoye":
            continue
        echeance = lire_date(un["envoye_le"]).date() + timedelta(days=delais[suivant["etape"] - 1])
        if now.date() >= echeance:
            relances.append((p, suivant, un))
    premiers.sort(key=lambda t: t[0]["cree"])
    quota = max(0, fiche["cible"]["prospects_par_mois"] - engages)
    return relances + premiers[:quota]


def envoyer(fiche, etat, transport, dormir=time.sleep, force=False):
    """Un passage d'envoi. Renvoie (nombre envoyé, raison si rien n'est parti)."""
    c, now = fiche["cadence"], maintenant()
    if not fiche["actif"]:
        return 0, "client inactif"
    if not fiche.get("envoi", True):
        return 0, "préparation : les envois ne sont pas encore ouverts"
    if etat["pause"]:
        return 0, "en pause : " + etat["motif_pause"]
    heure = now.hour + now.minute / 60
    if not force and (now.weekday() not in c["jours"] or not c["heures"][0] <= heure < c["heures"][1]):
        return 0, "hors des heures d'envoi"
    apres = etat["boite"].get("prochain_envoi_apres")
    if not force and apres and now < lire_date(apres):
        return 0, "écart entre deux envois non écoulé"
    aujourdhui = now.date().isoformat()
    deja = sum(1 for m in _envoyes(etat) if m["envoye_le"][:10] == aujourdhui)
    reste = plafond_du_jour(fiche, etat, now.date()) - deja
    if reste <= 0:
        return 0, "plafond du jour atteint"
    file = a_envoyer(fiche, etat, now)[:min(reste, c["par_passage"])]
    if not file:
        return 0, "rien à envoyer"
    partis = 0
    for i, (p, m, premier) in enumerate(file):
        if i:
            dormir(random.uniform(45, 150))
        msg = construire(fiche, p, m, premier)
        try:
            transport(msg)
        except Exception as e:                      # panne d'envoi : on s'arrête, on ne réessaie pas en boucle
            noter(etat, "erreur", f"envoi vers {p['email']} : {type(e).__name__} {e}")
            if isinstance(e, smtplib.SMTPAuthenticationError):
                etat["pause"], etat["motif_pause"] = True, "la boîte d'envoi refuse la connexion"
            break
        m["statut"], m["envoye_le"], m["message_id"] = "envoye", iso(now), msg["Message-ID"]
        if not etat["demarrage"]:
            etat["demarrage"] = iso(now)
        p["statut"] = "en_sequence"
        partis += 1
        noter(etat, "envoi", f"étape {m['etape']} à {p['email']}")
    if partis:
        a, b = c["ecart_minutes"]
        etat["boite"]["prochain_envoi_apres"] = iso(now + timedelta(minutes=random.uniform(a, b)))
    return partis, ""


def cloturer(fiche, etat):
    """Ferme les séquences allées au bout sans réponse."""
    now, n = maintenant(), 0
    for p in etat["prospects"].values():
        if p["statut"] != "en_sequence":
            continue
        ms = messages_de(etat, p["id"])
        vivants = [m for m in ms if m["statut"] in ("valide", "brouillon")]
        partis = [m for m in ms if m["statut"] == "envoye"]
        if not vivants and partis:
            dernier = max(lire_date(m["envoye_le"]) for m in partis)
            if (now - dernier).days >= fiche["sequence"]["cloture_jours"]:
                p["statut"] = "termine"
                n += 1
    return n


def coupe_circuit(fiche, etat):
    """Met le client en pause si trop d'adresses rebondissent : c'est le signal qui précède un blocage de la boîte."""
    premiers = sorted((m for m in _envoyes(etat) if m["etape"] == 1), key=lambda m: m["envoye_le"])[-50:]
    if len(premiers) < 20 or etat["pause"]:
        return False
    rebonds = sum(1 for m in premiers if etat["prospects"][m["prospect"]]["statut"] == "rebond")
    if rebonds / len(premiers) > fiche["cadence"]["seuil_rebonds"]:
        etat["pause"] = True
        etat["motif_pause"] = f"{rebonds} rebonds sur les {len(premiers)} derniers premiers messages"
        noter(etat, "alerte", "pause automatique : " + etat["motif_pause"])
        return True
    return False
