# ruff: noqa
"""V2.0 marée, hauteurs de marée du SHOM (REFMAR, API publique, source 2 : 10 minutes) à La Pallice (34) et aux Sables-d'Olonne (62), mai 2022 à octobre 2025. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import os
import requests, pandas as pd, time, sys, datetime as dt

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
os.makedirs(f"{S}/maree", exist_ok=True)


def mois(a, b):
    d = a
    while d < b:
        n = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        yield d, min(n, b)
        d = n


out = []
for st in (34, 62):
    for src in (2, 1):
        got = []
        for d0, d1 in mois(dt.date(2022, 5, 20), dt.date(2025, 11, 1)):
            u = f"https://services.data.shom.fr/maregraphie/observation/json/{st}"
            p = dict(sources=src, dtStart=f"{d0}T00:00:00Z", dtEnd=f"{d1}T00:00:00Z")
            for t in range(6):
                try:
                    r = requests.get(u, params=p, timeout=120)
                    r.raise_for_status()
                    got += r.json()["data"]
                    break
                except Exception as e:
                    print("reprise", st, d0, e, flush=True)
                    time.sleep(5 * (t + 1))
        df = pd.DataFrame(got)
        print(st, "source", src, len(df), flush=True)
        if len(df):
            df["t"] = pd.to_datetime(df.timestamp, format="%Y/%m/%d %H:%M:%S", utc=True)
            df[["t", "value"]].assign(station=st, source=src).to_csv(
                f"{S}/maree/maree_{st}_s{src}.csv", index=False
            )
            if src == 2:
                break
print("terminé")
