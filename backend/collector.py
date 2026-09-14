"""
Collector — coleta NF-e do Omie, extrai itens, enriquece com de-para.

Fluxo:
  1. ListarNF  (filtro por data) → lista de chaves NF-e
  2. Para cada NF → extrai itens (det[])
  3. Resolve SKU → lin/cat/fr via DePara
  4. Resolve cliente → nome/cnpj/cidade via cache de ListarClientes
  5. Grava no banco (upsert — idempotente)

CFOPs considerados faturamento de venda:
  5.102, 5.405, 6.102, 6.108, 6.403  (saída de produto)
  Exclui 5.910/6.910 (remessas/brindes) e devoluções (1.xxx/2.xxx)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, date
from typing import Any

import httpx

from omie_client import OmieClient, OmieHardBlock, OmieError
from depara import get_depara
import db

log = logging.getLogger("collector")

# CFOPs de saída de venda — ajuste se necessário
CFOPS_VENDA = {
    "5102", "5405", "5401", "5403",
    "6102", "6108", "6403", "6404",
    "5115", "6115",
}

# UF por código de estado IBGE (para enriquecimento de cliente)
IBGE_UF: dict[int, str] = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL",
    28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
    42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}


async def _build_client(http: httpx.AsyncClient) -> OmieClient:
    return OmieClient(
        app_key=os.environ["OMIE_APP_KEY"],
        app_secret=os.environ["OMIE_APP_SECRET"],
        http=http,
    )


async def _carregar_clientes(omie: OmieClient) -> dict[int, dict]:
    """
    Carrega todos os clientes do Omie em memória.
    Retorna {cod_cliente: {nome, cnpj, cidade, uf}}.
    Fazemos isso uma vez por coleta para evitar ConsultarCliente item a item
    (que estoura rate limit).
    """
    cache: dict[int, dict] = {}
    log.info("Carregando clientes do Omie...")
    async for cli in omie.paginate(
        "geral/clientes/",
        "ListarClientes",
        {"clientesFiltro": {}, "clientesPadrao": {"camposRetorno": [
            "codigo_cliente_omie", "razao_social", "cnpj_cpf",
            "cidade", "estado", "codigo_vendedor"
        ]}},
        chave_registros="clientes_cadastro",
        por_pagina=50,
    ):
        cod = cli.get("codigo_cliente_omie")
        if not cod:
            continue
        cache[int(cod)] = {
            "cod_cliente": int(cod),
            "nome": cli.get("razao_social", ""),
            "cnpj": cli.get("cnpj_cpf", ""),
            "cidade": cli.get("cidade", ""),
            "uf": cli.get("estado", ""),
            "rep": "",  # preenchido via NF
        }
    log.info("Clientes carregados: %d", len(cache))
    return cache


async def _listar_nfs(
    omie: OmieClient,
    data_ini: str,
    data_fim: str,
) -> list[dict]:
    """
    Retorna lista de NFs no período.
    data_ini / data_fim: formato DD/MM/AAAA
    Filtra: tpNF=1 (saída), status=N (normal/autorizada)
    """
    nfs = []
    async for nf in omie.paginate(
        "produtos/nfconsultar/",
        "ListarNF",
        {
            "tpNF": "1",
            "filtrar_por_status": "N",
            "dEmiInicial": data_ini,
            "dEmiFinal": data_fim,
        },
        chave_registros="nfCadastro",
        por_pagina=50,
    ):
        nfs.append(nf)
    log.info("NFs listadas no período %s→%s: %d", data_ini, data_fim, len(nfs))
    return nfs


def _extrair_rep(nf: dict) -> str:
    """Extrai nome do vendedor/representante da NF."""
    # Tenta em vários campos possíveis
    inf = nf.get("compl") or {}
    return (
        inf.get("cVendedor")
        or nf.get("cVendedor")
        or ""
    ).strip().upper()


def _extrair_uf_dest(nf: dict) -> str:
    """UF do destinatário."""
    dest = nf.get("nfDestInt") or {}
    return (dest.get("cUF") or "").strip().upper()


def _processar_itens(
    nf: dict,
    clientes_cache: dict[int, dict],
    depara,
) -> list[dict]:
    """
    Extrai linhas de faturamento de uma NF.
    Retorna lista de dicts prontos para upsert_faturamento.
    """
    chave_nf = (nf.get("chave") or nf.get("cChaveNFe") or "").strip()
    if not chave_nf:
        log.warning("NF sem chave NF-e — pulando")
        return []

    # Data de emissão
    data_emissao = nf.get("dEmi") or nf.get("ide", {}).get("dEmi") or ""
    try:
        dt = datetime.strptime(data_emissao, "%d/%m/%Y")
        ano, mes = dt.year, dt.month
    except ValueError:
        log.warning("Data inválida na NF %s: %s", chave_nf, data_emissao)
        return []

    # Cliente
    dest = nf.get("nfDestInt") or {}
    cod_cliente_raw = dest.get("nCodCli") or nf.get("nCodCli") or 0
    try:
        cod_cliente = int(cod_cliente_raw)
    except (ValueError, TypeError):
        cod_cliente = 0

    uf = _extrair_uf_dest(nf)
    rep = _extrair_rep(nf)

    # Atualiza rep no cache de clientes
    if cod_cliente and cod_cliente in clientes_cache:
        if not clientes_cache[cod_cliente].get("rep"):
            clientes_cache[cod_cliente]["rep"] = rep
        if not clientes_cache[cod_cliente].get("uf") and uf:
            clientes_cache[cod_cliente]["uf"] = uf

    linhas = []
    itens = nf.get("det") or []
    for item in itens:
        prod = item.get("prod") or {}

        # Filtra por CFOP de venda
        cfop = str(prod.get("CFOP") or "").strip()
        if cfop and cfop not in CFOPS_VENDA:
            continue

        sku = str(prod.get("cCodigo") or prod.get("cProduto") or "").strip()
        descricao = str(prod.get("cDescrProduto") or prod.get("cDescr") or "").strip().upper()

        try:
            fat = float(prod.get("nValorTotal") or prod.get("vProd") or 0)
            qtd = float(prod.get("nQtde") or prod.get("qCom") or 0)
        except (ValueError, TypeError):
            fat, qtd = 0.0, 0.0

        if fat <= 0 or qtd <= 0:
            continue

        linha, categoria, fragancia = depara.resolver(sku, descricao)

        linhas.append({
            "ano": ano,
            "mes": mes,
            "uf": uf or "N/D",
            "rep": rep or "N/D",
            "linha": linha,
            "categoria": categoria,
            "fragancia": fragancia,
            "cod_cliente": cod_cliente,
            "item": descricao or sku,
            "fat": round(fat, 2),
            "qtd": round(qtd, 4),
            "chave_nf": chave_nf,
        })

    return linhas


async def coletar(data_ini: str, data_fim: str) -> dict:
    """
    Ponto de entrada principal.
    data_ini / data_fim: formato DD/MM/AAAA
    Retorna resumo da coleta.
    """
    log.info("Iniciando coleta %s → %s", data_ini, data_fim)
    db.set_status(em_andamento=1, erro=None, data_ini=data_ini, data_fim=data_fim)
    depara = get_depara()

    total_nfs = 0
    total_registros = 0
    clientes_gravados = set()

    try:
        async with httpx.AsyncClient() as http:
            omie = await _build_client(http)

            # 1. Carrega clientes
            clientes_cache = await _carregar_clientes(omie)

            # 2. Lista NFs no período
            nfs = await _listar_nfs(omie, data_ini, data_fim)
            total_nfs = len(nfs)

            # 3. Processa itens de cada NF
            lote: list[dict] = []
            LOTE_SIZE = 500

            for i, nf in enumerate(nfs):
                linhas = _processar_itens(nf, clientes_cache, depara)
                lote.extend(linhas)

                # Grava por lote para não perder progresso em coletas longas
                if len(lote) >= LOTE_SIZE:
                    total_registros += db.upsert_faturamento(lote)
                    lote = []

                if (i + 1) % 50 == 0:
                    log.info("Progresso: %d/%d NFs processadas", i + 1, total_nfs)
                    db.set_status(total_nfs=i + 1)

            # Grava restante
            if lote:
                total_registros += db.upsert_faturamento(lote)

            # 4. Grava clientes enriquecidos
            clientes_lista = list(clientes_cache.values())
            db.upsert_clientes(clientes_lista)

        skus_desconhecidos = depara.skus_desconhecidos()
        if skus_desconhecidos:
            log.warning(
                "%d SKUs sem de-para: %s",
                len(skus_desconhecidos),
                ", ".join(skus_desconhecidos[:20]),
            )

        db.set_status(
            em_andamento=0,
            ultima_coleta=datetime.now().isoformat(),
            total_nfs=total_nfs,
            total_registros=total_registros,
            erro=None,
        )

        return {
            "ok": True,
            "total_nfs": total_nfs,
            "total_registros": total_registros,
            "skus_desconhecidos": skus_desconhecidos[:50],
        }

    except OmieHardBlock as e:
        msg = f"API bloqueada por consumo indevido: {e}"
        log.error(msg)
        db.set_status(em_andamento=0, erro=msg)
        return {"ok": False, "erro": msg}

    except Exception as e:
        msg = str(e)
        log.exception("Erro na coleta")
        db.set_status(em_andamento=0, erro=msg)
        return {"ok": False, "erro": msg}
