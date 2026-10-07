"""Recherche de prospects sur des pages publiques d'entreprises.

Deux temps :
  1. decouvrir : une page de liste (annuaire, adhérents, exposants...) -> des entreprises et leur site
  2. explorer  : le site d'une entreprise -> personnes, adresses, et un fait cité mot pour mot

Garde-fous, appliqués par le code et non par le modèle :
  - une adresse n'est retenue que si elle figure telle quelle dans la page lue ;
  - un site n'est retenu que s'il figure dans les liens de la page de liste ;
  - une accroche n'est retenue que si sa citation est un passage exact de la page ;
  - robots.txt est respecté, une pause est marquée entre deux pages d'un même site.
"""
import csv
import html as html_lib
import re
import time
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import verif
from .ia import ErreurIA, en_json
from .socle import domaine, est_oppose, identifiant, iso, noter

AGENT = "Mozilla/5.0 (compatible; prospection-b2b/1.0)"
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RE_PAGES = re.compile(r"contact|mentions|l[ée]gal|[ée]quipe|team|qui-?sommes|a-?propos|about|nous", re.I)
_robots, _dernier = {}, {}


def recuperer(url, pause=2.0):
    """Lit une page publique. Renvoie le HTML, ou None si interdit ou indisponible."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": AGENT}, timeout=10)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
    if not _robots[base].can_fetch(AGENT, url):
        return None
    attente = pause - (time.time() - _dernier.get(base, 0))
    if attente > 0:
        time.sleep(attente)
    _dernier[base] = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": AGENT, "Accept-Language": "fr"}, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None
    return r.text


def lire_page(html, url):
    """HTML -> (texte, liens [(libellé, url)], adresses trouvées)."""
    soup = BeautifulSoup(html, "html.parser")
    adresses = set()
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            adresses.add(a["href"][7:].split("?")[0].strip().lower())
    for balise in soup(["script", "style", "noscript", "svg"]):
        balise.decompose()
    texte = re.sub(r"[ \t\r\f\v]+", " ", soup.get_text("\n"))
    texte = re.sub(r"\n\s*\n+", "\n", texte).strip()
    clair = re.sub(r"\s*[\[\(]\s*(at|arobase)\s*[\]\)]\s*", "@", texte, flags=re.I)
    adresses |= {m.lower().rstrip(".") for m in RE_EMAIL.findall(clair)}
    liens = []
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if h.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        liens.append((a.get_text(" ", strip=True)[:80], urljoin(url, h)))
    return texte, liens, {a for a in adresses if verif.syntaxe(a)}


def interdit(url):
    """robots.txt interdit-il cette page ? (inconnu = non)"""
    p = urlparse(url)
    rp = _robots.get(f"{p.scheme}://{p.netloc}")
    return bool(rp) and not rp.can_fetch(AGENT, url)


def md_en_html(md):
    """Markdown rendu par ScrapeGraphAI -> HTML simple, pour passer par la même lecture que les autres pages."""
    t = html_lib.escape(md, quote=False)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]*)\]\(<?(mailto:[^)\s>]+|https?://[^)\s>]+)>?[^)]*\)", r'<a href="\2">\1</a>', t)
    return "<html><body>" + "".join(f"<p>{l}</p>" for l in t.splitlines() if l.strip()) + "</body></html>"


def lire_avec_secours(url, fetch, sg, etat=None):
    """Lecture directe d'abord (gratuite). Si la page est vide ou illisible (site fait en JavaScript) et que
    robots.txt ne l'interdit pas, une lecture par ScrapeGraphAI (1 crédit), dans la limite du budget."""
    html = fetch(url)
    if html:
        texte = lire_page(html, url)[0]
        if len(texte) >= 200 or not sg:
            return html
    if not sg or interdit(url) or not sg.disponible(1):
        return html
    md = sg.lire(url)
    if md and (len(md) >= 200 or not html):
        if etat is not None:
            noter(etat, "sourcing", f"page lue par ScrapeGraphAI (1 crédit) : {url}")
        return md_en_html(md)
    return html


def _compact(t):
    return re.sub(r"\s+", " ", t).strip().lower()


# ---------------------------------------------------------------- 1. découvrir

SYS_LISTE = """Tu lis une page web qui liste des entreprises. Tu relèves celles qui correspondent à la cible décrite.
Tu ne retiens une entreprise que si son site web figure dans la liste de liens fournie. Tu n'inventes rien.
Réponds uniquement en JSON : {"entreprises": [{"nom": "...", "site": "https://..."}]}"""


def decouvrir(fiche, etat, ia, fetch=None, sg=None):
    """Explore les pages de liste de la fiche et ajoute les entreprises nouvelles."""
    fetch = fetch or recuperer
    ajout = 0
    deja = etat.setdefault("sources_lues", {})
    for s in fiche["cible"]["sites"]:
        d = domaine(s)
        if d and d not in etat["entreprises"]:
            url = s if "://" in s else "https://" + s
            etat["entreprises"][d] = {"nom": d, "site": url, "source": "fiche client", "statut": "a_explorer"}
            ajout += 1
    for src in fiche["cible"]["sources"]:
        if src in deja:
            continue
        html = lire_avec_secours(src, fetch, sg, etat)
        if not html:
            noter(etat, "sourcing", f"page de liste illisible ou interdite : {src}")
            deja[src] = iso()
            continue
        texte, liens, _ = lire_page(html, src)
        hote = domaine(src)
        externes = {domaine(u): u for _, u in liens if domaine(u) and domaine(u) != hote}
        if fiche["ia"]["scrapegraph"]:
            trouve = _scrapegraph(src, fiche, ia)
        else:
            message = (f"CIBLE : {fiche['cible']['description']}\n\nPAGE ({src}) :\n{texte[:14000]}\n\n"
                       "LIENS EXTERNES :\n" + "\n".join(f"{l} -> {u}" for l, u in liens
                                                       if domaine(u) != hote)[:6000])
            try:
                trouve = en_json(ia(SYS_LISTE, message, fiche["ia"]["extraction"], 3000)).get("entreprises", [])
            except ErreurIA as e:
                noter(etat, "erreur", f"découverte {src} : {e}")
                continue
        for ent in trouve:
            d = domaine(ent.get("site", "") or "")
            if not d or d not in externes or d in etat["entreprises"]:
                continue        # site absent des liens de la page : écarté
            etat["entreprises"][d] = {"nom": (ent.get("nom") or d)[:120], "site": externes[d],
                                      "source": src, "statut": "a_explorer"}
            ajout += 1
        deja[src] = iso()
    if ajout:
        noter(etat, "sourcing", f"{ajout} entreprise(s) ajoutée(s)")
    return ajout


def _scrapegraph(url, fiche, ia):
    """Variante : laisser la bibliothèque ScrapeGraphAI lire la page (elle sait rendre le JavaScript).
    Demande `pip install scrapegraphai` et `playwright install chromium` sur la machine qui fait tourner le moteur."""
    from scrapegraphai.graphs import SmartScraperGraph   # import tardif : dépendance facultative
    from .socle import secrets
    graphe = SmartScraperGraph(
        prompt=("Liste les entreprises de cette page qui correspondent à : "
                f"{fiche['cible']['description']}. Pour chacune : nom, site."),
        source=url,
        config={"llm": {"api_key": secrets(fiche["_id"])["anthropic"],
                        "model": "anthropic/" + fiche["ia"]["extraction"], "model_tokens": 200000},
                "headless": True, "verbose": False})
    res = graphe.run() or {}
    liste = res.get("entreprises") or next((v for v in res.values() if isinstance(v, list)), [])
    return [{"nom": e.get("nom") or e.get("name"), "site": e.get("site") or e.get("website")}
            for e in liste if isinstance(e, dict)]


# ---------------------------------------------------------------- 2. explorer

SYS_SITE = """Tu lis les pages publiques du site d'une entreprise pour préparer un premier contact professionnel.
Règles strictes :
- Tu ne retiens que les personnes dont le nom ET l'adresse email figurent dans le texte, et dont la fonction correspond aux fonctions visées.
- Tu ne devines, ne complètes et ne construis jamais une adresse email.
- Si une ENTREPRISE ATTENDUE est indiquée et que le site est manifestement celui d'une autre société (homonyme, annuaire, autre ville), mets "correspond_a_la_cible" à false.
- "accroche" : un seul fait concret et récent ou distinctif sur l'entreprise, utile pour ouvrir un message. "citation" doit être un passage copié mot pour mot du texte. Si rien de concret, mets null.
Réponds uniquement en JSON :
{"entreprise": "nom", "activite": "une ligne", "correspond_a_la_cible": true,
 "personnes": [{"prenom": "", "nom": "", "fonction": "", "email": ""}],
 "accroche": {"fait": "", "citation": ""}}"""


def explorer(fiche, etat, ia, fetch=None, mx=None, limite=15, sg=None):
    """Visite les entreprises en attente et crée les prospects. Renvoie le nombre de prospects créés."""
    fetch, mx = fetch or recuperer, mx or verif.a_un_mx
    cible, crees, vues = fiche["cible"], 0, 0
    for d, ent in etat["entreprises"].items():
        if ent["statut"] != "a_explorer":
            continue
        if vues >= limite:
            break
        vues += 1
        accueil = lire_avec_secours(ent["site"], fetch, sg, etat)
        if not accueil:
            ent["statut"] = "illisible"
            continue
        texte, liens, adresses = lire_page(accueil, ent["site"])
        pages = {ent["site"]: texte}
        origine = {a: ent["site"] for a in adresses}
        suivre = []
        for lib, u in liens:
            if domaine(u) == d and u not in pages and u not in suivre and RE_PAGES.search(lib + " " + urlparse(u).path):
                suivre.append(u)
        for u in suivre[:4]:
            h = fetch(u)
            if not h:
                continue
            t, _, adr = lire_page(h, u)
            pages[u] = t
            for a in adr:
                origine.setdefault(a, u)
        if not origine:
            ent["statut"] = "sans_adresse"
            continue
        corpus = "\n\n".join(f"=== {u} ===\n{t[:5000]}" for u, t in pages.items())
        message = (f"CIBLE : {cible['description']}\nFONCTIONS VISÉES : {', '.join(cible['fonctions']) or 'dirigeant'}\n"
                   + (f"ENTREPRISE ATTENDUE : {ent['nom']}, {ent.get('ville', '')}\n" if ent.get("siren") else "")
                   + (f"DIRIGEANTS AU REGISTRE PUBLIC : {'; '.join(x['prenom'] + ' ' + x['nom'] + ' (' + x['qualite'] + ')' for x in ent['dirigeants'])}\n"
                      if ent.get("dirigeants") else "")
                   + f"ADRESSES PRÉSENTES DANS LES PAGES : {', '.join(sorted(origine))}\n\n{corpus}")
        try:
            lu = en_json(ia(SYS_SITE, message, fiche["ia"]["extraction"], 1500))
        except ErreurIA as e:
            noter(etat, "erreur", f"exploration {d} : {e}")
            continue
        ent["nom"] = (lu.get("entreprise") or ent["nom"])[:120]
        ent["activite"] = (lu.get("activite") or "")[:200]
        if lu.get("correspond_a_la_cible") is False:
            ent["statut"] = "hors_cible"
            continue
        accroche = lu.get("accroche") or {}
        cit = accroche.get("citation") or ""
        if not (cit and len(cit) > 15 and _compact(cit) in _compact(corpus)):
            accroche = {}       # citation introuvable dans la page : on s'en passe
        candidats = []
        for p in lu.get("personnes") or []:
            e = (p.get("email") or "").strip().lower()
            if e in origine:    # adresse absente de la page : écartée
                candidats.append({**p, "email": e, "generique": False})
        if not candidats and cible["accepter_generiques"]:
            gen = sorted(a for a in origine if verif.est_generique(a) and domaine(a) == d)
            candidats = [{"prenom": "", "nom": "", "fonction": "", "email": a, "generique": True} for a in gen[:1]]
        retenus = 0
        for c in candidats:
            if retenus >= cible["max_par_entreprise"]:
                break
            ok, motif = verif.controler(c["email"], cible["accepter_webmails"], mx)
            pid = identifiant(c["email"])
            if not ok or pid in etat["prospects"] or est_oppose(etat, c["email"]):
                if not ok:
                    noter(etat, "sourcing", f"{c['email']} écartée : {motif}")
                continue
            etat["prospects"][pid] = {
                "id": pid, "email": c["email"], "prenom": (c.get("prenom") or "").strip()[:40],
                "nom": (c.get("nom") or "").strip()[:60], "fonction": (c.get("fonction") or "").strip()[:100],
                "generique": c["generique"], "entreprise": ent["nom"], "activite": ent.get("activite", ""),
                "site": ent["site"], "source_url": origine[c["email"]],
                "accroche": accroche.get("fait", "") if accroche else "",
                "citation": cit if accroche else "", "statut": "nouveau", "cree": iso(),
            }
            retenus += 1
            crees += 1
        ent["statut"] = "exploree" if retenus else "sans_contact"
    if crees:
        noter(etat, "sourcing", f"{crees} prospect(s) trouvé(s)")
    return crees


# ---------------------------------------------------------------- import d'un fichier

ALIAS = {
    "email": ["e-mail", "email address", "work email", "adresse email", "mail", "courriel"],
    "prenom": ["prénom", "first name", "firstname"],
    "nom": ["last name", "lastname", "surname"],
    "fonction": ["title", "job title", "poste", "position"],
    "entreprise": ["company", "company name", "société", "societe", "organization", "account name"],
    "site": ["website", "company website", "site web", "url"],
    "source": ["origine"],
}


def importer(fiche, etat, chemin, mx=None, origine=""):
    """Charge un CSV (colonnes : email, prenom, nom, fonction, entreprise, site, source ; les en-têtes
    d'un export Apollo sont reconnus). `origine` sert de source quand le fichier n'en donne pas.
    La colonne source dit où l'adresse a été trouvée ; elle est reprise au bas du premier message."""
    crees = ecartes = 0
    mx = mx or verif.a_un_mx
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        tete = f.readline()
        f.seek(0)
        lignes = csv.DictReader(f, delimiter=";" if tete.count(";") > tete.count(",") else ",")
        for l in lignes:
            l = {(k or "").strip().lower(): (v or "").strip() for k, v in l.items()}
            for cle, autres in ALIAS.items():          # exports Apollo, LinkedIn, tableurs en anglais
                if not l.get(cle):
                    l[cle] = next((l[a] for a in autres if l.get(a)), "")
            if not l.get("source") and origine:
                l["source"] = origine
            e = l.get("email", "").lower()
            ok, motif = verif.controler(e, fiche["cible"]["accepter_webmails"], mx)
            pid = identifiant(e) if e else ""
            if not ok or pid in etat["prospects"] or est_oppose(etat, e):
                ecartes += 1
                continue
            etat["prospects"][pid] = {
                "id": pid, "email": e, "prenom": l.get("prenom", ""), "nom": l.get("nom", ""),
                "fonction": l.get("fonction", ""), "generique": verif.est_generique(e),
                "entreprise": l.get("entreprise", ""), "activite": "", "site": l.get("site", ""),
                "source_url": l.get("source", ""), "accroche": "", "citation": "",
                "statut": "nouveau", "cree": iso(),
            }
            crees += 1
    noter(etat, "sourcing", f"import : {crees} prospect(s), {ecartes} ligne(s) écartée(s)")
    return crees, ecartes


# ---------------------------------------------------------------- 0. trouver des entreprises sans page de liste

REGISTRE = "https://recherche-entreprises.api.gouv.fr/search"
ANNUAIRES = {
    "societe.com", "pappers.fr", "infogreffe.fr", "verif.com", "manageo.fr", "annuaire-entreprises.data.gouv.fr",
    "pagesjaunes.fr", "kompass.com", "fr.kompass.com", "linkedin.com", "fr.linkedin.com", "facebook.com", "instagram.com",
    "x.com", "twitter.com", "youtube.com", "wikipedia.org", "fr.wikipedia.org", "bodacc.fr", "societeinfo.com",
    "entreprises.lefigaro.fr", "lefigaro.fr", "rubypayeur.com", "score3.fr", "data.gouv.fr", "europages.fr", "europages.com",
    "mappy.com", "google.com", "tripadvisor.fr", "indeed.com", "fr.indeed.com", "welcometothejungle.com", "b-reputation.com",
    "infonet.fr", "dirigeant.com", "sirene.fr", "118000.fr", "cylex-locale.fr", "hoodspot.fr", "trouver-ouvert.fr",
}
http = requests       # remplaçable dans les essais


def _annuaire(d):
    return d in ANNUAIRES or any(d.endswith("." + a) for a in ANNUAIRES)


def registre(fiche, etat, limite=40):
    """Entreprises actives tirées du registre public (API Recherche d'entreprises : gratuite, sans clé).
    Réglage dans la fiche : cible.registre = {"naf": ["49.41A"], "departements": ["17"], "effectifs": ["11", "12"]}.
    Sans "departements", la recherche porte sur la France entière ; "exclure_departements" retire des sièges.
    On y gagne le nom de l'entreprise, sa commune et ses dirigeants ; pas de site ni d'adresse email."""
    r = fiche["cible"].get("registre") or {}
    if not (r.get("naf") or r.get("sections") or r.get("departements")):
        return 0
    exclus = set(r.get("exclure_departements") or [])
    suivi = etat.setdefault("registre", {})
    connus = {e.get("siren") for e in etat["entreprises"].values()}
    ajout = 0
    for dep in r.get("departements") or [""]:          # aucun département = France entière
        cle = f"{','.join(r.get('naf', []) + r.get('sections', []))}|{dep}|{','.join(r.get('effectifs', []))}"
        page = suivi.get(cle, 1)
        while page and ajout < limite:
            params = {"etat_administratif": "A", "page": page, "per_page": 25}
            if r.get("naf"):
                params["activite_principale"] = ",".join(r["naf"])
            if r.get("sections"):                       # lettres de section : F construction, H transport, I restauration...
                params["section_activite_principale"] = ",".join(r["sections"])
            if dep:
                params["departement"] = dep
            if r.get("effectifs"):
                params["tranche_effectif_salarie"] = ",".join(r["effectifs"])
            try:
                rep = http.get(REGISTRE, params=params, headers={"User-Agent": AGENT}, timeout=20)
                data = rep.json() if rep.status_code == 200 else None
            except Exception:
                data = None
            if not data:
                noter(etat, "erreur", f"registre des entreprises injoignable ({dep or 'France entière'})")
                break
            for e in data.get("results", []):
                siren = e.get("siren")
                # « O » = diffusion complète. Les entreprises en diffusion partielle ont demandé à ne pas être démarchées.
                if not siren or siren in connus or e.get("statut_diffusion", "O") != "O":
                    continue
                siege = e.get("siege") or {}
                cp = str(siege.get("code_postal") or "")
                if (siege.get("departement") or (cp[:3] if cp[:2] in ("97", "98") else cp[:2])) in exclus:
                    continue
                dirigeants = [{"prenom": (x.get("prenoms") or "").split(" ")[0].title(), "nom": (x.get("nom") or "").title(),
                               "qualite": x.get("qualite") or ""} for x in (e.get("dirigeants") or [])
                              if x.get("type_dirigeant") == "personne physique" and x.get("nom")][:3]
                etat["entreprises"]["siren:" + siren] = {
                    "nom": re.sub(r"\s*\(.*?\)", "", e.get("nom_complet") or "").title()[:120], "site": "", "siren": siren,
                    "ville": (siege.get("libelle_commune") or "").title(), "dirigeants": dirigeants,
                    "source": "registre public des entreprises", "statut": "sans_site"}
                connus.add(siren)
                ajout += 1
            page = page + 1 if page < min(data.get("total_pages", 1), 400) else 0
            suivi[cle] = page
            time.sleep(0.2)
    if ajout:
        noter(etat, "sourcing", f"{ajout} entreprise(s) relevée(s) au registre public")
    return ajout


def _mots(nom):
    vides = {"sarl", "sas", "sasu", "eurl", "societe", "transports", "transport", "groupe", "france", "services", "entreprise", "ets"}
    brut = re.sub(r"[^a-z0-9 ]", " ", _sans_accent(nom.lower())).split()
    return [m for m in brut if len(m) >= 4 and m not in vides]


def _sans_accent(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def trouver_sites(fiche, etat, sg, limite=10):
    """Cherche le site des entreprises venues du registre (6 crédits l'une : 3 résultats à 2 crédits).
    Un site n'est retenu que si le nom de l'entreprise se retrouve dans son adresse ou son titre."""
    if not sg:
        return 0
    trouves, vus, nouveau = 0, 0, {}
    for cle, ent in etat["entreprises"].items():
        if ent["statut"] != "sans_site" or vus >= limite or not sg.disponible(6):
            nouveau[cle] = ent
            continue
        vus += 1
        res = sg.chercher(f"{ent['nom']} {ent.get('ville', '')}".strip(), 3)
        if res is None:
            nouveau[cle] = ent
            continue
        mots, choisi = _mots(ent["nom"]), None
        for x in res:
            d = domaine(x["url"])
            colle = re.sub(r"[^a-z0-9]", "", d.rsplit(".", 1)[0])
            titre = _sans_accent((x.get("title") or "").lower())
            if _annuaire(d) or d in etat["entreprises"] or d in nouveau or not mots:
                continue
            if all(m in colle for m in mots) or all(m in titre for m in mots):
                choisi = (d, x["url"])
                break
        if choisi:
            p = urlparse(choisi[1])
            nouveau[choisi[0]] = {**ent, "site": f"{p.scheme}://{p.netloc}", "statut": "a_explorer"}
            trouves += 1
        else:
            nouveau[cle] = {**ent, "statut": "site_introuvable"}
    etat["entreprises"].clear()
    etat["entreprises"].update(nouveau)
    if vus:
        noter(etat, "sourcing", f"recherche de sites : {trouves} trouvé(s) sur {vus} entreprise(s)")
    return trouves


def recherches(fiche, etat, sg):
    """Requêtes libres de la fiche (cible.recherches), 10 résultats chacune (20 crédits). Chaque requête n'est
    lancée qu'une fois. Les annuaires sont écartés ; le tri « dans la cible ou non » se fait à la lecture du site."""
    if not sg:
        return 0
    faites, ajout = etat.setdefault("recherches_faites", {}), 0
    for q in fiche["cible"].get("recherches") or []:
        if q in faites or not sg.disponible(20):
            continue
        res = sg.chercher(q, 10)
        if res is None:
            continue
        for x in res:
            d = domaine(x["url"])
            if not d or _annuaire(d) or d in etat["entreprises"]:
                continue
            p = urlparse(x["url"])
            etat["entreprises"][d] = {"nom": (x.get("title") or d)[:120], "site": f"{p.scheme}://{p.netloc}",
                                      "source": f"recherche web : {q}", "statut": "a_explorer"}
            ajout += 1
        faites[q] = iso()
    if ajout:
        noter(etat, "sourcing", f"{ajout} site(s) trouvé(s) par recherche web")
    return ajout
