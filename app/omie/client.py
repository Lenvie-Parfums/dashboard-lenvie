import time
import requests

class OmieClient:
    def __init__(self, app_key, app_secret, timeout=90):
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = timeout
        self.session = requests.Session()

    def call(self, endpoint, call, param=None, retries=4):
        payload = {"call": call, "app_key": self.app_key, "app_secret": self.app_secret, "param": [param or {}]}
        last = None
        for attempt in range(retries):
            try:
                r = self.session.post(endpoint, json=payload, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                if data.get("faultstring"):
                    raise RuntimeError(data["faultstring"])
                return data
            except Exception as exc:
                last = exc
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise last

    def paginate(self, endpoint, call, list_keys, extra=None, page_size=500, progress=None):
        page, total_pages, out = 1, 1, []
        while page <= total_pages:
            param = {"pagina": page, "registros_por_pagina": page_size}
            param.update(extra or {})
            data = self.call(endpoint, call, param)
            rows = []
            for key in list_keys:
                if isinstance(data.get(key), list):
                    rows = data[key]
                    break
            out.extend(rows)
            total_pages = int(data.get("total_de_paginas") or data.get("total_paginas") or 1)
            if progress:
                progress(page, total_pages, len(rows), len(out))
            page += 1
        return out
