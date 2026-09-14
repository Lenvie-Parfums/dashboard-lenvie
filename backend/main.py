"""
Dashboard Lenvie — Backend FastAPI
Serve o frontend, coleta do Omie e atualiza o de-para automaticamente.

Env obrigatórias: OMIE_APP_KEY, OMIE_APP_SECRET, REFRESH_TOKEN
Env opcionais:    DB_PATH, DEPARA_CSV, CORS_ORIGINS
"""

from __future__ import annotations
import csv, io, logging, os
from datetime import datetime, date
from pathlib import Path

import httpx
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from collector import coletar
from depara import get_depara, _inferir_linha, _inferir_categoria, _inferir_fragancia
from omie_client import OmieClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="Dashboard Lenvie", version="1.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Frontend estático ─────────────────────────────────────────────────────
FRONTEND = Path(__file__).parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

@app.get("/", include_in_schema=False)
async def index():
    html = FRONTEND / "index.html"
    if html.exists():
        return FileResponse(str(html))
    return {"ok": True, "msg": "API rodando. Frontend não encontrado."}


# ── Startup ───────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    db.init_db()
    log.info("Pronto.")


# ── Helpers ───────────────────────────────────────────────────────────────
def _token_ok(authorization: str | None) -> None:
    t = os.getenv("REFRESH_TOKEN", "")
    if t and authorization != f"Bearer {t}":
        raise HTTPException(401, "Token inválido.")

def _ini() -> str: return f"01/01/{date.today().year}"
def _fim() -> str: return date.today().strftime("%d/%m/%Y")


async def _atualizar_depara() -> int:
    """Puxa ListarProdutos, regenera o CSV e recarrega o de-para. Retorna nº de produtos."""
    produtos = []
    async with httpx.AsyncClient() as http:
        omie = OmieClient(os.environ["OMIE_APP_KEY"], os.environ["OMIE_APP_SECRET"], http)
        async for p in omie.paginate(
            "geral/produtos/", "ListarProdutos",
            {"filtrarPorTipo": "P", "inativo": "N", "exibirCaracteristicas": "N"},
            chave_registros="produto_servico_cadastro", por_pagina=50,
        ):
            sku  = (p.get("codigo") or p.get("codigo_produto") or "").strip().upper()
            desc = (p.get("descricao") or "").strip().upper()
            if sku or desc:
                produtos.append({"sku": sku, "descricao": desc})

    if not produtos:
        return 0

    csv_path = os.getenv("DEPARA_CSV", "/app/depara_produtos.csv")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["sku","descricao","linha","categoria","fragancia"], lineterminator="\n")
    w.writeheader()
    for p in produtos:
        d = p["descricao"]
        w.writerow({**p, "linha": _inferir_linha(d), "categoria": _inferir_categoria(d), "fragancia": _inferir_fragancia(d)})

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    Path(csv_path).write_text(buf.getvalue(), encoding="utf-8")
    get_depara.cache_clear()
    log.info("De-para atualizado: %d produtos", len(produtos))
    return len(produtos)


async def _coleta_completa(data_ini: str, data_fim: str):
    """Atualiza de-para e depois coleta NFs."""
    try:
        await _atualizar_depara()
    except Exception as e:
        log.warning("De-para falhou (coleta continua mesmo assim): %s", e)
    await coletar(data_ini, data_fim)


# ── Endpoints ─────────────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    data_ini: str | None = None
    data_fim: str | None = None


@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now().isoformat()}


@app.get("/status")
async def status():
    return db.get_status()


@app.post("/refresh")
async def refresh(
    req: RefreshRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    """Botão da Carla — atualiza de-para e coleta NFs em background."""
    _token_ok(authorization)
    if db.get_status().get("em_andamento"):
        raise HTTPException(409, "Coleta já em andamento.")

    ini = req.data_ini or _ini()
    fim = req.data_fim or _fim()
    for d, n in [(ini,"data_ini"),(fim,"data_fim")]:
        try: datetime.strptime(d, "%d/%m/%Y")
        except ValueError: raise HTTPException(422, f"{n}: use DD/MM/AAAA")

    background_tasks.add_task(_coleta_completa, ini, fim)
    return {"ok": True, "data_ini": ini, "data_fim": fim}


@app.get("/cron")
async def cron(authorization: str | None = Header(default=None)):
    """
    Chamado diariamente pelo cron-job.org às 6h.
    Atualiza de-para + coleta NFs do ano atual até hoje.
    Protegido pelo mesmo REFRESH_TOKEN.
    """
    _token_ok(authorization)
    if db.get_status().get("em_andamento"):
        return {"ok": False, "msg": "Coleta já em andamento."}

    import asyncio
    asyncio.create_task(_coleta_completa(_ini(), _fim()))
    return {"ok": True, "msg": "Coleta diária iniciada."}


@app.get("/data")
async def data():
    payload = db.get_data_payload()
    payload["coleta_status"] = db.get_status()
    return JSONResponse(content=payload)


@app.get("/skus-pendentes")
async def skus_pendentes():
    dp = get_depara()
    return {"skus_desconhecidos": dp.skus_desconhecidos(), "total": len(dp.skus_desconhecidos())}
