from __future__ import annotations
import logging, os
from datetime import datetime, date
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
import db
from collector import coletar
from depara import get_depara

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="Dashboard Lenvie", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["*"])

FRONTEND = Path(__file__).parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.on_event("startup")
async def startup():
    db.init_db()


@app.get("/", include_in_schema=False)
async def index():
    html = FRONTEND / "index.html"
    return FileResponse(str(html)) if html.exists() else {"ok": True}


class RefreshRequest(BaseModel):
    data_ini: str | None = None
    data_fim: str | None = None


def _verificar_token(authorization: str | None) -> None:
    token = os.getenv("REFRESH_TOKEN", "")
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Token inválido.")


@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now().isoformat()}


@app.get("/status")
async def status():
    return db.get_status()


@app.post("/refresh")
async def refresh(req: RefreshRequest, background_tasks: BackgroundTasks,
                  authorization: str | None = Header(default=None)):
    _verificar_token(authorization)
    if db.get_status().get("em_andamento"):
        raise HTTPException(status_code=409, detail="Coleta já em andamento.")
    data_ini = req.data_ini or f"01/01/{date.today().year}"
    data_fim = req.data_fim or date.today().strftime("%d/%m/%Y")
    for d, n in [(data_ini, "data_ini"), (data_fim, "data_fim")]:
        try:
            datetime.strptime(d, "%d/%m/%Y")
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{n}: use DD/MM/AAAA")
    background_tasks.add_task(coletar, data_ini, data_fim)
    return {"ok": True, "mensagem": "Coleta iniciada.", "data_ini": data_ini, "data_fim": data_fim}


@app.post("/reset")
async def reset(authorization: str | None = Header(default=None)):
    """Força em_andamento=0 e cancelar_coleta=0. Usar quando o serviço reiniciou com o lock travado."""
    _verificar_token(authorization)
    db.set_status(em_andamento=0, erro="resetado manualmente")
    db.set_cancelar(0)
    return {"ok": True, "mensagem": "Lock liberado."}


@app.post("/cancel")
async def cancel(authorization: str | None = Header(default=None)):
    _verificar_token(authorization)
    if not db.get_status().get("em_andamento"):
        return {"ok": False, "mensagem": "Nenhuma coleta em andamento."}
    db.set_cancelar(1)
    return {"ok": True, "mensagem": "Sinal enviado. A coleta para em até 1 minuto."}


@app.get("/data")
async def data():
    payload = db.get_data_payload()
    payload["coleta_status"] = db.get_status()
    return JSONResponse(content=payload)


@app.get("/skus-pendentes")
async def skus_pendentes():
    dp = get_depara()
    return {"skus_desconhecidos": dp.skus_desconhecidos(), "total": len(dp.skus_desconhecidos())}
