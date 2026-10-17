# PronoFoot

Outil de prédiction et de gestion de paris sur le football : 11 championnats européens, les marchés 1N2, buts, BTTS, corners, fautes, tirs et cartons, un backtest honnête et un journal de paris.

## Installation (une seule fois)

1. Installer Python 3.10 ou plus récent depuis python.org. Sous Windows, cocher « Add Python to PATH ».
2. Dans ce dossier, ouvrir un terminal et lancer :
   ```
   pip install -r requirements.txt
   ```

## Utilisation

Double-cliquer sur **LANCER.bat** (Windows), ou taper `python main.py`.

Le programme :
1. télécharge les résultats, statistiques et cotes depuis football-data.co.uk (6 saisons, environ 1 minute la première fois) ;
2. refait le backtest s'il date de plus de 7 jours ;
3. ajuste les modèles à la date du jour ;
4. ouvre **PronoFoot.html** dans votre navigateur.

Le meilleur moment pour lancer : le **vendredi en fin d'après-midi** pour les matchs du week-end (football-data.co.uk publie alors le calendrier et les cotes), et le **mardi après-midi** pour les matchs de semaine.

Options : `--hors-ligne` (sans téléchargement), `--backtest` (forcer un nouveau backtest).

## Activer les cotes en direct (The Odds API)

1. Sur the-odds-api.com, connectez-vous et copiez votre clé API (une suite de lettres et chiffres).
2. Dans le dossier de l'outil : clic droit dans un espace vide → Nouveau → Document texte. Nommez-le `cle_api`.
3. Ouvrez-le, collez la clé seule sur la première ligne, enregistrez et fermez.
4. Lancez `LANCER.bat`.

Ce fichier n'est jamais remplacé quand vous installez une nouvelle version de l'outil.

L'outil télécharge alors les cotes Pinnacle, Betclic et 1xBet de tous les matchs à venir (environ 28 crédits par lancement, 14 championnats). Il réutilise les cotes de moins de 3 heures pour économiser les crédits ; pour forcer une mise à jour, lancez `python main.py --cotes`.

Si un nom d'équipe n'est pas reconnu, il apparaît dans `correspondances.csv` : ouvrez ce fichier, écrivez dans la colonne `nom_outil` le nom tel qu'il apparaît dans l'onglet Équipes, enregistrez et relancez.

## La stratégie

Un pari est recommandé seulement si les deux conditions sont réunies :
1. votre cote (Betclic par défaut) dépasse d'au moins 3 % le prix juste Pinnacle ;
2. le pari a au moins 40 % de chances de passer, d'après Pinnacle.

Le seuil de 40 % se règle avec le curseur du tableau « Paris recommandés », ou dans `config.py` (`PROBA_MIN`).

## La routine de la semaine

1. Lancer l'outil la veille ou le jour des matchs. Onglet **Matchs à venir** : le tableau **Paris recommandés** liste les paris à jouer, chez quel bookmaker, à quelle cote et pour quelle mise.
2. Vérifier la cote sur le site : si elle est passée sous la « cote minimale », ne pas parier.
3. Parier, puis cliquer sur « Noter ».
4. Après les matchs, mettre à jour les résultats dans **Mon journal**. À la relance suivante, la colonne **CLV** compare vos cotes aux cotes de clôture Pinnacle : une CLV moyenne positive sur 50 à 100 paris est le meilleur signe que la méthode fonctionne.

## Version en ligne (GitHub)

Le dépôt GitHub fait tourner PronoFoot tout seul le mardi à 15 h, le vendredi à 18 h et le samedi à 11 h, puis publie le tableau de bord à l'adresse `https://VOTRE-NOM.github.io/pronofoot/`. Pour lancer une mise à jour à la main : onglet **Actions** → **Mise à jour PronoFoot** → **Run workflow**. La clé The Odds API est rangée dans Settings → Secrets and variables → Actions, sous le nom `ODDS_API_KEY`.

## Mise à jour automatique (sur l'ordinateur)

Double-cliquez une fois sur **PLANIFIER.bat**. PronoFoot se mettra alors à jour tout seul le mardi à 15 h, le vendredi à 18 h et le samedi à 11 h (environ 84 crédits The Odds API par semaine, soit 360 par mois sur 500). L'ordinateur doit être allumé à ces heures. Il suffit ensuite d'ouvrir **PronoFoot.html**. Le compte rendu du dernier lancement est dans `data\dernier_lancement.txt`.

Pour arrêter : double-cliquez sur **ARRETER_PLANIFICATION.bat**.

## Comment ça marche

- **Buts** : modèle de Dixon-Coles. Chaque équipe a une note d'attaque et de défense. On ajoute l'avantage du terrain et une correction des petits scores. Un match d'il y a un an pèse moitié moins qu'un match récent. Les promus démarrent avec le profil des équipes les plus faibles.
- **Corners, fautes, tirs, cartons** : même principe, avec une loi binomiale négative pour les totaux.
- **Cote juste** : les cotes Pinnacle sans la marge, quand elles existent. C'est la référence la plus précise du marché. À défaut, la probabilité du modèle.
- **Mise** : un quart de Kelly, plafonné à 2 % de la bankroll. Pas de pari au-dessus d'une cote de 4.

Tous les réglages (championnats, seuils, bankroll, lignes O/U) sont dans `config.py`.

## Ce que dit le backtest

Le backtest est fait sur 2 saisons. Chaque semaine, le modèle est ré-entraîné avec les seuls matchs déjà joués.

- Le modèle est bien calibré : quand il annonce 40 %, l'événement arrive environ 40 % du temps.
- Il reste moins précis que les cotes du marché. Parier sur ses seules « value » a perdu environ 10 % des mises, sur près de 3 800 paris.
- Pour les corners, les tirs cadrés et les cartons, il ne fait presque pas mieux que la moyenne de la ligue. Pour les fautes, l'apport est un peu plus net.

C'est pour cela que la stratégie repose sur la comparaison entre votre cote et le **prix juste Pinnacle**. Ce backtest-là est calculé automatiquement sur votre ordinateur, onglet Fiabilité. Ne l'appliquez avec de l'argent réel que s'il est positif sur plusieurs centaines de paris, et seulement avec une somme que vous pouvez perdre.

Données : [football-data.co.uk](https://www.football-data.co.uk/).
