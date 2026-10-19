"""PronoFoot — lance tout : données → modèles → backtest → tableau de bord.

    python main.py                 mise à jour complète (backtest refait s'il date de plus de 7 jours)
    python main.py --hors-ligne    sans téléchargement (utilise les données déjà en cache)
    python main.py --backtest      force un nouveau backtest
    python main.py --cotes         force le re-téléchargement des cotes en direct (The Odds API)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

import backtest
import config
import data
import oddsapi
from models import Predictor

ROOT = Path(__file__).parent
BT_FILE = ROOT / "data" / "backtest.json"
OUT_HTML = ROOT / "PronoFoot.html"


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def league_table(d: pd.DataFrame) -> tuple[list[dict], str]:
    """Classement de la saison en cours et forme récente."""
    last = d["date"].max()
    season = d.loc[d["date"] == last, "season"].iloc[0]
    s = d[d["season"] == season]
    rows = {}
    for _, m in s.sort_values("date").iterrows():
        for team, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
            t = rows.setdefault(team, {"equipe": team, "j": 0, "pts": 0, "bp": 0, "bc": 0, "forme": []})
            t["j"] += 1
            t["bp"] += int(gf)
            t["bc"] += int(ga)
            res = "V" if gf > ga else ("N" if gf == ga else "D")
            t["pts"] += {"V": 3, "N": 1, "D": 0}[res]
            t["forme"].append(res)
    table = sorted(rows.values(), key=lambda t: (-t["pts"], -(t["bp"] - t["bc"]), -t["bp"]))
    for t in table:
        t["forme"] = "".join(t["forme"][-5:])
    return table, str(season)


def export_league(code: str, d: pd.DataFrame, today: pd.Timestamp) -> dict | None:
    pred = Predictor(d, today)
    g = pred.goals
    if not g.fitted:
        return None
    table, season = league_table(d)
    current = {t["equipe"] for t in table}
    teams = sorted(current | {t for t in g.teams if g.n_eff.get(t, 0) > 8 and t in set(d[d["date"] > today - pd.Timedelta(days=400)]["home"])})
    out = {
        "nom": config.LEAGUES[code]["nom"], "pays": config.LEAGUES[code]["pays"],
        "saison": season, "derniere_journee": d["date"].max().strftime("%Y-%m-%d"),
        "mu": _r(g.mu), "home": _r(g.home), "rho": _r(pred.rho),
        "prior": [_r(g.prior_att), _r(g.prior_dfn)],
        "teams": {t: [_r(v) for v in g.team(t)] + [_r(g.n_eff.get(t, 0), 1)] for t in teams},
        "en_cours": sorted(current),
        "counts": {},
        "classement": table,
    }
    for key, m in pred.counts.items():
        out["counts"][key] = {"mu": _r(m.mu), "home": _r(m.home), "disp": _r(m.disp, 2),
                              "prior": [_r(m.prior_att), _r(m.prior_dfn)],
                              "teams": {t: [_r(v) for v in m.team(t)] for t in teams}}
    return out


def _uk_to_local(day: pd.Timestamp, hhmm: str) -> tuple[str, str]:
    """football-data publie les heures à l'heure de Londres (GMT l'hiver, GMT+1 l'été) : conversion vers FUSEAU_GMT."""
    try:
        h, mnt = (int(x) for x in str(hhmm)[:5].split(":"))
    except Exception:
        return day.strftime("%Y-%m-%d"), ""
    def last_sunday(year, month):
        d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    y = day.year
    naive = dt.datetime(day.year, day.month, day.day, h, mnt)
    bst = dt.datetime.combine(last_sunday(y, 3), dt.time(1)) <= naive < dt.datetime.combine(last_sunday(y, 10), dt.time(1))
    local = naive - dt.timedelta(hours=1 if bst else 0) + dt.timedelta(hours=config.FUSEAU_GMT)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def export_fixtures(fx: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in fx.iterrows():
        jour, heure = _uk_to_local(r.date, r.get("time", ""))
        fair = backtest.fair_probs(r)
        fou = backtest.fair_probs(r, ("o25", "u25"))
        src = "Pinnacle" if pd.notna(r.get("pin_h")) else "Moyenne du marché"
        out.append({
            "league": r.league, "date": jour, "heure": heure,
            "home": r.home, "away": r.away,
            "cotes_ref": {k: _r(r.get(f"odds_{k}"), 2) for k in ("h", "d", "a", "o25", "u25")},
            "juste": None if fair is None else {"h": _r(fair[0]), "d": _r(fair[1]), "a": _r(fair[2]),
                                                 **({} if fou is None else {"o25": _r(fou[0]), "u25": _r(fou[1])})},
            "source_juste": src,
        })
    return out


def merge_fixtures(fd: list[dict], live: list[dict]) -> list[dict]:
    """Les cotes en direct remplacent celles de football-data pour un même match."""
    seen = {(f["league"], f["home"], f["away"]) for f in live}
    out = live + [f for f in fd if (f["league"], f["home"], f["away"]) not in seen]
    return sorted(out, key=lambda f: (f["date"], f.get("heure") or "", f["league"]))


def count_bets(fixtures: list[dict]) -> int:
    """Nombre de lignes « PARIER » : votre meilleure cote dépasse le prix juste Pinnacle du seuil fixé."""
    n = 0
    for f in fixtures:
        j = f.get("juste") or {}
        for k, p in j.items():
            best = max([o.get(k) or 0 for o in (f.get("offres") or {}).values()] or [0])
            if best and best <= config.COTE_MAX and p * best - 1 >= config.EDGE_MIN_MARCHE and p >= config.PROBA_MIN:
                n += 1
    return n


def closing_odds(df: pd.DataFrame, ref: pd.Timestamp) -> dict:
    """Cotes de clôture des matchs récents, pour calculer la CLV des paris du journal."""
    d = df[df["date"] >= ref - pd.Timedelta(days=90)]
    out = {}
    for _, r in d.iterrows():
        c = {k: _r(r.get(f"close_{k}"), 3) for k in ("h", "d", "a", "o25", "u25")}
        if any(v for v in c.values()):
            out[f"{r.league}|{r.home}|{r.away}"] = {"date": r.date.strftime("%Y-%m-%d"), **c}
    return out


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 5)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (pd.Timestamp, dt.date)):
        return o.strftime("%Y-%m-%d")
    return o


def build(offline: bool = False, force_bt: bool = False, open_browser: bool = True, today: str | None = None,
          demo: str | None = None, out: Path = OUT_HTML, force_odds: bool = False, live_raw: dict | None = None) -> Path:
    print("⚽ PronoFoot")
    if not offline:
        print("1/4 Téléchargement des données football-data.co.uk…")
        data.download_all()
    df = data.load_matches()
    if df.empty:
        raise SystemExit("Aucune donnée. Vérifiez la connexion internet puis relancez.")
    ref = pd.Timestamp(today) if today else pd.Timestamp(dt.date.today())
    print(f"   {len(df):,} matchs en base, du {df.date.min():%d/%m/%Y} au {df.date.max():%d/%m/%Y}".replace(",", " "))

    print("2/4 Backtest (prédictions sur les 2 dernières saisons, sans tricher)…")
    bt = None
    if BT_FILE.exists() and not force_bt:
        age = (dt.datetime.now() - dt.datetime.fromtimestamp(BT_FILE.stat().st_mtime)).days
        if age < 7:
            bt = json.loads(BT_FILE.read_text(encoding="utf-8"))
            print("   (backtest récent réutilisé)")
    if bt is None:
        bt = clean(backtest.run(df))
        BT_FILE.write_text(json.dumps(bt, ensure_ascii=False), encoding="utf-8")

    strategie = clean(backtest.strategy_backtest(df, ref))

    print("3/4 Ajustement des modèles à aujourd'hui…")
    leagues = {}
    for code in config.LEAGUES:
        d = df[df["league"] == code]
        if len(d) < 300:
            continue
        lg = export_league(code, d, ref)
        if lg:
            lg["fiabilite"] = {k: bt.get(code, {}).get(k) for k in
                               ("n", "logloss_modele", "logloss_marche", "logloss_naif", "precision_1x2", "precision_marche")}
            lg["fiabilite"]["stats"] = {k: {kk: v[kk] for kk in ("mae", "mae_naif")}
                                        for k, v in bt.get(code, {}).get("stats", {}).items()}
            leagues[code] = lg
            print(f"   ✓ {lg['nom']}")

    fx = data.load_fixtures()
    fixtures = [f for f in export_fixtures(fx) if f["league"] in leagues] if not fx.empty else []
    if fx.empty:
        print("   ! " + data.fixtures_diagnostic())
    else:
        print(f"   {len(fx)} matchs dans le calendrier football-data, du {fx.date.min():%d/%m} au {fx.date.max():%d/%m} ;"
              f" {len(fixtures)} dans vos championnats")

    cotes_live = None
    if config.ODDS_API_KEY.strip() or live_raw:
        print("   Cotes en direct (The Odds API)…")
        raw = live_raw if live_raw is not None else (None if offline else oddsapi.fetch(force=force_odds))
        if raw is None and oddsapi.CACHE.exists():
            raw = json.loads(oddsapi.CACHE.read_text(encoding="utf-8"))
        if raw:
            recent = df[df["date"] > ref - pd.Timedelta(days=400)]
            teams = {c: sorted(set(g["home"]) | set(g["away"])) for c, g in recent.groupby("league")}
            live = [f for f in oddsapi.to_fixtures(raw, teams) if f["league"] in leagues]
            fixtures = merge_fixtures(fixtures, live)
            cotes_live = {"maj": raw.get("fetched"), "credits": raw.get("credits_restants"), "n": len(live)}
            print(f"   {len(live)} matchs avec cotes en direct")
    else:
        print(f"   ! Cotes en direct désactivées : fichier cle_api introuvable ou vide dans {ROOT.resolve()}")
        print("     Créez-y un fichier texte nommé cle_api contenant uniquement votre clé, à côté de LANCER.bat.")
    nb = count_bets(fixtures)
    print(f"   ➜ {nb} pari(s) recommandé(s) avec au moins {config.PROBA_MIN:.0%} de chances" if nb
          else "   ➜ aucun pari recommandé pour l'instant (au seuil de chances choisi)")

    payload = clean({
        "genere_le": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "donnees_jusquau": df.date.max().strftime("%Y-%m-%d"),
        "config": {"bankroll": config.BANKROLL_DEFAUT, "kelly": config.KELLY_FRACTION, "mise_max": config.MISE_MAX_PCT,
                   "edge_min": config.EDGE_MIN, "edge_min_marche": config.EDGE_MIN_MARCHE, "cote_max": config.COTE_MAX, "proba_min": config.PROBA_MIN, "mise_fixe": config.MISE_FIXE_PCT, "books_defaut": config.BOOKMAKERS_PAR_DEFAUT, "fuseau": config.FUSEAU_GMT,
                   "stats": {k: {"label": v[2], "lignes": v[3]} for k, v in config.COUNT_STATS.items()}},
        "ligues": leagues,
        "matchs": fixtures,
        "cotes_live": cotes_live,
        "clotures": closing_odds(df, ref),
        "alias": oddsapi.ALIASES,               # pour reconnaître le championnat d'un pari saisi à la main
        "generiques": sorted(oddsapi._GENERIC),
        "backtest": bt,
        "strategie": strategie,
        "demo": demo,
    })
    print("4/4 Création du tableau de bord…")
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    out.write_text('<!doctype html>\n<html lang="fr">\n' + html + "\n</html>\n", encoding="utf-8")
    print(f"✅ Terminé : {out}")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hors-ligne", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--pas-de-navigateur", action="store_true")
    ap.add_argument("--cotes", action="store_true", help="force le re-téléchargement des cotes en direct")
    ap.add_argument("--date", help="date de référence AAAA-MM-JJ (tests)")
    a = ap.parse_args()
    build(offline=a.hors_ligne, force_bt=a.backtest, open_browser=not a.pas_de_navigateur, today=a.date,
          force_odds=a.cotes)
