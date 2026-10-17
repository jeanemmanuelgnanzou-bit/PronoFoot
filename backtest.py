"""Backtest « walk-forward » : chaque semaine, on ré-entraîne le modèle avec les seuls
matchs déjà joués, puis on prédit les matchs de la semaine suivante. Aucune donnée
future n'est utilisée : c'est la seule façon honnête de mesurer un modèle de paris."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from models import Predictor


ODDS_COLS = [f"{p}_{s}" for p in ("odds", "pin", "avg", "close") for s in ("h", "d", "a", "o25", "u25")]


def fair_probs(r, keys=("h", "d", "a")) -> np.ndarray | None:
    """Probabilités « justes » du marché : cotes Pinnacle (sinon moyenne) sans la marge."""
    for src in ("pin", "avg"):
        o = np.array([r.get(f"{src}_{k}", np.nan) for k in keys], float)
        if np.isfinite(o).all() and (o > 1).all():
            p = 1 / o
            return p / p.sum()
    return None


def _kelly(p: float, odds: float) -> float:
    edge = p * odds - 1
    if edge <= 0:
        return 0.0
    return min(config.KELLY_FRACTION * edge / (odds - 1), config.MISE_MAX_PCT)


def run_league(df: pd.DataFrame, code: str, verbose: bool = True) -> pd.DataFrame:
    d = df[df["league"] == code]
    if len(d) < 400:
        return pd.DataFrame()
    end = d["date"].max()
    start = end - pd.Timedelta(days=365 * config.BACKTEST_SEASONS)
    rows = []
    t = start
    while t <= end:
        t_next = t + pd.Timedelta(days=config.REFIT_EVERY_DAYS)
        week = d[(d["date"] >= t) & (d["date"] < t_next)]
        if len(week):
            pred = Predictor(d, t)
            for _, m in week.iterrows():
                p = pred.predict(m["home"], m["away"])
                if p is None:
                    continue
                r = {"league": code, "date": m["date"], "home": m["home"], "away": m["away"],
                     "hg": m["hg"], "ag": m["ag"],
                     **{k: p[k] for k in ("p_h", "p_d", "p_a", "o25", "btts", "xg_h", "xg_a")}}
                for c in ODDS_COLS:
                    r[c] = m[c]
                for key, (ch, ca, _, lines) in config.COUNT_STATS.items():
                    if key in p and pd.notna(m[ch]) and pd.notna(m[ca]):
                        r[f"{key}_exp"] = p[key]["exp"]
                        r[f"{key}_act"] = m[ch] + m[ca]
                        for l in lines:
                            r[f"{key}_o{l}"] = p[key]["over"][str(l)]
                rows.append(r)
        t = t_next
    if verbose:
        print(f"   ✓ {config.LEAGUES[code]['nom']} : {len(rows)} matchs testés")
    return pd.DataFrame(rows)


def _calib(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 15:
            out.append({"pred": float(p[m].mean()), "obs": float(y[m].mean()), "n": int(m.sum())})
    return out


def _logloss(P: np.ndarray, Y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip((P * Y).sum(1), 1e-12, None))))


def _candidates(r, strategy: str):
    res = "H" if r.hg > r.ag else ("D" if r.hg == r.ag else "A")
    over = (r.hg + r.ag) > 2.5
    if strategy == "modele":
        p1x2 = [r.p_h, r.p_d, r.p_a]
        pou = [r.o25, 1 - r.o25]
    else:
        f = fair_probs(r)
        g = fair_probs(r, ("o25", "u25"))
        if f is None:
            return []
        p1x2 = list(f)
        pou = list(g) if g is not None else [np.nan, np.nan]
    return [
        ("1", p1x2[0], r.odds_h, r.close_h, res == "H"),
        ("N", p1x2[1], r.odds_d, r.close_d, res == "D"),
        ("2", p1x2[2], r.odds_a, r.close_a, res == "A"),
        ("+2.5", pou[0], r.odds_o25, r.close_o25, over),
        ("-2.5", pou[1], r.odds_u25, r.close_u25, not over),
    ]


def simulate_bets(bt: pd.DataFrame, strategy: str = "modele") -> dict | None:
    """Parie uniquement quand la value dépasse le seuil, au plus un pari par match.
    strategy="modele" : probabilités du modèle Dixon-Coles
    strategy="marche" : probabilités justes de Pinnacle (le pari est pris chez le bookmaker grand public)"""
    seuil = config.EDGE_MIN if strategy == "modele" else config.EDGE_MIN_MARCHE
    bets = []
    for _, r in bt.iterrows():
        best = None
        for name, p, o, c, won in _candidates(r, strategy):
            if pd.isna(p) or pd.isna(o) or o <= 1 or o > config.COTE_MAX:
                continue
            edge = p * o - 1
            if edge >= seuil and (best is None or edge > best[1]):
                best = (name, edge, p, o, c, won)
        if best:
            name, edge, p, o, c, won = best
            bets.append({"date": r.date, "league": r.league, "match": f"{r.home} - {r.away}",
                         "pari": name, "proba": p, "cote": o, "edge": edge, "gagne": bool(won),
                         "clv": (o / c - 1) if pd.notna(c) and c > 1 else np.nan})
    if len(bets) < 20:
        return None
    b = pd.DataFrame(bets).sort_values("date")
    b["profit_plat"] = np.where(b["gagne"], b["cote"] - 1, -1.0)
    bank, curve = 1.0, []
    for _, r in b.iterrows():
        stake = bank * _kelly(r.proba, r.cote)
        bank += stake * (r.cote - 1) if r.gagne else -stake
        curve.append(bank)
    b["bankroll_kelly"] = curve
    roll_max = np.maximum.accumulate(np.r_[1.0, curve])[1:]
    roi = b["profit_plat"].mean()
    se = b["profit_plat"].std() / np.sqrt(len(b))
    step = max(1, len(b) // 300)
    return {
        "n": int(len(b)),
        "reussite": float(b["gagne"].mean()),
        "cote_moy": float(b["cote"].mean()),
        "roi_plat": float(roi),
        "roi_ic95": [float(roi - 1.96 * se), float(roi + 1.96 * se)],
        "profit_plat": float(b["profit_plat"].sum()),
        "kelly_final": float(curve[-1]),
        "drawdown_max": float((1 - b["bankroll_kelly"].to_numpy() / roll_max).max()),
        "clv_moy": float(b["clv"].mean()) if b["clv"].notna().sum() > 20 else None,
        "courbe": [{"d": r.date.strftime("%Y-%m-%d"), "plat": float(cp), "kelly": float(r.bankroll_kelly)}
                   for i, ((_, r), cp) in enumerate(zip(b.iterrows(), b["profit_plat"].cumsum()))
                   if i % step == 0 or i == len(b) - 1],
        "par_marche": b.groupby("pari").agg(n=("gagne", "size"), reussite=("gagne", "mean"),
                                            roi=("profit_plat", "mean")).reset_index().to_dict("records"),
    }


def summarize(bt: pd.DataFrame) -> dict:
    if bt.empty:
        return {}
    res = np.where(bt.hg > bt.ag, 0, np.where(bt.hg == bt.ag, 1, 2))
    Y = np.eye(3)[res]
    P = bt[["p_h", "p_d", "p_a"]].to_numpy()
    freq = Y.mean(0)
    out = {
        "n": int(len(bt)),
        "periode": [bt.date.min().strftime("%Y-%m-%d"), bt.date.max().strftime("%Y-%m-%d")],
        "logloss_modele": _logloss(P, Y),
        "logloss_naif": _logloss(np.tile(freq, (len(bt), 1)), Y),
        "precision_1x2": float((P.argmax(1) == res).mean()),
        "calib_1x2": _calib(P.ravel(), Y.ravel()),
    }
    F = np.array([fair if (fair := fair_probs(r)) is not None else [np.nan] * 3 for _, r in bt.iterrows()])
    ok = np.isfinite(F).all(1)
    if ok.sum() < 100:  # pas de Pinnacle : on retire la marge des cotes grand public
        odds = bt[["odds_h", "odds_d", "odds_a"]].to_numpy(float)
        ok = np.isfinite(odds).all(1) & (odds > 1).all(1)
        F = 1 / np.where(ok[:, None], odds, 2.0)
        F /= F.sum(1, keepdims=True)
        out["marche_source"] = "Bet365 (marge retirée)"
    else:
        out["marche_source"] = "Pinnacle (marge retirée)"
    if ok.sum() > 100:
        out["logloss_marche"] = _logloss(F[ok], Y[ok])
        out["logloss_modele_meme_echantillon"] = _logloss(P[ok], Y[ok])
        out["precision_marche"] = float((F[ok].argmax(1) == res[ok]).mean())
    over = ((bt.hg + bt.ag) > 2.5).to_numpy(float)
    btts = ((bt.hg > 0) & (bt.ag > 0)).to_numpy(float)
    out["o25"] = {"precision": float(((bt.o25 > .5) == over).mean()), "calib": _calib(bt.o25.to_numpy(), over),
                  "brier": float(np.mean((bt.o25 - over) ** 2)), "brier_naif": float(np.mean((over.mean() - over) ** 2))}
    out["btts"] = {"precision": float(((bt.btts > .5) == btts).mean()), "calib": _calib(bt.btts.to_numpy(), btts),
                   "brier": float(np.mean((bt.btts - btts) ** 2)), "brier_naif": float(np.mean((btts.mean() - btts) ** 2))}
    counts = {}
    for key, (_, _, label, lines) in config.COUNT_STATS.items():
        c = bt.dropna(subset=[f"{key}_exp", f"{key}_act"]) if f"{key}_exp" in bt else pd.DataFrame()
        if len(c) < 100:
            continue
        act = c[f"{key}_act"].to_numpy()
        ps, ys = [], []
        for l in lines:
            ps.append(c[f"{key}_o{l}"].to_numpy())
            ys.append((act > l).astype(float))
        ps, ys = np.concatenate(ps), np.concatenate(ys)
        counts[key] = {"label": label,
                       "mae": float(np.mean(np.abs(c[f"{key}_exp"] - act))),
                       "mae_naif": float(np.mean(np.abs(act.mean() - act))),
                       "brier": float(np.mean((ps - ys) ** 2)),
                       "calib": _calib(ps, ys)}
    out["stats"] = counts
    out["paris"] = {}
    for strat in ("modele", "marche"):
        sim = simulate_bets(bt, strat)
        if sim:
            out["paris"][strat] = sim
    return out


def run(df: pd.DataFrame, verbose: bool = True) -> dict:
    results, allbt = {}, []
    for code in config.LEAGUES:
        bt = run_league(df, code, verbose)
        if bt.empty:
            continue
        allbt.append(bt)
        results[code] = summarize(bt)
    if allbt:
        results["_global"] = summarize(pd.concat(allbt).sort_values("date"))
    return results


# ---------------------------------------------------------------------------
# Backtest de la stratégie retenue : cote grand public vs prix juste Pinnacle
# ---------------------------------------------------------------------------
GRILLE_PROBA = [0.35, 0.40, 0.45, 0.50, 0.55]
GRILLE_EDGE = [0.02, 0.03, 0.05]


def _candidates_table(df: pd.DataFrame, soft: str = "odds") -> pd.DataFrame:
    """Une ligne par (match, pari) : probabilité juste Pinnacle, cote grand public, cote de clôture, résultat."""
    d = df.copy()
    res_h, res_d = d.hg > d.ag, d.hg == d.ag
    over = (d.hg + d.ag) > 2.5
    rows = []

    def fair(cols):
        o = d[cols].to_numpy(float)
        ok = np.isfinite(o).all(1) & (o > 1).all(1)
        inv = np.where(ok[:, None], 1 / np.where(o > 1, o, 2.0), np.nan)
        return inv / inv.sum(1, keepdims=True), ok

    src = "Pinnacle"
    f1, ok1 = fair(["pin_h", "pin_d", "pin_a"])
    if ok1.mean() < 0.3:  # pas de Pinnacle dans les données : moyenne du marché
        f1, ok1 = fair(["avg_h", "avg_d", "avg_a"])
        src = "moyenne du marché"
    f2, ok2 = fair(["pin_o25", "pin_u25"])
    if ok2.mean() < 0.3:
        f2, ok2 = fair(["avg_o25", "avg_u25"])
    for i, (k, won) in enumerate((("h", res_h), ("d", res_d), ("a", ~res_h & ~res_d))):
        rows.append(pd.DataFrame({"idx": d.index, "league": d.league, "date": d.date, "mk": k, "p": f1[:, i],
                                  "odds": d[f"{soft}_{k}"], "close": d[f"close_{k}"], "won": won.to_numpy()})[ok1])
    for i, (k, won) in enumerate((("o25", over), ("u25", ~over))):
        rows.append(pd.DataFrame({"idx": d.index, "league": d.league, "date": d.date, "mk": k, "p": f2[:, i],
                                  "odds": d[f"{soft}_{k}"], "close": d[f"close_{k}"], "won": won.to_numpy()})[ok2])
    c = pd.concat(rows, ignore_index=True)
    c = c[np.isfinite(c.odds) & (c.odds > 1) & (c.odds <= config.COTE_MAX)]
    c["edge"] = c.p * c.odds - 1
    c = c[c.edge <= 0.15]  # écarts aberrants = erreurs de données
    c.attrs["source"] = src
    return c


def _select(c: pd.DataFrame, pmin: float, emin: float) -> pd.DataFrame:
    s = c[(c.p >= pmin) & (c.edge >= emin)]
    if s.empty:
        return s
    s = s.sort_values("edge", ascending=False).drop_duplicates("idx").sort_values("date")
    s = s.assign(profit=np.where(s.won, s.odds - 1, -1.0),
                 clv=np.where(np.isfinite(s.close) & (s.close > 1), s.odds / s.close - 1, np.nan))
    return s


def _stats(s: pd.DataFrame) -> dict:
    n = len(s)
    if n == 0:
        return {"n": 0}
    roi = s.profit.mean()
    se = s.profit.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {"n": int(n), "reussite": float(s.won.mean()), "cote_moy": float(s.odds.mean()), "roi": float(roi),
            "ic": [float(roi - 1.96 * se), float(roi + 1.96 * se)] if n > 1 else None,
            "clv": float(s.clv.mean()) if s.clv.notna().sum() >= 10 else None}


def strategy_backtest(df: pd.DataFrame, ref: pd.Timestamp | None = None, verbose: bool = True) -> dict:
    """Rejoue la stratégie (value ≥ EDGE_MIN_MARCHE face à Pinnacle, chances ≥ PROBA_MIN) sur les saisons passées,
    selon deux hypothèses de cotes disponibles : prudente (Bet365) et haute (meilleure cote du marché)."""
    ref = ref or df.date.max()
    d = df[(df.date >= ref - pd.Timedelta(days=365 * config.BACKTEST_SEASONS)) & (df.date < ref)]
    if d.empty:
        return {}
    out = {}
    for key, soft, label in (("prudent", "odds", "Bet365"), ("haut", "max", "meilleure cote du marché")):
        if d[[f"{soft}_h", f"{soft}_d", f"{soft}_a"]].notna().all(1).mean() < 0.3:
            continue
        r = _scenario(d, soft, verbose and False)
        if r:
            r["bookmaker"] = label
            out[key] = r
            if verbose:
                roi = r.get("roi")
                print(f"   Stratégie, hypothèse {label} : {r['n']} paris sur 2 saisons" + (f", ROI {roi:+.1%}" if roi is not None else ""))
    return out


def _scenario(d: pd.DataFrame, soft: str, verbose: bool) -> dict:
    c = _candidates_table(d, soft)
    pmin, emin = config.PROBA_MIN, config.EDGE_MIN_MARCHE
    s = _select(c, pmin, emin)
    weeks = max((d.date.max() - d.date.min()).days / 7, 1)
    out = {"params": {"pmin": pmin, "edge": emin}, "source_ref": c.attrs.get("source"),
           "periode": [d.date.min().strftime("%Y-%m-%d"), d.date.max().strftime("%Y-%m-%d")],
           "matchs": int(d.index.nunique()), **_stats(s)}
    out["par_semaine"] = out["n"] / weeks
    if len(s):
        bank, peak, dd, curve = 1.0, 1.0, 0.0, []
        for _, r in s.iterrows():
            stake = bank * _kelly(r.p, r.odds)
            bank += stake * (r.odds - 1) if r.won else -stake
            peak, dd = max(peak, bank), max(dd, 1 - bank / max(peak, bank))
            curve.append(bank)
        step = max(1, len(s) // 300)
        cum = s.profit.cumsum().to_numpy()
        out["kelly_final"], out["drawdown"] = float(bank), float(dd)
        out["courbe"] = [{"d": dte.strftime("%Y-%m-%d"), "plat": float(cp)}
                         for i, (dte, cp) in enumerate(zip(s.date, cum)) if i % step == 0 or i == len(s) - 1]
        lab = {"h": "1", "d": "N", "a": "2", "o25": "+2,5 buts", "u25": "-2,5 buts"}
        out["par_marche"] = [{"pari": lab[k], **_stats(g)} for k, g in s.groupby("mk")]
        out["par_ligue"] = {lg: _stats(g) for lg, g in s.groupby("league")}
    out["grille"] = [{"pmin": p, "edge": e, **_stats(_select(c, p, e))} for p in GRILLE_PROBA for e in GRILLE_EDGE]
    if verbose:
        r = out.get("roi")
        print(f"   Stratégie ({pmin:.0%} de chances, value ≥ {emin:.0%}) : {out['n']} paris sur 2 saisons"
              + (f", ROI {r:+.1%}" if r is not None else ""))
    return out
