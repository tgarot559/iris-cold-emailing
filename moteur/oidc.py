"""Authentification sans secret du moteur GitHub Actions auprès du backend IRIS."""
import os
import requests

AUDIENCE="iris-cold-emailing-engine"

def token():
    url=(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL") or "").strip()
    bearer=(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN") or "").strip()
    if not url or not bearer:
        return ""
    sep="&" if "?" in url else "?"
    try:
        r=requests.get(url+sep+"audience="+AUDIENCE,
                       headers={"Authorization":"Bearer "+bearer},timeout=20)
        if r.status_code!=200:
            return ""
        return str((r.json() or {}).get("value") or "")
    except Exception:
        return ""

def headers():
    t=token()
    return {"Authorization":"Bearer "+t,"Content-Type":"application/json"} if t else {}
