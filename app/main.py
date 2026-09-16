from fastapi import FastAPI, Header, HTTPException
from app.config import get_settings
from app.services.sync import SyncService

app=FastAPI(title='Lenvie Comercial KPIs',version='1.0.0')

def guard(token):
    expected=get_settings().admin_token
    if expected and token != expected: raise HTTPException(401,'Token inválido')

@app.get('/health')
def health(): return {'status':'ok','architecture':'render+sheets-v1'}

@app.post('/admin/sync')
def sync(x_admin_token: str|None=Header(default=None)):
    guard(x_admin_token); return SyncService().run_all()

@app.post('/admin/recalc')
def recalc(x_admin_token: str|None=Header(default=None)):
    guard(x_admin_token); return SyncService().recalc()

@app.get('/api/kpis')
def kpis():
    s=get_settings(); sh=SyncService().sh
    values=sh.get('KPI_MENSAL!A3:L50000')
    if not values: return []
    h=values[0]; return [{h[i]:r[i] if i<len(r) else '' for i in range(len(h))} for r in values[1:]]
