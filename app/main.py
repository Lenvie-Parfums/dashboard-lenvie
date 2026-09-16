import json
import os

from fastapi import FastAPI

from app.services.sync import SyncService
from app.sheets.client import SheetsClient


app = FastAPI(
    title="Lenvie Commercial KPIs",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Lenvie Commercial KPIs",
        "architecture": "render+sheets-v1",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "architecture": "render+sheets-v1",
    }


@app.get("/sheets/test")
def test_sheets():
    """
    Testa:
    Render -> Service Account -> Google Sheets.

    Não consulta o Omie e não altera a planilha.
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

        # GOOGLE_SA_JSON está armazenado no Render como texto JSON.
        service_account_info = json.loads(google_sa_json)

        sheets = SheetsClient(
            service_account_info=service_account_info,
            spreadsheet_id=spreadsheet_id,
        )

        # Faz uma leitura real para confirmar que a Service Account
        # tem acesso à planilha.
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


@app.post("/sync")
def run_sync():
    """
    Executa:
    Omie -> processamento -> Google Sheets.
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