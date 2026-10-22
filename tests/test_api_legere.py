"""L'API ne doit importer aucune bibliothèque du pipeline de calcul.

L'image Docker de l'API n'installe pas le groupe de dépendances `pipeline` (pandas, scipy,
geopandas, pyarrow, dvc…) : un import qui les ramènerait casserait l'API en production sans
rien signaler aux tests, qui tournent avec toutes les dépendances.
"""

import subprocess
import sys

INTERDITS = ["pandas", "numpy", "scipy", "geopandas", "pyarrow", "shapely", "pyogrio", "dvc"]

SCRIPT = """
import importlib.abc, sys

class Bloqueur(importlib.abc.MetaPathFinder):
    def find_spec(self, nom, chemin=None, cible=None):
        if nom.split(".")[0] in {interdits!r}:
            raise ImportError(f"import interdit dans l'API : {{nom}}")
        return None

sys.meta_path.insert(0, Bloqueur())
import api.app  # noqa: F401
print("ok")
"""


def test_api_sans_dependances_du_pipeline() -> None:
    resultat = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(interdits=set(INTERDITS))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.strip() == "ok"
