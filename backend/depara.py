"""
De-para de produtos — lin / cat / fr por SKU.

Duas camadas:
  1. CSV (depara_produtos.csv) — fonte de verdade, gerado pelo endpoint /gerar-depara
  2. Inferência por palavra-chave — fallback quando o SKU não está no CSV

Formato do CSV:
  sku,descricao,linha,categoria,fragancia
"""

from __future__ import annotations

import csv
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("depara")

CSV_PATH = Path(os.getenv("DEPARA_CSV", "/app/depara_produtos.csv"))

# ── Regras de inferência ────────────────────────────────────────────────

# Linha: palavra-chave no nome do produto → linha comercial
_LINHA_KW: list[tuple[str, list[str]]] = [
    ("ARABESC",          ["arabesc"]),
    ("CLASSIC",          ["classic", "into", "fountain", "lumiere"]),
    ("ELEMENTOS",        ["elemento", " flor ", "musgo", "pessego", "sunset", "legno"]),
    ("ESSENTIA",         ["essentia", "body cream", "body mist", "capuccino", "framboesa", "maracuja"]),
    ("URBAN",            ["urban", "ambar & patchouli", "bergamota & framboesa",
                          "matcha & hinoki", "peonia & lima", "tabaco & vanilla"]),
    ("MAMY",             ["mamy", "carneirinho"]),
    ("AGUA DE COCO",     ["agua de coco", "terra do sol"]),
    ("PATBO",            ["patbo", "lotus garden", "summer pear", "vanilla bloom"]),
    ("MASP",             ["masp", "concreto", " cristal", "vermelho masp"]),
    ("BACIO DI LATTE",   ["bacio", "fragola", "pistacchio", "limoncello"]),
    ("HERBARIUM",        ["herbarium"]),
    ("PERFUMES AUTORAIS",["edp 0", "sao paulo is", "patchoulli affair", "san junipero",
                          "the patchoulli", "falling water", "you had me", "stop it i love",
                          "mood indigo", "idee fixe", "mango a gogo", "ode a cologne",
                          "figorativo", "energy place", "happy place"]),
    ("KIT",              ["kit "]),
    ("ACESSÓRIOS",       ["acessorio", "fosforo", "aromatizador", "difusor elet"]),
    ("ROSEWOOD",         ["rosewood", "floresta noturna"]),
    ("SMILEY",           ["smiley"]),
    ("DECOR",            ["decor"]),
]

# Categoria: palavra-chave → categoria
_CAT_KW: list[tuple[str, list[str]]] = [
    ("DIFUSOR DE PERFUME",  ["dif de perf", "dif de per", "difusor de perf", "difusor de per"]),
    ("REFIL DIFUSOR",       ["ref dif", "refil dif"]),
    ("AGUA PERFUMADA",      ["agua perf"]),
    ("HOME SPRAY",          ["home spray", "hm spray"]),
    ("REFIL HOME SPRAY",    ["refil home", "ref home spray"]),
    ("VELA",                ["vela perf", "vela ", "velas "]),
    ("SABONETE LIQUIDO",    ["sab liq", "sabonete liq"]),
    ("SABONETE EM BARRA",   ["sab barra", "sabonete barra", "sab em barra"]),
    ("REFIL SAB",           ["refil sab", "ref sab"]),
    ("OLEO CONCENTRADO",    ["oleo conc", "óleo conc"]),
    ("BARRA DE CERA",       ["barra de cera", "barra cera"]),
    ("AGUA SPLASH",         ["agua splash"]),
    ("CORPO",               ["body cream", "body mist"]),
    ("PERFUMES",            ["edp ", "tester edp", "tester edt", "edt "]),
    ("KIT",                 ["kit "]),
    ("ACESSÓRIOS",          ["fosforo", "aromatizador", "difusor elet", "caixa"]),
    ("CREME PARA AS MÃOS",  ["creme de mao", "creme para"]),
    ("PROVADOR",            ["provador"]),
]

# Fragrância: token discriminador no nome → fragrância
# Ordem importa: mais específico primeiro
_FR_KW: list[tuple[str, list[str]]] = [
    ("ALECRIM MEDITERRANEO",  ["alecrim"]),
    ("AMBAR & PATCHOULI",     ["ambar"]),
    ("BACIO DI LATTE",        ["bacio", "latte"]),
    ("BERGAMOTA & FRAMBOESA", ["bergamota"]),
    ("CAPUCCINO",             ["capuccino"]),
    ("CITRUS VERBENA",        ["citrus"]),
    ("Concreto",              ["concreto"]),
    ("Cristal",               ["cristal"]),
    ("ENERGY PLACE",          ["energy place"]),
    ("FALLING WATER",         ["falling water"]),
    ("FIGO AMBARADO",         ["figo"]),
    ("FIGORATIVO",            ["figorativo"]),
    ("FLOR DE LARANJEIRA",    ["flor de laranjeira", " flor ", "laranjeira"]),
    ("FLORESTA NOTURNA",      ["floresta noturna", "rosewood"]),
    ("FOUNTAIN",              ["fountain"]),
    ("FRAGOLA",               ["fragola"]),
    ("FRAMBOESA",             ["framboesa"]),
    ("HAPPY PLACE",           ["happy place"]),
    ("IDEE FIXE",             ["idee fixe"]),
    ("INTO THE NIGHT",        ["into the night", " into "]),
    ("LAVANDA ABSOLUTA",      ["lavanda"]),
    ("LEGNO DI MALTA",        ["legno", "malta"]),
    ("LIMONCELLO",            ["limoncello"]),
    ("LOTUS GARDEN",          ["lotus garden"]),
    ("LUMIERE",               ["lumiere"]),
    ("MAGNOLIA PACIFICA",     ["magnolia"]),
    ("MAMY CARNEIRINHO",      ["mamy", "carneirinho"]),
    ("MANDARINA CEYLON",      ["mandarina"]),
    ("MANGO A GOGO",          ["mango a gogo"]),
    ("MARACUJA",              ["maracuja"]),
    ("MATCHA & HINOKI",       ["matcha"]),
    ("MOOD INDIGO",           ["mood indigo"]),
    ("MUSGO DE CARVALHO",     ["musgo"]),
    ("NATAL",                 ["natal 2", "natal 24", "natal 23"]),
    ("ODE A COLOGNE",         ["ode a cologne", "ode à cologne"]),
    ("PATCHOULI VANILLA",     ["patchouli vanilla", "patchouli arab"]),
    ("PEONIA & LIMA",         ["peonia", " lima "]),
    ("PESSEGO ORIENTAL",      ["pessego"]),
    ("PISTACCHIO",            ["pistacchio"]),
    ("SAN JUNIPERO",          ["san junipero"]),
    ("SAO PAULO IS BURNING",  ["sao paulo is", "sao paulo"]),
    ("STOP IT I LOVE",        ["stop it i love"]),
    ("SUMMER PEAR",           ["summer pear"]),
    ("SUNSET ROSE",           ["sunset"]),
    ("TABACO & VANILLA",      ["tabaco"]),
    ("TERRA DO SOL",          ["terra do sol"]),
    ("THE PATCHOULLI AFFAIR", ["patchoulli"]),
    ("VANILLA BLOOM",         ["vanilla bloom"]),
    ("VANILLA",               ["vanilla"]),  # depois de VANILLA BLOOM e PATCHOULI VANILLA
    ("Vermelho",              ["vermelho"]),
    ("YOU HAD ME AT HELLO",   ["you had me", "hello"]),
]


def _norm(texto: str) -> str:
    return " " + re.sub(r"\s+", " ", texto.lower().strip()) + " "


def _inferir_linha(desc: str) -> str:
    d = _norm(desc)
    for linha, kws in _LINHA_KW:
        if any(kw in d for kw in kws):
            return linha
    return "N/D"


def _inferir_categoria(desc: str) -> str:
    d = _norm(desc)
    for cat, kws in _CAT_KW:
        if any(kw in d for kw in kws):
            return cat
    return "N/D"


def _inferir_fragancia(desc: str) -> str:
    d = _norm(desc)
    for fr, kws in _FR_KW:
        if any(kw in d for kw in kws):
            return fr
    return "N/D"


# ── De-para via CSV ─────────────────────────────────────────────────────

class DePara:
    """
    Uso:
        dp = DePara()
        lin, cat, fr = dp.resolver(sku="DIF-FIGO-200", descricao="DIF DE PERF FIGO ARABESC 200ML")
    """

    def __init__(self):
        self._mapa: dict[str, dict] = {}
        self._skus_desconhecidos: set[str] = set()
        self._carregar()

    def _carregar(self) -> None:
        if not CSV_PATH.exists():
            log.warning(
                "depara_produtos.csv não encontrado em %s — usando só inferência",
                CSV_PATH,
            )
            return

        with CSV_PATH.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = (row.get("sku") or "").strip().upper()
                if not sku:
                    continue
                self._mapa[sku] = {
                    "linha":     (row.get("linha")     or "N/D").strip().upper(),
                    "categoria": (row.get("categoria") or "N/D").strip().upper(),
                    "fragancia": (row.get("fragancia") or "N/D").strip(),
                }
        log.info("De-para carregado: %d SKUs do CSV", len(self._mapa))

    def resolver(self, sku: str, descricao: str) -> tuple[str, str, str]:
        """Retorna (linha, categoria, fragancia)."""
        key = sku.strip().upper()

        # 1. CSV tem prioridade
        if key in self._mapa:
            m = self._mapa[key]
            return m["linha"], m["categoria"], m["fragancia"]

        # 2. Inferência por palavra-chave
        linha     = _inferir_linha(descricao)
        categoria = _inferir_categoria(descricao)
        fragancia = _inferir_fragancia(descricao)

        if fragancia == "N/D":
            if key not in self._skus_desconhecidos:
                log.warning("SKU sem fragrância inferida: %s | %s", sku, descricao)
                self._skus_desconhecidos.add(key)

        return linha, categoria, fragancia

    def skus_desconhecidos(self) -> list[str]:
        return sorted(self._skus_desconhecidos)

    def inferir_tudo(self, sku: str, descricao: str) -> dict:
        """Retorna dict com todos os campos inferidos — usado pelo /gerar-depara."""
        return {
            "sku":       sku.strip().upper(),
            "descricao": descricao.strip().upper(),
            "linha":     _inferir_linha(descricao),
            "categoria": _inferir_categoria(descricao),
            "fragancia": _inferir_fragancia(descricao),
        }


@lru_cache(maxsize=1)
def get_depara() -> DePara:
    return DePara()
