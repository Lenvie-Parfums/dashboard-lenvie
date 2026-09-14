"""
Cliente Omie — rate limit, retry seletivo, paginação.
Baseado no padrão Lenvie de produção.
Credenciais SEMPRE via variável de ambiente.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger("omie")

BASE_URL = "https://app.omie.com.br/api/v1"

TRANSIENT_MARKERS = (
    "consumo redundante",
    "redundant",
    "processo ja em andamento",
    "processo já em andamento",
    "ja existe uma requisicao",
    "já existe uma requisição",
    "bloqueado por concorr",
    "tente novamente",
    "timeout",
    "servico indisponivel",
    "serviço indisponível",
    "erro interno",
)

HARD_BLOCK_MARKERS = ("misuse_api_process", "bloqueada por consumo indevido")
RETRIABLE_STATUS = {408, 429, 500, 502, 503, 504}


class OmieHardBlock(Exception):
    """API bloqueada por consumo indevido. Não tente de novo nesta execução."""


class OmieError(Exception):
    def __init__(self, code: str | int | None, message: str, payload: Any = None):
        self.code = code
        self.message = message
        self.payload = payload
        super().__init__(f"[{code}] {message}")

    @property
    def transient(self) -> bool:
        msg = (self.message or "").lower()
        return any(m in msg for m in TRANSIENT_MARKERS)


def _espera_sugerida(faultstring: str, padrao: int = 56) -> int:
    m = re.search(r"(\d+)\s*segundos", faultstring or "")
    return int(m.group(1)) if m else padrao


class RateLimiter:
    """Token bucket. Omie tolera ~3 req/s por app_key."""

    def __init__(self, rate_per_sec: float = 3.0, burst: int = 3):
        self.rate = rate_per_sec
        self.capacity = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)


class OmieClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        http: httpx.AsyncClient,
        *,
        rate_per_sec: float = 3.0,
        burst: int = 3,
        max_retries: int = 6,
        timeout: float = 60.0,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.http = http
        self.limiter = RateLimiter(rate_per_sec, burst)
        self.max_retries = max_retries
        self.timeout = timeout

    async def call(self, path: str, method: str, params: dict) -> dict:
        payload = {
            "call": method,
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "param": [params],
        }
        url = f"{BASE_URL}/{path.strip('/')}/"

        for tentativa in range(1, self.max_retries + 1):
            await self.limiter.acquire()
            try:
                resp = await self.http.post(url, json=payload, timeout=self.timeout)
            except httpx.TimeoutException:
                log.warning("timeout %s (%d/%d)", method, tentativa, self.max_retries)
                await asyncio.sleep(10)
                continue

            texto = resp.text or ""
            baixo = texto.lower()

            if any(m in baixo for m in HARD_BLOCK_MARKERS):
                raise OmieHardBlock(texto[:300])

            try:
                data = resp.json()
            except ValueError:
                if resp.status_code in RETRIABLE_STATUS:
                    await asyncio.sleep(self._backoff(tentativa))
                    continue
                raise OmieError(resp.status_code, texto[:300])

            fault = data.get("faultstring")
            if fault:
                err = OmieError(data.get("faultcode"), fault, data)
                if err.transient and tentativa < self.max_retries:
                    espera = _espera_sugerida(fault)
                    log.warning("transitório %ss (%d/%d)", espera, tentativa, self.max_retries)
                    await asyncio.sleep(espera + 2)
                    continue
                raise err

            if resp.status_code in RETRIABLE_STATUS and tentativa < self.max_retries:
                await asyncio.sleep(self._backoff(tentativa))
                continue

            return data

        raise OmieError("RETRY", f"{method}: tentativas esgotadas")

    @staticmethod
    def _backoff(tentativa: int) -> float:
        return min(60.0, 2 ** tentativa) + random.uniform(0, 1.5)

    async def paginate(
        self,
        path: str,
        method: str,
        params: dict,
        *,
        chave_registros: str,
        por_pagina: int = 50,
    ) -> AsyncIterator[dict]:
        """
        registros_por_pagina é silenciosamente limitado a 100 pelo Omie.
        """
        base = {**params, "registros_por_pagina": min(por_pagina, 100)}
        primeira = await self.call(path, method, {**base, "pagina": 1})
        total = int(primeira.get("total_de_paginas", 1))
        log.info("%s: %d páginas", method, total)

        for pagina in range(1, total + 1):
            data = primeira if pagina == 1 else \
                await self.call(path, method, {**base, "pagina": pagina})
            registros = data.get(chave_registros) or []
            if not registros:
                # "Não existem registros" é legítimo, não erro
                break
            for r in registros:
                yield r
            await asyncio.sleep(1.0)  # 1000ms entre páginas: seguro em produção
