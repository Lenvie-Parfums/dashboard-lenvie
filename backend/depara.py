from __future__ import annotations
import re
import logging

log = logging.getLogger("depara")

# Mapeamento de categoria baseado na descrição do produto
# Padrão da descrição: "CATEGORIA FRAGÂNCIA - LINHA - VOLUME"
# Ex: "AGUA PERFUMADA FIGO AMBARADO - ARABESC - 500ML"
#     "DIFUSOR DE PERFUME FIGO - ARABESC - 200ML"
#     "VELA PERFUMADA INTO THE NIGHT - CLASSIC - 210G"

CATEGORIAS_CONHECIDAS = [
    "AGUA PERFUMADA",
    "AGUA SPLASH",
    "DIFUSOR DE PERFUME",
    "HOME SPRAY",
    "SABONETE LIQUIDO",
    "SABONETE EM BARRA",
    "OLEO CONCENTRADO",
    "REFIL DIFUSOR",
    "REFIL SAB",
    "VELA PERF",
    "VELA PERFUMADA",
    "BODY MIST",
    "BODY CREAM",
    "CREME DE MAO",
    "BARRA DE CERA",
    "KIT",
    "EDP",
    "PERFUMES",
    "CORPO",
    "ACESSORIOS",
    "ACESSÓRIOS",
]

CATEGORIA_NORMALIZADA = {
    "VELA PERF": "VELA",
    "VELA PERFUMADA": "VELA",
    "REFIL SAB": "REFIL SAB",
    "SABONETE EM BARRA": "SABONETE EM BARRA",
    "BODY MIST": "CORPO",
    "BODY CREAM": "CORPO",
    "CREME DE MAO": "CORPO",
    "EDP": "PERFUMES",
}


def extrair_linha_categoria(descricao: str) -> tuple[str, str]:
    """
    Extrai linha e categoria da descrição do produto.
    Padrão: "CATEGORIA FRAGANCIA - LINHA - VOLUME"
    Ex: "AGUA PERFUMADA FIGO AMBARADO - ARABESC - 500ML"
      → linha="ARABESC", categoria="AGUA PERFUMADA"
    """
    if not descricao:
        return ("Outros", "Outros")

    desc = descricao.strip().upper()
    partes = [p.strip() for p in desc.split(" - ")]

    # Linha = segundo segmento (índice 1)
    linha = "Outros"
    if len(partes) >= 2:
        linha = partes[1].strip()
        # Remove volume se ficou junto (ex: "ARABESC 500ML")
        linha = re.sub(r'\s+\d+.*$', '', linha).strip()
        if not linha:
            linha = "Outros"

    # Categoria = extraída do primeiro segmento
    categoria = "Outros"
    primeiro = partes[0] if partes else ""
    for cat in sorted(CATEGORIAS_CONHECIDAS, key=len, reverse=True):
        if primeiro.startswith(cat):
            categoria = CATEGORIA_NORMALIZADA.get(cat, cat)
            break

    return (linha, categoria)


class DeparaResolver:
    """
    Resolve linha/categoria de um item de NF a partir da descrição do produto.

    Ordem de resolução:
      1. Cache em memória (carregado do banco no início da coleta)
      2. Extração da descrição (padrão: CATEGORIA - LINHA - VOLUME)
      3. Salva no cache para não repetir
    """

    def __init__(self, omie_client=None, cache_inicial: dict[str, dict] | None = None):
        self.omie = omie_client  # mantido por compatibilidade, não usado
        self.cache: dict[str, dict] = dict(cache_inicial or {})
        self.pendentes_gravar: dict[str, dict] = {}

    async def resolver_async(self, sku: str, descricao: str) -> tuple[str, str]:
        sku = (sku or "").strip()

        # 1. Cache em memória
        if sku and sku in self.cache:
            info = self.cache[sku]
            return (info.get("linha") or "Outros", info.get("categoria") or "Outros")

        # 2. Extrair da descrição
        linha, categoria = extrair_linha_categoria(descricao)

        # 3. Salvar no cache
        if sku:
            info = {"descricao": descricao, "linha": linha, "categoria": categoria}
            self.cache[sku] = info
            self.pendentes_gravar[sku] = info

        return (linha, categoria)


_instancia: DeparaResolver | None = None


def get_depara(omie_client=None, cache_inicial: dict[str, dict] | None = None) -> DeparaResolver:
    global _instancia
    if _instancia is None:
        _instancia = DeparaResolver(omie_client=omie_client, cache_inicial=cache_inicial)
    return _instancia


def reset_depara() -> None:
    global _instancia
    _instancia = None