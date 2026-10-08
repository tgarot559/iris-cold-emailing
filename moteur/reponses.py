"""Relève de la boîte : réponses, demandes d'arrêt, rebonds."""
import email
import imaplib
import re
import requests
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr

from .ia import ErreurIA, en_json
from .socle import annuler_messages, iso, lire_date, noter, opposer

RE_STOP = re.compile(
    r"\bstop\b|d[ée]sinscri|d[ée]sabonn|unsubscribe|ne (?:plus|pas) (?:me |nous |m'|)(?:recevoir|contacter|[ée]crire|solliciter|relancer|d[ée]marcher)"
    r"|retire[zr]?[- ]?(?:moi|nous)|supprime[zr]? .{0,40}(?:liste|coordonn|adresse|fichier)|cesse[zr] ", re.I)
RE_ABSENCE = re.compile(r"absen|out of office|automatique|auto-?reply|cong[ée]s|de retour le", re.I)
RE_CITE = re.compile(r"^(?:>|Le .{5,80} a [ée]crit|On .{5,80} wrote|-{3,} ?Message|De ?:|From:|Envoy[ée] ?:)", re.I)
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

SYS = """Tu classes la réponse d'un professionnel à un email de prospection. Tu ne rédiges aucune réponse.
Catégories : "interesse" (veut échanger, demande un créneau ou un numéro), "question" (demande une précision),
"plus_tard" (pas maintenant, recontacter), "pas_interesse", "mauvais_contact" (renvoie vers quelqu'un d'autre), "autre".
Réponds uniquement en JSON : {"intention": "...", "resume": "une phrase factuelle"}"""



def par_linkup(fiche, api_key, etat):
    """Relève les nouveaux messages via LinkupAPI et les convertit au format EmailMessage attendu par traiter()."""
    account_id=(fiche.get("linkup") or {}).get("account_id") or ""
    if not account_id or not api_key:
        return []
    payload={"account_id":account_id,"action":"list_inbox","params":{"count":50}}
    r=requests.post("https://api.linkupapi.com/v2/messages",
                    headers={"x-api-key":api_key,"Content-Type":"application/json"},
                    json=payload,timeout=45)
    try:d=r.json()
    except Exception:d={}
    if r.status_code>=400 or not d.get("success"):
        raise RuntimeError(((d.get("error") or {}).get("message") or f"HTTP {r.status_code}"))
    convs=((d.get("data") or {}).get("conversations") or [])
    vus=set(etat.setdefault("boite",{}).get("linkup_vus") or [])
    par_fil={m.get("message_id"):m.get("prospect") for m in etat.get("messages",[]) if m.get("message_id")}
    recus=[]
    nouveaux=[]
    for x in convs:
        lm=x.get("last_message") or {}
        sender=lm.get("sender") or {}
        mid=str(x.get("message_id") or x.get("id") or "")
        if not mid or mid in vus or sender.get("is_me"):
            continue
        em=EmailMessage()
        de=(sender.get("email") or (x.get("participant") or {}).get("email") or "").strip()
        em["From"]=de
        em["Subject"]=str(lm.get("subject") or "")
        if x.get("message_id"): em["Message-ID"]=str(x.get("message_id"))
        if x.get("in_reply_to"): em["In-Reply-To"]=str(x.get("in_reply_to"))
        em.set_content(str(lm.get("text") or ""))
        if x.get("is_bounce"):
            ref=str(x.get("in_reply_to") or "")
            pid=par_fil.get(ref)
            if pid and pid in etat.get("prospects",{}):
                em["X-Failed-Recipients"]=etat["prospects"][pid]["email"]
            else:
                em["X-Failed-Recipients"]=de
        recus.append(em)
        nouveaux.append(mid)
    if nouveaux:
        etat["boite"]["linkup_vus"]=(list(vus)+nouveaux)[-500:]
    return recus

def par_imap(fiche, mdp, etat):
    """Lit les messages arrivés depuis la dernière relève, sans les marquer comme lus."""
    b = fiche["boite"]
    srv = imaplib.IMAP4_SSL(b["imap"]["hote"], int(b["imap"]["port"]))
    try:
        srv.login(b.get("identifiant") or b["adresse"], mdp)
        srv.select("INBOX", readonly=True)
        dernier = etat["boite"].get("dernier_uid")
        if dernier is None:
            depuis = lire_date(etat["demarrage"]).strftime("%d-%b-%Y")
            _, data = srv.uid("search", None, f"(SINCE {depuis})")
        else:
            _, data = srv.uid("search", None, f"UID {dernier + 1}:*")
        uids = [int(u) for u in (data[0] or b"").split() if dernier is None or int(u) > dernier]
        recus = []
        for u in uids[:200]:
            _, d = srv.uid("fetch", str(u), "(BODY.PEEK[])")
            if d and d[0]:
                recus.append(email.message_from_bytes(d[0][1], policy=policy.default))
        if uids:
            etat["boite"]["dernier_uid"] = max(uids[:200])
        elif dernier is None:
            etat["boite"]["dernier_uid"] = 0
        return recus
    finally:
        try:
            srv.logout()
        except Exception:
            pass


def _texte(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    try:
        brut = part.get_content() if part else ""
    except Exception:
        brut = ""
    if part is not None and part.get_content_type() == "text/html":
        brut = re.sub(r"<[^>]+>", " ", brut)
    return brut


def _propre(texte):
    """La réponse elle-même, sans le message cité en dessous."""
    lignes = []
    for l in texte.splitlines():
        if RE_CITE.match(l.strip()):
            break
        lignes.append(l)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()


def traiter(fiche, etat, recus, ia=None):
    """Classe chaque message reçu. Renvoie un compte par catégorie."""
    compte = {"reponse": 0, "stop": 0, "rebond": 0, "absence": 0, "autre": 0}
    par_email = {p["email"]: p for p in etat["prospects"].values()}
    par_fil = {m["message_id"]: m["prospect"] for m in etat["messages"] if m.get("message_id")}
    for msg in recus:
        de = parseaddr(msg.get("From", ""))[1].lower()
        sujet = str(msg.get("Subject", ""))
        corps = _texte(msg)
        # 1. rebond : avis de non-remise
        if (de.split("@")[0] in ("mailer-daemon", "postmaster") or msg.get_content_type() == "multipart/report"
                or msg.get("X-Failed-Recipients")):
            tout = msg.as_string()
            vises = {a.strip().lower() for a in str(msg.get("X-Failed-Recipients", "")).split(",") if a.strip()}
            vises |= {a.lower() for a in re.findall(r"Final-Recipient:[^;]*;\s*(\S+@\S+)", tout)}
            if not vises:
                vises = {a.lower() for a in RE_EMAIL.findall(tout)} & set(par_email)
            definitif = not re.search(r"\b4\.\d\.\d\b|temporar|delay|retard|will be retried", tout, re.I) \
                or re.search(r"\b5\.\d\.\d\b|550|does not exist|n'existe pas|user unknown", tout, re.I)
            for a in vises & set(par_email):
                if definitif:
                    opposer(etat, a, "rebond")
                    par_email[a]["statut"] = "rebond"
                    compte["rebond"] += 1
            continue
        fils = " ".join(str(msg.get(h, "")) for h in ("In-Reply-To", "References"))
        pid = next((v for k, v in par_fil.items() if k and k in fils), None)
        p = par_email.get(de) or (etat["prospects"].get(pid) if pid else None)
        if not p:
            compte["autre"] += 1
            continue
        # 2. réponse automatique : la séquence continue
        auto = str(msg.get("Auto-Submitted", "no")).lower() != "no" or msg.get("X-Autoreply") \
            or msg.get("X-Autorespond") or RE_ABSENCE.search(sujet)
        if auto:
            compte["absence"] += 1
            continue
        reponse = _propre(corps)
        # 3. demande d'arrêt : au moindre doute, on arrête
        if RE_STOP.search(reponse[:600]) or RE_STOP.search(sujet):
            opposer(etat, p["email"], "demande du destinataire")
            if de != p["email"]:
                opposer(etat, de, "demande du destinataire")
            p["reponse"] = {"date": iso(), "extrait": reponse[:400], "intention": "stop", "resume": "Demande d'arrêt."}
            compte["stop"] += 1
            continue
        # 4. vraie réponse : la séquence s'arrête, un humain prend la suite
        annuler_messages(etat, p["id"])
        p["statut"] = "repondu"
        info = {"intention": "a_lire", "resume": ""}
        if ia:
            try:
                info.update(en_json(ia(SYS, f"OFFRE PROPOSÉE : {fiche['offre']['proposition']}\n\nRÉPONSE REÇUE :\n{reponse[:1500]}",
                                       fiche["ia"]["extraction"], 200)))
            except ErreurIA:
                pass
        p["reponse"] = {"date": iso(), "de": de, "extrait": reponse[:600],
                        "intention": info.get("intention", "a_lire"), "resume": info.get("resume", "")}
        noter(etat, "reponse", f"{p['email']} : {p['reponse']['intention']}")
        compte["reponse"] += 1
    return compte
