# Spike V0 n°5 — DVC et DagsHub

Date : 2026-09-30 · Script : [`dvc_dagshub.sh`](dvc_dagshub.sh)

## Question

`dvc push` et `dvc pull` d'un Parquet de test vers le remote DVC de DagsHub fonctionnent-ils, sans qu'aucun secret ne soit versionné ?

## Mise en place

- Code sur GitHub (`baptistefeldmann/observatoire-secheresse`), dépôt DagsHub du même nom.
- `dvc` (3.67) en dépendance du projet : le job hebdomadaire en aura besoin pour `dvc push`.
- `.dvc/config`, versionné : remote par défaut `origin` = `https://dagshub.com/baptistefeldmann/observatoire-secheresse.dvc`, `core.autostage = true` (les `.dvc` produits par `dvc add` sont indexés dans Git automatiquement).
- Identifiants : `DAGSHUB_USER` et `DAGSHUB_TOKEN` dans `.env`, copiés par `make dvc-auth` dans `.dvc/config.local`, ignoré par Git. Ni `.env` ni `config.local` ne sont versionnés (vérifié avec `git check-ignore`).
- `.dvcignore` exclut `rasters/`.

## Résultat

| Étape | Résultat |
|---|---|
| GeoParquet de test (100 000 points, EPSG:2154) | 2,7 Mo |
| `dvc push` | 5,2 s |
| suppression du fichier et du cache local, puis `dvc pull` | 4,4 s |
| empreinte md5 avant / après | identiques |
| `dvc status -c` | cache et remote synchronisés |

Le cas « `dvc pull` sans cache local » est celui d'un nouveau poste, ou de la reconstruction prévue par `make db-rebuild`. Il fonctionne.

Le temps est surtout du temps de connexion : à ce volume, le débit n'est pas limitant. L'objet de test reste sur le remote, mais le dépôt n'en garde aucune trace.

## Estimation du volume

DVC conserve chaque version entière d'un fichier ; chaque semaine, seuls les fichiers de l'année en cours changent (§5.2) :

| Fichier annuel | Taille estimée |
|---|---|
| `meteo/sim_<annee>.parquet` (145 mailles, 3 variables) | 1 à 2 Mo |
| `piezo/chroniques_<annee>.parquet`, `hydro/qmj_<annee>.parquet`, `onde/observations_<annee>.parquet` | moins de 1 Mo chacun |
| `indices/indices_hebdo_<annee>.parquet` | moins de 1 Mo |

Soit environ 5 Mo par semaine, 250 Mo par an, plus un historique initial de quelques dizaines de Mo : bien en dessous du quota gratuit de 10 Go. La carte d'occupation du sol (V2, environ 70 millions de pixels de 8 bits par millésime, compressés) sera le poste le plus lourd, à raison d'un fichier par an.

## Conséquences

- La chaîne `dvc pull` puis `make db-rebuild` du §3 est validée côté données.
- Pour une autre instance territoriale : un dépôt DagsHub par territoire, puis `dvc remote modify origin url ...` et `make dvc-auth` (README).
- Le job hebdomadaire devra disposer d'un jeton DagsHub sur la machine Linux (déjà le cas avec `.env`) et d'une clé SSH GitHub pour pousser les commits et les tags `data-AAAA-Www` (déjà fonctionnelle).
