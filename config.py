"""Paramètres de PronoFoot. Tout ce qu'on peut vouloir ajuster est ici."""

# Championnats suivis (codes football-data.co.uk)
# "format": "main" = fichiers par saison avec stats (tirs, corners, fautes)
#           "new"  = un seul fichier historique, buts + cotes uniquement
LEAGUES = {
    "E0":  {"nom": "Premier League",  "pays": "Angleterre", "format": "main"},
    "SP1": {"nom": "La Liga",         "pays": "Espagne",    "format": "main"},
    "I1":  {"nom": "Serie A",         "pays": "Italie",     "format": "main"},
    "D1":  {"nom": "Bundesliga",      "pays": "Allemagne",  "format": "main"},
    "F1":  {"nom": "Ligue 1",         "pays": "France",     "format": "main"},
    "P1":  {"nom": "Liga Portugal",   "pays": "Portugal",   "format": "main"},
    "N1":  {"nom": "Eredivisie",      "pays": "Pays-Bas",   "format": "main"},
    "B1":  {"nom": "Pro League",      "pays": "Belgique",   "format": "main"},
    "T1":  {"nom": "Süper Lig",       "pays": "Turquie",    "format": "main"},
    "SC0": {"nom": "Premiership",     "pays": "Écosse",     "format": "main"},
    "NOR": {"nom": "Eliteserien",     "pays": "Norvège",    "format": "new"},
    "AUT": {"nom": "Bundesliga AUT",  "pays": "Autriche",   "format": "new", "fichiers": ["AUT"]},
    "DNK": {"nom": "Superliga",       "pays": "Danemark",   "format": "new", "fichiers": ["DNK", "DEN"]},
    "SWZ": {"nom": "Super League",    "pays": "Suisse",     "format": "new", "fichiers": ["SWZ", "SUI"]},
}

# Nombre de saisons d'historique à télécharger (saison en cours incluse)
N_SEASONS = 6

URL_MAIN = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
URL_NEW = "https://www.football-data.co.uk/new/{code}.csv"
URL_FIXTURES = [
    "https://www.football-data.co.uk/fixtures.csv",
    "https://www.football-data.co.uk/new_league_fixtures.csv",
]

# --- Modèle ---
# Demi-vie de l'importance d'un match passé (jours). 365 j : un match d'il y a
# un an pèse moitié moins qu'un match d'hier.
HALF_LIFE_DAYS = 365
# Fenêtre d'entraînement (jours)
TRAIN_WINDOW_DAYS = 3 * 365
# Pénalité de régularisation : tire les équipes peu observées (promus) vers la moyenne
RIDGE = 2.0

# Statistiques de match modélisées en plus des buts : (colonne dom., colonne ext., libellé, lignes O/U)
COUNT_STATS = {
    "corners": ("HC", "AC", "Corners", [8.5, 9.5, 10.5, 11.5]),
    "fautes":  ("HF", "AF", "Fautes", [20.5, 22.5, 24.5, 26.5]),
    "tirs":    ("HS", "AS", "Tirs", [22.5, 24.5, 26.5, 28.5]),
    "tirs_cadres": ("HST", "AST", "Tirs cadrés", [7.5, 8.5, 9.5, 10.5]),
    "cartons": ("HY", "AY", "Cartons jaunes", [3.5, 4.5, 5.5]),
}

# --- Stratégie de mise ---
BANKROLL_DEFAUT = 100_000      # FCFA, modifiable dans le tableau de bord
KELLY_FRACTION = 0.25          # quart de Kelly : réduit fortement la variance
MISE_MAX_PCT = 0.02            # jamais plus de 2 % de la bankroll sur un pari
EDGE_MIN = 0.05                # value minimale exigée (5 %) pour signaler un pari
EDGE_MIN_MARCHE = 0.03         # value minimale face au prix juste Pinnacle
MISE_FIXE_PCT = 0.01           # liste « Les plus probables » : mise fixe de 1 % de la bankroll
COTE_MAX = 4.0                 # au-delà, l'erreur de modèle domine : on s'abstient
PROBA_MIN = 0.40               # stratégie retenue : value ≥ 3 % face à Pinnacle ET au moins 40 % de chances

# --- Backtest ---
BACKTEST_SEASONS = 2           # nombre de saisons complètes testées hors échantillon
REFIT_EVERY_DAYS = 7

# --- Fuseau horaire d'affichage ---
# Décalage par rapport à GMT, en heures. Abidjan / Côte d'Ivoire : 0 (pas d'heure d'été).
FUSEAU_GMT = 0

# --- Cotes en direct : The Odds API (the-odds-api.com) ---
# Votre clé est lue dans le fichier cle_api.txt du dossier (jamais écrasé par une mise à jour de l'outil).
from pathlib import Path as _Path
_cles = sorted(_Path(__file__).parent.glob("cle_api*"))  # accepte aussi « cle_api.txt.txt »
ODDS_API_KEY = ""
for _f in _cles:
    if _f.is_file():
        _txt = _f.read_text(encoding="utf-8-sig", errors="ignore").strip().split()
        if _txt:
            ODDS_API_KEY = _txt[0].strip().strip('"')
            break
# Bookmaker de référence (prix juste) et vos bookmakers (où vous pariez)
ODDS_REFERENCE = "pinnacle"
ODDS_MES_BOOKMAKERS = {"betclic_fr": "Betclic", "onexbet": "1xBet"}
# Bookmakers cochés par défaut dans le tableau de bord (modifiable en un clic)
BOOKMAKERS_PAR_DEFAUT = ["Betclic", "1xBet"]
# Ne re-télécharge pas les cotes si les dernières ont moins de N heures (économise les crédits)
ODDS_REFRESH_HOURS = 3
# Codes des championnats chez The Odds API
ODDS_SPORT_KEYS = {
    "E0": "soccer_epl",
    "SP1": "soccer_spain_la_liga",
    "I1": "soccer_italy_serie_a",
    "D1": "soccer_germany_bundesliga",
    "F1": "soccer_france_ligue_one",
    "P1": "soccer_portugal_primeira_liga",
    "N1": "soccer_netherlands_eredivisie",
    "B1": "soccer_belgium_first_div",
    "T1": "soccer_turkey_super_league",
    "SC0": "soccer_spl",
    "NOR": "soccer_norway_eliteserien",
    "AUT": "soccer_austria_bundesliga",
    "DNK": "soccer_denmark_superliga",
    "SWZ": "soccer_switzerland_superleague",
}
