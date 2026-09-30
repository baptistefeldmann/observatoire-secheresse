#!/usr/bin/env bash
# Spike V0 n°5 : aller-retour DVC avec le remote DagsHub.
#
#   make dvc-auth && bash docs/spikes/dvc_dagshub.sh
#
# Crée un GeoParquet de test dans data/_spike/, le pousse, supprime la copie locale et le
# cache, le récupère et vérifie l'empreinte. Le fichier .dvc de test est retiré à la fin :
# rien n'est laissé dans le dépôt, seul l'objet de test reste sur le remote.
set -euo pipefail
cd "$(dirname "$0")/../.."

FICHIER=data/_spike/test.parquet
mkdir -p "$(dirname "$FICHIER")"

uv run python - "$FICHIER" <<'PY'
import sys
import geopandas as gpd
import numpy as np
from shapely.geometry import Point

rng = np.random.default_rng(0)  # déterministe : même fichier à chaque exécution
n = 100_000
gdf = gpd.GeoDataFrame(
    {"station_id": [f"test:{i % 50}" for i in range(n)], "valeur": rng.normal(size=n)},
    geometry=[Point(x, y) for x, y in rng.uniform([300_000, 6_600_000], [400_000, 6_700_000], (n, 2))],
    crs=2154,
)
gdf.to_parquet(sys.argv[1])
PY

AVANT=$(md5sum "$FICHIER" | cut -d' ' -f1)
echo "Fichier de test : $(du -h "$FICHIER" | cut -f1), md5 $AVANT"

uv run dvc add -q "$FICHIER"
debut=$(date +%s%N); uv run dvc push -q "$FICHIER.dvc"
echo "dvc push : $(( ($(date +%s%N) - debut) / 1000000 )) ms"

rm -f "$FICHIER"; rm -rf .dvc/cache
debut=$(date +%s%N); uv run dvc pull -q "$FICHIER.dvc"
echo "dvc pull : $(( ($(date +%s%N) - debut) / 1000000 )) ms"

APRES=$(md5sum "$FICHIER" | cut -d' ' -f1)
if [[ "$AVANT" == "$APRES" ]]; then echo "OK : fichier récupéré identique"; else echo "ÉCHEC : $AVANT != $APRES"; fi

uv run dvc status -c "$FICHIER.dvc"

# Nettoyage du dépôt : dvc add (autostage) a indexé le .dvc et un .gitignore dans data/_spike/
git rm -rq --cached --ignore-unmatch data/_spike
rm -rf data/_spike
[[ "$AVANT" == "$APRES" ]]
