from __future__ import annotations
import logging

log = logging.getLogger("depara")

# Campos candidatos no retorno do ConsultarProduto do Omie para linha/categoria.
# Ajustados a partir do diagnóstico real do endpoint geral/produtos/.
CAMPOS_LINHA = ["familia_produto", "descricao_familia", "linha_produto", "linha"]
CAMPOS_CATEGORIA = ["categoria", "descricao_categoria", "tipo_item"]


class DeparaResolver:
    """
    Resolve linha/categoria de um item de nota fiscal a partir do SKU (código do produto).

    Ordem de resolução:
      1. Cache em memória (carregado do banco no início da coleta)
      2. Consulta direta à API do Omie (ConsultarProduto) — resultado salvo no cache
      3. Se a API não retornar nada utilizável, usa "Outros" (nunca usa CSV nem
         inferência por palavra-chave na descrição)
    """

    def __init__(self, omie_client=None, cache_inicial: dict[str, dict] | None = None):
        self.omie = omie_client
        self.cache: dict[str, dict] = dict(cache_inicial or {})
        self.pendentes_gravar: dict[str, dict] = {}

    async def resolver_async(self, sku: str, descricao: str) -> tuple[str, str]:
        sku = (sku or "").strip()
        if not sku:
            return ("Outros", "Outros")

        if sku in self.cache:
            info = self.cache[sku]
            return (info.get("linha") or "Outros", info.get("categoria") or "Outros")

        if self.omie is None:
            return ("Outros", "Outros")

        try:
            resp = await self.omie.call("ConsultarProduto", "geral/produtos/", {
                "codigo_produto_integracao": "",
                "codigo": sku,
            })
        except Exception as e:
            log.warning("Falha ao consultar produto %s no Omie: %s", sku, e)
            return ("Outros", "Outros")

        linha = self._primeiro_campo(resp, CAMPOS_LINHA) or "Outros"
        categoria = self._primeiro_campo(resp, CAMPOS_CATEGORIA) or "Outros"

        info = {"descricao": descricao, "linha": linha, "categoria": categoria}
        self.cache[sku] = info
        self.pendentes_gravar[sku] = info

        return (linha, categoria)

    @staticmethod
    def _primeiro_campo(resp: dict, campos: list[str]) -> str | None:
        for campo in campos:
            valor = resp.get(campo)
            if valor:
                return str(valor).strip().upper()
        return None


_instancia: DeparaResolver | None = None


def get_depara(omie_client=None, cache_inicial: dict[str, dict] | None = None) -> DeparaResolver:
    global _instancia
    if _instancia is None:
        _instancia = DeparaResolver(omie_client=omie_client, cache_inicial=cache_inicial)
    return _instancia


def reset_depara() -> None:
    """Usado no início de cada coleta para recarregar o cache do banco."""
    global _instancia
    _instancia = None
