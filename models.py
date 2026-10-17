"""Modèles de prédiction.

1. Buts : Dixon-Coles (1997). Chaque équipe a une force offensive et une faiblesse
   défensive ; on ajoute l'avantage du terrain et une correction des petits scores
   (0-0, 1-0, 0-1, 1-1). Les matchs récents pèsent plus que les anciens.
2. Corners, fautes, tirs, cartons : même structure (attaque/défense par équipe),
   puis loi binomiale négative pour les totaux, car ces stats varient plus que
   ce que prévoit une loi de Poisson.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import nbinom, poisson

import config

MAX_GOALS = 10
PRIOR_K = 6.0  # nb de matchs « équivalents » pour faire confiance aux notes d'une équipe


class RatingModel:
    """Notes attaque/défense par équipe, ajustées par maximum de vraisemblance pondérée (Poisson)."""

    def __init__(self, ridge: float = config.RIDGE, half_life: float = config.HALF_LIFE_DAYS):
        self.ridge = ridge
        self.xi = np.log(2) / half_life
        self.fitted = False

    def fit(self, df: pd.DataFrame, col_h: str, col_a: str, ref_date: pd.Timestamp) -> "RatingModel":
        d = df.dropna(subset=[col_h, col_a])
        d = d[(d["date"] < ref_date) & (d["date"] >= ref_date - pd.Timedelta(days=config.TRAIN_WINDOW_DAYS))]
        if len(d) < 60:
            return self
        teams = sorted(set(d["home"]) | set(d["away"]))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = d["home"].map(idx).to_numpy()
        ai = d["away"].map(idx).to_numpy()
        yh = d[col_h].to_numpy(float)
        ya = d[col_a].to_numpy(float)
        age = (ref_date - d["date"]).dt.days.to_numpy(float)
        w = np.exp(-self.xi * age)
        r = self.ridge

        def nll(theta):
            mu, h = theta[0], theta[1]
            att, dfn = theta[2:2 + n], theta[2 + n:]
            llh = mu + h + att[hi] + dfn[ai]
            lla = mu + att[ai] + dfn[hi]
            lh, la = np.exp(llh), np.exp(lla)
            f = np.sum(w * (lh - yh * llh)) + np.sum(w * (la - ya * lla)) + r * (att @ att + dfn @ dfn)
            gh, ga = w * (lh - yh), w * (la - ya)
            g = np.empty_like(theta)
            g[0] = gh.sum() + ga.sum()
            g[1] = gh.sum()
            g[2:2 + n] = np.bincount(hi, gh, n) + np.bincount(ai, ga, n) + 2 * r * att
            g[2 + n:] = np.bincount(ai, gh, n) + np.bincount(hi, ga, n) + 2 * r * dfn
            return f, g

        x0 = np.zeros(2 + 2 * n)
        x0[0] = np.log(max(np.average(np.r_[yh, ya], weights=np.r_[w, w]), 0.1))
        res = minimize(nll, x0, jac=True, method="L-BFGS-B")
        th = res.x
        self.teams = teams
        self.mu, self.home = float(th[0]), float(th[1])
        self.att = dict(zip(teams, th[2:2 + n]))
        self.dfn = dict(zip(teams, th[2 + n:]))
        # Poids effectif de chaque équipe (pour savoir si on peut se fier à ses notes)
        self.n_eff = {t: float(np.bincount(hi, w, n)[i] + np.bincount(ai, w, n)[i]) for t, i in idx.items()}
        # Profil « promu / inconnu » : moyenne des 3 équipes les plus faibles bien observées
        est = [t for t in teams if self.n_eff[t] >= 15] or teams
        weak = sorted(est, key=lambda t: self.att[t] - self.dfn[t])[:3]
        self.prior_att = float(np.mean([self.att[t] for t in weak]))
        self.prior_dfn = float(np.mean([self.dfn[t] for t in weak]))
        # Dispersion (binomiale négative) des totaux
        lh = np.exp(self.mu + self.home + th[2:2 + n][hi] + th[2 + n:][ai])
        la = np.exp(self.mu + th[2:2 + n][ai] + th[2 + n:][hi])
        m, y = lh + la, yh + ya
        excess = np.sum(w * ((y - m) ** 2 - m))
        self.disp = float(np.sum(w * m ** 2) / excess) if excess > 0 else 0.0  # 0 = Poisson
        self.fitted = True
        self.ref_date = ref_date
        return self

    def team(self, t: str) -> tuple[float, float]:
        """Notes (attaque, défense) avec rétrécissement vers le profil « promu » si peu de données."""
        n = self.n_eff.get(t, 0.0)
        a = self.att.get(t, self.prior_att)
        d = self.dfn.get(t, self.prior_dfn)
        k = PRIOR_K
        return (n * a + k * self.prior_att) / (n + k), (n * d + k * self.prior_dfn) / (n + k)

    def rates(self, home: str, away: str) -> tuple[float, float]:
        ah, dh = self.team(home)
        aa, da = self.team(away)
        return float(np.exp(self.mu + self.home + ah + da)), float(np.exp(self.mu + aa + dh))


def fit_rho(df: pd.DataFrame, m: RatingModel, ref_date: pd.Timestamp) -> float:
    """Paramètre de corrélation des petits scores (Dixon-Coles)."""
    d = df[(df["date"] < ref_date) & (df["date"] >= ref_date - pd.Timedelta(days=config.TRAIN_WINDOW_DAYS))]
    d = d[(d["hg"] <= 1) & (d["ag"] <= 1)]
    if len(d) < 30:
        return 0.0
    rates = np.array([m.rates(h, a) for h, a in zip(d["home"], d["away"])])
    lh, la = rates[:, 0], rates[:, 1]
    x, y = d["hg"].to_numpy(), d["ag"].to_numpy()
    w = np.exp(-m.xi * (ref_date - d["date"]).dt.days.to_numpy(float))

    def neg(rho):
        tau = np.ones_like(lh)
        tau = np.where((x == 0) & (y == 0), 1 - lh * la * rho, tau)
        tau = np.where((x == 0) & (y == 1), 1 + lh * rho, tau)
        tau = np.where((x == 1) & (y == 0), 1 + la * rho, tau)
        tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
        return -np.sum(w * np.log(np.clip(tau, 1e-9, None)))

    return float(minimize_scalar(neg, bounds=(-0.25, 0.25), method="bounded").x)


def score_matrix(lh: float, la: float, rho: float) -> np.ndarray:
    g = np.arange(MAX_GOALS + 1)
    M = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    M[0, 0] *= 1 - lh * la * rho
    M[0, 1] *= 1 + lh * rho
    M[1, 0] *= 1 + la * rho
    M[1, 1] *= 1 - rho
    return M / M.sum()


def goal_markets(lh: float, la: float, rho: float) -> dict:
    M = score_matrix(lh, la, rho)
    tot = np.add.outer(np.arange(MAX_GOALS + 1), np.arange(MAX_GOALS + 1))
    out = {
        "xg_h": lh, "xg_a": la,
        "p_h": float(np.tril(M, -1).sum()), "p_d": float(np.trace(M)), "p_a": float(np.triu(M, 1).sum()),
        "btts": float(M[1:, 1:].sum()),
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f"o{int(line * 10)}"] = float(M[tot > line].sum())
    return out


def count_dist(mean: float, disp: float, kmax: int = 80) -> np.ndarray:
    k = np.arange(kmax + 1)
    if disp <= 0 or disp > 1e4:
        return poisson.pmf(k, mean)
    return nbinom.pmf(k, disp, disp / (disp + mean))


def count_markets(mh: float, ma: float, disp: float, lines: list[float]) -> dict:
    p = count_dist(mh + ma, disp)
    k = np.arange(len(p))
    return {"exp_h": mh, "exp_a": ma, "exp": mh + ma,
            "over": {str(l): float(p[k > l].sum()) for l in lines}}


class Predictor:
    """Ensemble des modèles d'une ligue, ajustés à une date donnée."""

    def __init__(self, df_league: pd.DataFrame, ref_date: pd.Timestamp, with_counts: bool = True):
        self.goals = RatingModel().fit(df_league, "hg", "ag", ref_date)
        self.rho = fit_rho(df_league, self.goals, ref_date) if self.goals.fitted else 0.0
        self.counts = {}
        if with_counts:
            for key, (ch, ca, _, _) in config.COUNT_STATS.items():
                if df_league[ch].notna().sum() > 200:
                    m = RatingModel().fit(df_league, ch, ca, ref_date)
                    if m.fitted:
                        self.counts[key] = m

    def predict(self, home: str, away: str) -> dict | None:
        if not self.goals.fitted:
            return None
        lh, la = self.goals.rates(home, away)
        out = goal_markets(lh, la, self.rho)
        for key, m in self.counts.items():
            mh, ma = m.rates(home, away)
            out[key] = count_markets(mh, ma, m.disp, config.COUNT_STATS[key][3])
        return out
