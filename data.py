"""Téléchargement et nettoyage des données football-data.co.uk."""
from __future__ import annotations

import io
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

import config

RAW = Path(__file__).parent / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

# Colonnes de stats conservées (format "main")
STAT_COLS = ["HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"]


def season_codes(n: int, today: dt.date | None = None) -> list[str]:
    """Codes de saison football-data ('2627', '2526', ...) du plus récent au plus ancien."""
    today = today or dt.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return [f"{(y % 100):02d}{((y + 1) % 100):02d}" for y in range(start, start - n, -1)]


def _get(url: str) -> bytes | None:
    import requests
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 PronoFoot"})
        if r.status_code == 200 and len(r.content) > 200:
            return r.content
    except Exception as e:  # réseau coupé, site indisponible...
        print(f"   ! {url} : {e}")
    return None


def download_all(verbose: bool = True) -> None:
    """Télécharge l'historique. Les saisons terminées déjà en cache ne sont pas re-téléchargées."""
    seasons = season_codes(config.N_SEASONS)
    for code, meta in config.LEAGUES.items():
        if meta["format"] == "main":
            for i, s in enumerate(seasons):
                f = RAW / f"{code}_{s}.csv"
                if f.exists() and i > 0:  # saison passée en cache : inutile de re-télécharger
                    continue
                content = _get(config.URL_MAIN.format(season=s, code=code))
                if content:
                    f.write_bytes(content)
                    if verbose:
                        print(f"   ✓ {meta['nom']} {s}")
        else:
            content = None
            for fname in meta.get("fichiers", [code]):  # le nom du fichier varie selon les pays
                content = _get(config.URL_NEW.format(code=fname))
                if content:
                    break
            if content:
                (RAW / f"{code}_all.csv").write_bytes(content)
                if verbose:
                    print(f"   ✓ {meta['nom']} (historique complet)")
    for i, url in enumerate(config.URL_FIXTURES):
        content = _get(url)
        f = RAW / f"fixtures_{i}.csv"
        if content:
            f.write_bytes(content)
            if verbose:
                print(f"   ✓ calendrier {i + 1}/2 téléchargé ({content.count(b'\n')} lignes)")
        elif verbose:
            print(f"   ! calendrier {i + 1}/2 indisponible ({url})")


def _read_csv(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):  # marque BOM en tête de fichier
        raw = raw[3:]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, on_bad_lines="skip")
            df.columns = [str(c).replace("\ufeff", "").replace("ï»¿", "").strip() for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"   ! lecture impossible de {path.name} : {e}")
            return pd.DataFrame()
    return pd.DataFrame()


def _parse_dates(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    d4 = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    d2 = pd.to_datetime(s, format="%d/%m/%y", errors="coerce")
    return iso.fillna(d4).fillna(d2)


def _first(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Première colonne disponible et non vide parmi plusieurs noms (les noms varient selon les années)."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for c in cols:
        if c in df.columns:
            out = out.fillna(pd.to_numeric(df[c], errors="coerce"))
    return out


def _standardize(df: pd.DataFrame, code: str, season: str) -> pd.DataFrame:
    if "HomeTeam" not in df.columns and "Home" in df.columns:
        df = df.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"})
    need = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
    if not all(c in df.columns for c in need):
        return pd.DataFrame()
    out = pd.DataFrame({
        "league": code,
        "season": df["Season"].astype(str) if "Season" in df.columns else season,
        "date": _parse_dates(df["Date"]),
        "home": df["HomeTeam"].astype(str).str.strip(),
        "away": df["AwayTeam"].astype(str).str.strip(),
        "hg": pd.to_numeric(df["FTHG"], errors="coerce"),
        "ag": pd.to_numeric(df["FTAG"], errors="coerce"),
    })
    for c in STAT_COLS:
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    # odds_* : cote d'un bookmaker « grand public » (Bet365, proche de 1xBet/Betclic) = le prix obtenu
    # pin_*  : Pinnacle, le bookmaker de référence (marge faible, prix les plus justes)
    # close_*: cote de clôture Pinnacle (juste avant le coup d'envoi)
    for s, x in (("h", "H"), ("d", "D"), ("a", "A")):
        out[f"odds_{s}"] = _first(df, [f"B365{x}", f"Avg{x}", f"BbAv{x}", f"B365C{x}", f"AvgC{x}"])
        out[f"pin_{s}"] = _first(df, [f"PS{x}", f"P{x}", f"PSC{x}"])
        out[f"avg_{s}"] = _first(df, [f"Avg{x}", f"BbAv{x}"])
        out[f"close_{s}"] = _first(df, [f"PSC{x}", f"AvgC{x}"])
        out[f"max_{s}"] = _first(df, [f"Max{x}", f"BbMx{x}", f"MaxC{x}"])
    for s, x in (("o25", ">2.5"), ("u25", "<2.5")):
        out[f"odds_{s}"] = _first(df, [f"B365{x}", f"Avg{x}", f"BbAv{x}"])
        out[f"pin_{s}"] = _first(df, [f"P{x}"])
        out[f"avg_{s}"] = _first(df, [f"Avg{x}", f"BbAv{x}"])
        out[f"close_{s}"] = _first(df, [f"PC{x}", f"AvgC{x}"])
        out[f"max_{s}"] = _first(df, [f"Max{x}", f"BbMx{x}", f"MaxC{x}"])
    return out.dropna(subset=["date", "hg", "ag"])


def load_matches() -> pd.DataFrame:
    """Tous les matchs joués, toutes ligues, triés par date."""
    frames = []
    for code, meta in config.LEAGUES.items():
        if meta["format"] == "main":
            for f in sorted(RAW.glob(f"{code}_*.csv")):
                season = f.stem.split("_")[1]
                frames.append(_standardize(_read_csv(f), code, season))
        else:
            f = RAW / f"{code}_all.csv"
            if f.exists():
                frames.append(_standardize(_read_csv(f), code, ""))
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["league", "date", "home", "away"]).sort_values("date")
    return df.reset_index(drop=True)


_NEW_COUNTRY = {"Norway": "NOR", "Austria": "AUT", "Denmark": "DNK", "Switzerland": "SWZ"}


def load_fixtures(include_past: bool = False) -> pd.DataFrame:
    """Prochains matchs publiés par football-data.co.uk, avec les cotes moyennes du marché."""
    frames = []
    for f in sorted(RAW.glob("fixtures_*.csv")):
        df = _read_csv(f)
        if df.empty:
            continue
        if "Div" in df.columns:
            df["league"] = df["Div"].astype(str).str.strip()
        elif "Country" in df.columns:
            df["league"] = df["Country"].map(_NEW_COUNTRY)
        else:
            continue
        df = df[df["league"].isin(config.LEAGUES.keys())]
        if df.empty:
            continue
        std = _standardize(df.assign(FTHG=0, FTAG=0), "", "")
        std["league"] = df.loc[std.index, "league"].values
        std["time"] = df.loc[std.index, "Time"].astype(str).values if "Time" in df.columns else ""
        frames.append(std)
    if not frames:
        return pd.DataFrame()
    fx = pd.concat(frames, ignore_index=True)
    if not include_past:
        today = pd.Timestamp(dt.date.today())
        fx = fx[fx["date"] >= today]
    return fx.drop(columns=["hg", "ag"] + STAT_COLS).sort_values(["date", "league"]).reset_index(drop=True)


def fixtures_diagnostic() -> str:
    """Explique en clair pourquoi aucun match à venir n'a été trouvé."""
    files = sorted(RAW.glob("fixtures_*.csv"))
    if not files:
        return "Calendrier non téléchargé : vérifiez la connexion internet puis relancez."
    lines = []
    for f in files:
        df = _read_csv(f)
        if df.empty:
            lines.append(f"{f.name} : fichier vide (aucun match publié pour l'instant)")
            continue
        col = "Div" if "Div" in df.columns else ("Country" if "Country" in df.columns else None)
        dates = _parse_dates(df["Date"]) if "Date" in df.columns else pd.Series(dtype="datetime64[ns]")
        divs = sorted(df[col].astype(str).unique())[:12] if col else ["?"]
        span = f"du {dates.min():%d/%m} au {dates.max():%d/%m}" if dates.notna().any() else "dates illisibles"
        lines.append(f"{f.name} : {len(df)} matchs, {span}, championnats {', '.join(divs)}")
    return "Calendrier lu, mais aucun match à venir dans vos championnats.\n     " + "\n     ".join(lines) + \
        "\n     Les matchs du week-end sont publiés le vendredi après-midi : relancez à ce moment-là."
