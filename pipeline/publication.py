"""Publication des données de la semaine (SPEC §7.1, étape 4) : `dvc add` et `dvc push`, commit
des seuls fichiers `data/*.dvc`, étiquette `data-AAAA-Www`, envoi sur le remote Git.

Idempotent : sans changement de données, pas de commit, et l'étiquette déjà posée sur le
commit courant n'est pas modifiée. Garde-fous : pas de commit hors de la branche configurée
(ni pendant un rebase, où HEAD est détachée) ; le travail en cours de l'utilisateur, indexé
ou non, n'entre jamais dans le commit ; **rien n'est poussé** si la branche a des commits locaux
que l'utilisateur n'a pas encore poussés (un push les enverrait aussi, ainsi qu'une étiquette,
qui emporte ses commits parents) ou si l'état du remote est inconnu : le commit de données et
l'étiquette restent locaux, et le rapport donne les commandes à lancer."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config import Config

# Dossiers de `data/` modifiés chaque semaine ; référentiels et normales ne changent qu'à la
# demande (make referentiels, make reference).
DOSSIERS = ("raw", "indices")

Executer = Callable[[list[str], Path], str]


def executer(commande: list[str], racine: Path) -> str:
    """Lance une commande dans `racine` ; sortie standard, exception si elle échoue."""
    resultat = subprocess.run(commande, cwd=racine, capture_output=True, text=True, check=False)
    if resultat.returncode != 0:
        message = (resultat.stderr or resultat.stdout).strip().splitlines()
        raise RuntimeError(f"{' '.join(commande[:3])} : {message[-1] if message else 'échec'}")
    return resultat.stdout.strip()


@dataclass
class Publication:
    commit: str | None = None  # empreinte du commit de données, None si rien n'a changé
    etiquette: str | None = None
    messages: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)


def etiquette(semaine: str) -> str:
    return f"data-{semaine}"


def envoi_autorise(config: Config, racine: Path, lancer: Executer) -> str | None:
    """None si on peut pousser ; sinon la raison de s'en abstenir.

    Compare la branche locale à celle du remote (après un `git fetch`, qui ne modifie rien
    d'autre que la copie locale du remote) : un commit local non poussé est du travail de
    l'utilisateur, que le job ne doit pas publier à sa place."""
    hebdo = config.projet.hebdo
    suivie = f"{hebdo.remote_git}/{hebdo.branche}"
    try:
        lancer(["git", "fetch", "--quiet", hebdo.remote_git, hebdo.branche], racine)
        avance = lancer(["git", "log", "--format=%h %s", f"{suivie}..{hebdo.branche}"], racine)
    except RuntimeError as exc:
        return f"état de {suivie} non vérifiable ({exc})"
    commits = avance.splitlines()
    if commits:
        return (
            f"{len(commits)} commit(s) local(aux) non poussé(s) sur {suivie} "
            f"(dernier : {commits[0]})"
        )
    return None


def publier(
    config: Config,
    semaine: str,
    resume: str,
    racine: Path,
    lancer: Executer = executer,
) -> Publication:
    """Versionne `data/` et publie ; `resume` sert de corps au commit et à l'étiquette."""
    resultat = Publication()
    data = config.projet.chemins.data
    dossiers = [str((data / d).relative_to(racine) if data.is_absolute() else data / d)
                for d in DOSSIERS]  # fmt: skip
    dvc = [sys.executable, "-m", "dvc"]
    try:
        lancer([*dvc, "add", *dossiers], racine)
        lancer([*dvc, "push"], racine)
        resultat.messages.append("données envoyées sur le remote DVC")
    except RuntimeError as exc:
        resultat.erreurs.append(f"DVC : {exc}")
        return resultat  # sans données sur le remote, un commit les référencerait en vain

    git = ["git"]
    hebdo = config.projet.hebdo
    try:
        branche = lancer([*git, "rev-parse", "--abbrev-ref", "HEAD"], racine)
        if branche != hebdo.branche:
            resultat.erreurs.append(
                f"Git : branche « {branche} » et non « {hebdo.branche} », pas de commit"
            )
            return resultat
        raison_de_ne_pas_pousser = envoi_autorise(config, racine, lancer)  # avant notre commit
        fichiers = [f"{d}.dvc" for d in dossiers]
        if lancer([*git, "status", "--porcelain", "--", *fichiers], racine):
            lancer([*git, "add", "--", *fichiers], racine)
            message = f"Données {semaine}\n\n{resume}"
            lancer([*git, "commit", "--quiet", "-m", message, "--", *fichiers], racine)
            resultat.commit = lancer([*git, "rev-parse", "--short", "HEAD"], racine)
            resultat.messages.append(f"commit {resultat.commit}")
        else:
            resultat.messages.append("données inchangées : pas de commit")

        nom = etiquette(semaine)
        tete = lancer([*git, "rev-parse", "HEAD"], racine)
        existantes = lancer([*git, "tag", "--list", nom], racine)
        cible = lancer([*git, "rev-parse", f"{nom}^{{commit}}"], racine) if existantes else ""
        if cible != tete:
            lancer([*git, "tag", "--force", "--annotate", nom, "-m", f"{nom}\n\n{resume}"], racine)
            resultat.messages.append(f"étiquette {nom} {'déplacée' if existantes else 'posée'}")
        resultat.etiquette = nom

        remote = hebdo.remote_git
        if raison_de_ne_pas_pousser:
            resultat.erreurs.append(
                f"Git : {raison_de_ne_pas_pousser}. Rien n'est poussé (le commit de données et "
                f"l'étiquette restent locaux). Après avoir poussé vos commits : "
                f"git push {remote} {hebdo.branche} && git push --force {remote} refs/tags/{nom}"
            )
            return resultat
        lancer([*git, "push", "--quiet", remote, hebdo.branche], racine)
        lancer([*git, "push", "--quiet", "--force", remote, f"refs/tags/{nom}"], racine)
        resultat.messages.append(f"poussé sur {remote}")
    except RuntimeError as exc:
        resultat.erreurs.append(f"Git : {exc}")
    return resultat
