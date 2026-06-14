"""Shared test fixtures for the Kraty server SDK."""

from __future__ import annotations

import pytest

from kraty_server_sdk import KratyServer, RetryConfig

API_KEY = "sUUVdrM8.djr4-0Iv9h1JvVNSMZNDmSsSN7lSVq2F9dG6DG4A5uQ"
BASE_URL = "https://api.test.kraty.app"


class _CountingKeyGen:
    """Deterministic idempotency-key generator for assertions."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> str:
        self.count += 1
        return f"idem-{self.count}"


@pytest.fixture
def key_gen() -> _CountingKeyGen:
    return _CountingKeyGen()


@pytest.fixture
def make_kraty(
    respx_mock,  # noqa: ARG001 — fixture must run, side effects only
    key_gen: _CountingKeyGen,
):
    """Returns a factory that builds a KratyServer pointed at the
    test base URL, with deterministic idempotency keys and a tight
    retry budget so failure paths return quickly."""

    created: list[KratyServer] = []

    def _make(**overrides) -> KratyServer:
        defaults = dict(
            api_key=API_KEY,
            base_url=BASE_URL,
            retry=RetryConfig(attempts=3, initial_delay=0.001, max_delay=0.005, jitter=0),
            timeout=1.0,
            generate_idempotency_key=key_gen,
        )
        defaults.update(overrides)
        k = KratyServer(**defaults)
        created.append(k)
        return k

    yield _make
    for k in created:
        k.close()
