from pathlib import Path
import json, shutil

root=Path(__file__).resolve().parents[1]
out=root/"site-dist"
if out.exists(): shutil.rmtree(out)
out.mkdir(parents=True)

tpl=(root/"moteur"/"gabarit_espace.html").read_text(encoding="utf-8")
param_tpl=(root/"site"/"parametres.html").read_text(encoding="utf-8")
spaces=root/"espaces"
data_dir=out/"data"
data_dir.mkdir(parents=True,exist_ok=True)
for p in spaces.glob("*.json"):
    if p.name=="_index.json":
        shutil.copy2(p,data_dir/"index.json")
        continue
    d=json.loads(p.read_text(encoding="utf-8"))
    (data_dir/p.name).write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
    payload=json.dumps(d,ensure_ascii=False).replace("</","<\\/")
    html=tpl.replace("/*DONNEES*/null",payload)
    target=out/"e"/p.stem
    target.mkdir(parents=True,exist_ok=True)
    (target/"index.html").write_text(html,encoding="utf-8")
    pdir=target/"parametres"
    pdir.mkdir(parents=True,exist_ok=True)
    (pdir/"index.html").write_text(param_tpl,encoding="utf-8")

# page d'accueil simple
(out/"index.html").write_text("""<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='robots' content='noindex,nofollow'><title>IRIS Cold Emailing</title><body style='font-family:Arial;padding:40px'><h1>IRIS Cold Emailing</h1><p>Utilisez votre lien client privé.</p></body></html>""",encoding="utf-8")
print("built",out)
