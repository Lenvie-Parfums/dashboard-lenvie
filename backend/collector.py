from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx

from omie_client import OmieClient, OmieHardBlock, OmieError
from depara import get_depara, reset_depara
import db

log = logging.getLogger("collector")

CFOPS_VENDA = {
    "5101", "5102", "5103", "5104", "5105", "5106", "5109", "5110",
    "5115", "5116", "5117", "5118", "5119", "5120", "5122", "5123",
    "5401", "5402", "5403", "5405",
    "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108",
    "6109", "6110", "6115", "6116", "6117", "6118", "6119", "6120",
    "6122", "6123", "6401", "6402", "6403", "6404",
    "7101", "7102",
    "5910", "6910",
}


async def _build_client(http: httpx.AsyncClient) -> OmieClient:
    return OmieClient(
        app_key=os.environ["OMIE_APP_KEY"],
        app_secret=os.environ["OMIE_APP_SECRET"],
        http=http,
    )


async def _carregar_vendedores(omie: OmieClient) -> dict[int, str]:
    cache: dict[int, str] = {}
    try:
        async for v in omie.paginate(
            "geral/vendedores/",
            "ListarVendedores",
            {},
            chave_registros="cadastro",
            por_pagina=100,
        ):
            cod  = v.get("nCodVend") or v.get("codigo")
            nome = v.get("cNome") or v.get("nome") or ""
            if cod:
                cache[int(cod)] = nome.strip().upper()
        log.info("Vendedores carregados: %d", len(cache))
    except Exception as e:
        log.warning("Falha ao carregar vendedores: %s", e)
    return cache


async def _consultar_cliente(
    omie: OmieClient,
    cod_cliente: int,
    vendedores: dict[int, str],
) -> dict:
    """Consulta um único cliente pelo código. Retorna dict com os dados."""
    try:
        resp = await omie.call("ConsultarCliente", "geral/clientes/", {
            "codigo_cliente_omie": cod_cliente,
        })
        cod_vend = resp.get("codigo_vendedor") or resp.get("nCodVend") or 0
        rep = vendedores.get(int(cod_vend), "") if cod_vend else ""
        return {
            "cod_cliente": cod_cliente,
            "nome":   (resp.get("razao_social") or resp.get("nome_fantasia") or "").strip(),
            "cnpj":   (resp.get("cnpj_cpf") or "").strip(),
            "cidade": (resp.get("cidade") or "").strip(),
            "uf":     (resp.get("estado") or "").strip().upper(),
            "rep":    rep,
        }
    except Exception as e:
        log.warning("Falha ao consultar cliente %d: %s", cod_cliente, e)
        return {"cod_cliente": cod_cliente, "nome": "", "cnpj": "", "cidade": "", "uf": "", "rep": ""}


def _extrair_chave(nf: dict) -> str:
    chave = (nf.get("compl") or {}).get("cChaveNFe", "").strip()
    if chave:
        return chave
    chave = str(nf.get("cChaveNFe") or nf.get("chave_nfe") or "").strip()
    if chave:
        return chave
    nid = nf.get("nIdNF") or (nf.get("compl") or {}).get("nIdNF") or ""
    if nid:
        return f"OMIE-{nid}"
    ide = nf.get("ide") or {}
    nnf = ide.get("nNF") or nf.get("nNF") or ""
    serie = ide.get("serie") or nf.get("serie") or ""
    if nnf:
        return f"NF-{nnf}-{serie}"
    return ""


async def _processar_itens(nf: dict, clientes_cache: dict[int, dict], depara, omie_ref: list, vendedores_ref: list) -> list[dict]:
    chave_nf = _extrair_chave(nf)
    if not chave_nf:
        return []

    ide = nf.get("ide") or {}
    data_emissao = ide.get("dEmi") or nf.get("dEmi") or ""
    try:
        dt = datetime.strptime(data_emissao, "%d/%m/%Y")
        ano, mes = dt.year, dt.month
    except ValueError:
        return []

    dest = nf.get("nfDestInt") or {}
    try:
        cod_cliente = int(dest.get("nCodCli") or nf.get("nCodCli") or 0)
    except (ValueError, TypeError):
        cod_cliente = 0

    if cod_cliente and cod_cliente not in clientes_cache:
        # Cliente novo — consulta Omie e salva no banco e cache
        cli_novo = await _consultar_cliente(omie_ref[0], cod_cliente, vendedores_ref[0])
        clientes_cache[cod_cliente] = cli_novo
        db.upsert_clientes([cli_novo])

    cli_info = clientes_cache.get(cod_cliente, {})
    rep = cli_info.get("rep") or "N/D"
    uf  = cli_info.get("uf")  or "N/D"

    linhas = []
    det = nf.get("det") or []
    if not det:
        return []

    for item in det:
        prod = item.get("prod") or item

        cfop = str(prod.get("CFOP") or prod.get("cfop") or prod.get("cCFOP") or "").strip()
        cfop_limpo = cfop.replace(".", "")
        if cfop and cfop_limpo not in CFOPS_VENDA and cfop not in CFOPS_VENDA:
            continue

        sku = str(
            prod.get("cProd") or prod.get("cCodigo") or prod.get("cCodProd") or ""
        ).strip()
        descricao = str(
            prod.get("xProd") or prod.get("cDescrProduto") or prod.get("cDescr") or ""
        ).strip().upper()

        try:
            fat = float(
                prod.get("vProd") or prod.get("nValorTotal") or
                prod.get("vTotItem") or prod.get("nValItem") or 0
            )
            qtd = float(
                prod.get("qCom") or prod.get("nQtde") or
                prod.get("nQtdItem") or 0
            )
        except (ValueError, TypeError):
            fat, qtd = 0.0, 0.0

        if fat <= 0 or qtd <= 0:
            continue

        linha, categoria = await depara.resolver_async(sku, descricao)

        linhas.append({
            "ano": ano, "mes": mes, "uf": uf, "rep": rep,
            "linha": linha, "categoria": categoria, "fragancia": "Outros",
            "cod_cliente": cod_cliente,
            "item": descricao or sku,
            "fat": round(fat, 2), "qtd": round(qtd, 4),
            "chave_nf": chave_nf,
        })
    return linhas


async def coletar(data_ini: str, data_fim: str) -> dict:
    log.info("Coleta incremental iniciada: %s → %s", data_ini, data_fim)
    db.set_status(em_andamento=1, erro=None, data_ini=data_ini, data_fim=data_fim)
    db.set_cancelar(0)

    chaves_existentes = db.get_chaves_faturamento_existentes()
    log.info("Notas já cadastradas no banco local: %d chaves", len(chaves_existentes))

    total_nfs = 0
    nfs_ignoradas = 0
    total_registros = 0

    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            omie = await _build_client(http)
            vendedores = await _carregar_vendedores(omie)

            # Clientes: carrega do banco o que já existe, consulta Omie só os novos
            clientes_cache: dict[int, dict] = db.get_todos_clientes()
            log.info("Clientes já no banco: %d", len(clientes_cache))

            reset_depara()
            cache_produtos = db.get_todos_produtos_cache()
            depara = get_depara(omie_client=omie, cache_inicial=cache_produtos)
            log.info("Depara: %d SKUs já em cache no banco", len(cache_produtos))

            lote: list[dict] = []

            async for nf in omie.paginate(
                "produtos/nfconsultar/",
                "ListarNF",
                {"tpNF": "1", "dEmiInicial": data_ini, "dEmiFinal": data_fim},
                chave_registros="nfCadastro",
                por_pagina=20,
            ):
                if db.deve_cancelar():
                    log.info("Cancelado pelo usuário em %d NFs", total_nfs)
                    db.set_status(em_andamento=0, erro="Cancelado pelo usuário")
                    return {"ok": False, "erro": "Cancelado", "total_nfs": total_nfs}

                total_nfs += 1
                chave_nf = _extrair_chave(nf)

                if chave_nf and chave_nf in chaves_existentes:
                    nfs_ignoradas += 1
                    continue

                # ListarNF não retorna os itens (det) — precisa ConsultarNF
                nid = nf.get("nIdNF") or (nf.get("compl") or {}).get("nIdNF")
                cChaveNFe = (nf.get("compl") or {}).get("cChaveNFe") or nf.get("cChaveNFe") or ""
                if nid or cChaveNFe:
                    try:
                        param_consulta = {}
                        if cChaveNFe:
                            param_consulta["cChaveNFe"] = cChaveNFe
                        elif nid:
                            param_consulta["nIdNF"] = int(nid)
                        nf_completa = await omie.call("ConsultarNF", "produtos/nfconsultar/", param_consulta)
                        if nf_completa and not nf_completa.get("faultstring"):
                            nf = nf_completa
                    except Exception as e:
                        log.warning("Falha ao consultar NF completa nIdNF=%s chave=%s: %s", nid, cChaveNFe, e)

                itens = await _processar_itens(nf, clientes_cache, depara, [omie], [vendedores])
                lote.extend(itens)
                
                if len(lote) >= 100:
                    total_registros += db.upsert_faturamento(lote)
                    lote.clear()

                if total_nfs % 200 == 0:
                    log.info("Progresso: %d NFs varridas (%d novas processadas, %d ignoradas) — novos registros: %d",
                        total_nfs, total_nfs - nfs_ignoradas, nfs_ignoradas, total_registros)

            if lote:
                total_registros += db.upsert_faturamento(lote)
                lote.clear()

            if depara.pendentes_gravar:
                for sku, info in depara.pendentes_gravar.items():
                    db.upsert_produto_cache(sku, info.get("descricao", ""), info["linha"], info["categoria"])
                log.info("Depara: %d novos SKUs consultados no Omie e salvos no cache", len(depara.pendentes_gravar))

        log.info("RESULTADO FINAL: total_nfs=%d, nfs_ignoradas=%d, novos_registros=%d",
            total_nfs, nfs_ignoradas, total_registros)

        db.set_status(
            em_andamento=0,
            ultima_coleta=datetime.now().isoformat(),
            total_nfs=total_nfs,
            total_registros=total_registros,
            erro=None,
        )
        return {"ok": True, "total_nfs": total_nfs, "nfs_ignoradas": nfs_ignoradas, "total_registros": total_registros}

    except OmieHardBlock as e:
        msg = f"API bloqueada: {e}"
        log.error(msg)
        db.set_status(em_andamento=0, erro=msg)
        return {"ok": False, "erro": msg}

    except Exception as e:
        log.exception("Erro na coleta")
        db.set_status(em_andamento=0, erro=str(e))
        return {"ok": False, "erro": str(e)}
