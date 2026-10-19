"""Cotes en direct via The Odds API (the-odds-api.com).

Récupère, pour chaque championnat, les cotes 1N2 et +/- 2,5 buts de Pinnacle
(prix de référence) et de vos bookmakers (Betclic, 1xBet), puis relie les noms
d'équipes de l'API à ceux de football-data.co.uk.

Coût : 1 crédit par championnat et par marché (2 marchés → 22 crédits pour 11 championnats).
"""
from __future__ import annotations

import csv
import datetime as dt
import difflib
import json
import re
import unicodedata
from pathlib import Path

import config

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "cotes_live.json"
MANUAL = ROOT / "correspondances.csv"
URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"

# Mots sans valeur pour reconnaître un club
_GENERIC = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "us", "rc", "cd", "ud", "sd", "fk", "sk", "bk", "if",
            "kv", "krc", "rsc", "kaa", "sv", "vfb", "vfl", "tsg", "fsv", "1", "05", "1899", "04", "de", "club",
            "calcio", "the", "and", "royal", "royale", "ssc", "acf", "ogc", "losc", "aj", "sco", "esm"}

# Noms de l'API (normalisés) → nom(s) possibles chez football-data
ALIASES = {
    "manchester united": ["Man United"], "manchester city": ["Man City"],
    "nottingham forest": ["Nott'm Forest", "Nottm Forest"], "wolverhampton wanderers": ["Wolves"],
    "wolverhampton": ["Wolves"], "tottenham hotspur": ["Tottenham"], "brighton hove albion": ["Brighton"],
    "atletico madrid": ["Ath Madrid"], "athletic bilbao": ["Ath Bilbao"], "athletic club": ["Ath Bilbao"],
    "real betis": ["Betis"], "real sociedad": ["Sociedad"], "celta vigo": ["Celta"], "rayo vallecano": ["Vallecano"],
    "espanyol": ["Espanol"], "deportivo alaves": ["Alaves"], "deportivo la coruna": ["La Coruna"],
    "racing santander": ["Santander"], "real oviedo": ["Oviedo"],
    "inter milan": ["Inter"], "internazionale": ["Inter"], "milan": ["Milan"], "hellas verona": ["Verona"],
    "borussia dortmund": ["Dortmund"], "borussia monchengladbach": ["M'gladbach", "MGladbach"],
    "eintracht frankfurt": ["Ein Frankfurt"], "bayer leverkusen": ["Leverkusen"], "koln": ["FC Koln"],
    "hamburger": ["Hamburg"], "mainz": ["Mainz"], "hoffenheim": ["Hoffenheim"],
    "paris saint germain": ["Paris SG"], "saint etienne": ["St Etienne"], "olympique lyonnais": ["Lyon"],
    "olympique marseille": ["Marseille"], "stade rennais": ["Rennes"], "stade brestois 29": ["Brest"],
    "stade brestois": ["Brest"], "stade reims": ["Reims"],
    "sporting lisbon": ["Sp Lisbon"], "sporting cp": ["Sp Lisbon"], "braga": ["Sp Braga"],
    "vitoria guimaraes": ["Guimaraes"], "vitoria": ["Guimaraes"],
    "fortuna sittard": ["For Sittard"], "nec nijmegen": ["Nijmegen"], "nec": ["Nijmegen"],
    "pec zwolle": ["Zwolle"], "rkc waalwijk": ["Waalwijk"], "heracles almelo": ["Heracles"],
    "ado den haag": ["Den Haag"], "union saint gilloise": ["St. Gilloise"], "union sg": ["St. Gilloise"],
    "sint truidense": ["St Truiden"], "sint truiden": ["St Truiden"], "standard liege": ["Standard"],
    "zulte waregem": ["Waregem"], "oh leuven": ["Oud-Heverlee Leuven"], "oud heverlee leuven": ["Oud-Heverlee Leuven"],
    "raal la louviere": ["RAAL La Louviere"], "la louviere": ["RAAL La Louviere"],
    "istanbul basaksehir": ["Buyuksehyr"], "basaksehir": ["Buyuksehyr"], "goztepe": ["Goztep"],
    "caykur rizespor": ["Rizespor"], "fatih karagumruk": ["Karagumruk"], "gaziantep": ["Gaziantep"],
    "adana demirspor": ["Ad. Demirspor"],
    "heart midlothian": ["Hearts"], "hearts": ["Hearts"],
    "rapid wien": ["SK Rapid", "Rapid Vienna"], "sk rapid": ["SK Rapid", "Rapid Vienna"], "rapid vienna": ["SK Rapid", "Rapid Vienna"],
    "austria wien": ["Austria Vienna"], "fk austria wien": ["Austria Vienna"], "red bull salzburg": ["Salzburg"], "rb salzburg": ["Salzburg"],
    "sturm graz": ["Sturm Graz"], "wolfsberger": ["Wolfsberger AC", "Wolfsberger"], "wolfsberger ac": ["Wolfsberger AC", "Wolfsberger"],
    "austria klagenfurt": ["A. Klagenfurt"], "blau weiss linz": ["BW Linz"], "grazer": ["Grazer AK"], "lask linz": ["LASK"],
    "copenhagen": ["FC Copenhagen"], "kobenhavn": ["FC Copenhagen"], "brondby": ["Brondby"], "agf": ["Aarhus"], "aarhus": ["Aarhus"],
    "aab": ["Aalborg"], "aalborg": ["Aalborg"], "ob": ["Odense"], "odense": ["Odense"], "fc nordsjaelland": ["Nordsjaelland"],
    "silkeborg": ["Silkeborg"], "randers": ["Randers FC", "Randers"], "viborg": ["Viborg"], "vejle": ["Vejle"], "sonderjyske": ["Sonderjyske"],
    "young boys": ["Young Boys"], "bsc young boys": ["Young Boys"], "fc zurich": ["Zurich"], "zurich": ["Zurich"], "st gallen": ["St. Gallen"],
    "lausanne sport": ["Lausanne"], "grasshopper": ["Grasshoppers"], "grasshopper zurich": ["Grasshoppers"], "grasshoppers zurich": ["Grasshoppers"],
    "kfum": ["KFUM Oslo", "KFUM"], "kfum oslo": ["KFUM Oslo", "KFUM"],
    "amed": ["Amedspor", "Amed"], "amedspor": ["Amedspor", "Amed"],
    "erzurum bb": ["Erzurumspor", "Erzurum"], "erzurumspor": ["Erzurumspor", "Erzurum"],
}

# Noms français et surnoms courants (saisie manuelle dans le journal)
ALIASES.update({
    "man utd": ["Man United"], "manchester utd": ["Man United"], "man u": ["Man United"], "spurs": ["Tottenham"],
    "forest": ["Nott'm Forest"], "nottingham": ["Nott'm Forest"], "villa": ["Aston Villa"], "palace": ["Crystal Palace"],
    "barcelone": ["Barcelona"], "barca": ["Barcelona"], "real": ["Real Madrid"], "seville": ["Sevilla"], "atletico": ["Ath Madrid"],
    "atletico de madrid": ["Ath Madrid"], "bilbao": ["Ath Bilbao"], "valence": ["Valencia"], "majorque": ["Mallorca"],
    "gerone": ["Girona"], "betis seville": ["Betis"], "la corogne": ["La Coruna"], "villareal": ["Villarreal"],
    "naples": ["Napoli"], "rome": ["Roma"], "as rome": ["Roma"], "juve": ["Juventus"], "inter milan": ["Inter"],
    "milan ac": ["Milan"], "lazio rome": ["Lazio"], "turin": ["Torino"], "genes": ["Genoa"], "venise": ["Venezia"], "verone": ["Verona"],
    "fribourg": ["Freiburg"], "cologne": ["FC Koln"], "koeln": ["FC Koln"], "gladbach": ["M'gladbach"], "monchengladbach": ["M'gladbach"],
    "moenchengladbach": ["M'gladbach"], "francfort": ["Ein Frankfurt"], "frankfurt": ["Ein Frankfurt"], "leipzig": ["RB Leipzig"],
    "bayern": ["Bayern Munich"], "bayern munchen": ["Bayern Munich"], "breme": ["Werder Bremen"], "werder breme": ["Werder Bremen"],
    "werder": ["Werder Bremen"], "augsbourg": ["Augsburg"], "hambourg": ["Hamburg"], "schalke": ["Schalke 04"], "sankt pauli": ["St Pauli"],
    "psg": ["Paris SG"], "paris saint germain": ["Paris SG"], "paris sg": ["Paris SG"], "om": ["Marseille"], "ol": ["Lyon"],
    "asse": ["St Etienne"], "saint etienne": ["St Etienne"], "rcl": ["Lens"], "rc lens": ["Lens"], "stade rennais": ["Rennes"],
    "rcsa": ["Strasbourg"], "havre": ["Le Havre"], "estac": ["Troyes"],
    "sporting": ["Sp Lisbon"], "sporting portugal": ["Sp Lisbon"], "fc porto": ["Porto"], "sc braga": ["Sp Braga"], "guimaraes": ["Guimaraes"],
    "psv": ["PSV Eindhoven"], "az": ["AZ Alkmaar"], "alkmaar": ["AZ Alkmaar"], "sittard": ["For Sittard"], "nimegue": ["Nijmegen"],
    "go ahead": ["Go Ahead Eagles"], "sparta": ["Sparta Rotterdam"], "breda": ["NAC Breda"],
    "bruges": ["Club Brugge"], "club bruges": ["Club Brugge"], "cercle bruges": ["Cercle Brugge"], "anvers": ["Antwerp"],
    "malines": ["Mechelen"], "gand": ["Gent"], "la gantoise": ["Gent"], "courtrai": ["Kortrijk"], "louvain": ["Oud-Heverlee Leuven"],
    "saint trond": ["St Truiden"], "union saint gilloise": ["St. Gilloise"], "usg": ["St. Gilloise"], "standard de liege": ["Standard"],
    "lommel": ["Lommel SK"], "basaksehir": ["Buyuksehyr"],
    "hearts": ["Hearts"], "hibs": ["Hibernian"], "dundee utd": ["Dundee United"],
    "bodo": ["Bodo/Glimt"], "bodo glimt": ["Bodo/Glimt"], "glimt": ["Bodo/Glimt"], "sarpsborg": ["Sarpsborg 08"], "tromso": ["Tromso"],
    "salzbourg": ["Salzburg"], "rapid vienne": ["SK Rapid"], "austria vienne": ["Austria Vienna"], "klagenfurt": ["A. Klagenfurt"],
    "linz": ["LASK"], "wolfsberg": ["Wolfsberger AC"], "lustenau": ["A. Lustenau"],
    "copenhague": ["FC Copenhagen"], "fc copenhague": ["FC Copenhagen"], "midtjylland": ["Midtjylland"], "nordsjaelland": ["Nordsjaelland"],
    "bale": ["Basel"], "fc bale": ["Basel"], "geneve": ["Servette"], "servette geneve": ["Servette"], "saint gall": ["St. Gallen"],
    "lucerne": ["Luzern"], "fc lucerne": ["Luzern"], "sion": ["Sion"], "thoune": ["Thun"], "grasshopper": ["Grasshoppers"],
})


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in _GENERIC]
    return " ".join(toks)


def _load_manual() -> dict[tuple[str, str], str]:
    out = {}
    if MANUAL.exists():
        with MANUAL.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row.get("ligue") and row.get("nom_api") and row.get("nom_outil"):
                    out[(row["ligue"].strip(), row["nom_api"].strip())] = row["nom_outil"].strip()
    return out


class TeamMatcher:
    """Relie un nom d'équipe de l'API au nom utilisé par football-data, dans un championnat donné."""

    def __init__(self, league: str, teams: list[str], manual: dict | None = None):
        self.league = league
        self.teams = sorted(set(teams))
        self.by_norm = {}
        for t in self.teams:
            self.by_norm.setdefault(norm(t), t)
        self.manual = manual or {}

    def match(self, api_name: str) -> str | None:
        if (self.league, api_name) in self.manual:
            return self.manual[(self.league, api_name)]
        n = norm(api_name)
        if n in self.by_norm:
            return self.by_norm[n]
        for cand in ALIASES.get(n, []):
            if cand in self.teams:
                return cand
        api_toks = n.split()
        scored = []
        for t in self.teams:
            tn = norm(t)
            ttoks = tn.split()
            if not ttoks:
                continue
            # chaque mot du nom football-data doit être le début d'un mot du nom API (« Man » → « Manchester »)
            used = [any(a.startswith(w) for a in api_toks) for w in ttoks]
            if all(used):
                cover = sum(any(a.startswith(w) for w in ttoks) for a in api_toks) / max(len(api_toks), 1)
                score = 0.6 + 0.4 * cover
            else:
                score = 0.9 * difflib.SequenceMatcher(None, n, tn).ratio()
            scored.append((score, t))
        scored.sort(reverse=True)
        if not scored:
            return None
        best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        if best[0] >= 0.62 and best[0] - second > 0.04:
            return best[1]
        return None


def _get(sport: str, markets: str):
    import requests
    params = {
        "apiKey": config.ODDS_API_KEY, "markets": markets, "oddsFormat": "decimal", "dateFormat": "iso",
        "bookmakers": ",".join([config.ODDS_REFERENCE, *config.ODDS_MES_BOOKMAKERS.keys()]),
    }
    return requests.get(URL.format(sport=sport), params=params, timeout=30)


def fetch(force: bool = False, verbose: bool = True) -> dict | None:
    """Télécharge les cotes (ou réutilise le cache récent). Renvoie {"fetched": ..., "events": {code: [...]}}."""
    if not config.ODDS_API_KEY.strip():
        return None
    if CACHE.exists() and not force:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        age_h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cached["fetched"])).total_seconds() / 3600
        if age_h < config.ODDS_REFRESH_HOURS:
            if verbose:
                print(f"   (cotes de il y a {age_h:.1f} h réutilisées ; relancer avec --cotes pour forcer)")
            return cached
    events, remaining = {}, None
    for code, sport in config.ODDS_SPORT_KEYS.items():
        if code not in config.LEAGUES:
            continue
        try:
            r = _get(sport, "h2h,totals")
            if r.status_code == 422:  # marché totals indisponible pour ce championnat
                r = _get(sport, "h2h")
        except Exception as e:
            print(f"   ! {config.LEAGUES[code]['nom']} : connexion impossible ({e})")
            continue
        if r.status_code == 401:
            msg = r.text[:200]
            print("   ! The Odds API refuse la clé : vérifiez ODDS_API_KEY dans config.py, ou vos crédits du mois.")
            print(f"     Réponse : {msg}")
            break
        if r.status_code == 429:
            print("   ! Trop de requêtes d'un coup ; réessayez dans une minute.")
            break
        if r.status_code != 200:
            print(f"   ! {config.LEAGUES[code]['nom']} : erreur {r.status_code} ({r.text[:120]})")
            continue
        remaining = r.headers.get("x-requests-remaining", remaining)
        events[code] = r.json()
        if verbose:
            print(f"   ✓ cotes {config.LEAGUES[code]['nom']} : {len(events[code])} matchs")
    if not events:
        return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else None
    out = {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(), "events": events, "credits_restants": remaining}
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    if verbose and remaining is not None:
        print(f"   Crédits The Odds API restants ce mois-ci : {remaining}")
    return out


def _book_odds(bm: dict, home: str, away: str) -> dict:
    o = {}
    for mk in bm.get("markets", []):
        if mk.get("key") == "h2h":
            for oc in mk.get("outcomes", []):
                if oc.get("name") == home:
                    o["h"] = oc.get("price")
                elif oc.get("name") == away:
                    o["a"] = oc.get("price")
                elif str(oc.get("name")).lower() == "draw":
                    o["d"] = oc.get("price")
        elif mk.get("key") == "totals":
            for oc in mk.get("outcomes", []):
                if abs(float(oc.get("point", 0)) - 2.5) < 1e-6:
                    if str(oc.get("name")).lower() == "over":
                        o["o25"] = oc.get("price")
                    elif str(oc.get("name")).lower() == "under":
                        o["u25"] = oc.get("price")
    return o


def _fair(odds: dict, keys: tuple) -> list | None:
    vals = [odds.get(k) for k in keys]
    if any(v is None or v <= 1 for v in vals):
        return None
    inv = [1 / v for v in vals]
    s = sum(inv)
    return [x / s for x in inv]


def to_fixtures(raw: dict, teams_by_league: dict[str, list[str]], verbose: bool = True) -> list[dict]:
    """Transforme la réponse de l'API en matchs pour le tableau de bord."""
    manual = _load_manual()
    fixtures, unmatched = [], []
    now = dt.datetime.now(dt.timezone.utc)
    for code, evs in raw.get("events", {}).items():
        matcher = TeamMatcher(code, teams_by_league.get(code, []), manual)
        for ev in evs:
            start = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            if start < now:
                continue  # match commencé : les cotes ne sont plus d'avant-match
            local = start.astimezone(dt.timezone(dt.timedelta(hours=config.FUSEAU_GMT)))
            h, a = matcher.match(ev["home_team"]), matcher.match(ev["away_team"])
            if h and h == a:  # deux équipes reconnues comme la même : correspondance douteuse
                h = a = None
            for api_n, got in ((ev["home_team"], h), (ev["away_team"], a)):
                if got is None:
                    unmatched.append((code, api_n))
            books = {bm["key"]: _book_odds(bm, ev["home_team"], ev["away_team"]) for bm in ev.get("bookmakers", [])}
            ref = books.get(config.ODDS_REFERENCE, {})
            f1 = _fair(ref, ("h", "d", "a"))
            f2 = _fair(ref, ("o25", "u25"))
            juste = None
            if f1:
                juste = {"h": f1[0], "d": f1[1], "a": f1[2]}
                if f2:
                    juste.update({"o25": f2[0], "u25": f2[1]})
            offres = {}
            for key, label in config.ODDS_MES_BOOKMAKERS.items():
                if books.get(key):
                    offres[label] = books[key]
            fixtures.append({
                "league": code, "date": local.strftime("%Y-%m-%d"), "heure": local.strftime("%H:%M"),
                "home": h or ev["home_team"], "away": a or ev["away_team"], "connu": bool(h and a),
                "juste": juste, "source_juste": "Pinnacle (en direct)" if juste else None,
                "cotes_ref": ref, "offres": offres,
                "maj": raw.get("fetched", ""),
            })
    if unmatched and verbose:
        seen = sorted(set(unmatched))
        print(f"   ! {len(seen)} nom(s) d'équipe non reconnu(s) : ajoutez-les dans correspondances.csv")
        for code, n in seen[:15]:
            print(f"     {code} ; {n}")
        _append_manual_template(seen)
    fixtures.sort(key=lambda f: (f["date"], f["heure"], f["league"]))
    return fixtures


def _append_manual_template(rows: list[tuple[str, str]]) -> None:
    """Ajoute les noms inconnus à correspondances.csv, colonne nom_outil à compléter."""
    existing = set()
    if MANUAL.exists():
        with MANUAL.open(encoding="utf-8-sig") as f:
            existing = {(r["ligue"], r["nom_api"]) for r in csv.DictReader(f, delimiter=";")}
    new = [r for r in rows if r not in existing]
    if not new:
        return
    write_header = not MANUAL.exists()
    with MANUAL.open("a", encoding="utf-8-sig" if write_header else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if write_header:
            w.writerow(["ligue", "nom_api", "nom_outil"])
        for code, n in new:
            w.writerow([code, n, ""])
