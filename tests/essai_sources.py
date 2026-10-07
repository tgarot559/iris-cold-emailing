"""Essai des sources de prospects : registre public, API ScrapeGraphAI tenue dans son budget, export Apollo.
Aucun appel réel : le registre et ScrapeGraphAI sont remplacés par des doublures.
    python tests/essai_sources.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib import robotparser

ICI = Path(__file__).resolve().parent.parent
RACINE = Path(tempfile.mkdtemp(prefix="coldmail-sources-"))
os.environ["COLDMAIL_RACINE"] = str(RACINE)
os.environ["COLDMAIL_MAINTENANT"] = "2026-10-07T10:00:00"
sys.path.insert(0, str(ICI))
shutil.copytree(ICI / "clients" / "exemple", RACINE / "clients" / "essai", ignore=shutil.ignore_patterns("espace"))
fp = RACINE / "clients" / "essai" / "client.json"
f = json.loads(fp.read_text(encoding="utf-8"))
f["cible"].update({"sources": [], "registre": {"naf": ["49.41A"], "departements": ["17"], "effectifs": ["11", "12"]},
                   "recherches": ["livraison vélo cargo La Rochelle"]})
fp.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
(RACINE / "secrets.json").write_text(json.dumps({"anthropic": "x", "scrapegraph": "sgai-essai"}), encoding="utf-8")

from moteur import sgai, sourcing, verif                                   # noqa: E402
from moteur.__main__ import passage                                        # noqa: E402
from moteur.socle import charger_etat, charger_fiche, identifiant, secrets  # noqa: E402

ok = ko = 0


def verifie(condition, libelle):
    global ok, ko
    ok, ko = ok + bool(condition), ko + (not condition)
    print(("  ok   " if condition else "  ECHEC ") + libelle)


class Rep:
    def __init__(self, data, code=200):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


def ent(siren, nom, ville, diffusion="O", dirigeant=("PAUL HENRI", "LEMOINE", "Gérant")):
    return {"siren": siren, "nom_complet": nom, "statut_diffusion": diffusion, "siege": {"libelle_commune": ville},
            "dirigeants": [{"type_dirigeant": "personne physique", "prenoms": dirigeant[0], "nom": dirigeant[1], "qualite": dirigeant[2]},
                           {"type_dirigeant": "personne morale", "denomination": "HOLDING X"}]}


PAGES = {1: [ent("111111111", "TRANSPORTS LEMOINE", "LA ROCHELLE"), ent("222222222", "SARL DUVAL FRET", "ROCHEFORT", "P"),
             ent("333333333", "MESSAGERIE DU PERTUIS", "AYTRE", dirigeant=("ANNE", "RIVOAL", "Présidente"))],
         2: [ent("444444444", "ATLANTIC COURSES", "LA ROCHELLE", dirigeant=("LEA", "MARTIN", "Gérante")), ent("111111111", "TRANSPORTS LEMOINE", "LA ROCHELLE")]}
appels = {"registre": [], "search": [], "scrape": [], "credits": 0}
mode = {"statut": 200}


class FauxHttp:
    @staticmethod
    def get(url, params=None, headers=None, timeout=0):
        if url == sourcing.REGISTRE:
            appels["registre"].append(dict(params))
            return Rep({"results": PAGES[params["page"]], "total_pages": 2})
        appels["credits"] += 1
        return Rep({"remaining": 412, "used": 88, "plan": "Free Plan"})

    @staticmethod
    def post(url, headers=None, json=None, timeout=0):
        assert headers["SGAI-APIKEY"] == "sgai-essai"
        if mode["statut"] != 200:
            return Rep({}, mode["statut"])
        if url.endswith("/search"):
            appels["search"].append(json["query"])
            q = json["query"]
            if "Lemoine" in q:
                res = [{"url": "https://www.societe.com/societe/transports-lemoine-111111111.html", "title": "TRANSPORTS LEMOINE (La Rochelle)"},
                       {"url": "https://www.transports-lemoine.example/accueil", "title": "Transports Lemoine, messagerie en Charente-Maritime"},
                       {"url": "https://autre.example", "title": "Autre"}]
            elif "Pertuis" in q:
                res = [{"url": "https://www.pagesjaunes.fr/pros/1", "title": "Messagerie du Pertuis"},
                       {"url": "https://pertuis-plongee.example", "title": "Club de plongée du Pertuis"}]      # homonyme partiel
            elif "Atlantic" in q:
                res = [{"url": "https://ac17.example/", "title": "Atlantic Courses - coursiers à La Rochelle"}]
            else:
                res = ([{"url": f"https://livreur{i}.example/page", "title": f"Livreur {i}"} for i in range(7)]
                       + [{"url": "https://www.pagesjaunes.fr/x", "title": "PJ"}, {"url": "https://fr.linkedin.com/company/x", "title": "LI"},
                          {"url": "https://livreur0.example/autre", "title": "doublon"}])
            return Rep({"id": "u", "results": res[:json["numResults"]]})
        appels["scrape"].append(json["url"])
        assert json["fetchConfig"]["mode"] == "js" and json["formats"] == [{"type": "markdown"}]
        return Rep({"id": "u", "results": {"markdown": {"data": [
            "# Transports Lemoine\n\nMessagerie et fret palettisé depuis La Rochelle, quarante véhicules sur les routes de l'Ouest chaque jour. "
            "Notre équipe répond du lundi au vendredi. ![logo](https://x.example/l.png)\n\n"
            "Paul Lemoine, gérant : [paul@transports-lemoine.example](mailto:paul@transports-lemoine.example)\n\n"
            "[Nous contacter](https://www.transports-lemoine.example/contact) " + "Texte. " * 20]}}})


sgai.http = sourcing.http = FauxHttp
sgai.dormir = lambda s: None
sourcing.time.sleep = lambda s: None
verif.a_un_mx = lambda dom: True
WEB = {"https://www.transports-lemoine.example": '<html><body><div id="app"></div><script src="app.js"></script></body></html>',
       "https://ac17.example": "<html><body><h1>Atlantic Courses</h1><p>" + "Coursiers à vélo et en utilitaire à La Rochelle. " * 6
                               + "</p><p>Léa Martin, gérante : lea@ac17.example</p></body></html>"}
sourcing.recuperer = lambda url: WEB.get(url.rstrip("/"))


def fausse_ia(systeme, message, modele, max_tokens=0):
    if systeme is sourcing.SYS_SITE:
        vues["messages"].append(message)
        if "transports-lemoine" in message:
            return json.dumps({"entreprise": "Transports Lemoine", "activite": "messagerie", "correspond_a_la_cible": True,
                               "personnes": [{"prenom": "Paul", "nom": "Lemoine", "fonction": "gérant", "email": "paul@transports-lemoine.example"}],
                               "accroche": {"fait": "40 véhicules", "citation": "quarante véhicules sur les routes de l'Ouest chaque jour"}})
        if "ac17" in message:
            return json.dumps({"entreprise": "Atlantic Courses", "activite": "coursiers", "correspond_a_la_cible": True,
                               "personnes": [{"prenom": "Léa", "nom": "Martin", "fonction": "gérante", "email": "lea@ac17.example"}], "accroche": None})
        return json.dumps({"entreprise": "x", "correspond_a_la_cible": False, "personnes": []})
    return json.dumps({"messages": [{"objet": "Vos tournées", "corps": "Bonjour,\n\nUn mot."}, {"objet": "", "corps": "Bonjour,\n\nRelance."},
                                    {"objet": "", "corps": "Bonjour,\n\nDernier."}]})


vues = {"messages": []}
fiche = charger_fiche("essai")
etat = charger_etat("essai")
sg = sgai.ouvrir(fiche, secrets("essai"))

print("\n1. Registre public des entreprises")
n = sourcing.registre(fiche, etat)
e = etat["entreprises"]
verifie(n == 3 and set(e) == {"siren:111111111", "siren:333333333", "siren:444444444"}, "3 entreprises relevées sur 2 pages, sans doublon")
verifie("siren:222222222" not in e, "entreprise en diffusion partielle (opposée au démarchage) : écartée")
verifie(e["siren:111111111"]["dirigeants"] == [{"prenom": "Paul", "nom": "Lemoine", "qualite": "Gérant"}] and e["siren:111111111"]["ville"] == "La Rochelle",
        "dirigeant et commune repris, personnes morales ignorées")
verifie(appels["registre"][0]["activite_principale"] == "49.41A" and appels["registre"][0]["tranche_effectif_salarie"] == "11,12"
        and appels["registre"][0]["etat_administratif"] == "A", "filtres de la fiche transmis : activité, effectif, entreprises actives")
verifie(sourcing.registre(fiche, etat) == 0 and len(appels["registre"]) == 2, "second passage : rien n'est redemandé")

f_nat = {"cible": {"registre": {"naf": ["49.41A"], "exclure_departements": ["17"]}}}
PAGES[1][0]["siege"]["code_postal"] = PAGES[2][1]["siege"]["code_postal"] = "17000"
PAGES[1].append({**ent("666666666", "FRET LYONNAIS", "LYON"), "siege": {"libelle_commune": "LYON", "code_postal": "69003"}})
et_nat = {"entreprises": {}, "journal": []}
sourcing.registre(f_nat, et_nat)
verifie("departement" not in appels["registre"][-1] and "siren:666666666" in et_nat["entreprises"]
        and "siren:111111111" not in et_nat["entreprises"], "France entière sans département ; siège en Charente-Maritime écarté")
PAGES[1].pop()

print("\n2. Trouver les sites (ScrapeGraphAI, recherche)")
t = sourcing.trouver_sites(fiche, etat, sg)
verifie(t == 2 and e["transports-lemoine.example"]["site"] == "https://www.transports-lemoine.example" and "ac17.example" in e,
        "2 sites trouvés ; l'annuaire placé en tête est ignoré")
verifie(e["siren:333333333"]["statut"] == "site_introuvable", "homonyme sans rapport : refusé plutôt que deviné")
verifie(e["transports-lemoine.example"]["dirigeants"][0]["nom"] == "Lemoine", "les informations du registre suivent l'entreprise")
verifie(sg.utilises() == (2 * 3 + 2 * 2 + 2 * 1, 12), f"crédits comptés au résultat rendu : {sg.utilises()[0]}")
r = sourcing.recherches(fiche, etat, sg)
verifie(r == 7 and sg.utilises()[0] == 32 and sourcing.recherches(fiche, etat, sg) == 0,
        "requête libre : 7 sites retenus sur 10 résultats (annuaires et doublon écartés), 20 crédits, jamais relancée")

print("\n3. Lire un site fait en JavaScript")
for d in list(e):
    if d.startswith("livreur"):
        e[d]["statut"] = "ecarte_essai"
crees = sourcing.explorer(fiche, etat, fausse_ia, sg=sg)
p = etat["prospects"]
verifie(crees == 2 and appels["scrape"] == ["https://www.transports-lemoine.example"],
        "page vide en lecture directe : relue par ScrapeGraphAI ; l'autre site, lisible, ne coûte rien")
paul = p[identifiant("paul@transports-lemoine.example")]
verifie(paul["prenom"] == "Paul" and paul["citation"].startswith("quarante véhicules"), "adresse et citation retrouvées dans la page rendue")
verifie(sg.utilises()[0] == 33, "1 crédit pour la page")
verifie(any("DIRIGEANTS AU REGISTRE PUBLIC : Paul Lemoine (Gérant)" in m and "ENTREPRISE ATTENDUE : Transports Lemoine, La Rochelle" in m for m in vues["messages"]),
        "le modèle reçoit le dirigeant et l'entreprise attendue pour repérer un homonyme")
rp = robotparser.RobotFileParser()
rp.parse(["User-agent: *", "Disallow: /"])
sourcing._robots["https://ferme.example"] = rp
avant = len(appels["scrape"])
verifie(sourcing.lire_avec_secours("https://ferme.example/", lambda u: None, sg) is None and len(appels["scrape"]) == avant,
        "site qui interdit les robots : ScrapeGraphAI n'est pas utilisé pour contourner")

print("\n4. Budget du compte gratuit")
(RACINE / "reglages.json").write_text('{"scrapegraph": {"credits_par_client": 60}}', encoding="utf-8")
sg2 = sgai.ouvrir(fiche, secrets("essai"))
avant = len(appels["search"])
res = [sg2.chercher(f"requête {i}", 10) for i in range(5)]
verifie([x is not None for x in res] == [True, False, False, False, False] and len(appels["search"]) == avant + 1 and sg2.utilises()[1] == 53,
        "plafond par client (60) : un seul appel passe, les suivants ne sont même pas lancés")
(RACINE / "reglages.json").write_text('{"scrapegraph": {"credits_par_client": 9999}}', encoding="utf-8")
sg3 = sgai.ouvrir(fiche, secrets("essai"))
k = 0
while sg3.chercher("tout", 10) is not None and k < 100:
    k += 1
verifie(sg3.utilises()[0] <= 480 and sg3.utilises()[0] > 460, f"plafond du mois (480 sur les 500 gratuits) jamais dépassé : {sg3.utilises()[0]}")
(RACINE / "credits.json").unlink()
mode["statut"] = 402
sg4 = sgai.ouvrir(fiche, secrets("essai"))
avant = len(appels["search"])
verifie(sg4.lire("https://x.example") is None and sg4.utilises()[0] == 0 and not sg4.disponible(1),
        "ScrapeGraphAI répond « crédits épuisés » : plus aucun appel ce mois-ci, rien n'est compté")
mode["statut"] = 200
os.environ["COLDMAIL_MAINTENANT"] = "2026-11-02T10:00:00"
verifie(sg4.disponible(20) and sg4.utilises() == (0, 0), "le mois suivant, le compteur repart de zéro")
verifie(sg4.solde()["remaining"] == 412, "solde réel lisible auprès de ScrapeGraphAI")
os.environ["COLDMAIL_MAINTENANT"] = "2026-10-07T10:00:00"

print("\n5. Export Apollo et fonctionnement sans clé")
imp = RACINE / "clients" / "essai" / "imports"
imp.mkdir()
(imp / "apollo-export.csv").write_text(
    "First Name,Last Name,Title,Company,Email,Website\nMarc,Ollivier,Fleet Manager,Ouest Logistique,marc@ouest-logistique.example,https://ouest-logistique.example\n"
    "Zoé,Perso,CEO,Solo,zoe@gmail.com,\n", encoding="utf-8")
(RACINE / "secrets.json").write_text(json.dumps({"anthropic": "x"}), encoding="utf-8")
fiche2 = json.loads(fp.read_text(encoding="utf-8"))
fiche2["cible"]["registre"]["departements"] = ["79"]
fp.write_text(json.dumps(fiche2, ensure_ascii=False), encoding="utf-8")
PAGES[1] = [ent("555555555", "FRET DES DEUX SEVRES", "NIORT")]
PAGES[2] = []
avant = (len(appels["search"]), len(appels["scrape"]))
boite = []
b = passage("essai", ia=fausse_ia, transport=boite.append, releve=lambda fi, et: [], dormir=lambda s: None)
et = charger_etat("essai")
marc = et["prospects"][identifiant("marc@ouest-logistique.example")]
verifie(b["importes"] == 1 and marc["fonction"] == "Fleet Manager" and marc["entreprise"] == "Ouest Logistique"
        and identifiant("zoe@gmail.com") not in et["prospects"], "export Apollo reconnu tel quel ; l'adresse gmail est écartée")
verifie(marc["source_url"] == "l'annuaire professionnel Apollo", "origine « Apollo » notée, pour la dire au destinataire")
verifie("credits_scrapegraph" not in b and (len(appels["search"]), len(appels["scrape"])) == avant
        and et["entreprises"]["siren:555555555"]["statut"] == "sans_site",
        "sans clé ScrapeGraphAI : le moteur tourne, le registre est relevé, aucun appel payant")

print("\n6. Préparer sans envoyer (adresse d'envoi pas encore prête)")
fiche3 = json.loads(fp.read_text(encoding="utf-8"))
fiche3.update({"envoi": False})
fiche3["boite"]["adresse"] = ""
fp.write_text(json.dumps(fiche3, ensure_ascii=False), encoding="utf-8")
from moteur.__main__ import main      # noqa: E402
main(["decider", "essai", '{"action": "valider", "prospect": "tous"}'])
boite.clear()
b = passage("essai", ia=fausse_ia, transport=boite.append, releve=lambda fi, et: [], dormir=lambda s: None)
et = charger_etat("essai")
verifie("bloque" not in b and b["envoyes"] == 0 and "préparation" in b["raison"] and not boite
        and et["prospects"][identifiant("marc@ouest-logistique.example")]["statut"] == "pret" and et["demarrage"] is None,
        "sans adresse d'envoi : contacts trouvés, messages validés, prêts à partir, rien n'est envoyé")
page = (RACINE / "clients" / "essai" / "espace" / "page.html").read_text(encoding="utf-8")
verifie('"etat": "preparation"' in page, "la page du client affiche « En préparation »")

print(f"\n{ok} vérifications réussies, {ko} en échec.")
sys.exit(1 if ko else 0)
