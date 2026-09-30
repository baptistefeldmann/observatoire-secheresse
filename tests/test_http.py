from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from pipeline.http import ClientHttp


def test_reprise_sur_erreur_transitoire(fabrique_client: Callable[..., ClientHttp]) -> None:
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(503) if len(appels) < 3 else httpx.Response(200, json={"ok": 1})

    assert fabrique_client(gestionnaire).json("https://api.test/x") == {"ok": 1}
    assert len(appels) == 3


def test_pas_de_reprise_sur_erreur_definitive(fabrique_client: Callable[..., ClientHttp]) -> None:
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError):
        fabrique_client(gestionnaire).json("https://api.test/x")
    assert len(appels) == 1


def _pages(count: int) -> Callable[[httpx.Request], httpx.Response]:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.params.get("page") == "2":
            return httpx.Response(200, json={"count": count, "next": None, "data": [{"i": 3}]})
        suite = "https://api.test/stations?page=2"
        return httpx.Response(
            200, json={"count": count, "next": suite, "data": [{"i": 1}, {"i": 2}]}
        )

    return gestionnaire


def test_pagination_suit_next(fabrique_client: Callable[..., ClientHttp]) -> None:
    client = fabrique_client(_pages(3))
    assert [e["i"] for e in client.pages_hubeau("https://api.test/stations", {})] == [1, 2, 3]


def test_pagination_incomplete_detectee(fabrique_client: Callable[..., ClientHttp]) -> None:
    client = fabrique_client(_pages(4))
    with pytest.raises(RuntimeError, match="3 enregistrements reçus pour 4"):
        list(client.pages_hubeau("https://api.test/stations", {}))
