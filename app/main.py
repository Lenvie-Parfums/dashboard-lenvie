import json
import os

from fastapi import FastAPI

from app.services.sync import SyncService
from app.sheets.client import SheetsClient
from app.omie.client import OmieClient
from app.omie.resources import ENDPOINTS, normalize_nfe


app = FastAPI(
    title="Lenvie Commercial KPIs",
    version="1.0.0",
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
        google_sa_json = os.getenv("GOOGLE_SA_JSON")
        spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")

        if not google_sa_json:
            return {
                "status": "error",
                "error": "Variável GOOGLE_SA_JSON não configurada.",
            }

        if not spreadsheet_id:
            return {
                "status": "error",
                "error": "Variável GOOGLE_SPREADSHEET_ID não configurada.",
            }

        service_account_info = json.loads(google_sa_json)

        sheets = SheetsClient(
            service_account_info=service_account_info,
            spreadsheet_id=spreadsheet_id,
        )

        values = sheets.get("CONFIG!A1:B5")

        return {
            "status": "ok",
            "message": "Conexão com Google Sheets realizada com sucesso.",
            "spreadsheet_id": spreadsheet_id,
            "range_testado": "CONFIG!A1:B5",
            "linhas_lidas": len(values),
        }

    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "error": "GOOGLE_SA_JSON não contém um JSON válido.",
            "detail": str(e),
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
        app_key = os.getenv("APP_KEY_OMIE")
        app_secret = os.getenv("APP_SECRET_OMIE")

        if not app_key:
            return {
                "status": "error",
                "error": "Variável APP_KEY_OMIE não configurada.",
            }

        if not app_secret:
            return {
                "status": "error",
                "error": "Variável APP_SECRET_OMIE não configurada.",
            }

        omie = OmieClient(
            app_key=app_key,
            app_secret=app_secret,
        )

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
            "total_de_registros": resposta.get("total_de_registros"),
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
    """
    Consulta somente 1 NF no Omie.

    NÃO grava nada no Google Sheets.
    NÃO executa sincronização.
    NÃO altera KPIs.

    Serve apenas para validar:
    Omie -> ListarNF -> normalização.
    """

    try:
        app_key = os.getenv("APP_KEY_OMIE")
        app_secret = os.getenv("APP_SECRET_OMIE")

        if not app_key:
            return {
                "status": "error",
                "error": "Variável APP_KEY_OMIE não configurada.",
            }

        if not app_secret:
            return {
                "status": "error",
                "error": "Variável APP_SECRET_OMIE não configurada.",
            }

        omie = OmieClient(
            app_key=app_key,
            app_secret=app_secret,
        )

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

        # Não retornamos o RAW completo.
        # Apenas uma amostra da primeira linha normalizada.
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
            "message": "ListarNF executado e normalizado com sucesso.",
            "pagina": resposta.get("pagina"),
            "total_de_paginas": resposta.get("total_de_paginas"),
            "total_de_registros": resposta.get("total_de_registros"),
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
# SYNC
# ============================================================

@app.post("/sync")
def run_sync():
    """
    IMPORTANTE:
    Esta rota ainda não deve ser executada.
    A sincronização será reestruturada para NF-e.
    """

    return {
        "status": "blocked",
        "message": (
            "Sincronização temporariamente bloqueada "
            "enquanto a arquitetura NF-e é validada."
        ),
    }