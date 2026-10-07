"""Essai à blanc complet : aucun réseau, aucun envoi réel, aucune vraie personne.
Le web, l'IA, la boîte d'envoi et l'horloge sont remplacés par des doublures.
    python tests/essai_a_blanc.py
"""
import email
import json
import os
import shutil
import sys
import tempfile
from email import policy
from email.message import EmailMessage
from pathlib import Path

ICI = Path(__file__).resolve().parent.parent
RACINE = Path(tempfile.mkdtemp(prefix="coldmail-essai-"))
os.environ["COLDMAIL_RACINE"] = str(RACINE)
os.environ.pop("COLDMAIL_SECRETS", None)
sys.path.insert(0, str(ICI))
shutil.copytree(ICI / "clients" / "exemple", RACINE / "clients" / "essai")
fiche_p = RACINE / "clients" / "essai" / "client.json"
f = json.loads(fiche_p.read_text(encoding="utf-8"))
f["cadence"].update({"depart_par_jour": 3, "par_passage": 2})
fiche_p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
for reste in ("etat.json", "espace", "sorties"):
    cible = RACINE / "clients" / "essai" / reste
    shutil.rmtree(cible, ignore_errors=True) if cible.is_dir() else cible.unlink(missing_ok=True)

from moteur import envoi, redaction, reponses, sourcing, verif  # noqa: E402
from moteur.__main__ import main, passage                       # noqa: E402
from moteur.socle import charger_etat, charger_fiche, identifiant  # noqa: E402

ok = ko = 0


def verifie(condition, libelle):
    global ok, ko
    ok, ko = ok + bool(condition), ko + (not condition)
    print(("  ok   " if condition else "  ECHEC ") + libelle)


def a(heure):
    os.environ["COLDMAIL_MAINTENANT"] = heure


# ------------------------------------------------------------------ doublures
LISTE = "https://annuaire-artisans.example/la-rochelle/livraison-velo"
SITES = {
    "boulangerie-dumarais": ("Boulangerie du Marais", "Depuis mars, nos tournées du matin se font en vélo cargo dans tout le centre-ville.",
                             '<a href="/equipe">Notre équipe</a>', {"/equipe": "Hélène Marchais, gérante : helene@boulangerie-dumarais.example"}),
    "coursiers-ouest": ("Coursiers de l'Ouest", "Livraison à vélo pour les commerces rochelais.",
                        '<a href="/contact">Contact</a>', {"/contact": "Écrivez-nous : contact@coursiers-ouest.example"}),
    "fleurs-du-port": ("Fleurs du Port", "Bouquets livrés à vélo. Contact : fleursduport17@gmail.com", "", {}),
    "plomberie-vasseur": ("Plomberie Vasseur", "Interventions en centre-ville à vélo cargo.",
                          '<a href="/contact">Nous joindre</a>', {"/contact": "Julien Vasseur, gérant - julien@plomberie-vasseur.example"}),
    "traiteur-lagrange": ("Traiteur Lagrange", "Nos plateaux repas sont livrés en vélo cargo réfrigéré.",
                          '<a href="/contact">Contact</a>', {"/contact": "Sophie Lagrange, dirigeante : sophie [at] traiteur-lagrange.example"}),
    "menuiserie-noroit": ("Menuiserie Noroît", "Petits chantiers en ville, outillage transporté en vélo cargo.",
                          '<a href="/a-propos">À propos</a>', {"/a-propos": "Marc Noroît, gérant, marc@menuiserie-noroit.example"}),
    "torrefaction-phare": ("Torréfaction du Phare", "Café livré chaque semaine aux bureaux du Vieux-Port, à vélo.",
                           '<a href="/contact">Contact</a>', {"/contact": "Inès Phare, gérante : ines@torrefaction-phare.example"}),
    "banque-atlantique": ("Banque Atlantique", "Agence bancaire. direction@banque-atlantique.example", "", {}),
}
WEB = {LISTE: "<h1>Artisans livrant à vélo</h1>" + "".join(
    f'<p><a href="https://{d}.example">{v[0]}</a></p>' for d, v in SITES.items()) + "<p>Vélos Fantômes (sans site)</p>"}
for d, (nom, phrase, lien, pages) in SITES.items():
    WEB[f"https://{d}.example"] = f"<html><body><h1>{nom}</h1><p>{phrase}</p>{lien}<script>var x='piege@script.example'</script></body></html>"
    for chemin, texte in pages.items():
        WEB[f"https://{d}.example{chemin}"] = f"<html><body><p>{texte}</p></body></html>"
lus = []


def faux_web(url):
    lus.append(url)
    return WEB.get(url.rstrip("/")) or WEB.get(url)


PERSONNES = {
    "boulangerie-dumarais": [("Hélène", "Marchais", "gérante", "helene@boulangerie-dumarais.example")],
    "plomberie-vasseur": [("Paul", "Durand", "directeur", "paul.durand@plomberie-vasseur.example"),   # inventée
                          ("Julien", "Vasseur", "gérant", "julien@plomberie-vasseur.example")],
    "traiteur-lagrange": [("Sophie", "Lagrange", "dirigeante", "sophie@traiteur-lagrange.example")],
    "menuiserie-noroit": [("Marc", "Noroît", "gérant", "marc@menuiserie-noroit.example")],
    "torrefaction-phare": [("Inès", "Phare", "gérante", "ines@torrefaction-phare.example")],
}
appels = {"liste": 0, "site": 0, "redaction": 0, "reponse": 0}


def fausse_ia(systeme, message, modele, max_tokens=0):
    if systeme is sourcing.SYS_LISTE:
        appels["liste"] += 1
        ents = [{"nom": v[0], "site": f"https://{d}.example"} for d, v in SITES.items()]
        return json.dumps({"entreprises": ents + [{"nom": "Vélos Fantômes", "site": "https://velos-fantomes.example"}]})
    if systeme is sourcing.SYS_SITE:
        appels["site"] += 1
        d = next(k for k in SITES if f"https://{k}.example ===" in message)
        cit = SITES[d][1]
        if d == "plomberie-vasseur":
            cit = "Élue meilleure entreprise de l'année 2025 par la chambre des métiers."      # inventée
        return "```json\n" + json.dumps({
            "entreprise": SITES[d][0], "activite": "artisan", "correspond_a_la_cible": d != "banque-atlantique",
            "personnes": [dict(zip(("prenom", "nom", "fonction", "email"), p)) for p in PERSONNES.get(d, [])],
            "accroche": {"fait": "livre à vélo cargo", "citation": cit}}, ensure_ascii=False) + "\n```"
    if systeme is redaction.SYS:
        appels["redaction"] += 1
        gen = "prénom «  »" in message
        un = ("Bonjour,\n\nNous réduisons de 40 % l'immobilisation des vélos cargo." if gen else
              "Bonjour,\n\nJ'ai vu que vous livrez en vélo cargo. Nous entretenons ces vélos sur place, avec un vélo de prêt.\n\n"
              "Auriez-vous dix minutes au téléphone cette semaine ?")
        return json.dumps({"messages": [
            {"objet": "Entretien de vos vélos cargo", "corps": un},
            {"objet": "", "corps": "Bonjour,\n\nUn mot pour savoir si le sujet vous concerne. Si ce n'est pas le moment, dites-le-moi simplement."},
            {"objet": "", "corps": "Bonjour,\n\nDernier message de ma part. Je reste joignable si un vélo vous fait défaut un jour."}]})
    if systeme is reponses.SYS:
        appels["reponse"] += 1
        return '{"intention": "interesse", "resume": "Accepte un appel jeudi."}'
    raise AssertionError("appel IA inattendu")


sourcing.recuperer = faux_web
verif.a_un_mx = lambda dom: True
boite, a_relever = [], []


def tour(heure, **kw):
    a(heure)
    recus, a_relever[:] = list(a_relever), []
    return passage("essai", ia=fausse_ia, transport=boite.append, releve=lambda fi, et: recus,
                   dormir=lambda s: None, **kw)


def recu(de, corps, sujet="Re: Entretien de vos vélos cargo", **entetes):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = de, "camille@atelier-rouelibre.example", sujet
    for k, v in entetes.items():
        m[k.replace("_", "-")] = v
    m.set_content(corps)
    return email.message_from_bytes(bytes(m), policy=policy.default)


E = lambda: charger_etat("essai")                              # noqa: E731
P = lambda adr: E()["prospects"].get(identifiant(adr), {})     # noqa: E731

# ------------------------------------------------------------------ scénario
print("\n1. Recherche et rédaction (mercredi 7 octobre, 10 h)")
b = tour("2026-10-07T10:00:00")
e = E()
emails = sorted(p["email"] for p in e["prospects"].values())
verifie(len(emails) == 6, f"6 prospects créés ({len(emails)})")
verifie("velos-fantomes.example" not in e["entreprises"], "entreprise dont le site n'est pas dans la page : écartée")
verifie("paul.durand@plomberie-vasseur.example" not in emails, "adresse inventée par le modèle : écartée")
verifie("fleursduport17@gmail.com" not in emails and e["entreprises"]["fleurs-du-port.example"]["statut"] == "sans_contact",
        "adresse gmail d'un commerce : écartée")
verifie("piege@script.example" not in emails, "adresse cachée dans du code : ignorée")
verifie("sophie@traiteur-lagrange.example" in emails, "adresse écrite « [at] » : lue correctement")
verifie(e["entreprises"]["banque-atlantique.example"]["statut"] == "hors_cible", "entreprise hors cible : écartée")
verifie(P("julien@plomberie-vasseur.example")["citation"] == "", "citation introuvable sur le site : accroche retirée")
verifie(P("helene@boulangerie-dumarais.example")["citation"].startswith("Depuis mars"), "citation exacte : conservée")
verifie(P("helene@boulangerie-dumarais.example")["source_url"].endswith("/equipe"), "page d'origine de l'adresse : mémorisée")
verifie(P("contact@coursiers-ouest.example")["generique"], "adresse générale retenue faute de personne nommée")
verifie(any("40" in x for x in P("contact@coursiers-ouest.example")["alertes"]), "chiffre absent de la fiche : signalé")
verifie(all(p["statut"] == "a_valider" for p in e["prospects"].values()) and not boite, "mode validation : rien n'est parti")

print("\n2. Décisions puis premiers envois")
dec = RACINE / "clients" / "essai" / "decisions"
dec.mkdir(exist_ok=True)
(dec / "001.json").write_text(json.dumps({"decisions": [
    {"action": "refuser", "prospect": "contact@coursiers-ouest.example", "motif": "chiffre non prouvé"},
    {"action": "modifier", "prospect": "helene@boulangerie-dumarais.example", "etape": 1,
     "corps": "Bonjour Hélène,\n\nVos tournées du matin en vélo cargo m'ont donné envie de vous écrire. "
              "Nous entretenons ces vélos sur place.\n\nDix minutes au téléphone cette semaine ?"},
    {"action": "valider", "prospect": "tous"}]}), encoding="utf-8")
b = tour("2026-10-07T10:30:00")
verifie(b["envoyes"] == 2 and len(boite) == 2, "2 messages par passage, pas plus")
verifie(P("contact@coursiers-ouest.example")["statut"] == "ecarte", "prospect refusé : écarté, rien ne partira")
verifie((dec / "appliquees" / "001.json").exists() and not (dec / "001.json").exists(), "décision rangée après application")
m = boite[0]
corps = m.get_content()
verifie("Bonjour Hélène" in corps, "texte modifié à la main : c'est lui qui part")
verifie("Camille Verdier" in corps and "12 quai des Exemples" in corps, "signature et mentions de l'expéditeur")
verifie("répondez simplement STOP" in corps and "boulangerie-dumarais.example/equipe" in corps, "origine de l'adresse et moyen d'arrêt")
verifie(m["List-Unsubscribe"] == "<mailto:camille@atelier-rouelibre.example?subject=STOP>" and m["Message-ID"].endswith("@atelier-rouelibre.example>"),
        "en-têtes : désinscription et identifiant sur le domaine d'envoi")
verifie(m.get_content_type() == "text/plain" and "http" not in corps.split("Camille Verdier")[0], "texte brut, sans lien ni image de pistage")
b = tour("2026-10-07T10:35:00")
verifie(b["envoyes"] == 0 and "écart" in b["raison"], "5 minutes plus tard : attend l'écart entre deux envois")
b = tour("2026-10-07T11:30:00")
verifie(b["envoyes"] == 1, "troisième message du jour")
b = tour("2026-10-07T12:30:00")
verifie(b["envoyes"] == 0 and "plafond" in b["raison"], "plafond du premier jour (3) respecté")
b = tour("2026-10-07T19:00:00")
verifie(b["envoyes"] == 0, "19 h : hors des heures d'envoi")
b = tour("2026-10-08T09:00:00")
verifie(b["envoyes"] == 2 and len(boite) == 5, "jeudi : les 2 premiers messages restants")

print("\n3. Réponses (jeudi 14 h)")
un = {x["prospect"]: x["message_id"] for x in E()["messages"] if x["etape"] == 1 and x["message_id"]}
a_relever += [
    recu("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Address not found. 550 5.1.1 user unknown",
         "Delivery Status Notification (Failure)", X_Failed_Recipients="marc@menuiserie-noroit.example"),
    recu("accueil@traiteur-lagrange.example", "Bonjour,\nOui volontiers, appelez Sophie jeudi matin.\n\nLe mer. 7 oct. 2026 à 10:30, Camille a écrit :\n> Bonjour",
         In_Reply_To=un[identifiant("sophie@traiteur-lagrange.example")]),
    recu("julien@plomberie-vasseur.example", "Merci de ne plus me contacter."),
    recu("ines@torrefaction-phare.example", "Je suis absente jusqu'au 12.", "Réponse automatique", Auto_Submitted="auto-replied"),
    recu("newsletter@autre.example", "Promo", "Offre du mois"),
]
b = tour("2026-10-08T14:00:00")
verifie(b["releve"] == {"reponse": 1, "stop": 1, "rebond": 1, "absence": 1, "autre": 1}, f"5 messages reçus, classés ({b['releve']})")
verifie(P("marc@menuiserie-noroit.example")["statut"] == "rebond", "adresse invalide : retirée")
s = P("sophie@traiteur-lagrange.example")
verifie(s["statut"] == "repondu" and s["reponse"]["intention"] == "interesse", "réponse d'une collègue rattachée au bon contact par le fil")
verifie("a écrit" not in s["reponse"]["extrait"], "message cité retiré de l'extrait")
verifie(P("julien@plomberie-vasseur.example")["statut"] == "stop" and "julien@plomberie-vasseur.example" in E()["opposition"],
        "« ne plus me contacter » : arrêt définitif")
verifie(P("ines@torrefaction-phare.example")["statut"] == "en_sequence", "réponse automatique d'absence : la séquence continue")
annules = [x for x in E()["messages"] if x["statut"] == "annule"]
verifie(len(annules) == 3 * 1 + 2 * 3, f"relances annulées pour qui a répondu, refusé ou rebondi ({len(annules)})")

if os.environ.get("COLDMAIL_EXEMPLE"):      # fabrique la page d'exemple publiée avec la documentation
    from moteur import espace
    csvx = RACINE / "x.csv"
    csvx.write_text("email;prenom;nom;fonction;entreprise;source\nnadia@serrurerie-quai.example;Nadia;Quai;gérante;Serrurerie du Quai;https://serrurerie-quai.example/contact\n"
                    "theo@cave-des-minimes.example;Théo;Bernier;gérant;Cave des Minimes;https://cave-des-minimes.example/equipe\n", encoding="utf-8")
    main(["importer", "essai", str(csvx)])
    tour("2026-10-08T15:00:00")
    espace.produire(charger_fiche("essai"), E(), exemple=True)
    shutil.copytree(RACINE / "clients" / "essai" / "espace", ICI / "clients" / "exemple" / "espace", dirs_exist_ok=True)
    sys.exit(0)

print("\n4. Relances")
b = tour("2026-10-10T10:00:00")
verifie(b["envoyes"] == 0 and "hors" in b["raison"], "samedi : rien ne part")
avant = len(boite)
b = tour("2026-10-12T10:00:00")
verifie(b["envoyes"] == 2, "lundi : 2 relances (Hélène et Inès), aucune pour les autres")
r = boite[avant]
verifie(r["Subject"] == "Re: Entretien de vos vélos cargo" and r["In-Reply-To"] in un.values(), "relance dans le fil du premier message")
verifie({x["To"] for x in boite[avant:]} == {"helene@boulangerie-dumarais.example", "ines@torrefaction-phare.example"}, "destinataires des relances")
tour("2026-10-15T10:00:00")
verifie(len(boite) == avant + 4, "jeudi 15 : troisième et dernier message")
tour("2026-10-23T10:00:00")
verifie(P("helene@boulangerie-dumarais.example")["statut"] == "termine" and len(boite) == avant + 4, "une semaine après : séquence close, plus aucun envoi")
verifie(sum(1 for x in boite if x["To"] in ("julien@plomberie-vasseur.example", "marc@menuiserie-noroit.example",
                                             "sophie@traiteur-lagrange.example")) == 3, "un seul message reçu par ceux qui ont répondu, refusé ou rebondi")

print("\n5. Protections")
csvp = RACINE / "liste.csv"
csvp.write_text("email;prenom;nom;entreprise;source\njulien@plomberie-vasseur.example;Julien;Vasseur;Plomberie;salon\n"
                "nadia@serrurerie-quai.example;Nadia;Quai;Serrurerie du Quai;salon de l'artisanat\nperso@orange.fr;X;Y;Z;w\n", encoding="utf-8")
main(["importer", "essai", str(csvp)])
verifie(P("nadia@serrurerie-quai.example").get("statut") == "nouveau" and not P("perso@orange.fr")
        and P("julien@plomberie-vasseur.example")["statut"] == "stop", "import : la personne opposée et l'adresse grand public ne reviennent pas")
(dec / "002.json").write_text('[{"action": "effacer", "email": "sophie@traiteur-lagrange.example"}]', encoding="utf-8")
imp = RACINE / "clients" / "essai" / "imports"
imp.mkdir()
(imp / "salon.csv").write_text("email,entreprise,source\nluc@cycles-arsenal.example,Cycles de l'Arsenal,salon\n", encoding="utf-8")
b = tour("2026-10-23T11:00:00", recherche=False)
verifie(b.get("importes") == 1 and (imp / "faits" / "salon.csv").exists() and P("luc@cycles-arsenal.example")["statut"] == "a_valider",
        "fichier déposé dans imports/ : chargé puis rédigé, en attente d'accord")
e = E()
verifie(not P("sophie@traiteur-lagrange.example") and "sophie@traiteur-lagrange.example" in e["opposition"]
        and "sophie@" not in json.dumps([e["prospects"], e["messages"], e["journal"]]), "effacement : plus aucune donnée, adresse bloquée")
fiche = charger_fiche("essai")
faux = {"pause": False, "motif_pause": "", "journal": [], "prospects": {}, "messages": []}
for i in range(20):
    faux["prospects"][str(i)] = {"statut": "rebond" if i < 2 else "en_sequence"}
    faux["messages"].append({"prospect": str(i), "etape": 1, "statut": "envoye", "envoye_le": f"2026-10-07T10:{i:02d}:00+02:00"})
verifie(envoi.coupe_circuit(fiche, faux) and faux["pause"], "2 rebonds sur 20 : mise en pause automatique")
faux["pause"] = False
faux["prospects"]["0"]["statut"] = "en_sequence"
verifie(not envoi.coupe_circuit(fiche, faux), "1 rebond sur 20 : on continue")
os.environ["COLDMAIL_MAINTENANT"] = "2026-11-04T10:00:00"
verifie(envoi.plafond_du_jour(fiche, {"demarrage": "2026-10-07T10:30:00+02:00"}, __import__("datetime").date(2026, 11, 4)) == 23
        and envoi.plafond_du_jour(fiche, {"demarrage": "2026-10-07T10:30:00+02:00"}, __import__("datetime").date(2027, 3, 1)) == 30,
        "montée en charge : 3, puis +5 par semaine, jamais plus de 30 par jour")
page = (RACINE / "clients" / "essai" / "espace" / "page.html").read_text(encoding="utf-8")
verifie("/*DONNEES*/" not in page and '"client": "Atelier Roue Libre"' in page and "sophie@" not in page, "page de suivi produite, à jour")
verifie(appels == {"liste": 1, "site": 8, "redaction": 8, "reponse": 1}, f"appels au modèle : {appels}")

print(f"\n{ok} vérifications réussies, {ko} en échec.   Dossier d'essai : {RACINE}")
sys.exit(1 if ko else 0)
