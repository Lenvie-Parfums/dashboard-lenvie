"""
Collector — coleta NF-e do Omie, extrai itens, enriquece com de-para.

Campos confirmados via diagnóstico (14/09/2026):
  compl.cChaveNFe  → chave NF-e
  ide.dEmi         → data emissão
  nfDestInt.nCodCli → código cliente
  pedido: {}        → VAZIO, rep não vem na NF
  Rep vem de: ListarVendedores + ListarClientes.codigo_vendedor
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx

from omie_client import OmieClient, OmieHardBlock, OmieError
from depara import get_depara
import db

log = logging.getLogger("collector")

CFOPS_VENDA = {
    "5102", "5405", "5401", "5403",
    "6102", "6108", "6403", "6404",
    "5115", "6115",
}


async def _build_client(http: httpx.AsyncClient) -> OmieClient:
    return OmieClient(
        app_key=os.environ["OMIE_APP_KEY"],
        app_secret=os.environ["OMIE_APP_SECRET"],
        http=http,
    )


async def _carregar_vendedores(omie: OmieClient) -> dict[int, str]:
    """Retorna {cod_vendedor: nome}."""
    cache: dict[int, str] = {}
    try:
        async for v in omie.paginate(
            "geral/vendedores/",
            "ListarVendedores",
            {},
            chave_registros="cadastro",
            por_pagina=50,
        ):
            cod  = v.get("nCodVend") or v.get("codigo")
            nome = v.get("cNome") or v.get("nome") or ""
            if cod:
                cache[int(cod)] = nome.strip().upper()
        log.info("Vendedores: %d", len(cache))
    except Exception as e:
        log.warning("Falha ao carregar vendedores: %s", e)
    return cache


async def _carregar_clientes(
    omie: OmieClient,
    vendedores: dict[int, str],
) -> dict[int, dict]:
    """Retorna {cod_cliente: {nome, cnpj, cidade, uf, rep}}."""
    cache: dict[int, dict] = {}
    log.info("Carregando clientes...")
    async for cli in omie.paginate(
        "geral/clientes/",
        "ListarClientes",
        {"clientesFiltro": {}},
        chave_registros="clientes_cadastro",
        por_pagina=50,
    ):
        cod = cli.get("codigo_cliente_omie")
        if not cod:
            continue
        cod_vend = cli.get("codigo_vendedor") or 0
        rep = vendedores.get(int(cod_vend), "") if cod_vend else ""
        cache[int(cod)] = {
            "cod_cliente": int(cod),
            "nome":   (cli.get("razao_social") or "").strip(),
            "cnpj":   (cli.get("cnpj_cpf") or "").strip(),
            "cidade": (cli.get("cidade") or "").strip(),
            "uf":     (cli.get("estado") or "").strip().upper(),
            "rep":    rep,
        }
    log.info("Clientes: %d", len(cache))
    return cache


async def _listar_nfs(omie: OmieClient, data_ini: str, data_fim: str) -> list[dict]:
    nfs = []
    async for nf in omie.paginate(
        "produtos/nfconsultar/",
        "ListarNF",
        {"tpNF": "1", "filtrar_por_status": "N",
         "dEmiInicial": data_ini, "dEmiFinal": data_fim},
        chave_registros="nfCadastro",
        por_pagina=50,
    ):
        nfs.append(nf)
    log.info("NFs %s→%s: %d", data_ini, data_fim, len(nfs))
    return nfs


def _processar_itens(nf: dict, clientes_cache: dict[int, dict], depara) -> list[dict]:
    compl    = nf.get("compl") or {}
    chave_nf = compl.get("cChaveNFe", "").strip()
    if not chave_nf:
        return []

    data_emissao = (nf.get("ide") or {}).get("dEmi", "")
    try:
        dt = datetime.strptime(data_emissao, "%d/%m/%Y")
        ano, mes = dt.year, dt.month
    except ValueError:
        return []

    dest = nf.get("nfDestInt") or {}
    try:
        cod_cliente = int(dest.get("nCodCli") or 0)
    except (ValueError, TypeError):
        cod_cliente = 0

    cli_info = clientes_cache.get(cod_cliente, {})
    rep = cli_info.get("rep") or "N/D"
    uf  = cli_info.get("uf")  or "N/D"

    linhas = []
    for item in (nf.get("det") or []):
        prod = item.get("prod") or {}
        cfop = str(prod.get("CFOP") or "").strip()
        if cfop and cfop not in CFOPS_VENDA:
            continue

        sku       = str(prod.get("cCodigo") or "").strip()
        descricao = str(prod.get("cDescrProduto") or "").strip().upper()

        try:
            fat = float(prod.get("nValorTotal") or 0)
            qtd = float(prod.get("nQtde") or 0)
        except (ValueError, TypeError):
            fat, qtd = 0.0, 0.0

        if fat <= 0 or qtd <= 0:
            continue

        linha, categoria, fragancia = depara.resolver(sku, descricao)

        linhas.append({
            "ano": ano, "mes": mes, "uf": uf, "rep": rep,
            "linha": linha, "categoria": categoria, "fragancia": fragancia,
            "cod_cliente": cod_cliente,
            "item": descricao or sku,
            "fat": round(fat, 2), "qtd": round(qtd, 4),
            "chave_nf": chave_nf,
        })
    return linhas


async def coletar(data_ini: str, data_fim: str) -> dict:
    log.info("Coleta %s → %s", data_ini, data_fim)
    db.set_status(em_andamento=1, erro=None, data_ini=data_ini, data_fim=data_fim)
    db.set_cancelar(0)  # reseta flag ao iniciar
    depara = get_depara()

    total_nfs = 0
    total_registros = 0

    try:
        async with httpx.AsyncClient() as http:
            omie = await _build_client(http)
            vendedores     = await _carregar_vendedores(omie)
            clientes_cache = await _carregar_clientes(omie, vendedores)
            nfs = await _listar_nfs(omie, data_ini, data_fim)
            total_nfs = len(nfs)

            lote: list[dict] = []
            for i, nf in enumerate(nfs):
                if db.deve_cancelar():
                    log.info("Coleta cancelada pelo usuário em %d/%d NFs", i, total_nfs)
                    db.set_status(em_andamento=0, erro="Cancelado pelo usuário")
                    return {"ok": False, "erro": "Cancelado pelo usuário", "total_nfs": i}

                lote.extend(_processar_itens(nf, clientes_cache, depara))
                if len(lote) >= 500:
                    total_registros += db.upsert_faturamento(lote)
                    lote = []
                if (i + 1) % 100 == 0:
                    log.info("Progresso: %d/%d", i + 1, total_nfs)

            if lote:
                total_registros += db.upsert_faturamento(lote)

            db.upsert_clientes(list(clientes_cache.values()))

        db.set_status(
            em_andamento=0,
            ultima_coleta=datetime.now().isoformat(),
            total_nfs=total_nfs,
            total_registros=total_registros,
            erro=None,
        )
        return {"ok": True, "total_nfs": total_nfs, "total_registros": total_registros}

    except OmieHardBlock as e:
        msg = f"API bloqueada: {e}"
        log.error(msg)
        db.set_status(em_andamento=0, erro=msg)
        return {"ok": False, "erro": msg}

    except Exception as e:
        log.exception("Erro na coleta")
        db.set_status(em_andamento=0, erro=str(e))
        return {"ok": False, "erro": str(e)}
