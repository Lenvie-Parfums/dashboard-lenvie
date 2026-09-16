import json
import os

from fastapi import FastAPI

from app.services.sync import SyncService
from app.sheets.client import SheetsClient
from app.omie.client import OmieClient


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
# HEALTH CHECK
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
    """
    Testa:
    Render -> Google Service Account -> Google Sheets

    Não consulta o Omie.
    Não altera a planilha.
    """

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

        # Apenas leitura.
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
    """
    Testa:
    Render -> API Omie

    Busca somente 1 cliente para validar:
    - APP_KEY_OMIE
    - APP_SECRET_OMIE
    - comunicação com a API

    Não grava nada no Sheets.
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

        endpoint = (
            "https://app.omie.com.br/"
            "api/v1/geral/clientes/"
        )

        resposta = omie.call(
            endpoint=endpoint,
            call="ListarClientes",
            param={
                "pagina": 1,
                "registros_por_pagina": 1,
                "apenas_importado_api": "N",
            },
        )

        # Não devolvemos dados do cliente.
        # Apenas informações gerais da consulta.
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
# SINCRONIZAÇÃO
# ============================================================

@app.post("/sync")
def run_sync():
    """
    Executa a sincronização completa:

    Omie
      ->
    processamento
      ->
    Google Sheets

    Esta rota ALTERA a planilha.
    """

    try:
        service = SyncService()

        result = service.run()

        return {
            "status": "ok",
            "result": result,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }