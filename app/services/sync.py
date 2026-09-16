from datetime import datetime
from app.config import get_settings
from app.omie.client import OmieClient
from app.omie.resources import ENDPOINTS, normalize_clientes, normalize_vendedores, normalize_produtos, normalize_pedidos
from app.sheets.client import SheetsClient
from app.services.transform import objects, cfg, build_base, build_kpis

RANGES = ["CONFIG!A1:E200","DE_PARA_REPS!A1:F500","CARTEIRA!A1:J50000","OMIE_PEDIDOS!A1:N200000","OMIE_CLIENTES!A1:K100000","OMIE_VENDEDORES!A1:E5000"]

class SyncService:
    def __init__(self):
        s=get_settings(); self.s=s
        self.sh=SheetsClient(s.google_service_account_json,s.spreadsheet_id)
        self.omie=OmieClient(s.omie_app_key,s.omie_app_secret)

    def log(self, routine,status,read=0,written=0,stage='',page='',message=''):
        self.sh.append('LOG_ATUALIZACAO', [[datetime.now().isoformat(timespec='seconds'),routine,status,read,written,stage,page,message[:1000]]])

    def _progress(self, stage):
        def f(page,total,count,acc):
            self.log('OMIE_SYNC','ANDAMENTO',acc,0,stage,f'{page}/{total}',f'Página {page} de {total}')
        return f

    def sync_omie(self):
        tasks=[
          ('CLIENTES','clientes','ListarClientes',['clientes_cadastro','clientesCadastro'],{},normalize_clientes,'OMIE_CLIENTES'),
          ('VENDEDORES','vendedores','ListarVendedores',['cadastro','vendedores','lista_vendedores'],{},normalize_vendedores,'OMIE_VENDEDORES'),
          ('PRODUTOS','produtos','ListarProdutos',['produto_servico_cadastro','produtos','produtoCadastro'],{'filtrar_apenas_omie':'N'},normalize_produtos,'OMIE_PRODUTOS'),
          ('PEDIDOS','pedidos','ListarPedidos',['pedido_venda_produto','pedidos','pedidoVendaProduto'],{'apenas_importado_api':'N'},normalize_pedidos,'OMIE_PEDIDOS'),
        ]
        for stage,key,call,listkeys,extra,normalizer,sheet in tasks:
            self.log('OMIE_SYNC','INICIO',stage=stage)
            data=self.omie.paginate(ENDPOINTS[key],call,listkeys,extra=extra,progress=self._progress(stage))
            rows=normalizer(data); self.sh.replace_rows(sheet,rows)
            self.log('OMIE_SYNC','OK',len(data),len(rows),stage=stage)
        return {'status':'ok'}

    def recalc(self):
        vals=self.sh.batch_get(RANGES)
        config=cfg(vals[RANGES[0]]); reps=objects(vals[RANGES[1]]); carteira=objects(vals[RANGES[2]])
        pedidos=objects(vals[RANGES[3]]); clientes=objects(vals[RANGES[4]]); vendedores=objects(vals[RANGES[5]])
        base_rows=build_base(pedidos,clientes,vendedores,reps,config)
        self.sh.replace_rows('BASE_VENDAS',base_rows)
        base_values=[[],[],['ANO','MES','COMPETENCIA','COD_PEDIDO','NUM_PEDIDO','COD_CLIENTE','CNPJ_CPF','CLIENTE_NOME','COD_VENDEDOR','VENDEDOR_OMIE','REP_ID','REPRESENTANTE','VALOR','STATUS','CATEGORIA','VENDA_VALIDA','MOTIVO_EXCLUSAO','ATUALIZADO_EM']]+base_rows
        kpis=build_kpis(objects(base_values),carteira); self.sh.replace_rows('KPI_MENSAL',kpis)
        self.log('RECALCULAR','OK',len(pedidos),len(base_rows),stage='KPIS',message=f'{len(kpis)} linhas de KPI')
        return {'base_vendas':len(base_rows),'kpis':len(kpis)}

    def run_all(self):
        self.log('SYNC_COMPLETO','INICIO')
        try:
            self.sync_omie(); result=self.recalc()
            # Atualiza ULTIMA_SINCRONIZACAO localizando a chave na CONFIG
            config_rows=self.sh.get('CONFIG!A4:B200')
            for idx,row in enumerate(config_rows,start=4):
                if row and row[0]=='ULTIMA_SINCRONIZACAO': self.sh.set_value(f'CONFIG!B{idx}',datetime.now().isoformat(timespec='seconds')); break
            self.log('SYNC_COMPLETO','OK',message=str(result)); return result
        except Exception as e:
            self.log('SYNC_COMPLETO','ERRO',message=repr(e)); raise
