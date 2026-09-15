from __future__ import annotations
import logging
import httpx

log = logging.getLogger("omie")


class OmieError(Exception):
    pass


class OmieHardBlock(OmieError):
    pass


class OmieClient:
    def __init__(self, app_key: str, app_secret: str, http: httpx.AsyncClient):
        self.app_key = app_key
        self.app_secret = app_secret
        self.http = http
        self.base_url = "https://app.omie.com.br/api/v1/"

    async def call(self, call: str, endpoint: str, param: dict) -> dict:
        url = self.base_url + endpoint.strip("/") + "/"
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "call": call,
            "param": [param],
        }
        try:
            resp = await self.http.post(url, json=payload, timeout=60.0)
            if resp.status_code == 429:
                raise OmieError("Rate limit (429) atingido no Omie.")
            if resp.status_code == 404:
                # NF não encontrada — retorna dict vazio para o caller decidir
                return {}
            if resp.status_code >= 400:
                body = resp.text
                if "bloqueio" in body.lower() or "limite" in body.lower():
                    raise OmieHardBlock(f"Bloqueio Omie: {body}")
                raise OmieError(f"Erro HTTP {resp.status_code}: {body}")
            
            data = resp.json()
            if "faultstring" in data:
                err = data["faultstring"]
                if "bloqueio" in err.lower() or "limite" in err.lower():
                    raise OmieHardBlock(err)
                raise OmieError(err)
            return data
        except httpx.TimeoutException:
            raise OmieError(f"Timeout ao chamar {endpoint} ({call})")

    async def paginate(self, endpoint: str, call: str, param_base: dict,
                         chave_registros: str, por_pagina: int = 200):
        pagina = 1
        while True:
            param = {**param_base, "pagina": pagina, "registros_por_pagina": por_pagina}
            data = await self.call(call, endpoint, param)
            
            registros = data.get(chave_registros) or []
            if not registros:
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        registros = v
                        break
            if not registros:
                break

            for reg in registros:
                yield reg

            total_paginas = data.get("total_de_paginas") or data.get("nTotPag") or 1
            if pagina >= total_paginas:
                break
            pagina += 1
