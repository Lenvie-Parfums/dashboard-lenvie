import requests
import json
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.sheets.client import SheetsClient
from app.omie.client import OmieClient
from app.omie.resources import ENDPOINTS, normalize_nfe


app = FastAPI(
    title="Lenvie Commercial KPIs",
    version="1.1.0",
)


# ============================================================
# CLIENTES / CONFIG
# ============================================================

def get_omie_client():
    app_key = os.getenv("APP_KEY_OMIE")
    app_secret = os.getenv("APP_SECRET_OMIE")

    if not app_key:
        raise RuntimeError("Variável APP_KEY_OMIE não configurada.")

    if not app_secret:
        raise RuntimeError("Variável APP_SECRET_OMIE não configurada.")

    return OmieClient(
        app_key=app_key,
        app_secret=app_secret,
    )


def get_sheets_client():
    google_sa_json = os.getenv("GOOGLE_SA_JSON")
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")

    if not google_sa_json:
        raise RuntimeError("Variável GOOGLE_SA_JSON não configurada.")

    if not spreadsheet_id:
        raise RuntimeError(
            "Variável GOOGLE_SPREADSHEET_ID não configurada."
        )

    try:
        service_account_info = json.loads(google_sa_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SA_JSON não contém um JSON válido."
        ) from exc

    return SheetsClient(
        service_account_info=service_account_info,
        spreadsheet_id=spreadsheet_id,
    )


# ============================================================
# AUXILIARES
# ============================================================

def clean(value):
    return str(value or "").strip()


def normalize_cfop(value):
    """
    Exemplos:
    6.101 -> 6101
    6.910 -> 6910
    5.102 -> 5102
    """
    return "".join(
        char for char in clean(value)
        if char.isdigit()
    )


def parse_br_date(value):
    value = clean(value)

    if not value:
        return None

    for fmt in (
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            pass

    return None


def get_or_create_sheet(sheets, sheet_name):
    """
    Cria a aba caso ainda não exista.
    """

    metadata = (
        sheets.api
        .spreadsheets()
        .get(spreadsheetId=sheets.spreadsheet_id)
        .execute()
    )

    existing = {
        item["properties"]["title"]
        for item in metadata.get("sheets", [])
    }

    if sheet_name not in existing:
        (
            sheets.api
            .spreadsheets()
            .batchUpdate(
                spreadsheetId=sheets.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": sheet_name
                                }
                            }
                        }
                    ]
                },
            )
            .execute()
        )


def rows_to_objects(values):
    if not values:
        return []

    headers = [clean(x) for x in values[0]]

    result = []

    for row in values[1:]:
        if not any(clean(x) for x in row):
            continue

        obj = {}

        for i, header in enumerate(headers):
            obj[header] = row[i] if i < len(row) else ""

        result.append(obj)

    return result


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "KPIs comerciais da Lenvie",
        "arquitetura": "render+sheets-v1",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "architecture": "render+sheets-v1",
    }


# ============================================================
# GOOGLE SHEETS TEST
# ============================================================

@app.get("/sheets/test")
def test_sheets():
    try:
        sheets = get_sheets_client()

        values = sheets.get("CONFIG!A1:B5")

        return {
            "status": "ok",
            "message": (
                "Conexão com Google Sheets realizada com sucesso."
            ),
            "spreadsheet_id": os.getenv(
                "GOOGLE_SPREADSHEET_ID"
            ),
            "range_testado": "CONFIG!A1:B5",
            "linhas_lidas": len(values),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================
# OMIE TEST
# ============================================================

@app.get("/omie/test")
def test_omie():
    try:
        omie = get_omie_client()

        resposta = omie.call(
            endpoint=ENDPOINTS["clientes"],
            call="ListarClientes",
            param={
                "pagina": 1,
                "registros_por_pagina": 1,
                "apenas_importado_api": "N",
            },
        )

        return {
            "status": "ok",
            "message": "Conexão com Omie realizada com sucesso.",
            "pagina": resposta.get("pagina"),
            "total_de_paginas": resposta.get(
                "total_de_paginas"
            ),
            "total_de_registros": resposta.get(
                "total_de_registros"
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================
# LISTAR NF TEST
# ============================================================

@app.get("/omie/nfe/test")
def test_omie_nfe():
    try:
        omie = get_omie_client()

        resposta = omie.call(
            endpoint=ENDPOINTS["nfe"],
            call="ListarNF",
            param={
                "pagina": 1,
                "registros_por_pagina": 1,
            },
        )

        notas = resposta.get("nfCadastro") or []
        rows = normalize_nfe(notas)

        amostra = None

        if rows:
            r = rows[0]

            amostra = {
                "id_nf": r[0],
                "chave_nfe": r[1],
                "numero_nf": r[2],
                "serie": r[3],
                "data_emissao": r[4],
                "tipo_nf": r[5],
                "id_pedido": r[7],
                "numero_pedido": r[8],
                "cliente_id": r[9],
                "cliente_documento": r[10],
                "cliente_nome": r[11],
                "vendedor_id": r[12],
                "categoria": r[13],
                "sku": r[16],
                "produto": r[17],
                "cfop": r[18],
                "quantidade": r[20],
                "valor_unitario": r[22],
                "valor_produto": r[23],
                "desconto_item": r[24],
                "valor_total_item": r[27],
                "valor_nf": r[30],
            }

        return {
            "status": "ok",
            "message": (
                "ListarNF executado e normalizado com sucesso."
            ),
            "pagina": resposta.get("pagina"),
            "total_de_paginas": resposta.get(
                "total_de_paginas"
            ),
            "total_de_registros": resposta.get(
                "total_de_registros"
            ),
            "nfs_recebidas": len(notas),
            "itens_normalizados": len(rows),
            "amostra_primeiro_item": amostra,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================
# CARGA CONTROLADA NF -> OMIE_NF
# ============================================================


@app.get("/omie/nfe/load-page")
def load_nfe_page(ano: int = 2026, mes: int = 1, pagina: int = 1):
    """
    Carrega UMA página (até 100 NFs) por chamada e faz merge idempotente
    na OMIE_NF. Não altera BASE_VENDAS.
    """
    import calendar

    if ano < 2020 or ano > 2100 or mes < 1 or mes > 12 or pagina < 1:
        return {"status": "error", "error": "Ano, mês ou página inválidos."}

    try:
        omie = get_omie_client()
        sheets = get_sheets_client()

        ultimo_dia = calendar.monthrange(ano, mes)[1]
        data_inicial = f"01/{mes:02d}/{ano}"
        data_final = f"{ultimo_dia:02d}/{mes:02d}/{ano}"

        resposta = omie.call(
            endpoint=ENDPOINTS["nfe"],
            call="ListarNF",
            param={
                "pagina": pagina,
                "registros_por_pagina": 100,
                "dEmiInicial": data_inicial,
                "dEmiFinal": data_final,
            },
        )

        notas = resposta.get("nfCadastro") or []
        total_paginas = int(resposta.get("total_de_paginas") or 1)
        novas_rows = normalize_nfe(notas)

        headers = [
            "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
            "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
            "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
            "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
            "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
            "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
        ]

        get_or_create_sheet(sheets, "OMIE_NF")
        atual = sheets.get("OMIE_NF!A1:AF50000")
        existentes = []

        if atual:
            cab = [clean(x) for x in atual[0]]
            if cab != headers:
                return {
                    "status": "error",
                    "error": "Cabeçalho da OMIE_NF diferente do contrato. Nada foi alterado.",
                    "cabecalho_atual": cab,
                    "cabecalho_esperado": headers,
                }
            existentes = atual[1:]

        def row_key(r):
            id_nf = clean(r[0]) if len(r) > 0 else ""
            id_item = clean(r[14]) if len(r) > 14 else ""
            # fallback apenas quando a origem não fornece ID_ITEM
            fallback = "|".join([
                clean(r[16]) if len(r) > 16 else "",
                clean(r[18]) if len(r) > 18 else "",
                clean(r[23]) if len(r) > 23 else "",
                clean(r[20]) if len(r) > 20 else "",
            ])
            return f"{id_nf}|{id_item or fallback}"

        merged = {row_key(r): r for r in existentes if r}
        chaves_antes = set(merged)

        for r in novas_rows:
            if r:
                merged[row_key(r)] = r

        consolidadas = list(merged.values())
        itens_realmente_novos = len(set(merged) - chaves_antes)

        # Só grava depois que consulta/normalização/validação terminaram.
        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range="'OMIE_NF'!A:AF",
            body={},
        ).execute()

        sheets.api.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id,
            range="'OMIE_NF'!A1",
            valueInputOption="RAW",
            body={"values": [headers] + consolidadas},
        ).execute()

        nfs_pagina = {clean(r[0]) for r in novas_rows if r and clean(r[0])}
        cfops_pagina = sorted({
            clean(r[18]) for r in novas_rows
            if len(r) > 18 and clean(r[18])
        })
        finalizado = pagina >= total_paginas

        return {
            "status": "ok",
            "message": "Página carregada e gravada na OMIE_NF.",
            "periodo": {"inicio": data_inicial, "fim": data_final},
            "pagina": pagina,
            "total_paginas": total_paginas,
            "finalizado": finalizado,
            "proxima_pagina": None if finalizado else pagina + 1,
            "nfs_recebidas_pagina": len(notas),
            "nfs_unicas_pagina": len(nfs_pagina),
            "itens_pagina": len(novas_rows),
            "itens_realmente_novos": itens_realmente_novos,
            "total_itens_omie_nf": len(consolidadas),
            "cfops_pagina": cfops_pagina,
            "aba_destino": "OMIE_NF",
            "base_vendas_alterada": False,
        }

    except Exception as e:
        return {"status": "error", "error": repr(e)}

@app.get("/omie/nfe/load-test")
def load_test_nfe():
    """
    Carga controlada:
    01/08/2026 até 03/08/2026.

    Grava somente OMIE_NF.
    """

    try:
        omie = get_omie_client()
        sheets = get_sheets_client()

        data_inicial = "01/08/2026"
        data_final = "03/08/2026"

        todas_notas = []

        pagina = 1
        total_paginas = 1

        while pagina <= total_paginas:
            resposta = omie.call(
                endpoint=ENDPOINTS["nfe"],
                call="ListarNF",
                param={
                    "pagina": pagina,
                    "registros_por_pagina": 100,
                    "dEmiInicial": data_inicial,
                    "dEmiFinal": data_final,
                },
            )

            notas = resposta.get("nfCadastro") or []

            todas_notas.extend(notas)

            total_paginas = int(
                resposta.get("total_de_paginas") or 1
            )

            pagina += 1

        rows = normalize_nfe(todas_notas)

        headers = [
            "ID_NF",
            "CHAVE_NFE",
            "NUM_NF",
            "SERIE",
            "DATA_EMISSAO",
            "TIPO_NF",
            "DATA_CANCELAMENTO",
            "ID_PEDIDO",
            "NUM_PEDIDO",
            "COD_CLIENTE",
            "CNPJ_CPF",
            "CLIENTE_NOME",
            "COD_VENDEDOR",
            "CATEGORIA",
            "ID_ITEM",
            "COD_PRODUTO_OMIE",
            "SKU",
            "PRODUTO",
            "CFOP",
            "NCM",
            "QUANTIDADE",
            "UNIDADE",
            "VALOR_UNITARIO",
            "VALOR_PRODUTO",
            "DESCONTO_ITEM",
            "FRETE_ITEM",
            "OUTROS_ITEM",
            "VALOR_TOTAL_ITEM",
            "VALOR_PRODUTOS_NF",
            "DESCONTO_NF",
            "VALOR_NF",
            "RAW_JSON",
        ]

        get_or_create_sheet(
            sheets,
            "OMIE_NF",
        )

        (
            sheets.api
            .spreadsheets()
            .values()
            .clear(
                spreadsheetId=sheets.spreadsheet_id,
                range="'OMIE_NF'!A:AF",
                body={},
            )
            .execute()
        )

        (
            sheets.api
            .spreadsheets()
            .values()
            .update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'OMIE_NF'!A1",
                valueInputOption="RAW",
                body={
                    "values": [headers] + rows
                },
            )
            .execute()
        )

        nfs_unicas = {
            str(row[0])
            for row in rows
            if row and row[0]
        }

        cfops = sorted(
            {
                str(row[18])
                for row in rows
                if len(row) > 18 and row[18]
            }
        )

        return {
            "status": "ok",
            "message": (
                "Carga controlada gravada na aba OMIE_NF."
            ),
            "periodo": {
                "inicio": data_inicial,
                "fim": data_final,
            },
            "nfs_recebidas": len(todas_notas),
            "nfs_unicas": len(nfs_unicas),
            "itens_gravados": len(rows),
            "cfops_encontrados": cfops,
            "aba_destino": "OMIE_NF",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================
# OMIE_NF -> BASE_VENDAS
# ============================================================


# ============================================================
# REPARO CONTROLADO DA ESTRUTURA DA BASE_VENDAS
# ============================================================

@app.post("/admin/repair-base-vendas")
def repair_base_vendas(confirmar: str = ""):
    """
    Repara SOMENTE a aba BASE_VENDAS:
    1) cria backup da estrutura/dados atuais em BASE_VENDAS_BACKUP;
    2) limpa BASE_VENDAS;
    3) recria exatamente o contrato A:AE.
    Não chama Omie e não altera outras abas.
    """
    try:
        if confirmar != "SIM":
            return {
                "status": "blocked",
                "message": "Operação não executada. Use ?confirmar=SIM para confirmar o reparo.",
            }

        sheets = get_sheets_client()

        headers = [
            "COMPETENCIA",
            "DATA_EMISSAO",
            "ID_NF",
            "CHAVE_NFE",
            "NUM_NF",
            "SERIE",
            "ID_PEDIDO",
            "NUM_PEDIDO",
            "COD_CLIENTE",
            "CNPJ_CPF",
            "CLIENTE_NOME",
            "COD_VENDEDOR",
            "REP_ID",
            "REPRESENTANTE",
            "CATEGORIA",
            "VALOR_NF",
            "VALOR_COMERCIAL",
            "VALOR_EXCLUIDO",
            "VALOR_PENDENTE",
            "TIPO_NF",
            "CFOPS",
            "CFOPS_VENDA",
            "CFOPS_EXCLUIDOS",
            "CFOPS_PENDENTES",
            "QTD_ITENS",
            "ITENS_VENDA",
            "ITENS_EXCLUIDOS",
            "ITENS_PENDENTES",
            "QTD_SKUS",
            "VENDA_VALIDA",
            "MOTIVO",
        ]

        get_or_create_sheet(sheets, "BASE_VENDAS")
        get_or_create_sheet(sheets, "BASE_VENDAS_BACKUP")

        atual = sheets.get("BASE_VENDAS!A1:AE50000")

        # Backup antes de qualquer alteração.
        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range="'BASE_VENDAS_BACKUP'!A:AE",
            body={},
        ).execute()

        if atual:
            sheets.api.spreadsheets().values().update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS_BACKUP'!A1",
                valueInputOption="RAW",
                body={"values": atual},
            ).execute()

        # Só depois do backup limpa a aba operacional.
        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range="'BASE_VENDAS'!A:AE",
            body={},
        ).execute()

        sheets.api.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id,
            range="'BASE_VENDAS'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

        conferido = sheets.get("BASE_VENDAS!A1:AE1")
        cabecalho_final = [clean(x) for x in (conferido[0] if conferido else [])]

        if cabecalho_final != headers:
            return {
                "status": "error",
                "error": "Reparo executado, mas a validação final do cabeçalho falhou.",
                "cabecalho_final": cabecalho_final,
                "cabecalho_esperado": headers,
                "backup": "BASE_VENDAS_BACKUP",
            }

        return {
            "status": "ok",
            "message": "BASE_VENDAS reparada com sucesso. Cabeçalho A:AE recriado e conteúdo anterior preservado em backup.",
            "colunas": len(headers),
            "cabecalho": headers,
            "linhas_backup": max(0, len(atual) - 1) if atual else 0,
            "aba_backup": "BASE_VENDAS_BACKUP",
            "proximo_passo": "/omie/nfe/build-base-test",
        }

    except Exception as e:
        return {"status": "error", "error": repr(e)}


@app.get("/omie/nfe/build-base-test")
def build_base_test():
    """
    Lê OMIE_NF, classifica cada ITEM pelo CFOP e depois
    consolida UMA LINHA POR NF.

    Regras atuais:
    - Venda: 5101, 6101, 5102, 6102, 5910, 6910, 5403, 6403, 6109, 6110
    - CFOPs não classificados: PENDENTE
    - Cancelamento: somente quando DATA_CANCELAMENTO contém indicação real de cancelamento
    """
    try:
        sheets = get_sheets_client()
        values = sheets.get("OMIE_NF!A1:AF50000")

        if not values or not values[0]:
            return {"status": "error", "error": "A aba OMIE_NF está vazia. BASE_VENDAS não foi alterada."}

        origem_headers = [clean(h) for h in values[0]]
        obrigatorias_origem = [
            "ID_NF", "CHAVE_NFE", "NUM_NF", "SERIE", "DATA_EMISSAO",
            "ID_PEDIDO", "COD_CLIENTE", "CLIENTE_NOME", "CFOP",
            "VALOR_PRODUTO", "DESCONTO_ITEM", "VALOR_NF",
        ]
        faltantes_origem = [h for h in obrigatorias_origem if h not in origem_headers]
        if faltantes_origem:
            return {
                "status": "error",
                "error": "OMIE_NF sem colunas obrigatórias. BASE_VENDAS não foi alterada.",
                "colunas_faltantes": faltantes_origem,
                "cabecalho_omie_nf": origem_headers,
            }

        itens = rows_to_objects(values)
        if not itens:
            return {"status": "error", "error": "OMIE_NF sem linhas de dados. BASE_VENDAS não foi alterada."}

        itens_com_id_nf = sum(1 for x in itens if clean(x.get("ID_NF")))
        itens_com_num_nf = sum(1 for x in itens if clean(x.get("NUM_NF")))
        if itens_com_id_nf == 0 or itens_com_num_nf == 0:
            return {
                "status": "error",
                "error": "OMIE_NF está sem ID_NF ou NUM_NF populados. BASE_VENDAS não foi alterada.",
                "itens_origem": len(itens),
                "itens_com_id_nf": itens_com_id_nf,
                "itens_com_num_nf": itens_com_num_nf,
            }

        CFOPS_VENDA = {
            "5101",
            "6101",
            "5102",
            "6102",
            "5910",
            "6910",
            "5403",
            "6403",
            "6109",
            "6110",
        }
        CFOPS_EXCLUIR = set()

        def is_cancelada(value):
            """
            DATA_CANCELAMENTO é um campo de data.
            Só considera a NF cancelada quando houver uma DATA reconhecível.
            Qualquer código/status/texto residual (ex.: 0, 91, N, NAO) não cancela.
            """
            import re

            v = clean(value)
            if not v:
                return False

            s = v.strip()

            # Formatos esperados de data vindos da origem/planilha.
            padroes_data = (
                r"^\\d{2}/\\d{2}/\\d{4}$",          # 31/08/2026
                r"^\\d{4}-\\d{2}-\\d{2}$",          # 2026-08-31
                r"^\\d{2}/\\d{2}/\\d{4}\\s+\\d{2}:\\d{2}",  # data + hora
                r"^\\d{4}-\\d{2}-\\d{2}[T\\s]\\d{2}:\\d{2}", # ISO/data + hora
            )
            return any(re.match(p, s) for p in padroes_data)

        def to_float(value):
            if value in (None, ""):
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            txt = str(value).strip()
            try:
                return float(txt)
            except ValueError:
                try:
                    return float(txt.replace(".", "").replace(",", "."))
                except ValueError:
                    return 0.0

        nfs = {}
        resumo_itens = {"VENDA": 0, "EXCLUIDO": 0, "PENDENTE": 0}
        cfops_pendentes = set()

        for item in itens:
            id_nf = clean(item.get("ID_NF"))
            if not id_nf:
                continue

            cfop_original = clean(item.get("CFOP"))
            cfop = normalize_cfop(cfop_original)

            if cfop in CFOPS_VENDA:
                classificacao = "VENDA"
            elif cfop in CFOPS_EXCLUIR:
                classificacao = "EXCLUIDO"
            else:
                classificacao = "PENDENTE"
                if cfop_original:
                    cfops_pendentes.add(cfop_original)

            resumo_itens[classificacao] += 1
            valor_produto = to_float(item.get("VALOR_PRODUTO"))
            desconto_item = to_float(item.get("DESCONTO_ITEM"))
            valor_liquido_item = valor_produto - desconto_item

            if id_nf not in nfs:
                nfs[id_nf] = {
                    "ID_NF": id_nf,
                    "CHAVE_NFE": clean(item.get("CHAVE_NFE")),
                    "NUM_NF": clean(item.get("NUM_NF")),
                    "SERIE": clean(item.get("SERIE")),
                    "DATA_EMISSAO": clean(item.get("DATA_EMISSAO")),
                    "TIPO_NF": clean(item.get("TIPO_NF")),
                    "DATA_CANCELAMENTO": clean(item.get("DATA_CANCELAMENTO")),
                    "ID_PEDIDO": clean(item.get("ID_PEDIDO")),
                    "NUM_PEDIDO": clean(item.get("NUM_PEDIDO")),
                    "COD_CLIENTE": clean(item.get("COD_CLIENTE")),
                    "CNPJ_CPF": clean(item.get("CNPJ_CPF")),
                    "CLIENTE_NOME": clean(item.get("CLIENTE_NOME")),
                    "COD_VENDEDOR": clean(item.get("COD_VENDEDOR")),
                    "CATEGORIA": clean(item.get("CATEGORIA")),
                    "VALOR_NF": to_float(item.get("VALOR_NF")),
                    "CFOPS": set(),
                    "CFOPS_VENDA": set(),
                    "CFOPS_EXCLUIDOS": set(),
                    "CFOPS_PENDENTES": set(),
                    "SKUS": set(),
                    "QTD_ITENS": 0,
                    "ITENS_VENDA": 0,
                    "ITENS_EXCLUIDOS": 0,
                    "ITENS_PENDENTES": 0,
                    "VALOR_COMERCIAL": 0.0,
                    "VALOR_EXCLUIDO": 0.0,
                    "VALOR_PENDENTE": 0.0,
                }

            nf = nfs[id_nf]
            if cfop_original:
                nf["CFOPS"].add(cfop_original)

            sku = clean(item.get("SKU"))
            if sku:
                nf["SKUS"].add(sku)

            nf["QTD_ITENS"] += 1

            if classificacao == "VENDA":
                nf["ITENS_VENDA"] += 1
                nf["VALOR_COMERCIAL"] += valor_liquido_item
                if cfop_original:
                    nf["CFOPS_VENDA"].add(cfop_original)
            elif classificacao == "EXCLUIDO":
                nf["ITENS_EXCLUIDOS"] += 1
                nf["VALOR_EXCLUIDO"] += valor_liquido_item
                if cfop_original:
                    nf["CFOPS_EXCLUIDOS"].add(cfop_original)
            else:
                nf["ITENS_PENDENTES"] += 1
                nf["VALOR_PENDENTE"] += valor_liquido_item
                if cfop_original:
                    nf["CFOPS_PENDENTES"].add(cfop_original)

        rows = []
        resumo_nfs = {"SIM": 0, "NAO": 0, "PENDENTE": 0}

        for nf in nfs.values():
            data = parse_br_date(nf["DATA_EMISSAO"])
            competencia = f"{data.year:04d}-{data.month:02d}" if data else ""

            if is_cancelada(nf["DATA_CANCELAMENTO"]):
                venda_valida = "NAO"
                motivo = "NF_CANCELADA"
                valor_comercial = 0.0
            elif nf["ITENS_VENDA"] > 0 and nf["ITENS_PENDENTES"] == 0:
                venda_valida = "SIM"
                motivo = "VENDA_COM_ITENS_EXCLUIDOS" if nf["ITENS_EXCLUIDOS"] > 0 else "VENDA"
                valor_comercial = nf["VALOR_COMERCIAL"]
            elif nf["ITENS_VENDA"] > 0:
                venda_valida = "PENDENTE"
                motivo = "VENDA_COM_CFOP_PENDENTE"
                valor_comercial = nf["VALOR_COMERCIAL"]
            elif nf["ITENS_PENDENTES"] > 0:
                venda_valida = "PENDENTE"
                motivo = "SOMENTE_CFOP_PENDENTE"
                valor_comercial = 0.0
            else:
                venda_valida = "NAO"
                motivo = "SOMENTE_ITENS_EXCLUIDOS"
                valor_comercial = 0.0

            resumo_nfs[venda_valida] += 1

            rows.append([
                competencia, nf["DATA_EMISSAO"], nf["ID_NF"], nf["CHAVE_NFE"],
                nf["NUM_NF"], nf["SERIE"], nf["ID_PEDIDO"], nf["NUM_PEDIDO"],
                nf["COD_CLIENTE"], nf["CNPJ_CPF"], nf["CLIENTE_NOME"],
                nf["COD_VENDEDOR"], "", "", nf["CATEGORIA"],
                round(nf["VALOR_NF"], 2), round(valor_comercial, 2),
                round(nf["VALOR_EXCLUIDO"], 2), round(nf["VALOR_PENDENTE"], 2),
                nf["TIPO_NF"], ";".join(sorted(nf["CFOPS"])),
                ";".join(sorted(nf["CFOPS_VENDA"])),
                ";".join(sorted(nf["CFOPS_EXCLUIDOS"])),
                ";".join(sorted(nf["CFOPS_PENDENTES"])),
                nf["QTD_ITENS"], nf["ITENS_VENDA"], nf["ITENS_EXCLUIDOS"],
                nf["ITENS_PENDENTES"], len(nf["SKUS"]), venda_valida, motivo,
            ])

        rows.sort(key=lambda r: (r[0], r[1], r[4]))

        # Não grava uma consolidação que perdeu a identificação fiscal.
        linhas_sem_id_nf = [r for r in rows if not clean(r[2])]
        linhas_sem_num_nf = [r for r in rows if not clean(r[4])]
        if linhas_sem_id_nf or linhas_sem_num_nf:
            return {
                "status": "error",
                "error": "Falha de integridade na consolidação. BASE_VENDAS não foi alterada.",
                "nfs_consolidadas": len(rows),
                "linhas_sem_id_nf": len(linhas_sem_id_nf),
                "linhas_sem_num_nf": len(linhas_sem_num_nf),
            }

        headers = [
            "COMPETENCIA", "DATA_EMISSAO", "ID_NF", "CHAVE_NFE", "NUM_NF",
            "SERIE", "ID_PEDIDO", "NUM_PEDIDO", "COD_CLIENTE", "CNPJ_CPF",
            "CLIENTE_NOME", "COD_VENDEDOR", "REP_ID", "REPRESENTANTE",
            "CATEGORIA", "VALOR_NF", "VALOR_COMERCIAL", "VALOR_EXCLUIDO",
            "VALOR_PENDENTE", "TIPO_NF", "CFOPS", "CFOPS_VENDA",
            "CFOPS_EXCLUIDOS", "CFOPS_PENDENTES", "QTD_ITENS", "ITENS_VENDA",
            "ITENS_EXCLUIDOS", "ITENS_PENDENTES", "QTD_SKUS", "VENDA_VALIDA",
            "MOTIVO",
        ]

        get_or_create_sheet(sheets, "BASE_VENDAS")

        # REGRA DE SEGURANÇA: o cabeçalho A1:AE1 é contrato da planilha.
        # Nunca limpamos nem recriamos a linha 1 durante a população da base.
        header_atual_values = sheets.get("BASE_VENDAS!A1:AE1")
        header_atual = header_atual_values[0] if header_atual_values else []

        if not header_atual:
            # Somente uma aba realmente vazia recebe o cabeçalho padrão.
            sheets.api.spreadsheets().values().update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
        elif header_atual != headers:
            # Não tenta "corrigir" automaticamente: isso evita deslocar/quebrar colunas.
            return {
                "status": "error",
                "error": "Cabeçalho da BASE_VENDAS diferente do contrato esperado. Nenhuma linha foi alterada.",
                "cabecalho_atual": header_atual,
                "cabecalho_esperado": headers,
            }

        # Limpa SOMENTE os dados e mantém o cabeçalho intacto.
        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range="'BASE_VENDAS'!A2:AE",
            body={},
        ).execute()

        if rows:
            sheets.api.spreadsheets().values().update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS'!A2",
                valueInputOption="RAW",
                body={"values": rows},
            ).execute()

        faturamento_aprovado = round(
            sum(row[16] for row in rows if row[29] == "SIM"), 2
        )
        faturamento_pendente = round(
            sum(row[16] for row in rows if row[29] == "PENDENTE"), 2
        )

        return {
            "status": "ok",
            "message": "BASE_VENDAS reconstruída com classificação por item/CFOP.",
            "itens_origem": len(itens),
            "nfs_consolidadas": len(rows),
            "nfs_com_id_nf": sum(1 for r in rows if clean(r[2])),
            "nfs_com_num_nf": sum(1 for r in rows if clean(r[4])),
            "nfs_com_data_cancelamento_reconhecida": sum(
                1 for nf in nfs.values() if is_cancelada(nf["DATA_CANCELAMENTO"])
            ),
            "amostra_data_cancelamento_origem": sorted({
                clean(nf["DATA_CANCELAMENTO"])
                for nf in nfs.values()
                if clean(nf["DATA_CANCELAMENTO"])
            })[:10],
            "itens": resumo_itens,
            "nfs": resumo_nfs,
            "faturamento_aprovado": faturamento_aprovado,
            "faturamento_conhecido_em_nfs_pendentes": faturamento_pendente,
            "cfops_pendentes": sorted(cfops_pendentes),
            "aba_destino": "BASE_VENDAS",
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}



# ============================================================
# CONSULTA DIRETA DOS PEDIDOS VINCULADOS ÀS NFs
# ============================================================

@app.get("/omie/pedidos/load-test")
def load_test_pedidos(limit: int = 5, offset: int = 0):
    """
    Lê os ID_PEDIDO já existentes em OMIE_NF e consulta
    diretamente cada pedido no Omie usando ConsultarPedido.

    Grava somente OMIE_PEDIDOS_TESTE.
    Não altera OMIE_NF, BASE_VENDAS ou KPIs.
    """
    try:
        limit = max(1, min(limit, 10))
        offset = max(0, offset)

        omie = get_omie_client()
        sheets = get_sheets_client()

        nf_values = sheets.get("OMIE_NF!A1:AF50000")
        nf_rows = rows_to_objects(nf_values)

        if not nf_rows:
            return {
                "status": "error",
                "error": "A aba OMIE_NF está vazia.",
            }

        # ID_PEDIDO -> NFs vinculadas
        pedidos_nfs = {}

        for row in nf_rows:
            id_pedido = clean(row.get("ID_PEDIDO"))
            num_nf = clean(row.get("NUM_NF"))

            if not id_pedido:
                continue

            pedidos_nfs.setdefault(id_pedido, set())

            if num_nf:
                pedidos_nfs[id_pedido].add(num_nf)

        ids_pedidos = sorted(pedidos_nfs.keys())

        if not ids_pedidos:
            return {
                "status": "error",
                "error": "Nenhum ID_PEDIDO encontrado na OMIE_NF.",
            }

        total_ids = len(ids_pedidos)
        lote = ids_pedidos[offset:offset + limit]

        if not lote:
            return {
                "status": "ok",
                "message": "Não há mais pedidos para este offset.",
                "total_ids_pedido": total_ids,
                "offset": offset,
                "limit": limit,
                "consultados_neste_lote": 0,
                "proximo_offset": None,
                "finalizado": True,
            }

        rows = []
        erros = []
        categorias = set()
        origens = set()
        vendedores = set()
        etapas = set()

        for id_pedido in lote:
            try:
                # A documentação do Omie define ConsultarPedido
                # com o parâmetro codigo_pedido.
                pedido = omie.call(
                    endpoint=ENDPOINTS["pedidos"],
                    call="ConsultarPedido",
                    param={
                        "codigo_pedido": int(id_pedido)
                    },
                )

                cab = pedido.get("cabecalho") or {}

                info_adic = (
                    pedido.get("informacoes_adicionais")
                    or {}
                )

                total = (
                    pedido.get("total_pedido")
                    or pedido.get("totalPedido")
                    or {}
                )

                info_cadastro = (
                    pedido.get("infoCadastro")
                    or pedido.get("info_cadastro")
                    or {}
                )

                codigo_pedido = (
                    cab.get("codigo_pedido")
                    or id_pedido
                )

                numero_pedido = (
                    cab.get("numero_pedido")
                    or ""
                )

                codigo_cliente = (
                    cab.get("codigo_cliente")
                    or ""
                )

                codigo_vendedor = (
                    cab.get("codigo_vendedor")
                    or info_adic.get("codigo_vendedor")
                    or ""
                )

                codigo_categoria = (
                    info_adic.get("codigo_categoria")
                    or cab.get("codigo_categoria")
                    or cab.get("categoria")
                    or ""
                )

                origem_pedido = (
                    cab.get("origem_pedido")
                    or ""
                )

                etapa = cab.get("etapa") or ""

                encerrado = (
                    cab.get("encerrado")
                    or ""
                )

                motivo_encerramento = (
                    cab.get("enc_motivo")
                    or ""
                )

                data_previsao = (
                    cab.get("data_previsao")
                    or ""
                )

                valor_mercadorias = (
                    total.get("valor_mercadorias")
                    or 0
                )

                valor_total_pedido = (
                    total.get("valor_total_pedido")
                    or total.get("valor_total")
                    or 0
                )

                qtd_itens = (
                    cab.get("quantidade_itens")
                    or len(pedido.get("det") or [])
                    or 0
                )

                nfs_vinculadas = ";".join(
                    sorted(pedidos_nfs.get(id_pedido, set()))
                )

                if codigo_categoria:
                    categorias.add(str(codigo_categoria))

                if origem_pedido:
                    origens.add(str(origem_pedido))

                if codigo_vendedor:
                    vendedores.add(str(codigo_vendedor))

                if etapa:
                    etapas.add(str(etapa))

                rows.append([
                    codigo_pedido,
                    numero_pedido,
                    nfs_vinculadas,
                    data_previsao,
                    codigo_cliente,
                    codigo_vendedor,
                    codigo_categoria,
                    origem_pedido,
                    etapa,
                    encerrado,
                    motivo_encerramento,
                    qtd_itens,
                    valor_mercadorias,
                    valor_total_pedido,
                    ";".join(sorted(pedido.keys())),
                    ";".join(sorted(cab.keys())),
                    ";".join(sorted(info_adic.keys())),
                    ";".join(sorted(info_cadastro.keys())),
                ])

            except Exception as exc:
                erros.append({
                    "id_pedido": id_pedido,
                    "erro": str(exc)[:500],
                })

        headers = [
            "COD_PEDIDO",
            "NUM_PEDIDO",
            "NFS_VINCULADAS",
            "DATA_PREVISAO",
            "COD_CLIENTE",
            "COD_VENDEDOR",
            "CATEGORIA",
            "ORIGEM_PEDIDO",
            "ETAPA",
            "ENCERRADO",
            "MOTIVO_ENCERRAMENTO",
            "QTD_ITENS",
            "VALOR_MERCADORIAS",
            "VALOR_TOTAL_PEDIDO",
            "CAMPOS_RAIZ",
            "CAMPOS_CABECALHO",
            "CAMPOS_INFO_ADIC",
            "CAMPOS_INFO_CADASTRO",
        ]

        get_or_create_sheet(sheets, "OMIE_PEDIDOS_TESTE")

        if offset == 0:
            sheets.api.spreadsheets().values().clear(
                spreadsheetId=sheets.spreadsheet_id,
                range="'OMIE_PEDIDOS_TESTE'!A:R",
                body={},
            ).execute()
            sheets.api.spreadsheets().values().update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'OMIE_PEDIDOS_TESTE'!A1",
                valueInputOption="RAW",
                body={"values": [headers] + rows},
            ).execute()
        elif rows:
            sheets.api.spreadsheets().values().append(
                spreadsheetId=sheets.spreadsheet_id,
                range="'OMIE_PEDIDOS_TESTE'!A:R",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()

        proximo_offset = offset + len(lote)
        finalizado = proximo_offset >= total_ids

        return {
            "status": "ok",
            "message": (
                "Pedidos vinculados às NFs consultados diretamente "
                "com ConsultarPedido."
            ),
            "total_ids_pedido": total_ids,
            "offset": offset,
            "limit": limit,
            "ids_neste_lote": lote,
            "consultados_neste_lote": len(lote),
            "sucessos_neste_lote": len(rows),
            "erros_neste_lote": len(erros),
            "categorias_encontradas": sorted(categorias),
            "origens_encontradas": sorted(origens),
            "etapas_encontradas": sorted(etapas),
            "vendedores_encontrados": len(vendedores),
            "erros_amostra": erros[:10],
            "proximo_offset": None if finalizado else proximo_offset,
            "finalizado": finalizado,
            "aba_destino": "OMIE_PEDIDOS_TESTE",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }



# ============================================================
# DIAGNOSTICO DIRETO DO CONSULTARPEDIDO OMIE
# ============================================================

@app.get("/omie/pedidos/debug-consultar")
def debug_consultar_pedido():
    """Diagnostica ConsultarPedido sem alterar o Google Sheets."""
    try:
        s = get_settings()
        codigo_pedido = 9204861332
        endpoint = ENDPOINTS["pedidos"]

        payload = {
            "call": "ConsultarPedido",
            "app_key": s.omie_app_key,
            "app_secret": s.omie_app_secret,
            "param": [{"codigo_pedido": codigo_pedido}],
        }

        response = requests.post(endpoint, json=payload, timeout=30)

        try:
            response_body = response.json()
        except Exception:
            response_body = response.text[:5000]

        return {
            "status": "ok" if response.ok else "error",
            "codigo_pedido": codigo_pedido,
            "endpoint": endpoint,
            "http_status": response.status_code,
            "response_body": response_body,
        }

    except Exception as e:
        return {"status": "error", "error": repr(e)}


# ============================================================
# SYNC OFICIAL
# ============================================================

@app.post("/sync")
def run_sync():
    return {
        "status": "blocked",
        "message": (
            "Sincronização oficial permanece bloqueada "
            "durante a validação da arquitetura NF-e."
        ),
    }
# ============================================================
# DASHBOARD EXECUTIVO (somente leitura)
# ============================================================


@app.get("/dashboard/auditoria-nfs")
def dashboard_auditoria_nfs(
    ano: int = 2026,
    mes_inicio: int = 1,
    mes_fim: int = 12,
    representante: str = "ALL",
):
    """Auditoria somente leitura das linhas que entram nos KPIs comerciais."""
    try:
        sheets = get_sheets_client()
        rows = rows_to_objects(sheets.get("BASE_VENDAS!A1:AE50000"))

        detalhes = []
        total = 0.0

        for i, row in enumerate(rows, start=2):
            competencia = clean(row.get("COMPETENCIA"))
            if not competencia:
                continue

            partes = competencia.replace("/", "-").split("-")
            try:
                if len(partes) >= 2 and len(partes[0]) == 4:
                    row_ano, row_mes = int(partes[0]), int(partes[1])
                elif len(partes) >= 2:
                    row_mes, row_ano = int(partes[0]), int(partes[1])
                else:
                    continue
            except Exception:
                continue

            if row_ano != ano or not (mes_inicio <= row_mes <= mes_fim):
                continue

            venda_valida = clean(row.get("VENDA_VALIDA")).upper()
            if venda_valida != "SIM":
                continue

            if representante != "ALL":
                rep = clean(row.get("REPRESENTANTE"))
                rep_id = clean(row.get("REP_ID"))
                if representante not in (rep, rep_id):
                    continue

            raw_valor = row.get("VALOR_COMERCIAL")
            try:
                if isinstance(raw_valor, (int, float)):
                    valor = float(raw_valor)
                else:
                    s = clean(raw_valor).replace("R$", "").replace(" ", "")
                    if "," in s:
                        s = s.replace(".", "").replace(",", ".")
                    valor = float(s or 0)
            except Exception:
                valor = 0.0
            total += valor

            detalhes.append({
                "linha_base_vendas": i,
                "id_nf": clean(row.get("ID_NF")),
                "num_nf": clean(row.get("NUM_NF")),
                "cliente": clean(row.get("CLIENTE_NOME")),
                "valor_comercial": round(valor, 2),
                "venda_valida": venda_valida,
                "cfops_venda": clean(row.get("CFOPS_VENDA")),
                "motivo": clean(row.get("MOTIVO")),
            })

        return {
            "status": "ok",
            "ano": ano,
            "mes_inicio": mes_inicio,
            "mes_fim": mes_fim,
            "representante": representante,
            "quantidade_linhas": len(detalhes),
            "soma_valor_comercial": round(total, 2),
            "nfs": detalhes,
            "fonte": "BASE_VENDAS",
            "modo": "somente_leitura",
        }
    except Exception as e:
        return {"status": "error", "error": repr(e)}

@app.get("/dashboard/executive-kpis")
def dashboard_executive_kpis(
    ano: int = 2026,
    mes_inicio: int = 1,
    mes_fim: int = 12,
    representante: str = "ALL",
):
    """KPIs executivos calculados da BASE_VENDAS sem alterar a planilha."""
    try:
        mes_inicio = max(1, min(int(mes_inicio), 12))
        mes_fim = max(1, min(int(mes_fim), 12))
        if mes_inicio > mes_fim:
            mes_inicio, mes_fim = mes_fim, mes_inicio

        sheets = get_sheets_client()
        values = sheets.get("BASE_VENDAS!A1:AE50000")
        rows = rows_to_objects(values)

        selecionadas = []
        for row in rows:
            if clean(row.get("VENDA_VALIDA")).upper() != "SIM":
                continue
            competencia = clean(row.get("COMPETENCIA"))
            try:
                y, m = [int(x) for x in competencia[:7].split("-")]
            except Exception:
                dt = parse_br_date(row.get("DATA_EMISSAO"))
                if not dt:
                    continue
                y, m = dt.year, dt.month
            if y != ano or not (mes_inicio <= m <= mes_fim):
                continue
            if representante != "ALL" and clean(row.get("REPRESENTANTE")) != representante:
                continue
            selecionadas.append(row)

        def to_float(v):
            try:
                return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in v else float(v or 0)
            except Exception:
                return 0.0

        faturamento = round(sum(to_float(r.get("VALOR_COMERCIAL")) for r in selecionadas), 2)
        clientes = {clean(r.get("CNPJ_CPF")) or clean(r.get("COD_CLIENTE")) for r in selecionadas}
        clientes.discard("")
        # Ticket só pode usar uma identificação fiscal real.
        # Nunca usa número da linha como se fosse NF.
        nfs = set()
        for r in selecionadas:
            nf_key = (
                clean(r.get("ID_NF"))
                or clean(r.get("CHAVE_NFE"))
                or clean(r.get("NUM_NF"))
            )
            if nf_key:
                nfs.add(nf_key)

        venda_media = round(faturamento / len(clientes), 2) if clientes else 0.0
        ticket_medio = round(faturamento / len(nfs), 2) if nfs else 0.0

        return {
            "status": "ok",
            "ano": ano,
            "mes_inicio": mes_inicio,
            "mes_fim": mes_fim,
            "representante": representante,
            "faturamento": faturamento,
            "clientes_compradores": len(clientes),
            "nfs_comerciais": len(nfs),
            "venda_media_cliente": venda_media,
            "ticket_medio_nf": ticket_medio,
            "positivacao_carteira": None,
            "positivacao_status": "aguardando_carteira_validada",
            "fonte": "BASE_VENDAS",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================
# FRONTEND V10
# ============================================================

@app.get("/dashboard", include_in_schema=False)
def dashboard_frontend():
    """Entrega o dashboard HTML V10 sem alterar os endpoints da API."""
    from pathlib import Path

    index_path = Path(__file__).resolve().parent.parent / "static" / "index.html"

    if not index_path.exists():
        return {
            "status": "error",
            "error": "Frontend não encontrado.",
            "arquivo_esperado": "static/index.html",
        }

    return FileResponse(index_path, media_type="text/html")

