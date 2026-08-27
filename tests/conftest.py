"""Dobles de prueba compartidos por los tests de fetchers (sin red)."""

import pytest


class FakeResponse:
    """Sustituto mínimo de ``requests.Response``."""

    def __init__(
        self,
        content: bytes = b"",
        status_code: int = 200,
        headers: dict | None = None,
    ):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    """Sustituto de ``requests.Session`` con respuestas programadas.

    Las respuestas se registran por fragmento de URL y se aplica la
    primera coincidencia; si una "respuesta" es una instancia de
    ``Exception`` se eleva (simula fallos de red). Si la "respuesta" es
    una lista, se consumen sus elementos en orden por llamada (permite
    simular secuencias como 429 → 200). Cada llamada queda grabada para
    asertar URLs, timeouts y cabeceras enviadas.
    """

    def __init__(self):
        self.headers = {"User-Agent": "gpatch-notes/test"}
        self.calls = []
        self._routes = []
        self._default = FakeResponse()

    def route(self, fragment: str, response):
        self._routes.append((fragment, response))
        return self

    def get(self, url: str, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        for fragment, response in self._routes:
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                if isinstance(response, list):
                    response = response.pop(0) if response else FakeResponse(
                        status_code=404
                    )
                return response
        return self._default


@pytest.fixture
def fake_session():
    return FakeSession()
