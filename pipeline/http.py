"""Client HTTP commun : délai, reprises avec backoff exponentiel, pagination Hub'Eau (SPEC §7.2)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from pipeline.config import Http

STATUTS_TRANSITOIRES = {408, 429, 500, 502, 503, 504}


def _transitoire(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in STATUTS_TRANSITOIRES
    return isinstance(exc, httpx.TransportError)


class ClientHttp:
    """Enveloppe `httpx.Client` : les erreurs transitoires sont rejouées, les autres levées.

    `transport` permet d'injecter des réponses enregistrées dans les tests.
    """

    def __init__(
        self,
        parametres: Http,
        transport: httpx.BaseTransport | None = None,
        attente_max_s: float = 60,
    ) -> None:
        self._client = httpx.Client(
            timeout=parametres.timeout_s, transport=transport, follow_redirects=True
        )
        self._get = retry(
            stop=stop_after_attempt(parametres.tentatives),
            wait=wait_exponential(min=min(1, attente_max_s), max=attente_max_s),
            retry=retry_if_exception(_transitoire),
            reraise=True,
        )(self._get_brut)

    def _get_brut(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        reponse = self._client.get(url, params=params)
        reponse.raise_for_status()
        return reponse

    def json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self._get(url, params).json()

    def contenu(self, url: str) -> bytes:
        return self._get(url, None).content

    def pages_hubeau(self, url: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Enregistrements de toutes les pages, en suivant `next` (pages v1 comme curseur v2).

        Vérifie à la fin que le nombre reçu correspond au `count` annoncé.
        """
        attendu: int | None = None
        recus = 0
        suivant: str | None = url
        parametres: dict[str, Any] | None = params
        while suivant:
            page = self.json(suivant, parametres)
            if attendu is None:
                attendu = page.get("count")
            for enregistrement in page["data"]:
                recus += 1
                yield enregistrement
            suivant, parametres = page.get("next"), None
        if attendu is not None and recus != attendu:
            raise RuntimeError(f"{url} : {recus} enregistrements reçus pour {attendu} annoncés")
