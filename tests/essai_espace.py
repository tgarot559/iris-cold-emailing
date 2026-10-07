"""Essai de la page de suivi en direct : un vrai navigateur clique, les vraies fonctions du site
enregistrent, le moteur applique. GitHub et Cloudflare sont remplacés par un serveur local.
Demande Node et Playwright (présents sur le poste de développement, inutiles en production).
    python tests/essai_espace.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ICI = Path(__file__).resolve().parent.parent
RACINE = Path(tempfile.mkdtemp(prefix="coldmail-espace-"))
os.environ["COLDMAIL_RACINE"] = str(RACINE)
os.environ.pop("COLDMAIL_SECRETS", None)
sys.path.insert(0, str(ICI))
CODE, PORT = "abcdefgh2345", 8791
shutil.copytree(ICI / "clients" / "exemple", RACINE / "clients" / "essai", ignore=shutil.ignore_patterns("espace"))
fp = RACINE / "clients" / "essai" / "client.json"
f = json.loads(fp.read_text(encoding="utf-8"))
f.update({"code": CODE})
f["cible"]["sources"] = []
fp.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")

from moteur import redaction, verif                      # noqa: E402
from moteur.__main__ import main, passage                # noqa: E402
from moteur.socle import charger_etat, identifiant       # noqa: E402

ok = ko = 0


def verifie(condition, libelle):
    global ok, ko
    ok, ko = ok + bool(condition), ko + (not condition)
    print(("  ok   " if condition else "  ECHEC ") + libelle)


def fausse_ia(systeme, message, modele, max_tokens=0):
    assert systeme is redaction.SYS
    return json.dumps({"messages": [
        {"objet": "Entretien de vos vélos cargo", "corps": "Bonjour,\n\nNous entretenons les vélos cargo sur place.\n\nDix minutes au téléphone ?"},
        {"objet": "", "corps": "Bonjour,\n\nUn mot pour savoir si le sujet vous concerne."},
        {"objet": "", "corps": "Bonjour,\n\nDernier message de ma part."}]})


verif.a_un_mx = lambda dom: True
boite = []


def tour(heure):
    os.environ["COLDMAIL_MAINTENANT"] = heure
    return passage("essai", ia=fausse_ia, transport=boite.append, releve=lambda fi, et: [], dormir=lambda s: None)


P = lambda adr: charger_etat("essai")["prospects"][identifiant(adr)]   # noqa: E731
csvp = RACINE / "liste.csv"
csvp.write_text("email;prenom;nom;fonction;entreprise;source\n"
                "nadia@serrurerie-quai.example;Nadia;Quai;gérante;Serrurerie du Quai;https://serrurerie-quai.example/contact\n"
                "theo@cave-des-minimes.example;Théo;Bernier;gérant;Cave des Minimes;https://cave-des-minimes.example/equipe\n"
                "luc@cycles-arsenal.example;Luc;Morel;gérant;Cycles de l'Arsenal;https://cycles-arsenal.example\n", encoding="utf-8")
os.environ["COLDMAIL_MAINTENANT"] = "2026-10-07T10:00:00"
main(["importer", "essai", str(csvp)])
tour("2026-10-07T10:00:00")

serveur = subprocess.Popen(["node", str(ICI / "tests" / "serveur_essai.mjs"), str(RACINE), str(PORT)],
                           stdout=subprocess.PIPE, text=True)
try:
    assert serveur.stdout.readline().strip() == "pret"
    base = f"http://127.0.0.1:{PORT}"
    web = requests.Session()
    web.trust_env = False

    print("\n1. Les fonctions du site")
    d = web.get(f"{base}/api/espace?code={CODE}").json()
    verifie(len(d["attente"]) == 3 and "dossier" not in d, "données du client servies, sans le nom du dossier interne")
    verifie(web.get(f"{base}/api/espace?code=zzzzzzzzzzzz").status_code == 404
            and web.get(f"{base}/api/espace?code=../clients").status_code == 404, "code inconnu ou trafiqué : refusé")
    verifie(web.get(f"{base}/api/espace?console=1").status_code == 403
            and web.get(f"{base}/api/espace?console=1", headers={"x-cle": "fausse"}).status_code == 403, "console sans la clé : refusée")
    c = web.get(f"{base}/api/espace?console=1", headers={"x-cle": "cle-essai"}).json()
    verifie(c[CODE]["attente"] == 3 and c[CODE]["client"] == "Atelier Roue Libre", "console avec la clé : liste des clients")
    interdit = web.post(f"{base}/api/espace", json={"code": CODE, "decisions": [
        {"action": "opposer", "email": "@serrurerie-quai.example"}, {"action": "effacer", "email": "x@y.fr"},
        {"action": "valider", "prospect": "tous"}, {"action": "valider", "prospect": "../../x"},
        {"action": "modifier", "prospect": identifiant("luc@cycles-arsenal.example"), "etape": 9, "corps": "x"}]})
    verifie(interdit.status_code == 400 and not list((RACINE / "clients" / "essai").glob("decisions/*.json")),
            "décisions réservées au pilote ou mal formées : aucune n'est déposée")
    verifie(web.post(f"{base}/api/espace", json={"code": "zzzzzzzzzzzz", "decisions": [{"action": "pause"}]}).status_code == 404,
            "décision envoyée avec un mauvais code : refusée")

    print("\n2. Le client clique dans sa page")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        page = nav.new_page(viewport={"width": 400, "height": 900})
        erreurs = []
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        page.goto(f"{base}/e/{CODE}")
        page.wait_for_selector("#attente article")
        verifie(page.locator("#attente article").count() == 3 and page.get_by_role("button", name="Tout valider (3)").count() == 1,
                "3 contacts à valider, avec leurs boutons")
        verifie(not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "pas de défilement horizontal sur téléphone")
        un = page.locator("#attente article").nth(0)
        un.get_by_role("button", name="Corriger").click()
        un = page.locator("#attente article").nth(0)
        un.locator("textarea").first.fill("Bonjour Nadia,\n\nJe passe devant votre atelier tous les matins. Nous entretenons les vélos cargo sur place.\n\nDix minutes au téléphone ?")
        un.locator("input").fill("Vos vélos cargo, quai Valin")
        shot = os.environ.get("COLDMAIL_CAPTURE")
        if shot:
            page.screenshot(path=shot, full_page=True)
        un.get_by_role("button", name="Enregistrer et valider").click()
        page.wait_for_selector("#attente article .note-ok")
        page.locator("#attente article").nth(1).get_by_role("button", name="Ne pas contacter").click()
        page.wait_for_function("document.querySelectorAll('#attente article .note-ok').length === 2")
        page.reload()
        page.wait_for_selector("#attente article")
        verifie(page.locator("#attente article .note-ok").count() == 2 and page.locator("#attente article .actions").count() == 1,
                "après rechargement : les deux décisions restent affichées comme prises")
        page.locator("#attente article").nth(2).get_by_role("button", name="Valider").click()
        page.wait_for_function("document.querySelectorAll('#attente article .note-ok').length === 3")
        fichiers = sorted((RACINE / "clients" / "essai" / "decisions").glob("*.json"))
        verifie(len(fichiers) == 3 and not erreurs, f"3 décisions déposées dans le dépôt, aucune erreur de page ({erreurs})")

        print("\n3. Le moteur applique au passage suivant")
        b = tour("2026-10-07T10:30:00")
        verifie(b["envoyes"] == 2 and len(boite) == 2, "2 messages partent : les deux contacts validés")
        nadia = next(m for m in boite if m["To"] == "nadia@serrurerie-quai.example")
        verifie(nadia["Subject"] == "Vos vélos cargo, quai Valin" and "Je passe devant votre atelier" in nadia.get_content(),
                "le message corrigé dans la page est celui qui part, objet compris")
        verifie(P("theo@cave-des-minimes.example")["statut"] == "ecarte" and all(m["To"] != "theo@cave-des-minimes.example" for m in boite),
                "le contact écarté ne reçoit rien")
        page.reload()
        page.wait_for_selector("table")
        verifie(page.locator("#attente").count() == 0 and page.get_by_text("2 messages sont partis").count() == 1,
                "la page se met à jour : plus rien à valider, 2 messages partis")

        print("\n4. Pause depuis la page")
        page.get_by_role("button", name="Mettre les envois en pause").click()
        page.wait_for_selector(".entete .note-ok")
        b = tour("2026-10-08T10:00:00")
        page.reload()
        page.wait_for_selector("table")
        verifie(charger_etat("essai")["pause"] and page.get_by_text("En pause").count() >= 1
                and page.get_by_role("button", name="Reprendre les envois").count() == 1, "pause appliquée et affichée, bouton de reprise proposé")
        page.goto(f"{base}/console/")
        page.fill("#cle", "cle-essai")
        page.get_by_role("button", name="Ouvrir").click()
        page.wait_for_selector("a.client")
        verifie("Atelier Roue Libre" in page.locator("a.client").inner_text() and "En pause" in page.locator("a.client").inner_text()
                and page.locator("a.client").get_attribute("href") == f"/e/{CODE}", "console : le client, son état et le lien vers sa page")
        nav.close()
finally:
    serveur.terminate()

print(f"\n{ok} vérifications réussies, {ko} en échec.")
sys.exit(1 if ko else 0)
