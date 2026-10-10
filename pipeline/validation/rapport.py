"""Mesures d'accord entre indices et arrêtés sécheresse, et rapport Markdown (`docs/validation.md`).

Mesures, sur les semaines de la saison (`validation` dans `projet.yaml`) des années détaillées :

- **par année** : part des semaines-zones sous restriction (alerte ou plus, crise), composite
  moyen, part en classes sèches ; corrélation de rang entre années ;
- **par zone** : AUC du composite et de ses composantes pour séparer les semaines « alerte ou
  plus » des autres : probabilité qu'une semaine sous alerte ait une valeur plus sèche qu'une
  semaine sans (0,5 : hasard, 1 : séparation parfaite) ;
- classes du composite selon le niveau de restriction ;
- semaines en crise avec un composite normal ou plus humide.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.config import Config

LIBELLES_NIVEAU = {0: "aucun", 1: "vigilance", 2: "alerte", 3: "alerte renforcée", 4: "crise"}
NIVEAU_ALERTE = 2
NIVEAU_CRISE = 4
CLASSE_NORMALE = 4  # classes 4 à 7 : normal ou plus humide
COMPOSANTES = ["spi_3", "ips", "debit"]
MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]  # fmt: skip


def auc(alerte: Sequence[bool] | pd.Series, valeur: Sequence[float] | pd.Series) -> float:
    """Probabilité qu'une semaine sous alerte ait une valeur plus basse (plus sèche) qu'une
    semaine sans alerte, ex aequo comptés pour moitié ; NaN sans les deux cas."""
    a = np.asarray(alerte, dtype=bool)
    v = np.asarray(valeur, dtype=float)
    garde = ~np.isnan(v)
    a, v = a[garde], v[garde]
    n1, n0 = int(a.sum()), int((~a).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    rangs = stats.rankdata(-v)  # rang 1 : la valeur la plus haute
    return float((rangs[a].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def assembler(
    config: Config, niveaux: pd.DataFrame, composite: pd.DataFrame, indices_zone: pd.DataFrame
) -> pd.DataFrame:
    """Une ligne par zone et par semaine de saison : niveau, composite (valeur, classe) et
    valeurs de zone des composantes."""
    v = config.projet.validation
    composantes = indices_zone[indices_zone["indice"].isin(COMPOSANTES)].pivot_table(
        index=["zone_id", "semaine"], columns="indice", values="valeur"
    )
    table = (
        niveaux.merge(
            composite[["zone_id", "semaine", "valeur", "classe", "version_methodo"]],
            on=["zone_id", "semaine"],
        )
        .merge(composantes.reset_index(), on=["zone_id", "semaine"], how="left")
    )  # fmt: skip
    for c in COMPOSANTES:
        if c not in table:
            table[c] = np.nan
    table["annee"] = table["semaine"].str[:4].astype(int)
    numero = table["semaine"].str[-2:].astype(int)
    table["mois"] = pd.to_datetime(table["semaine"] + "-7", format="%G-W%V-%u").dt.month
    return table[numero.between(v.semaine_debut, v.semaine_fin)].reset_index(drop=True)


def _pct(x: float) -> str:
    return "" if np.isnan(x) else f"{100 * x:.0f} %"


def _nb(x: float, chiffres: int = 2) -> str:
    return "" if np.isnan(x) else f"{x:.{chiffres}f}".replace(".", ",").replace("-", "−")


def _tableau(entetes: Sequence[str], lignes: Iterable[Sequence[str]]) -> list[str]:
    sortie = ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    sortie += ["| " + " | ".join(ligne) + " |" for ligne in lignes]
    return sortie


def par_annee(table: pd.DataFrame) -> pd.DataFrame:
    return table.groupby("annee").agg(
        alerte=("niveau", lambda s: (s >= NIVEAU_ALERTE).mean()),
        crise=("niveau", lambda s: (s == NIVEAU_CRISE).mean()),
        composite=("valeur", "mean"),
        seches=("classe", lambda s: (s <= 2).mean()),
        normales=("classe", lambda s: (s >= CLASSE_NORMALE).mean()),
    )


def par_zone(table: pd.DataFrame) -> pd.DataFrame:
    lignes = []
    for zone_id, g in table.groupby("zone_id"):
        alerte = g["niveau"] >= NIVEAU_ALERTE
        lignes.append(
            {"zone_id": zone_id, "semaines": len(g), "alerte": alerte.mean(),
             "composite": auc(alerte, g["valeur"])}
            | {c: auc(alerte, g[c]) for c in COMPOSANTES}
        )  # fmt: skip
    return pd.DataFrame(lignes).set_index("zone_id")


def rediger(
    config: Config,
    table: pd.DataFrame,
    arretes: pd.DataFrame,
    orphelines: list[tuple[str, str]],
    fin: str,
) -> str:
    """Rapport Markdown, entièrement déterminé par les données (aucune date d'exécution)."""
    v = config.projet.validation
    libelles = {z.zone_id: z.libelle for z in config.zonage.zones}
    sans_arretes = [z.libelle for z in config.zonage.zones if not z.zones_alerte_arretes]
    detailles = arretes.dropna(subset=["nom_zone_alerte"])
    annees = sorted(table["annee"].unique())
    methodo = ", ".join(sorted(table["version_methodo"].dropna().unique()))
    alerte = table["niveau"] >= NIVEAU_ALERTE
    t = config.projet.territoire

    s: list[str] = [
        f"# Validation des indices par les arrêtés sécheresse — {t.nom}",
        "",
        "*Rapport généré par `make validation` : ne pas modifier à la main.*",
        "",
        f"Arrêtés VigiEau jusqu'à la semaine {fin}"
        + (f" ; indices en version de méthode {methodo}." if methodo else "."),
        "",
        "## Données comparées",
        "",
        f"- **Arrêtés** : {arretes['arrete_id'].nunique()} arrêtés du département, dont "
        f"{detailles['arrete_id'].nunique()} listent leurs zones d'alerte (depuis "
        f"{min(d.year for d in detailles['date_debut'])}). Une semaine prend le niveau en vigueur "
        "le dimanche ; une zone prend le niveau le plus sévère de ses zones d'alerte.",
        f"- **Saison** : semaines {v.semaine_debut} à {v.semaine_fin}, années "
        f"{annees[0]} à {annees[-1]} ; {table['zone_id'].nunique()} zones, {len(table)} "
        "semaines-zones.",
        f"- **Zones sans zone d'alerte rattachée** (hors comparaison) : "
        f"{', '.join(sans_arretes) or 'aucune'}.",
        f"- **Zones d'alerte non rattachées** : "
        f"{', '.join(f'{n} ({ty})' for ty, n in orphelines) or 'aucune'}.",
        "",
        "Un arrêté se déclenche quand un débit ou un niveau de nappe passe sous un **seuil fixe**,",
        "alors que l'indice compare chaque semaine à la **normale de la saison**. Les petits cours",
        "d'eau passent sous leur seuil presque chaque fin d'été : un désaccord en août-septembre",
        "d'une année normale est attendu. Les arrêtés sont aussi levés avec retard après les",
        "pluies.",
        "",
        "## Par année",
        "",
    ]
    a = par_annee(table)
    rho = stats.spearmanr(a["alerte"], a["composite"]).statistic if len(a) > 2 else np.nan
    s += _tableau(
        ["Année", "Alerte ou plus", "Crise", "Composite moyen", "Classes 1-2", "Classes 4 à 7"],
        ([str(i), _pct(r.alerte), _pct(r.crise), _nb(r.composite), _pct(r.seches),
          _pct(r.normales)] for i, r in a.iterrows()),
    )  # fmt: skip
    lecture_rho = (
        "non calculable (moins de 3 années)."
        if np.isnan(rho)
        else f"**{_nb(rho)}** (−1 : les années les plus restreintes sont les plus sèches pour "
        "l'indice)."
    )
    s += [
        "",
        "Part des semaines-zones de la saison. Corrélation de rang entre années (part sous alerte",
        f"et composite moyen) : {lecture_rho}",
        "",
        "## Par zone",
        "",
    ]
    z = par_zone(table)
    s += _tableau(
        ["Zone", "Semaines", "Alerte ou plus", "AUC composite", "SPI 3 mois", "IPS", "Débit"],
        ([libelles.get(str(i), str(i)), str(int(r.semaines)), _pct(r.alerte), _nb(r.composite),
          _nb(r.spi_3), _nb(r.ips), _nb(r.debit)] for i, r in z.iterrows()),
    )  # fmt: skip
    s += [
        f"| **Ensemble** | {len(table)} | {_pct(alerte.mean())} | "
        f"**{_nb(auc(alerte, table['valeur']))}** | "
        + " | ".join(_nb(auc(alerte, table[c])) for c in COMPOSANTES)
        + " |",
        "",
        "AUC : probabilité qu'une semaine sous alerte (ou plus) ait une valeur plus sèche qu'une",
        "semaine sans alerte (0,5 : hasard ; 1 : séparation parfaite). Vide : composante absente.",
        "",
        "## Classes du composite selon le niveau de restriction",
        "",
    ]
    croise = pd.crosstab(table["classe"], table["niveau"], normalize="columns")
    niveaux = list(croise.columns)
    effectifs = table["niveau"].value_counts()
    s += _tableau(
        ["Classe"] + [f"{LIBELLES_NIVEAU[int(n)]} ({effectifs[n]})" for n in niveaux],
        ([str(c)] + [_pct(croise.loc[c, n]) for n in niveaux] for c in croise.index),
    )
    crise = table[table["niveau"] == NIVEAU_CRISE]
    ecart = crise[crise["classe"] >= CLASSE_NORMALE]
    part = f" ({_pct(len(ecart) / len(crise))})" if len(crise) else ""
    s += [
        "",
        "Part de chaque classe parmi les semaines-zones d'un niveau (effectif entre parenthèses).",
        "",
        "## Semaines en crise avec un composite normal ou plus humide",
        "",
        f"{len(ecart)} semaines-zones sur {len(crise)} en crise{part}.",
        "",
    ]
    if len(ecart):
        zones = ecart.groupby("zone_id").size().sort_values(ascending=False)
        mois = ecart.groupby("mois").size()
        s += _tableau(
            ["Zone", "Semaines"], ([libelles.get(str(i), str(i)), str(n)] for i, n in zones.items())
        )
        s += [""]
        s += _tableau(["Mois", "Semaines"], ([MOIS[int(str(m))], str(n)] for m, n in mois.items()))
    return "\n".join(s) + "\n"
