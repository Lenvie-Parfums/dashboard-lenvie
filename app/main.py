import json
import os

from fastapi import FastAPI

from app.sheets.client import SheetsClient
from app.omie.client import OmieClient
from app.omie.resources import ENDPOINTS, normalize_nfe


app = FastAPI(
    title="Lenvie Commercial KPIs",
    version="1.0.0",
)


# ============================================================
# CONFIGURAÇÕES AUXILIARES
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

    service_account_info = json.loads(google_sa_json)

    return SheetsClient(
        service_account_info=service_account_info,
        spreadsheet_id=spreadsheet_id,
    )


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


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "architecture": "render+sheets-v1",
    }


# ============================================================
# TESTE GOOGLE SHEETS
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
            "spreadsheet_id": os.getenv("GOOGLE_SPREADSHEET_ID"),
            "range_testado": "CONFIG!A1:B5",
            "linhas_lidas": len(values),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================
# TESTE OMIE
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
            "total_de_paginas": resposta.get("total_de_paginas"),
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
# TESTE CONTROLADO NF-e
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
            "total_de_paginas": resposta.get("total_de_paginas"),
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
# CARGA CONTROLADA NF-e -> SHEETS
# ============================================================

@app.get("/omie/nfe/load-test")
def load_test_nfe():
    """
    TESTE CONTROLADO.

    Busca NFs de 01/08/2026 até 03/08/2026
    e grava SOMENTE na aba OMIE_NF.

    Não altera:
    - BASE_VENDAS
    - KPI_MENSAL
    - CARTEIRA
    - CONFIG
    - demais abas
    """

    try:
        omie = get_omie_client()
        sheets = get_sheets_client()

        data_inicial = "01/08/2026"
        data_final = "03/08/2026"

        todas_notas = []

        pagina = 1
        total_paginas = 1

        # ----------------------------------------------------
        # Paginação controlada por período
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Normalização
        # Uma linha por item da NF
        # ----------------------------------------------------

        rows = normalize_nfe(todas_notas)

        # ----------------------------------------------------
        # Cabeçalho da OMIE_NF
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Gravação
        #
        # Como a aba é nova, escrevemos tudo desde A1.
        # Somente OMIE_NF será alterada.
        # ----------------------------------------------------

        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range="'OMIE_NF'!A:AF",
            body={},
        ).execute()

        sheets.api.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id,
            range="'OMIE_NF'!A1",
            valueInputOption="RAW",
            body={
                "values": [headers] + rows
            },
        ).execute()

        # ----------------------------------------------------
        # Resumo
        # ----------------------------------------------------

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
# SYNC OFICIAL
# ============================================================

@app.post("/sync")
def run_sync():
    """
    Sincronização oficial permanece bloqueada
    enquanto validamos a nova arquitetura NF-e.
    """

    return {
        "status": "blocked",
        "message": (
            "Sincronização temporariamente bloqueada "
            "enquanto a arquitetura NF-e é validada."
        ),
    }