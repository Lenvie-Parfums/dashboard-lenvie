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


RAW_HISTORICO_SPREADSHEET_ID = "1F8mJ6weCB0z7MykKJfm2GbVb3JsfTOJ5fOJeDB8ERv0"

def get_raw_historico_sheets_client():
    """Cliente separado para a nova planilha RAW histórica."""
    google_sa_json = os.getenv("GOOGLE_SA_JSON")
    if not google_sa_json:
        raise RuntimeError("Variável GOOGLE_SA_JSON não configurada.")
    try:
        service_account_info = json.loads(google_sa_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SA_JSON não contém um JSON válido.") from exc
    return SheetsClient(
        service_account_info=service_account_info,
        spreadsheet_id=RAW_HISTORICO_SPREADSHEET_ID,
    )


# ============================================================
# NOVA PLANILHA RAW HISTORICO - TESTE SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/teste-conexao")
def teste_conexao_raw_historico():
    """Somente lê metadados. Não grava e não chama Omie."""
    try:
        sheets = get_raw_historico_sheets_client()
        metadata = (
            sheets.api.spreadsheets().get(
                spreadsheetId=sheets.spreadsheet_id,
                fields="properties.title,sheets.properties.title",
            ).execute()
        )
        abas = [
            item.get("properties", {}).get("title", "")
            for item in metadata.get("sheets", [])
        ]
        return {
            "status": "ok",
            "message": "Conexão somente leitura com a nova planilha RAW realizada com sucesso.",
            "spreadsheet_id": sheets.spreadsheet_id,
            "titulo": metadata.get("properties", {}).get("title"),
            "abas_encontradas": abas,
            "omie_api_chamada": False,
            "planilha_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }
    except Exception as e:
        return {
            "status": "error", "error": repr(e),
            "omie_api_chamada": False, "planilha_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False, "cursor_2026_alterado": False,
        }


# ============================================================
# NOVA PLANILHA RAW HISTORICO - PREPARAR ESTRUTURA
# ============================================================

@app.post("/omie/raw-historico/preparar-estrutura")
def preparar_estrutura_raw_historico():
    """
    Cria/valida somente a aba OMIE_NF_2025 na NOVA planilha RAW.
    Não chama Omie, não lê/grava a planilha principal e não altera cursores.
    """
    try:
        sheets = get_raw_historico_sheets_client()
        aba = "OMIE_NF_2025"

        headers = [
            "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
            "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
            "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
            "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
            "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
            "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
        ]

        metadata = (
            sheets.api.spreadsheets()
            .get(
                spreadsheetId=sheets.spreadsheet_id,
                fields="sheets.properties.title",
            )
            .execute()
        )
        existentes = {
            item.get("properties", {}).get("title", "")
            for item in metadata.get("sheets", [])
        }

        aba_criada = False
        if aba not in existentes:
            sheets.api.spreadsheets().batchUpdate(
                spreadsheetId=sheets.spreadsheet_id,
                body={
                    "requests": [{
                        "addSheet": {
                            "properties": {
                                "title": aba,
                                "gridProperties": {
                                    "rowCount": 1000,
                                    "columnCount": 32,
                                },
                            }
                        }
                    }]
                },
            ).execute()
            aba_criada = True

        atual = sheets.get(f"'{aba}'!A1:AF1")

        if atual and any(clean(x) for x in atual[0]):
            cab_atual = [clean(x) for x in atual[0]]
            if cab_atual != headers:
                return {
                    "status": "error",
                    "error": "CABECALHO_RAW_DIFERENTE_DO_CONTRATO",
                    "aba": aba,
                    "aba_criada": aba_criada,
                    "cabecalho_atual": cab_atual,
                    "cabecalho_esperado": headers,
                    "omie_api_chamada": False,
                    "base_vendas_alterada": False,
                    "cursor_2025_alterado": False,
                    "cursor_2026_alterado": False,
                }
        else:
            sheets.api.spreadsheets().values().update(
                spreadsheetId=sheets.spreadsheet_id,
                range=f"'{aba}'!A1:AF1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()

        conferido = sheets.get(f"'{aba}'!A1:AF1")
        cab_final = [clean(x) for x in (conferido[0] if conferido else [])]

        if cab_final != headers:
            return {
                "status": "error",
                "error": "FALHA_VALIDACAO_CABECALHO_RAW",
                "aba": aba,
                "omie_api_chamada": False,
                "base_vendas_alterada": False,
                "cursor_2025_alterado": False,
                "cursor_2026_alterado": False,
            }

        return {
            "status": "ok",
            "message": "Estrutura RAW 2025 preparada e cabeçalho validado.",
            "spreadsheet_id": sheets.spreadsheet_id,
            "aba": aba,
            "aba_criada": aba_criada,
            "colunas": len(headers),
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
            "proximo_passo": "Testar uma unica pagina do cursor 2025 na nova RAW.",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": repr(e),
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }


# ============================================================
# NOVA PLANILHA RAW HISTORICO - TESTE CONTROLADO DE UMA PAGINA
# ============================================================

@app.post("/omie/raw-historico/testar-pagina-2025")
def testar_pagina_2025_raw(ano: int = 2025, mes: int = 10, pagina: int = 13):
    """
    Teste controlado: grava UMA página explícita de 2025 na nova RAW.
    NÃO lê nem altera o cursor 2025, NÃO altera cursor 2026 e NÃO altera BASE_VENDAS.
    """
    import calendar

    try:
        if ano != 2025 or mes < 1 or mes > 12 or pagina < 1:
            return {"status": "error", "error": "Parâmetros inválidos para teste 2025."}

        omie = get_omie_client()
        raw = get_raw_historico_sheets_client()
        aba = "OMIE_NF_2025"

        headers = [
            "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
            "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
            "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
            "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
            "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
            "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
        ]

        cab = raw.get(f"'{aba}'!A1:AF1")
        if not cab or [clean(x) for x in cab[0]] != headers:
            return {
                "status": "error",
                "error": "CABECALHO_RAW_INVALIDO",
                "cursor_2025_alterado": False,
                "cursor_2026_alterado": False,
                "base_vendas_alterada": False,
            }

        ultimo_dia = calendar.monthrange(ano, mes)[1]
        resposta = get_omie_client().call(
            endpoint=ENDPOINTS["nfe"],
            call="ListarNF",
            param={
                "pagina": pagina,
                "registros_por_pagina": 100,
                "dEmiInicial": f"01/{mes:02d}/{ano}",
                "dEmiFinal": f"{ultimo_dia:02d}/{mes:02d}/{ano}",
            },
        )

        notas = resposta.get("nfCadastro") or []
        rows = normalize_nfe(notas)
        total_paginas = int(resposta.get("total_de_paginas") or 1)

        if pagina > total_paginas:
            return {
                "status": "error",
                "error": "PAGINA_ACIMA_DO_TOTAL",
                "pagina": pagina,
                "total_paginas": total_paginas,
                "cursor_2025_alterado": False,
                "cursor_2026_alterado": False,
                "base_vendas_alterada": False,
            }

        # A nova RAW está vazia neste primeiro teste.
        # Ainda assim, deduplica dentro da própria página antes do append.
        def row_key(r):
            id_nf = clean(r[0]) if len(r) > 0 else ""
            id_item = clean(r[14]) if len(r) > 14 else ""
            fallback = "|".join([
                clean(r[16]) if len(r) > 16 else "",
                clean(r[18]) if len(r) > 18 else "",
                clean(r[23]) if len(r) > 23 else "",
                clean(r[20]) if len(r) > 20 else "",
            ])
            return f"{id_nf}|{id_item or fallback}"

        unicas = []
        chaves = set()
        for r in rows:
            if not r:
                continue
            k = row_key(r)
            if k in chaves:
                continue
            chaves.add(k)
            unicas.append(r)

        if unicas:
            raw.api.spreadsheets().values().append(
                spreadsheetId=raw.spreadsheet_id,
                range=f"'{aba}'!A:AF",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": unicas},
            ).execute()

        return {
            "status": "ok",
            "message": "Página de teste gravada somente na nova RAW.",
            "processado": {"ano": ano, "mes": mes, "pagina": pagina},
            "total_paginas_mes": total_paginas,
            "nfs_recebidas": len(notas),
            "itens_normalizados": len(rows),
            "itens_gravados_raw": len(unicas),
            "spreadsheet_raw": raw.spreadsheet_id,
            "aba_destino": aba,
            "planilha_principal_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
            "cron_deve_permanecer_suspenso": True,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": repr(e),
            "planilha_principal_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }


# ============================================================
# AUDITORIA 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/auditoria-2025")
def auditoria_historico_2025():
    """Audita 2025 nas RAW antiga/nova sem gravar, limpar ou mover dados."""
    from collections import Counter
    from datetime import datetime as _dt

    HEADER = [
        "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
        "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
        "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
        "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
        "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
        "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
    ]

    def ano_mes(v):
        s=clean(v)
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                d=_dt.strptime(s[:19],f); return d.year,d.month
            except Exception: pass
        try:
            d=_dt.fromisoformat(s.replace("Z","+00:00")); return d.year,d.month
        except Exception: return None,None

    def ler(client, aba, nome):
        cab=client.get(f"'{aba}'!A1:AF1")
        if not cab or [clean(x) for x in cab[0]] != HEADER:
            raise RuntimeError(f"{nome}: cabecalho A:AF invalido")
        meses={m:{"linhas":0,"nfs":set(),"keys":Counter(),"sem_item":0,"cfops":Counter()} for m in range(1,13)}
        inicio=2; bloco=10000; fora=0; invalidas=0
        while True:
            dados=client.get(f"'{aba}'!A{inicio}:AF{inicio+bloco-1}")
            if not dados: break
            for r in dados:
                if not r or not any(clean(x) for x in r): continue
                a,m=ano_mes(r[4] if len(r)>4 else "")
                if a is None: invalidas+=1; continue
                if a != 2025: fora+=1; continue
                idnf=clean(r[0]) if len(r)>0 else ""
                item=clean(r[14]) if len(r)>14 else ""
                cfop=clean(r[18]) if len(r)>18 else ""
                if item:
                    k=f"{idnf}|{item}"
                else:
                    meses[m]["sem_item"]+=1
                    sku=clean(r[16]) if len(r)>16 else ""
                    val=clean(r[27]) if len(r)>27 else ""
                    k=f"FALLBACK|{idnf}|{sku}|{cfop}|{val}"
                meses[m]["linhas"]+=1
                if idnf: meses[m]["nfs"].add(idnf)
                meses[m]["keys"][k]+=1
                if cfop: meses[m]["cfops"][cfop]+=1
            if len(dados)<bloco: break
            inicio+=bloco

        allkeys=Counter(); allnfs=set()
        resumo={}
        for m in range(1,13):
            allkeys.update(meses[m]["keys"]); allnfs.update(meses[m]["nfs"])
            c=meses[m]["keys"]
            resumo[f"{m:02d}"]={
                "linhas":meses[m]["linhas"],
                "nfs_unicas":len(meses[m]["nfs"]),
                "chaves_unicas":len(c),
                "chaves_duplicadas":sum(1 for v in c.values() if v>1),
                "linhas_duplicadas_extras":sum(v-1 for v in c.values() if v>1),
                "linhas_sem_id_item":meses[m]["sem_item"],
                "cfops":dict(sorted(meses[m]["cfops"].items())),
            }
        return {
            "fonte":nome,"aba":aba,
            "linhas_2025":sum(x["linhas"] for x in meses.values()),
            "nfs_unicas_2025":len(allnfs),
            "chaves_unicas_2025":len(allkeys),
            "chaves_duplicadas_2025":sum(1 for v in allkeys.values() if v>1),
            "linhas_duplicadas_extras_2025":sum(v-1 for v in allkeys.values() if v>1),
            "linhas_fora_2025":fora,"datas_invalidas":invalidas,
            "meses":resumo,"_keys":allkeys,"_nfs":allnfs,
        }

    try:
        antiga=ler(get_sheets_client(),"OMIE_NF","RAW_ANTIGA")
        nova=ler(get_raw_historico_sheets_client(),"OMIE_NF_2025","RAW_NOVA")
        ka=antiga.pop("_keys"); kn=nova.pop("_keys")
        na=antiga.pop("_nfs"); nn=nova.pop("_nfs")
        combinado=Counter(ka); combinado.update(kn)
        return {
            "status":"ok","somente_leitura":True,"omie_api_chamada":False,
            "planilha_principal_alterada":False,"planilha_raw_alterada":False,
            "base_vendas_alterada":False,"cursor_2025_alterado":False,
            "cursor_2026_alterado":False,
            "criterio_duplicidade":"ID_NF + ID_ITEM; fallback diagnostico quando ID_ITEM vazio",
            "raw_antiga":antiga,"raw_nova":nova,
            "cruzamento":{
                "chaves_presentes_nas_duas_fontes":len(set(ka)&set(kn)),
                "nfs_presentes_nas_duas_fontes":len(na&nn),
                "chaves_unicas_uniao_2025":len(set(ka)|set(kn)),
                "nfs_unicas_uniao_2025":len(na|nn),
                "chaves_duplicadas_considerando_as_duas_fontes":sum(1 for v in combinado.values() if v>1),
                "linhas_duplicadas_extras_considerando_as_duas_fontes":sum(v-1 for v in combinado.values() if v>1),
            }
        }
    except Exception as e:
        return {"status":"error","somente_leitura":True,"error":repr(e),
                "omie_api_chamada":False,"planilha_principal_alterada":False,
                "planilha_raw_alterada":False,"base_vendas_alterada":False,
                "cursor_2025_alterado":False,"cursor_2026_alterado":False}



# ============================================================
# PREVIA CONSOLIDADA DE NFs 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/previa-nfs-2025")
def previa_nfs_2025(mes: int):
    """
    Prévia mensal 2025 - SOMENTE LEITURA.
    Uso: GET /omie/raw-historico/previa-nfs-2025?mes=1

    Lê RAW antiga + RAW nova em blocos, mas mantém em memória somente
    as chaves/itens do mês solicitado. Não altera planilhas, cursores
    ou BASE_VENDAS e não chama a API Omie.
    """
    from collections import Counter
    from datetime import datetime as _dt

    if mes < 1 or mes > 12:
        return {
            "status": "error",
            "error": "mes deve estar entre 1 e 12",
            "somente_leitura": True
        }

    HEADER = [
        "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
        "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
        "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
        "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
        "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
        "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
    ]

    # Regra provisória para diagnóstico. Nada é gravado.
    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.113",
        "6.401","6.403","7.101","7.102",
    }
    CFOP_EXCLUIDO = {"5.910","6.910"}

    def ano_mes(v):
        s = clean(v)
        if not s:
            return None, None
        for f in (
            "%d/%m/%Y", "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"
        ):
            try:
                d = _dt.strptime(s[:19], f)
                return d.year, d.month
            except Exception:
                pass
        try:
            d = _dt.fromisoformat(s.replace("Z", "+00:00"))
            return d.year, d.month
        except Exception:
            return None, None

    def num(v):
        s = clean(v)
        if not s:
            return 0.0
        try:
            if "," in s:
                return float(s.replace(".", "").replace(",", "."))
            return float(s)
        except Exception:
            return 0.0

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()

        # Somente itens do mês solicitado ficam em memória.
        itens = {}
        origem_por_chave = {}

        def carregar_mes(client, aba, origem):
            cab = client.get(f"'{aba}'!A1:AF1")
            if not cab or [clean(x) for x in cab[0]] != HEADER:
                raise RuntimeError(f"{origem}: cabecalho A:AF invalido")

            # ETAPA 1: varre SOMENTE a coluna E (DATA_EMISSAO), que é leve.
            # Assim evitamos baixar centenas de milhares de linhas A:AF.
            inicio = 2
            bloco_datas = 20000
            linhas_datas_lidas = 0
            linhas_mes = 0
            duplicadas_ignoradas = 0
            linhas_alvo = []

            while True:
                datas = client.get(f"'{aba}'!E{inicio}:E{inicio+bloco_datas-1}")
                if not datas:
                    break

                linhas_datas_lidas += len(datas)

                for offset, cel in enumerate(datas):
                    valor = cel[0] if cel else ""
                    a, m = ano_mes(valor)
                    if a == 2025 and m == mes:
                        linhas_alvo.append(inicio + offset)

                if len(datas) < bloco_datas:
                    break
                inicio += bloco_datas

            # ETAPA 2: busca A:AF SOMENTE para trechos que realmente contêm
            # linhas do mês. Agrupa linhas consecutivas e limita cada leitura
            # a no máximo 2000 linhas, equilibrando memória e quota de leitura do Google Sheets.
            grupos = []
            if linhas_alvo:
                ini = ant = linhas_alvo[0]
                for linha in linhas_alvo[1:]:
                    if linha == ant + 1 and (linha - ini + 1) <= 2000:
                        ant = linha
                    else:
                        grupos.append((ini, ant))
                        ini = ant = linha
                grupos.append((ini, ant))

            linhas_detalhes_lidas = 0

            for ini, fim in grupos:
                dados = client.get(f"'{aba}'!A{ini}:AF{fim}")
                linhas_detalhes_lidas += len(dados or [])

                for r in (dados or []):
                    if not r or not any(clean(x) for x in r):
                        continue

                    a, m = ano_mes(r[4] if len(r) > 4 else "")
                    if a != 2025 or m != mes:
                        continue

                    linhas_mes += 1
                    rr = list(r) + [""] * (32 - len(r))
                    rr = rr[:32]

                    id_nf = clean(rr[0])
                    id_item = clean(rr[14])

                    if id_item:
                        chave = f"{id_nf}|{id_item}"
                    else:
                        sku = clean(rr[16])
                        cfop = clean(rr[18])
                        qtd = clean(rr[20])
                        val = clean(rr[27])
                        chave = f"FALLBACK|{id_nf}|{sku}|{cfop}|{qtd}|{val}"

                    if chave in itens:
                        duplicadas_ignoradas += 1
                        continue

                    itens[chave] = rr
                    origem_por_chave[chave] = origem

            return {
                "datas_lidas_coluna_e": linhas_datas_lidas,
                "linhas_alvo_encontradas": len(linhas_alvo),
                "linhas_detalhes_a_af_lidas": linhas_detalhes_lidas,
                "grupos_de_leitura": len(grupos),
                "linhas_do_mes": linhas_mes,
                "duplicadas_ignoradas_na_consolidacao": duplicadas_ignoradas,
            }

        carga_antiga = carregar_mes(principal, "OMIE_NF", "RAW_ANTIGA")
        carga_nova = carregar_mes(raw, "OMIE_NF_2025", "RAW_NOVA")

        nfs = {}

        for chave, r in itens.items():
            id_nf = clean(r[0])
            if not id_nf:
                continue

            if id_nf not in nfs:
                nfs[id_nf] = {
                    "id_nf": id_nf,
                    "num_nf": clean(r[2]),
                    "data_emissao": clean(r[4]),
                    "tipo_nf": clean(r[5]),
                    "data_cancelamento": clean(r[6]),
                    "cliente_nome": clean(r[11]),
                    "cnpj_cpf": clean(r[10]),
                    "cod_vendedor": clean(r[12]),
                    "categoria": clean(r[13]),
                    "valor_nf": num(r[30]),
                    "cfops": set(),
                    "cfops_venda": set(),
                    "cfops_excluidos": set(),
                    "cfops_pendentes": set(),
                    "qtd_itens": 0,
                    "itens_venda": 0,
                    "itens_excluidos": 0,
                    "itens_pendentes": 0,
                    "valor_itens_venda": 0.0,
                    "valor_itens_excluidos": 0.0,
                    "valor_itens_pendentes": 0.0,
                    "origens": set(),
                }

            nf = nfs[id_nf]
            cfop = clean(r[18])
            valor_item = num(r[27])

            nf["qtd_itens"] += 1
            nf["origens"].add(origem_por_chave.get(chave, ""))

            if cfop:
                nf["cfops"].add(cfop)

            if cfop in CFOP_VENDA:
                nf["cfops_venda"].add(cfop)
                nf["itens_venda"] += 1
                nf["valor_itens_venda"] += valor_item
            elif cfop in CFOP_EXCLUIDO:
                nf["cfops_excluidos"].add(cfop)
                nf["itens_excluidos"] += 1
                nf["valor_itens_excluidos"] += valor_item
            else:
                if cfop:
                    nf["cfops_pendentes"].add(cfop)
                nf["itens_pendentes"] += 1
                nf["valor_itens_pendentes"] += valor_item

        cfops = Counter()
        pendentes = Counter()
        combinacoes = Counter()
        exemplos = []

        total_valor_nf = 0.0
        total_venda = 0.0
        total_excluido = 0.0
        total_pendente = 0.0
        nfs_com_venda = 0
        nfs_com_pendente = 0
        nfs_so_excluidas = 0

        for nf in nfs.values():
            total_valor_nf += nf["valor_nf"]
            total_venda += nf["valor_itens_venda"]
            total_excluido += nf["valor_itens_excluidos"]
            total_pendente += nf["valor_itens_pendentes"]

            if nf["itens_venda"] > 0:
                nfs_com_venda += 1
            if nf["itens_pendentes"] > 0:
                nfs_com_pendente += 1
            if nf["itens_venda"] == 0 and nf["itens_pendentes"] == 0:
                nfs_so_excluidas += 1

            for c in nf["cfops"]:
                cfops[c] += 1
            for c in nf["cfops_pendentes"]:
                pendentes[c] += 1

            combinacoes[";".join(sorted(nf["cfops"]))] += 1

            if nf["cfops_pendentes"] and len(exemplos) < 50:
                exemplos.append({
                    "id_nf": nf["id_nf"],
                    "num_nf": nf["num_nf"],
                    "data_emissao": nf["data_emissao"],
                    "cliente_nome": nf["cliente_nome"],
                    "valor_nf": round(nf["valor_nf"], 2),
                    "cfops": sorted(nf["cfops"]),
                    "cfops_venda": sorted(nf["cfops_venda"]),
                    "cfops_excluidos": sorted(nf["cfops_excluidos"]),
                    "cfops_pendentes": sorted(nf["cfops_pendentes"]),
                    "qtd_itens": nf["qtd_itens"],
                    "itens_venda": nf["itens_venda"],
                    "itens_excluidos": nf["itens_excluidos"],
                    "itens_pendentes": nf["itens_pendentes"],
                    "origens": sorted(x for x in nf["origens"] if x),
                })

        return {
            "status": "ok",
            "ano": 2025,
            "mes": mes,
            "somente_leitura": True,
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "planilha_raw_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
            "carga": {
                "raw_antiga": carga_antiga,
                "raw_nova": carga_nova,
                "itens_unicos_consolidados_mes": len(itens),
                "nfs_unicas_consolidadas_mes": len(nfs),
            },
            "resumo": {
                "nfs_total": len(nfs),
                "nfs_com_cfop_venda": nfs_com_venda,
                "nfs_com_cfop_pendente": nfs_com_pendente,
                "nfs_somente_excluidas": nfs_so_excluidas,
                "soma_valor_nf": round(total_valor_nf, 2),
                "soma_valor_itens_venda": round(total_venda, 2),
                "soma_valor_itens_excluidos": round(total_excluido, 2),
                "soma_valor_itens_pendentes": round(total_pendente, 2),
            },
            "regra_previa": {
                "cfops_venda": sorted(CFOP_VENDA),
                "cfops_excluidos": sorted(CFOP_EXCLUIDO),
                "demais_cfops": "PENDENTE",
                "observacao": "Regra provisoria somente para diagnostico."
            },
            "cfops_por_quantidade_de_nfs": dict(sorted(cfops.items())),
            "cfops_pendentes_por_quantidade_de_nfs": dict(sorted(pendentes.items())),
            "combinacoes_cfop_mais_frequentes": [
                {"cfops": k, "nfs": v}
                for k, v in combinacoes.most_common(30)
            ],
            "exemplos_nfs_com_cfop_pendente": exemplos,
            "proximo_passo": (
                "Executar os demais meses de 2025 e validar os CFOPs pendentes "
                "antes de gerar BASE_VENDAS."
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "ano": 2025,
            "mes": mes,
            "somente_leitura": True,
            "error": repr(e),
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "planilha_raw_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }





# ============================================================
# AUDITORIA CFOP PENDENTE X VENDA 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/pendentes-com-venda-2025")
def pendentes_com_venda_2025():
    """
    Analisa 2025 em RAW antiga + nova e mostra quais CFOPs PENDENTES/A_VALIDAR
    aparecem em NFs que também possuem CFOP de VENDA.
    Somente leitura: não chama Omie, não grava planilhas, BASE_VENDAS ou cursores.
    """
    from collections import Counter, defaultdict
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    CFOP_A_VALIDAR = {"7.101","7.102"}

    def ano_2025(v):
        x = clean(v)
        if not x:
            return False
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                return _dt.strptime(x[:19], f).year == 2025
            except Exception:
                pass
        try:
            return _dt.fromisoformat(x.replace("Z", "+00:00")).year == 2025
        except Exception:
            return False

    def classificar(cfop):
        if cfop in CFOP_VENDA:
            return "VENDA"
        if cfop in CFOP_BONIFICACAO:
            return "BONIFICACAO"
        if cfop in CFOP_A_VALIDAR:
            return "A_VALIDAR"
        return "PENDENTE"

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()

        # Mantemos somente sets de CFOP por NF. Não carregamos A:AF nem valores/RAW_JSON.
        cfops_por_nf = defaultdict(set)
        chaves_itens = set()
        fontes = {}

        def ler_fonte(client, aba, nome):
            # A=ID_NF, E=DATA_EMISSAO, O=ID_ITEM, S=CFOP
            inicio = 2
            bloco = 20000
            linhas_2025 = 0
            duplicadas_ignoradas = 0
            while True:
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id,
                    ranges=[
                        f"'{aba}'!A{inicio}:A{inicio+bloco-1}",
                        f"'{aba}'!E{inicio}:E{inicio+bloco-1}",
                        f"'{aba}'!O{inicio}:O{inicio+bloco-1}",
                        f"'{aba}'!S{inicio}:S{inicio+bloco-1}",
                    ],
                    majorDimension="ROWS",
                ).execute()
                vr = resp.get("valueRanges") or []
                cols = [(x.get("values") or []) for x in vr]
                tamanhos = [len(x) for x in cols]
                n = max(tamanhos or [0])
                if n == 0:
                    break

                for i in range(n):
                    def cel(c):
                        if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]:
                            return ""
                        return clean(cols[c][i][0])
                    id_nf, data, id_item, cfop = cel(0), cel(1), cel(2), cel(3)
                    if not id_nf or not ano_2025(data):
                        continue
                    linhas_2025 += 1
                    # Deduplica entre RAW antiga/nova quando ID_ITEM existe.
                    if id_item:
                        chave = f"{id_nf}|{id_item}"
                        if chave in chaves_itens:
                            duplicadas_ignoradas += 1
                            continue
                        chaves_itens.add(chave)
                    if cfop:
                        cfops_por_nf[id_nf].add(cfop)

                if n < bloco:
                    break
                inicio += bloco

            fontes[nome] = {
                "linhas_2025_lidas": linhas_2025,
                "duplicidades_id_nf_id_item_ignoradas": duplicadas_ignoradas,
            }

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        pendentes_em_nf_com_venda = Counter()
        validar_em_nf_com_venda = Counter()
        combinacoes = Counter()
        exemplos = []
        nfs_com_venda = 0
        nfs_venda_com_pendente = 0
        nfs_venda_com_a_validar = 0

        for id_nf, cfops in cfops_por_nf.items():
            vendas = sorted(c for c in cfops if classificar(c) == "VENDA")
            if not vendas:
                continue
            nfs_com_venda += 1
            pend = sorted(c for c in cfops if classificar(c) == "PENDENTE")
            aval = sorted(c for c in cfops if classificar(c) == "A_VALIDAR")
            if pend:
                nfs_venda_com_pendente += 1
                for c in pend:
                    pendentes_em_nf_com_venda[c] += 1
            if aval:
                nfs_venda_com_a_validar += 1
                for c in aval:
                    validar_em_nf_com_venda[c] += 1
            if pend or aval:
                combinacoes[";".join(sorted(cfops))] += 1
                if len(exemplos) < 50:
                    exemplos.append({
                        "id_nf": id_nf,
                        "cfops_venda": vendas,
                        "cfops_pendentes": pend,
                        "cfops_a_validar": aval,
                        "cfops_todos": sorted(cfops),
                    })

        return {
            "status": "ok",
            "ano": 2025,
            "somente_leitura": True,
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "planilha_raw_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
            "criterio": "CFOPs PENDENTE/A_VALIDAR que coexistem na mesma NF com ao menos um CFOP_VENDA",
            "deduplicacao": "ID_NF + ID_ITEM quando ID_ITEM existe; análise final por conjunto de CFOPs da NF",
            "resumo": {
                "nfs_2025_com_cfop": len(cfops_por_nf),
                "nfs_com_venda": nfs_com_venda,
                "nfs_venda_com_algum_pendente": nfs_venda_com_pendente,
                "nfs_venda_com_algum_a_validar": nfs_venda_com_a_validar,
                "cfops_pendentes_relevantes": len(pendentes_em_nf_com_venda),
                "cfops_a_validar_relevantes": len(validar_em_nf_com_venda),
            },
            "cfops_pendentes_em_nfs_com_venda": dict(sorted(
                pendentes_em_nf_com_venda.items(), key=lambda x: (-x[1], x[0])
            )),
            "cfops_a_validar_em_nfs_com_venda": dict(sorted(
                validar_em_nf_com_venda.items(), key=lambda x: (-x[1], x[0])
            )),
            "combinacoes_mais_frequentes": [
                {"cfops": k, "nfs": v} for k, v in combinacoes.most_common(40)
            ],
            "exemplos": exemplos,
            "fontes": fontes,
            "proximo_passo": "Validar somente os CFOPs listados como relevantes antes de gerar BASE_VENDAS.",
        }
    except Exception as e:
        return {
            "status": "error",
            "ano": 2025,
            "somente_leitura": True,
            "error": repr(e),
            "omie_api_chamada": False,
            "planilha_principal_alterada": False,
            "planilha_raw_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }


# ============================================================
# PREVIA DEFINITIVA BASE_VENDAS 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/previa-base-vendas-2025")
def previa_base_vendas_2025():
    """
    Consolida RAW antiga + RAW nova de 2025 por NF, com deduplicacao ID_NF+ID_ITEM.
    Classifica itens em VENDA/BONIFICACAO/A_VALIDAR/PENDENTE e calcula uma previa
    mensal da futura BASE_VENDAS. SOMENTE LEITURA: nao chama Omie e nao grava nada.
    """
    from collections import defaultdict
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    CFOP_A_VALIDAR = {"7.101","7.102"}

    def parse_data(v):
        s = clean(v)
        if not s:
            return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                return _dt.strptime(s[:19], f)
            except Exception:
                pass
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def numero(v):
        s = clean(v)
        if not s:
            return 0.0
        try:
            if "," in s:
                return float(s.replace(".", "").replace(",", "."))
            return float(s)
        except Exception:
            return 0.0

    def classe(cfop):
        if cfop in CFOP_VENDA:
            return "VENDA"
        if cfop in CFOP_BONIFICACAO:
            return "BONIFICACAO"
        if cfop in CFOP_A_VALIDAR:
            return "A_VALIDAR"
        return "PENDENTE"

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()

        # Guarda apenas chaves de deduplicacao e o agregado compacto por NF.
        chaves = set()
        nfs = {}
        fontes = {}

        def ler_fonte(client, aba, nome):
            inicio = 2
            bloco = 10000
            linhas_2025 = 0
            duplicadas = 0

            # A ID_NF, C NUM_NF, E DATA_EMISSAO, G DATA_CANCELAMENTO,
            # K CNPJ_CPF, L CLIENTE_NOME, M COD_VENDEDOR, O ID_ITEM,
            # S CFOP, AB VALOR_TOTAL_ITEM, AE VALOR_NF.
            while True:
                ranges = [
                    f"'{aba}'!A{inicio}:A{inicio+bloco-1}",
                    f"'{aba}'!C{inicio}:C{inicio+bloco-1}",
                    f"'{aba}'!E{inicio}:E{inicio+bloco-1}",
                    f"'{aba}'!G{inicio}:G{inicio+bloco-1}",
                    f"'{aba}'!K{inicio}:K{inicio+bloco-1}",
                    f"'{aba}'!L{inicio}:L{inicio+bloco-1}",
                    f"'{aba}'!M{inicio}:M{inicio+bloco-1}",
                    f"'{aba}'!O{inicio}:O{inicio+bloco-1}",
                    f"'{aba}'!S{inicio}:S{inicio+bloco-1}",
                    f"'{aba}'!AB{inicio}:AB{inicio+bloco-1}",
                    f"'{aba}'!AE{inicio}:AE{inicio+bloco-1}",
                ]
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id,
                    ranges=ranges,
                    majorDimension="ROWS",
                ).execute()
                vr = resp.get("valueRanges") or []
                cols = [(x.get("values") or []) for x in vr]
                n = max([len(x) for x in cols] or [0])
                if n == 0:
                    break

                def cel(c, i):
                    if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]:
                        return ""
                    return clean(cols[c][i][0])

                for i in range(n):
                    id_nf = cel(0, i)
                    num_nf = cel(1, i)
                    data_txt = cel(2, i)
                    data = parse_data(data_txt)
                    if not id_nf or not data or data.year != 2025:
                        continue
                    linhas_2025 += 1

                    cancelamento = cel(3, i)
                    cnpj = cel(4, i)
                    cliente = cel(5, i)
                    vendedor = cel(6, i)
                    id_item = cel(7, i)
                    cfop = cel(8, i)
                    valor_item = numero(cel(9, i))
                    valor_nf = numero(cel(10, i))

                    # As RAWs auditadas possuem ID_ITEM. Se faltar, usa fallback conservador.
                    chave = f"{id_nf}|{id_item}" if id_item else f"FALLBACK|{id_nf}|{cfop}|{valor_item}|{i+inicio}"
                    if chave in chaves:
                        duplicadas += 1
                        continue
                    chaves.add(chave)

                    nf = nfs.get(id_nf)
                    if nf is None:
                        nf = {
                            "id_nf": id_nf,
                            "num_nf": num_nf,
                            "data_emissao": data_txt,
                            "mes": data.month,
                            "data_cancelamento": cancelamento,
                            "cnpj_cpf": cnpj,
                            "cliente_nome": cliente,
                            "cod_vendedor": vendedor,
                            "valor_nf": valor_nf,
                            "cfops": set(), "cfops_venda": set(), "cfops_bonificacao": set(),
                            "cfops_a_validar": set(), "cfops_pendentes": set(),
                            "qtd_itens": 0, "itens_venda": 0, "itens_bonificados": 0,
                            "itens_a_validar": 0, "itens_pendentes": 0,
                            "valor_comercial": 0.0, "valor_bonificado": 0.0,
                            "valor_a_validar": 0.0, "valor_pendente": 0.0,
                        }
                        nfs[id_nf] = nf
                    else:
                        # Completa metadados caso a primeira linha esteja vazia.
                        if not nf["num_nf"] and num_nf: nf["num_nf"] = num_nf
                        if not nf["data_cancelamento"] and cancelamento: nf["data_cancelamento"] = cancelamento
                        if not nf["cnpj_cpf"] and cnpj: nf["cnpj_cpf"] = cnpj
                        if not nf["cliente_nome"] and cliente: nf["cliente_nome"] = cliente
                        if not nf["cod_vendedor"] and vendedor: nf["cod_vendedor"] = vendedor
                        if not nf["valor_nf"] and valor_nf: nf["valor_nf"] = valor_nf

                    nf["qtd_itens"] += 1
                    if cfop:
                        nf["cfops"].add(cfop)
                    c = classe(cfop)
                    if c == "VENDA":
                        nf["cfops_venda"].add(cfop)
                        nf["itens_venda"] += 1
                        nf["valor_comercial"] += valor_item
                    elif c == "BONIFICACAO":
                        nf["cfops_bonificacao"].add(cfop)
                        nf["itens_bonificados"] += 1
                        nf["valor_bonificado"] += valor_item
                    elif c == "A_VALIDAR":
                        if cfop: nf["cfops_a_validar"].add(cfop)
                        nf["itens_a_validar"] += 1
                        nf["valor_a_validar"] += valor_item
                    else:
                        if cfop: nf["cfops_pendentes"].add(cfop)
                        nf["itens_pendentes"] += 1
                        nf["valor_pendente"] += valor_item

                if n < bloco:
                    break
                inicio += bloco

            fontes[nome] = {
                "linhas_2025_lidas": linhas_2025,
                "duplicidades_ignoradas": duplicadas,
            }

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        meses = {m: {
            "nfs_comerciais": 0, "nfs_comerciais_canceladas": 0,
            "clientes_unicos": set(), "faturamento_comercial": 0.0,
            "valor_bonificado": 0.0, "valor_nf_fiscal": 0.0,
        } for m in range(1, 13)}

        comerciais = []
        total_canceladas = 0
        total_comercial = 0.0
        total_bonificado = 0.0
        clientes_ano = set()

        for nf in nfs.values():
            # NF comercial = possui ao menos um item classificado como VENDA.
            if nf["itens_venda"] <= 0:
                continue
            cancelada = bool(clean(nf["data_cancelamento"]))
            m = nf["mes"]
            if cancelada:
                meses[m]["nfs_comerciais_canceladas"] += 1
                total_canceladas += 1
            else:
                meses[m]["nfs_comerciais"] += 1
                meses[m]["faturamento_comercial"] += nf["valor_comercial"]
                meses[m]["valor_bonificado"] += nf["valor_bonificado"]
                meses[m]["valor_nf_fiscal"] += nf["valor_nf"]
                cliente_key = nf["cnpj_cpf"] or nf["cliente_nome"]
                if cliente_key:
                    meses[m]["clientes_unicos"].add(cliente_key)
                    clientes_ano.add(cliente_key)
                total_comercial += nf["valor_comercial"]
                total_bonificado += nf["valor_bonificado"]

            # Apenas pequena amostra; a rota nao devolve 8 mil linhas.
            if len(comerciais) < 30:
                comerciais.append({
                    "id_nf": nf["id_nf"], "num_nf": nf["num_nf"],
                    "data_emissao": nf["data_emissao"], "cancelada": cancelada,
                    "cliente_nome": nf["cliente_nome"], "cnpj_cpf": nf["cnpj_cpf"],
                    "cod_vendedor": nf["cod_vendedor"],
                    "cfops": sorted(nf["cfops"]),
                    "cfops_venda": sorted(nf["cfops_venda"]),
                    "cfops_bonificacao": sorted(nf["cfops_bonificacao"]),
                    "valor_nf": round(nf["valor_nf"], 2),
                    "valor_comercial": round(nf["valor_comercial"], 2),
                    "valor_bonificado": round(nf["valor_bonificado"], 2),
                    "qtd_itens": nf["qtd_itens"], "itens_venda": nf["itens_venda"],
                    "itens_bonificados": nf["itens_bonificados"],
                })

        resumo_mensal = {}
        for m in range(1, 13):
            x = meses[m]
            resumo_mensal[f"{m:02d}"] = {
                "nfs_comerciais_validas": x["nfs_comerciais"],
                "nfs_comerciais_canceladas": x["nfs_comerciais_canceladas"],
                "clientes_unicos": len(x["clientes_unicos"]),
                "faturamento_comercial": round(x["faturamento_comercial"], 2),
                "valor_bonificado": round(x["valor_bonificado"], 2),
                "valor_nf_fiscal": round(x["valor_nf_fiscal"], 2),
            }

        nfs_com_venda_total = sum(1 for nf in nfs.values() if nf["itens_venda"] > 0)
        return {
            "status": "ok", "ano": 2025, "somente_leitura": True,
            "omie_api_chamada": False, "planilha_principal_alterada": False,
            "planilha_raw_alterada": False, "base_vendas_alterada": False,
            "cursor_2025_alterado": False, "cursor_2026_alterado": False,
            "criterio": {
                "deduplicacao": "ID_NF + ID_ITEM entre RAW antiga e nova",
                "nf_comercial": "NF com pelo menos um item CFOP_VENDA",
                "valor_comercial": "soma de VALOR_TOTAL_ITEM apenas dos itens CFOP_VENDA",
                "valor_bonificado": "soma de VALOR_TOTAL_ITEM dos itens 5.910/6.910",
                "canceladas": "separadas e nao somadas no faturamento_comercial da previa",
                "a_validar": sorted(CFOP_A_VALIDAR),
            },
            "resumo_ano": {
                "itens_unicos_2025": len(chaves),
                "nfs_unicas_2025": len(nfs),
                "nfs_com_cfop_venda": nfs_com_venda_total,
                "nfs_comerciais_validas": nfs_com_venda_total - total_canceladas,
                "nfs_comerciais_canceladas": total_canceladas,
                "clientes_unicos_compradores": len(clientes_ano),
                "faturamento_comercial": round(total_comercial, 2),
                "valor_bonificado": round(total_bonificado, 2),
            },
            "meses": resumo_mensal,
            "amostra_primeiras_30_nfs_comerciais": comerciais,
            "fontes": fontes,
            "base_vendas_alterada": False,
            "proximo_passo": "Conferir totais mensais/anuais antes de qualquer gravacao em BASE_VENDAS.",
        }
    except Exception as e:
        return {
            "status": "error", "ano": 2025, "somente_leitura": True,
            "error": repr(e), "omie_api_chamada": False,
            "planilha_principal_alterada": False, "planilha_raw_alterada": False,
            "base_vendas_alterada": False, "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }


# ============================================================
# AUDITORIA DE FECHAMENTO DE VALORES 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/auditar-fechamento-valores-2025")
def auditar_fechamento_valores_2025():
    """
    Audita NFs comerciais validas de 2025 para entender por que a soma dos itens
    classificados como VENDA/BONIFICACAO pode diferir do VALOR_NF fiscal.
    SOMENTE LEITURA: nao chama Omie, nao grava planilhas e nao altera cursores.
    """
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    TOL = 0.02

    def parse_data(v):
        s = clean(v)
        if not s:
            return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                return _dt.strptime(s[:19], f)
            except Exception:
                pass
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def numero(v):
        s = clean(v)
        if not s:
            return 0.0
        try:
            if "," in s:
                return float(s.replace(".", "").replace(",", "."))
            return float(s)
        except Exception:
            return 0.0

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()
        chaves = set()
        nfs = {}
        fontes = {}

        def ler_fonte(client, aba, nome):
            inicio = 2
            bloco = 10000
            linhas_2025 = 0
            duplicadas = 0
            while True:
                # A ID_NF; C NUM_NF; E DATA_EMISSAO; G DATA_CANCELAMENTO;
                # O ID_ITEM; S CFOP; X VALOR_PRODUTO; Y DESCONTO_ITEM;
                # Z FRETE_ITEM; AA OUTROS_ITEM; AB VALOR_TOTAL_ITEM;
                # AC VALOR_PRODUTOS_NF; AD DESCONTO_NF; AE VALOR_NF.
                letras = ["A","C","E","G","O","S","X","Y","Z","AA","AB","AC","AD","AE"]
                ranges = [f"'{aba}'!{c}{inicio}:{c}{inicio+bloco-1}" for c in letras]
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id,
                    ranges=ranges,
                    majorDimension="ROWS",
                ).execute()
                vr = resp.get("valueRanges") or []
                cols = [(x.get("values") or []) for x in vr]
                n = max([len(x) for x in cols] or [0])
                if n == 0:
                    break

                def cel(c, i):
                    if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]:
                        return ""
                    return clean(cols[c][i][0])

                for i in range(n):
                    id_nf = cel(0, i)
                    data_txt = cel(2, i)
                    data = parse_data(data_txt)
                    if not id_nf or not data or data.year != 2025:
                        continue
                    linhas_2025 += 1

                    num_nf = cel(1, i)
                    cancelamento = cel(3, i)
                    id_item = cel(4, i)
                    cfop = cel(5, i)
                    valor_produto = numero(cel(6, i))
                    desconto_item = numero(cel(7, i))
                    frete_item = numero(cel(8, i))
                    outros_item = numero(cel(9, i))
                    valor_total_item = numero(cel(10, i))
                    valor_produtos_nf = numero(cel(11, i))
                    desconto_nf = numero(cel(12, i))
                    valor_nf = numero(cel(13, i))

                    chave = f"{id_nf}|{id_item}" if id_item else f"FALLBACK|{id_nf}|{cfop}|{valor_total_item}|{i+inicio}"
                    if chave in chaves:
                        duplicadas += 1
                        continue
                    chaves.add(chave)

                    nf = nfs.get(id_nf)
                    if nf is None:
                        nf = {
                            "id_nf": id_nf, "num_nf": num_nf, "data_emissao": data_txt,
                            "mes": data.month, "cancelada": bool(cancelamento),
                            "valor_nf": valor_nf, "valor_produtos_nf": valor_produtos_nf,
                            "desconto_nf": desconto_nf,
                            "qtd_itens": 0, "itens_venda": 0, "itens_bonificados": 0,
                            "soma_valor_produto": 0.0, "soma_desconto_item": 0.0,
                            "soma_frete_item": 0.0, "soma_outros_item": 0.0,
                            "soma_total_item": 0.0, "valor_comercial": 0.0,
                            "valor_bonificado": 0.0, "cfops": set(),
                        }
                        nfs[id_nf] = nf
                    else:
                        if cancelamento: nf["cancelada"] = True
                        if not nf["num_nf"] and num_nf: nf["num_nf"] = num_nf
                        if not nf["valor_nf"] and valor_nf: nf["valor_nf"] = valor_nf
                        if not nf["valor_produtos_nf"] and valor_produtos_nf: nf["valor_produtos_nf"] = valor_produtos_nf
                        if not nf["desconto_nf"] and desconto_nf: nf["desconto_nf"] = desconto_nf

                    nf["qtd_itens"] += 1
                    if cfop: nf["cfops"].add(cfop)
                    nf["soma_valor_produto"] += valor_produto
                    nf["soma_desconto_item"] += desconto_item
                    nf["soma_frete_item"] += frete_item
                    nf["soma_outros_item"] += outros_item
                    nf["soma_total_item"] += valor_total_item
                    if cfop in CFOP_VENDA:
                        nf["itens_venda"] += 1
                        nf["valor_comercial"] += valor_total_item
                    elif cfop in CFOP_BONIFICACAO:
                        nf["itens_bonificados"] += 1
                        nf["valor_bonificado"] += valor_total_item

                if n < bloco:
                    break
                inicio += bloco

            fontes[nome] = {"linhas_2025_lidas": linhas_2025, "duplicidades_ignoradas": duplicadas}

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        contagem = {"igual": 0, "itens_menor_que_nf": 0, "itens_maior_que_nf": 0}
        por_mes = {m: {"nfs": 0, "igual": 0, "menor": 0, "maior": 0, "diferenca_liquida": 0.0, "diferenca_absoluta": 0.0} for m in range(1,13)}
        maiores = []
        total_nfs = 0
        soma_nf = soma_itens = soma_comercial = soma_bonificado = 0.0
        soma_produto = soma_desc_item = soma_frete = soma_outros = soma_desc_nf = 0.0

        for nf in nfs.values():
            if nf["itens_venda"] <= 0 or nf["cancelada"]:
                continue
            total_nfs += 1
            itens_classificados = nf["valor_comercial"] + nf["valor_bonificado"]
            diferenca = itens_classificados - nf["valor_nf"]
            abs_dif = abs(diferenca)
            if abs_dif <= TOL:
                classe = "IGUAL"
                contagem["igual"] += 1
                por_mes[nf["mes"]]["igual"] += 1
            elif diferenca < 0:
                classe = "ITENS_MENOR_QUE_NF"
                contagem["itens_menor_que_nf"] += 1
                por_mes[nf["mes"]]["menor"] += 1
            else:
                classe = "ITENS_MAIOR_QUE_NF"
                contagem["itens_maior_que_nf"] += 1
                por_mes[nf["mes"]]["maior"] += 1

            pm = por_mes[nf["mes"]]
            pm["nfs"] += 1
            pm["diferenca_liquida"] += diferenca
            pm["diferenca_absoluta"] += abs_dif

            soma_nf += nf["valor_nf"]
            soma_itens += itens_classificados
            soma_comercial += nf["valor_comercial"]
            soma_bonificado += nf["valor_bonificado"]
            soma_produto += nf["soma_valor_produto"]
            soma_desc_item += nf["soma_desconto_item"]
            soma_frete += nf["soma_frete_item"]
            soma_outros += nf["soma_outros_item"]
            soma_desc_nf += nf["desconto_nf"]

            if abs_dif > TOL:
                maiores.append({
                    "id_nf": nf["id_nf"], "num_nf": nf["num_nf"],
                    "data_emissao": nf["data_emissao"], "mes": nf["mes"],
                    "classificacao": classe, "cfops": sorted(nf["cfops"]),
                    "valor_nf": round(nf["valor_nf"],2),
                    "valor_comercial": round(nf["valor_comercial"],2),
                    "valor_bonificado": round(nf["valor_bonificado"],2),
                    "comercial_mais_bonificado": round(itens_classificados,2),
                    "diferenca_itens_menos_nf": round(diferenca,2),
                    "valor_produtos_nf": round(nf["valor_produtos_nf"],2),
                    "desconto_nf": round(nf["desconto_nf"],2),
                    "soma_valor_produto_itens": round(nf["soma_valor_produto"],2),
                    "soma_desconto_item": round(nf["soma_desconto_item"],2),
                    "soma_frete_item": round(nf["soma_frete_item"],2),
                    "soma_outros_item": round(nf["soma_outros_item"],2),
                    "soma_valor_total_item": round(nf["soma_total_item"],2),
                    "qtd_itens": nf["qtd_itens"], "itens_venda": nf["itens_venda"],
                    "itens_bonificados": nf["itens_bonificados"],
                })

        maiores.sort(key=lambda x: abs(x["diferenca_itens_menos_nf"]), reverse=True)
        meses_saida = {}
        for m in range(1,13):
            x = por_mes[m]
            meses_saida[f"{m:02d}"] = {
                "nfs_comerciais_validas": x["nfs"], "iguais": x["igual"],
                "itens_menor_que_nf": x["menor"], "itens_maior_que_nf": x["maior"],
                "diferenca_liquida": round(x["diferenca_liquida"],2),
                "diferenca_absoluta": round(x["diferenca_absoluta"],2),
            }

        return {
            "status": "ok", "ano": 2025, "somente_leitura": True,
            "omie_api_chamada": False, "planilha_principal_alterada": False,
            "planilha_raw_alterada": False, "base_vendas_alterada": False,
            "cursor_2025_alterado": False, "cursor_2026_alterado": False,
            "criterio": {
                "nfs_analisadas": "somente NFs 2025 com CFOP_VENDA e nao canceladas",
                "comparacao": "VALOR_COMERCIAL + VALOR_BONIFICADO versus VALOR_NF",
                "tolerancia_igualdade": TOL,
                "observacao": "VALOR_COMERCIAL ainda e a soma de VALOR_TOTAL_ITEM dos CFOPs de venda; esta rota apenas audita, nao redefine faturamento.",
            },
            "resumo": {
                "nfs_comerciais_validas": total_nfs,
                "iguais": contagem["igual"],
                "itens_menor_que_nf": contagem["itens_menor_que_nf"],
                "itens_maior_que_nf": contagem["itens_maior_que_nf"],
                "soma_valor_nf": round(soma_nf,2),
                "soma_valor_comercial": round(soma_comercial,2),
                "soma_valor_bonificado": round(soma_bonificado,2),
                "soma_comercial_mais_bonificado": round(soma_itens,2),
                "diferenca_liquida_itens_menos_nf": round(soma_itens-soma_nf,2),
                "soma_valor_produto_itens": round(soma_produto,2),
                "soma_desconto_item": round(soma_desc_item,2),
                "soma_frete_item": round(soma_frete,2),
                "soma_outros_item": round(soma_outros,2),
                "soma_desconto_nf": round(soma_desc_nf,2),
            },
            "meses": meses_saida,
            "maiores_50_diferencas": maiores[:50],
            "fontes": fontes,
            "proximo_passo": "Usar as diferencas e componentes fiscais para definir a formula correta de VALOR_COMERCIAL antes de gravar BASE_VENDAS.",
        }
    except Exception as e:
        return {
            "status": "error", "ano": 2025, "somente_leitura": True,
            "error": repr(e), "omie_api_chamada": False,
            "planilha_principal_alterada": False, "planilha_raw_alterada": False,
            "base_vendas_alterada": False, "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }


# ============================================================
# VALIDACAO FINAL DA FORMULA LIQUIDA 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/validar-formula-liquida-2025")
def validar_formula_liquida_2025():
    """Valida item a item: VALOR_TOTAL_ITEM - DESCONTO_ITEM + FRETE_ITEM + OUTROS_ITEM."""
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    TOL = 0.02

    def parse_data(v):
        s = clean(v)
        if not s: return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try: return _dt.strptime(s[:19], f)
            except Exception: pass
        try: return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None

    def numero(v):
        s = clean(v)
        if not s: return 0.0
        try:
            return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
        except Exception: return 0.0

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()
        chaves, nfs, fontes = set(), {}, {}

        def ler_fonte(client, aba, nome):
            inicio, bloco, linhas_2025, duplicadas = 2, 10000, 0, 0
            while True:
                # A ID_NF; C NUM_NF; E DATA; G CANCELAMENTO; O ID_ITEM; S CFOP;
                # Y DESCONTO_ITEM; Z FRETE_ITEM; AA OUTROS_ITEM; AB VALOR_TOTAL_ITEM; AE VALOR_NF
                letras = ["A","C","E","G","O","S","Y","Z","AA","AB","AE"]
                ranges = [f"'{aba}'!{c}{inicio}:{c}{inicio+bloco-1}" for c in letras]
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id, ranges=ranges, majorDimension="ROWS"
                ).execute()
                cols = [(x.get("values") or []) for x in (resp.get("valueRanges") or [])]
                n = max([len(x) for x in cols] or [0])
                if n == 0: break

                def cel(c, i):
                    if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]: return ""
                    return clean(cols[c][i][0])

                for i in range(n):
                    id_nf, data_txt = cel(0,i), cel(2,i)
                    data = parse_data(data_txt)
                    if not id_nf or not data or data.year != 2025: continue
                    linhas_2025 += 1
                    num_nf, cancelamento, id_item, cfop = cel(1,i), cel(3,i), cel(4,i), cel(5,i)
                    desconto, frete, outros = numero(cel(6,i)), numero(cel(7,i)), numero(cel(8,i))
                    total_item, valor_nf = numero(cel(9,i)), numero(cel(10,i))
                    chave = f"{id_nf}|{id_item}" if id_item else f"FALLBACK|{id_nf}|{cfop}|{total_item}|{i+inicio}"
                    if chave in chaves:
                        duplicadas += 1; continue
                    chaves.add(chave)
                    nf = nfs.setdefault(id_nf, {
                        "id_nf": id_nf, "num_nf": num_nf, "data_emissao": data_txt, "mes": data.month,
                        "cancelada": bool(cancelamento), "valor_nf": valor_nf, "itens_venda": 0,
                        "liquido_total": 0.0, "valor_comercial_liquido": 0.0, "valor_bonificado_liquido": 0.0,
                        "desconto": 0.0, "frete": 0.0, "outros": 0.0, "cfops": set(),
                    })
                    if cancelamento: nf["cancelada"] = True
                    if not nf["valor_nf"] and valor_nf: nf["valor_nf"] = valor_nf
                    if cfop: nf["cfops"].add(cfop)
                    liquido = total_item - desconto + frete + outros
                    nf["liquido_total"] += liquido
                    nf["desconto"] += desconto; nf["frete"] += frete; nf["outros"] += outros
                    if cfop in CFOP_VENDA:
                        nf["itens_venda"] += 1; nf["valor_comercial_liquido"] += liquido
                    elif cfop in CFOP_BONIFICACAO:
                        nf["valor_bonificado_liquido"] += liquido

                if n < bloco: break
                inicio += bloco
            fontes[nome] = {"linhas_2025_lidas": linhas_2025, "duplicidades_ignoradas": duplicadas}

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        iguais = menores = maiores_n = total_nfs = 0
        soma_nf = soma_liquida = soma_comercial = soma_bonificado = 0.0
        divergencias = []
        meses = {m:{"nfs":0,"iguais":0,"divergentes":0,"diferenca_liquida":0.0} for m in range(1,13)}

        for nf in nfs.values():
            if nf["itens_venda"] <= 0 or nf["cancelada"]: continue
            total_nfs += 1
            dif = nf["liquido_total"] - nf["valor_nf"]
            pm = meses[nf["mes"]]; pm["nfs"] += 1; pm["diferenca_liquida"] += dif
            if abs(dif) <= TOL:
                iguais += 1; pm["iguais"] += 1
            else:
                pm["divergentes"] += 1
                if dif < 0: menores += 1
                else: maiores_n += 1
                divergencias.append({
                    "id_nf": nf["id_nf"], "num_nf": nf["num_nf"], "data_emissao": nf["data_emissao"],
                    "cfops": sorted(nf["cfops"]), "valor_nf": round(nf["valor_nf"],2),
                    "soma_itens_liquidos": round(nf["liquido_total"],2), "diferenca": round(dif,2),
                    "valor_comercial_liquido": round(nf["valor_comercial_liquido"],2),
                    "valor_bonificado_liquido": round(nf["valor_bonificado_liquido"],2),
                    "desconto_itens": round(nf["desconto"],2), "frete_itens": round(nf["frete"],2),
                    "outros_itens": round(nf["outros"],2),
                })
            soma_nf += nf["valor_nf"]; soma_liquida += nf["liquido_total"]
            soma_comercial += nf["valor_comercial_liquido"]; soma_bonificado += nf["valor_bonificado_liquido"]

        divergencias.sort(key=lambda x: abs(x["diferenca"]), reverse=True)
        meses_saida = {f"{m:02d}": {
            "nfs_comerciais_validas": x["nfs"], "iguais": x["iguais"], "divergentes": x["divergentes"],
            "diferenca_liquida": round(x["diferenca_liquida"],2)
        } for m,x in meses.items()}

        return {
            "status":"ok", "ano":2025, "somente_leitura":True, "omie_api_chamada":False,
            "planilha_principal_alterada":False, "planilha_raw_alterada":False,
            "base_vendas_alterada":False, "cursor_2025_alterado":False, "cursor_2026_alterado":False,
            "formula_testada":"VALOR_TOTAL_ITEM - DESCONTO_ITEM + FRETE_ITEM + OUTROS_ITEM",
            "tolerancia_igualdade":TOL,
            "resumo": {
                "nfs_comerciais_validas":total_nfs, "iguais_ao_valor_nf":iguais,
                "divergentes":menores+maiores_n, "liquido_menor_que_nf":menores, "liquido_maior_que_nf":maiores_n,
                "percentual_fechamento":round((iguais/total_nfs*100) if total_nfs else 0,4),
                "soma_valor_nf":round(soma_nf,2), "soma_itens_liquidos":round(soma_liquida,2),
                "diferenca_liquida_total":round(soma_liquida-soma_nf,2),
                "valor_comercial_liquido":round(soma_comercial,2),
                "valor_bonificado_liquido":round(soma_bonificado,2),
            },
            "meses":meses_saida, "maiores_50_divergencias":divergencias[:50], "fontes":fontes,
            "proximo_passo":"Se o fechamento for praticamente total, usar a formula liquida por item na geracao da BASE_VENDAS."
        }
    except Exception as e:
        return {"status":"error","ano":2025,"somente_leitura":True,"error":repr(e),
                "omie_api_chamada":False,"planilha_principal_alterada":False,"planilha_raw_alterada":False,
                "base_vendas_alterada":False,"cursor_2025_alterado":False,"cursor_2026_alterado":False}


# ============================================================
# AUDITORIA DE RATEIO VENDA + BONIFICACAO 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/auditar-rateio-bonificacao-2025")
def auditar_rateio_bonificacao_2025():
    """Compara estrategias para retirar bonificacao do VALOR_NF sem gravar dados."""
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}

    def parse_data(v):
        s = clean(v)
        if not s: return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try: return _dt.strptime(s[:19], f)
            except Exception: pass
        try: return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None

    def numero(v):
        s = clean(v)
        if not s: return 0.0
        try: return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
        except Exception: return 0.0

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()
        chaves, nfs, fontes = set(), {}, {}

        def ler_fonte(client, aba, nome):
            inicio, bloco, linhas_2025, duplicadas = 2, 10000, 0, 0
            while True:
                # A ID_NF; C NUM_NF; E DATA; G CANCELAMENTO; O ID_ITEM; S CFOP;
                # X VALOR_PRODUTO; Y DESCONTO_ITEM; Z FRETE_ITEM; AA OUTROS_ITEM;
                # AB VALOR_TOTAL_ITEM; AE VALOR_NF
                letras = ["A","C","E","G","O","S","X","Y","Z","AA","AB","AE"]
                ranges = [f"'{aba}'!{c}{inicio}:{c}{inicio+bloco-1}" for c in letras]
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id, ranges=ranges, majorDimension="ROWS"
                ).execute()
                cols = [(x.get("values") or []) for x in (resp.get("valueRanges") or [])]
                n = max([len(x) for x in cols] or [0])
                if n == 0: break

                def cel(c, i):
                    if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]: return ""
                    return clean(cols[c][i][0])

                for i in range(n):
                    id_nf, data_txt = cel(0,i), cel(2,i)
                    data = parse_data(data_txt)
                    if not id_nf or not data or data.year != 2025: continue
                    linhas_2025 += 1
                    num_nf, cancelamento, id_item, cfop = cel(1,i), cel(3,i), cel(4,i), cel(5,i)
                    valor_produto = numero(cel(6,i)); desconto = numero(cel(7,i)); frete = numero(cel(8,i))
                    outros = numero(cel(9,i)); total_item = numero(cel(10,i)); valor_nf = numero(cel(11,i))
                    chave = f"{id_nf}|{id_item}" if id_item else f"FALLBACK|{id_nf}|{cfop}|{total_item}|{i+inicio}"
                    if chave in chaves:
                        duplicadas += 1; continue
                    chaves.add(chave)
                    nf = nfs.setdefault(id_nf, {
                        "id_nf":id_nf,"num_nf":num_nf,"data_emissao":data_txt,"mes":data.month,
                        "cancelada":bool(cancelamento),"valor_nf":valor_nf,"cfops":set(),
                        "itens_venda":0,"itens_bonif":0,
                        "venda_total":0.0,"bonif_total":0.0,
                        "venda_liquida":0.0,"bonif_liquida":0.0,
                        "venda_produto":0.0,"bonif_produto":0.0,
                    })
                    if cancelamento: nf["cancelada"] = True
                    if not nf["valor_nf"] and valor_nf: nf["valor_nf"] = valor_nf
                    if cfop: nf["cfops"].add(cfop)
                    liquido = total_item - desconto + frete + outros
                    if cfop in CFOP_VENDA:
                        nf["itens_venda"] += 1; nf["venda_total"] += total_item
                        nf["venda_liquida"] += liquido; nf["venda_produto"] += valor_produto
                    elif cfop in CFOP_BONIFICACAO:
                        nf["itens_bonif"] += 1; nf["bonif_total"] += total_item
                        nf["bonif_liquida"] += liquido; nf["bonif_produto"] += valor_produto

                if n < bloco: break
                inicio += bloco
            fontes[nome] = {"linhas_2025_lidas":linhas_2025,"duplicidades_ignoradas":duplicadas}

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        total = 0; soma_nf = soma_bonif_total = soma_bonif_liq = 0.0
        soma_metodos = {"nf_menos_bonif_total":0.0,"nf_menos_bonif_liquida":0.0,"rateio_total_item":0.0,"rateio_valor_produto":0.0}
        meses = {m:{"nfs":0,"valor_nf":0.0,"bonif_total":0.0,"bonif_liquida":0.0,"nf_menos_bonif_total":0.0,"nf_menos_bonif_liquida":0.0,"rateio_total_item":0.0,"rateio_valor_produto":0.0} for m in range(1,13)}
        exemplos = []

        for nf in nfs.values():
            if nf["cancelada"] or nf["itens_venda"] <= 0 or nf["itens_bonif"] <= 0: continue
            total += 1
            den_total = nf["venda_total"] + nf["bonif_total"]
            den_prod = nf["venda_produto"] + nf["bonif_produto"]
            m1 = nf["valor_nf"] - nf["bonif_total"]
            m2 = nf["valor_nf"] - nf["bonif_liquida"]
            m3 = nf["valor_nf"] * (nf["venda_total"] / den_total) if den_total else nf["valor_nf"]
            m4 = nf["valor_nf"] * (nf["venda_produto"] / den_prod) if den_prod else nf["valor_nf"]
            soma_nf += nf["valor_nf"]; soma_bonif_total += nf["bonif_total"]; soma_bonif_liq += nf["bonif_liquida"]
            vals={"nf_menos_bonif_total":m1,"nf_menos_bonif_liquida":m2,"rateio_total_item":m3,"rateio_valor_produto":m4}
            pm=meses[nf["mes"]]; pm["nfs"]+=1; pm["valor_nf"]+=nf["valor_nf"]; pm["bonif_total"]+=nf["bonif_total"]; pm["bonif_liquida"]+=nf["bonif_liquida"]
            for k,v in vals.items(): soma_metodos[k]+=v; pm[k]+=v
            exemplos.append({
                "id_nf":nf["id_nf"],"num_nf":nf["num_nf"],"data_emissao":nf["data_emissao"],"cfops":sorted(nf["cfops"]),
                "valor_nf":round(nf["valor_nf"],2),"bonificacao_valor_total_item":round(nf["bonif_total"],2),
                "bonificacao_liquida_item":round(nf["bonif_liquida"],2),"venda_liquida_item":round(nf["venda_liquida"],2),
                "metodo_nf_menos_bonif_total":round(m1,2),"metodo_nf_menos_bonif_liquida":round(m2,2),
                "metodo_rateio_total_item":round(m3,2),"metodo_rateio_valor_produto":round(m4,2),
                "peso_bonificacao_total_item_pct":round((nf["bonif_total"]/den_total*100) if den_total else 0,4),
                "peso_bonificacao_valor_produto_pct":round((nf["bonif_produto"]/den_prod*100) if den_prod else 0,4),
            })

        # exemplos mais relevantes: maior peso/valor de bonificacao
        exemplos.sort(key=lambda x: (x["bonificacao_valor_total_item"], x["valor_nf"]), reverse=True)
        meses_saida={f"{m:02d}":{k:(v if k=="nfs" else round(v,2)) for k,v in x.items()} for m,x in meses.items()}

        return {
            "status":"ok","ano":2025,"somente_leitura":True,"omie_api_chamada":False,
            "planilha_principal_alterada":False,"planilha_raw_alterada":False,"base_vendas_alterada":False,
            "cursor_2025_alterado":False,"cursor_2026_alterado":False,
            "criterio":"somente NFs comerciais validas que possuem VENDA + BONIFICACAO (5.910/6.910)",
            "metodos_comparados":{
                "nf_menos_bonif_total":"VALOR_NF - soma VALOR_TOTAL_ITEM da bonificacao",
                "nf_menos_bonif_liquida":"VALOR_NF - soma (VALOR_TOTAL_ITEM - DESCONTO_ITEM + FRETE_ITEM + OUTROS_ITEM) da bonificacao",
                "rateio_total_item":"VALOR_NF x participacao dos itens de VENDA no VALOR_TOTAL_ITEM classificado",
                "rateio_valor_produto":"VALOR_NF x participacao dos itens de VENDA no VALOR_PRODUTO classificado",
            },
            "resumo":{
                "nfs_venda_com_bonificacao":total,"soma_valor_nf":round(soma_nf,2),
                "soma_bonificacao_total_item":round(soma_bonif_total,2),"soma_bonificacao_liquida_item":round(soma_bonif_liq,2),
                **{k:round(v,2) for k,v in soma_metodos.items()},
            },
            "meses":meses_saida,"maiores_50_bonificacoes":exemplos[:50],"fontes":fontes,
            "proximo_passo":"Comparar os quatro criterios e validar qual representa o faturamento comercial desejado antes de gravar BASE_VENDAS."
        }
    except Exception as e:
        return {"status":"error","ano":2025,"somente_leitura":True,"error":repr(e),"omie_api_chamada":False,
                "planilha_principal_alterada":False,"planilha_raw_alterada":False,"base_vendas_alterada":False,
                "cursor_2025_alterado":False,"cursor_2026_alterado":False}

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






@app.post("/omie/nfe/restaurar-cursor-2025-setembro-7")
def restaurar_cursor_2025_setembro_7():
    """
    Recuperação pontual do cursor 2025 para o checkpoint confirmado em log:
    Setembro/2025, página 7. Não chama Omie e não altera OMIE_NF/BASE_VENDAS.
    """
    try:
        sheets = get_sheets_client()
        controle_aba = "OMIE_SYNC_2025_CONTROLE"
        get_or_create_sheet(sheets, controle_aba)
        headers_ctrl = ["ANO", "MES", "PAGINA", "STATUS", "ATUALIZADO_EM", "ULTIMO_ERRO"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctrl_row = [2025, 9, 7, "EM_ANDAMENTO", now, "RECUPERADO_APOS_RESET_DE_CURSOR"]

        sheets.api.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id,
            range=f"'{controle_aba}'!A1:F2",
            valueInputOption="RAW",
            body={"values": [headers_ctrl, ctrl_row]},
        ).execute()

        return {
            "status": "ok",
            "cursor_restaurado": {"ano": 2025, "mes": 9, "pagina": 7},
            "omie_api_chamada": False,
            "omie_nf_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2026_alterado": False,
        }
    except Exception as e:
        return {"status": "error", "error": repr(e)}

@app.get("/omie/nfe/sync-2025-step")
def sync_2025_step():
    """
    Continuação oficial do histórico 2025 na NOVA planilha RAW.
    O cursor permanece na planilha principal (OMIE_SYNC_2025_CONTROLE).
    A OMIE_NF antiga e a BASE_VENDAS não são alteradas.
    """
    import calendar

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()
        controle_aba = "OMIE_SYNC_2025_CONTROLE"
        aba_raw = "OMIE_NF_2025"

        headers_ctrl = ["ANO", "MES", "PAGINA", "STATUS", "ATUALIZADO_EM", "ULTIMO_ERRO"]
        controle = principal.get(f"{controle_aba}!A1:F10")

        if not controle or len(controle) < 2:
            return {
                "status": "error", "error": "CURSOR_2025_AUSENTE",
                "message": "Cursor 2025 ausente/vazio. Nada foi processado.",
                "base_vendas_alterada": False,
            }

        if [clean(x) for x in controle[0]] != headers_ctrl:
            return {
                "status": "error", "error": "CURSOR_2025_CABECALHO_INVALIDO",
                "message": "Cabeçalho do cursor 2025 inválido. Nada foi processado.",
                "base_vendas_alterada": False,
            }

        try:
            ano = int(clean(controle[1][0]))
            mes = int(clean(controle[1][1]))
            pagina = int(clean(controle[1][2]))
        except Exception:
            return {
                "status": "error", "error": "CURSOR_2025_INVALIDO",
                "message": "Cursor 2025 inválido. Nada foi processado.",
                "base_vendas_alterada": False,
            }

        if ano > 2025 or mes > 12:
            return {
                "status": "ok", "finalizado": True,
                "message": "Carga histórica Jan–Dez/2025 concluída.",
                "base_vendas_alterada": False,
                "destino": "NOVA_RAW",
            }

        headers = [
            "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
            "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
            "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
            "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
            "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
            "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
        ]

        cab = raw.get(f"'{aba_raw}'!A1:AF1")
        if not cab or [clean(x) for x in cab[0]] != headers:
            return {
                "status": "error", "error": "CABECALHO_RAW_INVALIDO",
                "message": "Cabeçalho da nova RAW inválido. Cursor não avançou.",
                "base_vendas_alterada": False,
            }

        omie = get_omie_client()
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        resposta = omie.call(
            endpoint=ENDPOINTS["nfe"],
            call="ListarNF",
            param={
                "pagina": pagina,
                "registros_por_pagina": 100,
                "dEmiInicial": f"01/{mes:02d}/{ano}",
                "dEmiFinal": f"{ultimo_dia:02d}/{mes:02d}/{ano}",
            },
        )

        notas = resposta.get("nfCadastro") or []
        total_paginas = int(resposta.get("total_de_paginas") or 1)
        novas_rows = normalize_nfe(notas)

        def row_key(r):
            id_nf = clean(r[0]) if len(r) > 0 else ""
            id_item = clean(r[14]) if len(r) > 14 else ""
            fallback = "|".join([
                clean(r[16]) if len(r) > 16 else "",
                clean(r[18]) if len(r) > 18 else "",
                clean(r[23]) if len(r) > 23 else "",
                clean(r[20]) if len(r) > 20 else "",
            ])
            return f"{id_nf}|{id_item or fallback}"

        # Como a nova RAW começou pequena, lê apenas A e O dela.
        # Mantém somente chaves das NFs da página atual.
        ids_nf_pagina = {
            clean(r[0]) for r in novas_rows
            if r and len(r) > 0 and clean(r[0])
        }

        batch = raw.api.spreadsheets().values().batchGet(
            spreadsheetId=raw.spreadsheet_id,
            ranges=[f"'{aba_raw}'!A2:A", f"'{aba_raw}'!O2:O"],
            majorDimension="COLUMNS",
        ).execute()

        vr = batch.get("valueRanges") or []
        ids_nf_exist = ((vr[0].get("values") or [[]])[0] if len(vr) > 0 else [])
        ids_item_exist = ((vr[1].get("values") or [[]])[0] if len(vr) > 1 else [])

        chaves_antes = set()
        for i, id_nf_raw in enumerate(ids_nf_exist):
            id_nf = clean(id_nf_raw)
            if not id_nf or id_nf not in ids_nf_pagina:
                continue
            id_item = clean(ids_item_exist[i]) if i < len(ids_item_exist) else ""
            if id_item:
                chaves_antes.add(f"{id_nf}|{id_item}")

        novas_para_append = []
        chaves_append = set()
        for r in novas_rows:
            if not r:
                continue
            k = row_key(r)
            id_item = clean(r[14]) if len(r) > 14 else ""
            ja_existe = (k in chaves_antes) if id_item else False
            if not ja_existe and k not in chaves_append:
                novas_para_append.append(r)
                chaves_append.add(k)

        # Só após deduplicação grava na NOVA RAW.
        if novas_para_append:
            raw.api.spreadsheets().values().append(
                spreadsheetId=raw.spreadsheet_id,
                range=f"'{aba_raw}'!A:AF",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": novas_para_append},
            ).execute()

        # Cursor avança somente depois do append (ou confirmação de que a página já existia).
        if pagina >= total_paginas:
            prox_mes, prox_pagina = mes + 1, 1
        else:
            prox_mes, prox_pagina = mes, pagina + 1

        finalizado = prox_mes > 12
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctrl_row = [
            2026 if finalizado else 2025,
            1 if finalizado else prox_mes,
            1 if finalizado else prox_pagina,
            "FINALIZADO" if finalizado else "EM_ANDAMENTO",
            now,
            "",
        ]

        principal.api.spreadsheets().values().update(
            spreadsheetId=principal.spreadsheet_id,
            range=f"'{controle_aba}'!A1:F2",
            valueInputOption="RAW",
            body={"values": [headers_ctrl, ctrl_row]},
        ).execute()

        return {
            "status": "ok",
            "processado": {"ano": ano, "mes": mes, "pagina": pagina},
            "total_paginas_mes": total_paginas,
            "nfs_recebidas": len(notas),
            "itens_pagina": len(novas_rows),
            "itens_realmente_novos": len(novas_para_append),
            "proximo": None if finalizado else {
                "ano": 2025, "mes": prox_mes, "pagina": prox_pagina
            },
            "finalizado": finalizado,
            "destino": "NOVA_RAW",
            "spreadsheet_raw": raw.spreadsheet_id,
            "aba_destino": aba_raw,
            "omie_nf_antiga_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2025_alterado": True,
            "cursor_2026_alterado": False,
            "modo_gravacao": "incremental_append",
            "modo_deduplicacao": "id_nf_id_item_na_nova_raw",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": repr(e),
            "message": "Cursor 2025 não avançou; a mesma página poderá ser repetida.",
            "omie_nf_antiga_alterada": False,
            "base_vendas_alterada": False,
            "cursor_2026_alterado": False,
        }


@app.get("/omie/nfe/sync-historico-step")
def sync_historico_step():
    """
    Processa UMA página por execução e salva o cursor em OMIE_SYNC_CONTROLE.
    Início padrão: Fev/2026 página 2 (página 1 já validada).
    Ao terminar um mês, avança automaticamente para o próximo.
    Para em Ago/2026.
    Não altera BASE_VENDAS.
    """
    import calendar

    try:
        sheets = get_sheets_client()
        controle_aba = "OMIE_SYNC_CONTROLE"
        get_or_create_sheet(sheets, controle_aba)

        controle = sheets.get(f"{controle_aba}!A1:F10")
        headers_ctrl = ["ANO", "MES", "PAGINA", "STATUS", "ATUALIZADO_EM", "ULTIMO_ERRO"]

        # Inicialização segura conforme o ponto já validado nesta conversa.
        ano, mes, pagina = 2026, 2, 2
        if controle and len(controle) >= 2:
            cab = [clean(x) for x in controle[0]]
            if cab == headers_ctrl:
                row = controle[1]
                try:
                    ano = int(clean(row[0]) or 2026)
                    mes = int(clean(row[1]) or 2)
                    pagina = int(clean(row[2]) or 2)
                except Exception:
                    pass

        if ano > 2026 or (ano == 2026 and mes > 8):
            return {
                "status": "ok",
                "finalizado": True,
                "message": "Carga histórica Fev–Ago/2026 concluída.",
                "base_vendas_alterada": False,
            }

        # Reutiliza a mesma lógica validada da rota paginada, mas sem chamada HTTP interna.
        omie = get_omie_client()
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

        atual = sheets.get("OMIE_NF!A1:AF50000")
        existentes = []
        if atual:
            cab = [clean(x) for x in atual[0]]
            if cab != headers:
                return {
                    "status": "error",
                    "error": "Cabeçalho da OMIE_NF diferente do contrato. Nada foi alterado.",
                }
            existentes = atual[1:]

        def row_key(r):
            id_nf = clean(r[0]) if len(r) > 0 else ""
            id_item = clean(r[14]) if len(r) > 14 else ""
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
        itens_novos = len(set(merged) - chaves_antes)

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

        # Avança cursor somente após a gravação bem-sucedida.
        if pagina >= total_paginas:
            prox_mes = mes + 1
            prox_pagina = 1
        else:
            prox_mes = mes
            prox_pagina = pagina + 1

        finalizado = prox_mes > 8
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        ctrl_row = [
            2026,
            9 if finalizado else prox_mes,
            1 if finalizado else prox_pagina,
            "FINALIZADO" if finalizado else "EM_ANDAMENTO",
            now,
            "",
        ]
        sheets.api.spreadsheets().values().clear(
            spreadsheetId=sheets.spreadsheet_id,
            range=f"'{controle_aba}'!A:F",
            body={},
        ).execute()
        sheets.api.spreadsheets().values().update(
            spreadsheetId=sheets.spreadsheet_id,
            range=f"'{controle_aba}'!A1",
            valueInputOption="RAW",
            body={"values": [headers_ctrl, ctrl_row]},
        ).execute()

        return {
            "status": "ok",
            "processado": {"ano": ano, "mes": mes, "pagina": pagina},
            "total_paginas_mes": total_paginas,
            "nfs_recebidas": len(notas),
            "itens_pagina": len(novas_rows),
            "itens_realmente_novos": itens_novos,
            "total_itens_omie_nf": len(consolidadas),
            "proximo": None if finalizado else {
                "ano": 2026, "mes": prox_mes, "pagina": prox_pagina
            },
            "finalizado": finalizado,
            "base_vendas_alterada": False,
            "controle": controle_aba,
        }

    except Exception as e:
        # Não avança cursor em caso de erro; próxima execução repete a mesma página.
        return {
            "status": "error",
            "error": repr(e),
            "message": "Cursor não avançou; a mesma página poderá ser repetida com segurança.",
        }


@app.get("/omie/nfe/sync-historico-batch")
def sync_historico_batch(passos: int = 3, pausa_segundos: int = 8):
    """
    Executa poucos passos sequenciais do cursor histórico.
    Proteções:
    - máximo de 5 páginas por chamada;
    - pausa entre páginas;
    - para imediatamente em qualquer erro;
    - em erro o próprio sync_historico_step não avança o cursor;
    - encerra ao atingir FINALIZADO;
    - não altera BASE_VENDAS.
    """
    import time

    passos = max(1, min(int(passos), 5))
    pausa_segundos = max(5, min(int(pausa_segundos), 60))

    resultados = []

    for i in range(passos):
        resultado = sync_historico_step()
        resultados.append(resultado)

        if not isinstance(resultado, dict):
            return {
                "status": "error",
                "message": "Retorno inesperado do passo histórico.",
                "passos_executados": len(resultados),
                "resultados": resultados,
            }

        if resultado.get("status") != "ok":
            return {
                "status": "pausado_por_erro",
                "message": "Processamento interrompido. O cursor não deve avançar no passo com erro.",
                "passos_executados": len(resultados),
                "ultimo_resultado": resultado,
                "resultados": resultados,
            }

        if resultado.get("finalizado"):
            return {
                "status": "ok",
                "finalizado": True,
                "message": "Carga histórica Fev–Ago/2026 concluída.",
                "passos_executados": len(resultados),
                "resultados": resultados,
                "base_vendas_alterada": False,
            }

        if i < passos - 1:
            time.sleep(pausa_segundos)

    return {
        "status": "ok",
        "finalizado": False,
        "message": "Lote concluído; cursor salvo para a próxima execução.",
        "passos_executados": len(resultados),
        "proximo": resultados[-1].get("proximo") if resultados else None,
        "resultados": resultados,
        "base_vendas_alterada": False,
    }

@app.get("/omie/nfe/diagnostico-local")
def diagnostico_omie_nf_local(ano: int = 2026):
    """
    Diagnóstico SOMENTE LEITURA da OMIE_NF.
    Não chama a API Omie e não grava/limpa nenhuma aba.
    Resume NFs e itens por mês usando DATA_EMISSAO.
    """
    try:
        sheets = get_sheets_client()
        values = sheets.get("OMIE_NF!A1:AF50000")

        if not values or len(values) < 2:
            return {
                "status": "ok",
                "ano": ano,
                "total_itens_omie_nf": 0,
                "meses": [],
                "modo": "somente_leitura",
            }

        rows = rows_to_objects(values)
        meses = {
            m: {"nfs": set(), "itens": 0, "datas": []}
            for m in range(1, 13)
        }

        primeira = None
        ultima = None
        fora_ano = 0
        datas_invalidas = 0

        for r in rows:
            raw_data = clean(r.get("DATA_EMISSAO"))
            dt = parse_br_date(raw_data)

            if not dt:
                datas_invalidas += 1
                continue

            if primeira is None or dt < primeira:
                primeira = dt
            if ultima is None or dt > ultima:
                ultima = dt

            if dt.year != ano:
                fora_ano += 1
                continue

            m = dt.month
            meses[m]["itens"] += 1

            id_nf = (
                clean(r.get("ID_NF"))
                or clean(r.get("CHAVE_NFE"))
                or clean(r.get("NUM_NF"))
            )
            if id_nf:
                meses[m]["nfs"].add(id_nf)

        nomes = [
            "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
        ]

        resumo = []
        for m in range(1, 13):
            resumo.append({
                "mes": m,
                "nome": nomes[m],
                "nfs_unicas": len(meses[m]["nfs"]),
                "itens": meses[m]["itens"],
            })

        return {
            "status": "ok",
            "ano": ano,
            "primeira_emissao_na_aba": primeira.strftime("%d/%m/%Y") if primeira else None,
            "ultima_emissao_na_aba": ultima.strftime("%d/%m/%Y") if ultima else None,
            "total_itens_omie_nf": len(rows),
            "linhas_do_ano": sum(x["itens"] for x in meses.values()),
            "linhas_fora_do_ano": fora_ano,
            "datas_invalidas": datas_invalidas,
            "meses": resumo,
            "modo": "somente_leitura",
            "omie_api_chamada": False,
            "planilha_alterada": False,
        }

    except Exception as e:
        return {"status": "error", "error": repr(e)}

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

# ============================================================
# PREVIA FINAL BASE_VENDAS 2025 - SOMENTE LEITURA
# ============================================================

@app.get("/omie/raw-historico/previa-final-base-vendas-2025")
def previa_final_base_vendas_2025():
    """
    Consolida RAW antiga + RAW nova de 2025 por NF, com deduplicacao ID_NF+ID_ITEM.
    Classifica itens em VENDA/BONIFICACAO/A_VALIDAR/PENDENTE e calcula uma previa
    mensal FINAL da futura BASE_VENDAS. SOMENTE LEITURA: nao chama Omie e nao grava nada.\n    Regra final: VALOR_COMERCIAL = VALOR_NF - VALOR_BONIFICADO (5.910/6.910).
    """
    from collections import defaultdict
    from datetime import datetime as _dt

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    CFOP_A_VALIDAR = {"7.101","7.102"}

    def parse_data(v):
        s = clean(v)
        if not s:
            return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                return _dt.strptime(s[:19], f)
            except Exception:
                pass
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def numero(v):
        s = clean(v)
        if not s:
            return 0.0
        try:
            if "," in s:
                return float(s.replace(".", "").replace(",", "."))
            return float(s)
        except Exception:
            return 0.0

    def classe(cfop):
        if cfop in CFOP_VENDA:
            return "VENDA"
        if cfop in CFOP_BONIFICACAO:
            return "BONIFICACAO"
        if cfop in CFOP_A_VALIDAR:
            return "A_VALIDAR"
        return "PENDENTE"

    try:
        principal = get_sheets_client()
        raw = get_raw_historico_sheets_client()

        # Guarda apenas chaves de deduplicacao e o agregado compacto por NF.
        chaves = set()
        nfs = {}
        fontes = {}

        def ler_fonte(client, aba, nome):
            inicio = 2
            bloco = 10000
            linhas_2025 = 0
            duplicadas = 0

            # A ID_NF, C NUM_NF, E DATA_EMISSAO, G DATA_CANCELAMENTO,
            # K CNPJ_CPF, L CLIENTE_NOME, M COD_VENDEDOR, O ID_ITEM,
            # S CFOP, AB VALOR_TOTAL_ITEM, AE VALOR_NF.
            while True:
                ranges = [
                    f"'{aba}'!A{inicio}:A{inicio+bloco-1}",
                    f"'{aba}'!C{inicio}:C{inicio+bloco-1}",
                    f"'{aba}'!E{inicio}:E{inicio+bloco-1}",
                    f"'{aba}'!G{inicio}:G{inicio+bloco-1}",
                    f"'{aba}'!K{inicio}:K{inicio+bloco-1}",
                    f"'{aba}'!L{inicio}:L{inicio+bloco-1}",
                    f"'{aba}'!M{inicio}:M{inicio+bloco-1}",
                    f"'{aba}'!O{inicio}:O{inicio+bloco-1}",
                    f"'{aba}'!S{inicio}:S{inicio+bloco-1}",
                    f"'{aba}'!AB{inicio}:AB{inicio+bloco-1}",
                    f"'{aba}'!AE{inicio}:AE{inicio+bloco-1}",
                ]
                resp = client.api.spreadsheets().values().batchGet(
                    spreadsheetId=client.spreadsheet_id,
                    ranges=ranges,
                    majorDimension="ROWS",
                ).execute()
                vr = resp.get("valueRanges") or []
                cols = [(x.get("values") or []) for x in vr]
                n = max([len(x) for x in cols] or [0])
                if n == 0:
                    break

                def cel(c, i):
                    if c >= len(cols) or i >= len(cols[c]) or not cols[c][i]:
                        return ""
                    return clean(cols[c][i][0])

                for i in range(n):
                    id_nf = cel(0, i)
                    num_nf = cel(1, i)
                    data_txt = cel(2, i)
                    data = parse_data(data_txt)
                    if not id_nf or not data or data.year != 2025:
                        continue
                    linhas_2025 += 1

                    cancelamento = cel(3, i)
                    cnpj = cel(4, i)
                    cliente = cel(5, i)
                    vendedor = cel(6, i)
                    id_item = cel(7, i)
                    cfop = cel(8, i)
                    valor_item = numero(cel(9, i))
                    valor_nf = numero(cel(10, i))

                    # As RAWs auditadas possuem ID_ITEM. Se faltar, usa fallback conservador.
                    chave = f"{id_nf}|{id_item}" if id_item else f"FALLBACK|{id_nf}|{cfop}|{valor_item}|{i+inicio}"
                    if chave in chaves:
                        duplicadas += 1
                        continue
                    chaves.add(chave)

                    nf = nfs.get(id_nf)
                    if nf is None:
                        nf = {
                            "id_nf": id_nf,
                            "num_nf": num_nf,
                            "data_emissao": data_txt,
                            "mes": data.month,
                            "data_cancelamento": cancelamento,
                            "cnpj_cpf": cnpj,
                            "cliente_nome": cliente,
                            "cod_vendedor": vendedor,
                            "valor_nf": valor_nf,
                            "cfops": set(), "cfops_venda": set(), "cfops_bonificacao": set(),
                            "cfops_a_validar": set(), "cfops_pendentes": set(),
                            "qtd_itens": 0, "itens_venda": 0, "itens_bonificados": 0,
                            "itens_a_validar": 0, "itens_pendentes": 0,
                            "valor_comercial": 0.0, "valor_bonificado": 0.0,
                            "valor_a_validar": 0.0, "valor_pendente": 0.0,
                        }
                        nfs[id_nf] = nf
                    else:
                        # Completa metadados caso a primeira linha esteja vazia.
                        if not nf["num_nf"] and num_nf: nf["num_nf"] = num_nf
                        if not nf["data_cancelamento"] and cancelamento: nf["data_cancelamento"] = cancelamento
                        if not nf["cnpj_cpf"] and cnpj: nf["cnpj_cpf"] = cnpj
                        if not nf["cliente_nome"] and cliente: nf["cliente_nome"] = cliente
                        if not nf["cod_vendedor"] and vendedor: nf["cod_vendedor"] = vendedor
                        if not nf["valor_nf"] and valor_nf: nf["valor_nf"] = valor_nf

                    nf["qtd_itens"] += 1
                    if cfop:
                        nf["cfops"].add(cfop)
                    c = classe(cfop)
                    if c == "VENDA":
                        nf["cfops_venda"].add(cfop)
                        nf["itens_venda"] += 1
                        nf["valor_comercial"] += valor_item
                    elif c == "BONIFICACAO":
                        nf["cfops_bonificacao"].add(cfop)
                        nf["itens_bonificados"] += 1
                        nf["valor_bonificado"] += valor_item
                    elif c == "A_VALIDAR":
                        if cfop: nf["cfops_a_validar"].add(cfop)
                        nf["itens_a_validar"] += 1
                        nf["valor_a_validar"] += valor_item
                    else:
                        if cfop: nf["cfops_pendentes"].add(cfop)
                        nf["itens_pendentes"] += 1
                        nf["valor_pendente"] += valor_item

                if n < bloco:
                    break
                inicio += bloco

            fontes[nome] = {
                "linhas_2025_lidas": linhas_2025,
                "duplicidades_ignoradas": duplicadas,
            }

        ler_fonte(principal, "OMIE_NF", "RAW_ANTIGA")
        ler_fonte(raw, "OMIE_NF_2025", "RAW_NOVA")

        meses = {m: {
            "nfs_comerciais": 0, "nfs_comerciais_canceladas": 0,
            "clientes_unicos": set(), "faturamento_comercial": 0.0,
            "valor_bonificado": 0.0, "valor_nf_fiscal": 0.0,
        } for m in range(1, 13)}

        comerciais = []
        total_canceladas = 0
        total_comercial = 0.0
        total_bonificado = 0.0
        clientes_ano = set()

        for nf in nfs.values():
            # NF comercial = possui ao menos um item classificado como VENDA.
            if nf["itens_venda"] <= 0:
                continue
            cancelada = bool(clean(nf["data_cancelamento"]))
            m = nf["mes"]
            if cancelada:
                meses[m]["nfs_comerciais_canceladas"] += 1
                total_canceladas += 1
            else:
                # REGRA FINAL VALIDADA:
                # VALOR_COMERCIAL = VALOR_NF oficial - bonificacao (5.910/6.910)
                valor_comercial_final = nf["valor_nf"] - nf["valor_bonificado"]
                meses[m]["nfs_comerciais"] += 1
                meses[m]["faturamento_comercial"] += valor_comercial_final
                meses[m]["valor_bonificado"] += nf["valor_bonificado"]
                meses[m]["valor_nf_fiscal"] += nf["valor_nf"]
                cliente_key = nf["cnpj_cpf"] or nf["cliente_nome"]
                if cliente_key:
                    meses[m]["clientes_unicos"].add(cliente_key)
                    clientes_ano.add(cliente_key)
                total_comercial += valor_comercial_final
                total_bonificado += nf["valor_bonificado"]

            # Apenas pequena amostra; a rota nao devolve 8 mil linhas.
            if len(comerciais) < 30:
                comerciais.append({
                    "id_nf": nf["id_nf"], "num_nf": nf["num_nf"],
                    "data_emissao": nf["data_emissao"], "cancelada": cancelada,
                    "cliente_nome": nf["cliente_nome"], "cnpj_cpf": nf["cnpj_cpf"],
                    "cod_vendedor": nf["cod_vendedor"],
                    "cfops": sorted(nf["cfops"]),
                    "cfops_venda": sorted(nf["cfops_venda"]),
                    "cfops_bonificacao": sorted(nf["cfops_bonificacao"]),
                    "valor_nf": round(nf["valor_nf"], 2),
                    "valor_comercial": round((nf["valor_nf"] - nf["valor_bonificado"]) if not cancelada else 0.0, 2),
                    "valor_bonificado": round(nf["valor_bonificado"], 2),
                    "qtd_itens": nf["qtd_itens"], "itens_venda": nf["itens_venda"],
                    "itens_bonificados": nf["itens_bonificados"],
                })

        resumo_mensal = {}
        for m in range(1, 13):
            x = meses[m]
            resumo_mensal[f"{m:02d}"] = {
                "nfs_comerciais_validas": x["nfs_comerciais"],
                "nfs_comerciais_canceladas": x["nfs_comerciais_canceladas"],
                "clientes_unicos": len(x["clientes_unicos"]),
                "faturamento_comercial": round(x["faturamento_comercial"], 2),
                "valor_bonificado": round(x["valor_bonificado"], 2),
                "valor_nf_fiscal": round(x["valor_nf_fiscal"], 2),
            }

        nfs_com_venda_total = sum(1 for nf in nfs.values() if nf["itens_venda"] > 0)
        return {
            "status": "ok", "ano": 2025, "somente_leitura": True,
            "omie_api_chamada": False, "planilha_principal_alterada": False,
            "planilha_raw_alterada": False, "base_vendas_alterada": False,
            "cursor_2025_alterado": False, "cursor_2026_alterado": False,
            "criterio": {
                "deduplicacao": "ID_NF + ID_ITEM entre RAW antiga e nova",
                "nf_comercial": "NF com pelo menos um item CFOP_VENDA",
                "valor_comercial": "VALOR_NF - VALOR_BONIFICADO (5.910/6.910)",
                "valor_bonificado": "soma de VALOR_TOTAL_ITEM dos itens 5.910/6.910",
                "canceladas": "separadas e nao somadas no faturamento_comercial da previa",
                "a_validar": sorted(CFOP_A_VALIDAR),
            },
            "resumo_ano": {
                "itens_unicos_2025": len(chaves),
                "nfs_unicas_2025": len(nfs),
                "nfs_com_cfop_venda": nfs_com_venda_total,
                "nfs_comerciais_validas": nfs_com_venda_total - total_canceladas,
                "nfs_comerciais_canceladas": total_canceladas,
                "clientes_unicos_compradores": len(clientes_ano),
                "nfs_validas_com_bonificacao": sum(1 for nf in nfs.values() if nf["itens_venda"] > 0 and not bool(clean(nf["data_cancelamento"])) and nf["valor_bonificado"] > 0),
                "faturamento_comercial": round(total_comercial, 2),
                "valor_bonificado": round(total_bonificado, 2),
            },
            "meses": resumo_mensal,
            "amostra_primeiras_30_nfs_comerciais": comerciais,
            "fontes": fontes,
            "base_vendas_alterada": False,
            "proximo_passo": "Se esta previa final for aprovada, gerar backup e gravar BASE_VENDAS 2025 com exatamente a mesma regra.",
        }
    except Exception as e:
        return {
            "status": "error", "ano": 2025, "somente_leitura": True,
            "error": repr(e), "omie_api_chamada": False,
            "planilha_principal_alterada": False, "planilha_raw_alterada": False,
            "base_vendas_alterada": False, "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }

# ============================================================
# GRAVACAO CONTROLADA BASE_VENDAS 2025
# ============================================================

@app.post("/omie/raw-historico/gravar-base-vendas-2025")
def gravar_base_vendas_2025(confirmar: str = ""):
    """
    Grava SOMENTE 2025 na BASE_VENDAS usando RAW antiga + RAW nova.
    Preserva integralmente as linhas de outros anos (incluindo 2026).
    Antes de alterar BASE_VENDAS, cria backup completo em BASE_VENDAS_BACKUP_2025.
    Não chama Omie e não altera RAW nem cursores.

    Regra final:
      VALOR_BONIFICADO = soma VALOR_TOTAL_ITEM dos CFOPs 5.910/6.910
      VALOR_COMERCIAL = VALOR_NF - VALOR_BONIFICADO
    """
    from datetime import datetime as _dt

    if confirmar != "SIM":
        return {
            "status": "blocked",
            "message": "Nada foi alterado. Para gravar use ?confirmar=SIM",
            "omie_api_chamada": False,
            "base_vendas_alterada": False,
        }

    HEADER_RAW = [
        "ID_NF","CHAVE_NFE","NUM_NF","SERIE","DATA_EMISSAO","TIPO_NF",
        "DATA_CANCELAMENTO","ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF",
        "CLIENTE_NOME","COD_VENDEDOR","CATEGORIA","ID_ITEM","COD_PRODUTO_OMIE",
        "SKU","PRODUTO","CFOP","NCM","QUANTIDADE","UNIDADE","VALOR_UNITARIO",
        "VALOR_PRODUTO","DESCONTO_ITEM","FRETE_ITEM","OUTROS_ITEM",
        "VALOR_TOTAL_ITEM","VALOR_PRODUTOS_NF","DESCONTO_NF","VALOR_NF","RAW_JSON",
    ]
    HEADER_BASE = [
        "COMPETENCIA","DATA_EMISSAO","ID_NF","CHAVE_NFE","NUM_NF","SERIE",
        "ID_PEDIDO","NUM_PEDIDO","COD_CLIENTE","CNPJ_CPF","CLIENTE_NOME",
        "COD_VENDEDOR","REP_ID","REPRESENTANTE","CATEGORIA","VALOR_NF",
        "VALOR_COMERCIAL","VALOR_EXCLUIDO","VALOR_PENDENTE","TIPO_NF","CFOPS",
        "CFOPS_VENDA","CFOPS_EXCLUIDOS","CFOPS_PENDENTES","QTD_ITENS",
        "ITENS_VENDA","ITENS_EXCLUIDOS","ITENS_PENDENTES","QTD_SKUS",
        "VENDA_VALIDA","MOTIVO",
    ]

    CFOP_VENDA = {
        "5.101","5.102","5.113","5.401","5.403",
        "6.101","6.102","6.107","6.108","6.109","6.110",
        "6.113","6.401","6.403",
    }
    CFOP_BONIFICACAO = {"5.910","6.910"}
    CFOP_A_VALIDAR = {"7.101","7.102"}

    def parse_data(v):
        s = clean(v)
        if not s:
            return None
        for f in ("%d/%m/%Y","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
            try:
                return _dt.strptime(s[:19], f)
            except Exception:
                pass
        try:
            return _dt.fromisoformat(s.replace("Z","+00:00"))
        except Exception:
            return None

    def numero(v):
        s = clean(v)
        if not s:
            return 0.0
        try:
            if "," in s:
                return float(s.replace(".","").replace(",","."))
            return float(s)
        except Exception:
            return 0.0

    def cancelada(v):
        s = clean(v).strip().lower()
        return s not in ("", "none", "null", "0", "false", "não", "nao")

    try:
        principal = get_sheets_client()
        raw_nova = get_raw_historico_sheets_client()

        # Valida BASE_VENDAS antes de qualquer escrita.
        atual = principal.get("BASE_VENDAS!A1:AE50000")
        if not atual or [clean(x) for x in atual[0]] != HEADER_BASE:
            return {
                "status": "error",
                "error": "CABECALHO_BASE_VENDAS_INVALIDO",
                "base_vendas_alterada": False,
            }

        # Guarda todas as linhas que NÃO são de 2025. Assim 2026 fica intocado.
        linhas_outros_anos = []
        linhas_2025_anteriores = 0
        for r in atual[1:]:
            rr = list(r) + [""] * (31 - len(r))
            rr = rr[:31]
            comp = clean(rr[0])
            dt = parse_data(rr[1])
            ano = dt.year if dt else None
            if ano is None and len(comp) >= 4:
                try:
                    ano = int(comp[:4])
                except Exception:
                    ano = None
            if ano == 2025:
                linhas_2025_anteriores += 1
            else:
                linhas_outros_anos.append(rr)

        # Consolidação lógica ID_NF + ID_ITEM entre as duas RAWs.
        itens = {}
        duplicadas = {"RAW_ANTIGA": 0, "RAW_NOVA": 0}

        def carregar(client, aba, origem):
            cab = client.get(f"'{aba}'!A1:AF1")
            if not cab or [clean(x) for x in cab[0]] != HEADER_RAW:
                raise RuntimeError(f"{origem}: CABECALHO_RAW_INVALIDO")

            inicio = 2
            bloco = 10000
            while True:
                dados = client.get(f"'{aba}'!A{inicio}:AF{inicio+bloco-1}")
                if not dados:
                    break
                for pos, r in enumerate(dados):
                    if not r or not any(clean(x) for x in r):
                        continue
                    rr = list(r) + [""] * (32 - len(r))
                    rr = rr[:32]
                    dt = parse_data(rr[4])
                    if not dt or dt.year != 2025:
                        continue

                    id_nf = clean(rr[0])
                    id_item = clean(rr[14])
                    if not id_nf:
                        continue
                    if id_item:
                        chave = f"{id_nf}|{id_item}"
                    else:
                        chave = "FALLBACK|" + "|".join([
                            id_nf, clean(rr[16]), clean(rr[18]),
                            clean(rr[20]), clean(rr[27])
                        ])

                    if chave in itens:
                        duplicadas[origem] += 1
                        continue
                    itens[chave] = rr

                if len(dados) < bloco:
                    break
                inicio += bloco

        carregar(principal, "OMIE_NF", "RAW_ANTIGA")
        carregar(raw_nova, "OMIE_NF_2025", "RAW_NOVA")

        nfs = {}
        for r in itens.values():
            id_nf = clean(r[0])
            if id_nf not in nfs:
                dt = parse_data(r[4])
                nfs[id_nf] = {
                    "DATA": clean(r[4]), "MES": dt.month if dt else 0,
                    "ID_NF": id_nf, "CHAVE": clean(r[1]), "NUM_NF": clean(r[2]),
                    "SERIE": clean(r[3]), "TIPO": clean(r[5]),
                    "CANCEL": clean(r[6]), "ID_PEDIDO": clean(r[7]),
                    "NUM_PEDIDO": clean(r[8]), "COD_CLIENTE": clean(r[9]),
                    "CNPJ": clean(r[10]), "CLIENTE": clean(r[11]),
                    "VENDEDOR": clean(r[12]), "CATEGORIA": clean(r[13]),
                    "VALOR_NF": numero(r[30]),
                    "CFOPS": set(), "VENDA": set(), "BONIF": set(),
                    "PEND": set(), "SKUS": set(),
                    "QTD": 0, "ITENS_VENDA": 0, "ITENS_BONIF": 0,
                    "ITENS_PEND": 0, "VALOR_BONIF": 0.0,
                }
            nf = nfs[id_nf]

            # Completa metadados se a primeira ocorrência vier incompleta.
            campos = [
                ("CHAVE",1),("NUM_NF",2),("SERIE",3),("TIPO",5),("CANCEL",6),
                ("ID_PEDIDO",7),("NUM_PEDIDO",8),("COD_CLIENTE",9),("CNPJ",10),
                ("CLIENTE",11),("VENDEDOR",12),("CATEGORIA",13)
            ]
            for nome, idx in campos:
                if not nf[nome] and clean(r[idx]):
                    nf[nome] = clean(r[idx])
            if not nf["VALOR_NF"] and numero(r[30]):
                nf["VALOR_NF"] = numero(r[30])

            cfop = clean(r[18])
            sku = clean(r[16])
            nf["QTD"] += 1
            if cfop: nf["CFOPS"].add(cfop)
            if sku: nf["SKUS"].add(sku)

            if cfop in CFOP_VENDA:
                nf["VENDA"].add(cfop)
                nf["ITENS_VENDA"] += 1
            elif cfop in CFOP_BONIFICACAO:
                nf["BONIF"].add(cfop)
                nf["ITENS_BONIF"] += 1
                nf["VALOR_BONIF"] += numero(r[27])
            elif cfop:
                # 7.101/7.102 e qualquer outro não aprovado ficam registrados
                # como pendentes; porém a auditoria já confirmou que não coexistem
                # com as NFs comerciais válidas de 2025.
                nf["PEND"].add(cfop)
                nf["ITENS_PEND"] += 1

        rows_2025 = []
        canceladas = 0
        for nf in nfs.values():
            if not nf["VENDA"]:
                continue
            if cancelada(nf["CANCEL"]):
                canceladas += 1
                continue

            valor_nf = round(nf["VALOR_NF"], 2)
            valor_bonif = round(nf["VALOR_BONIF"], 2)
            valor_comercial = round(valor_nf - valor_bonif, 2)
            competencia = f"2025-{nf['MES']:02d}"

            # Mantém o contrato A:AE atual:
            # VALOR_EXCLUIDO / CFOPS_EXCLUIDOS / ITENS_EXCLUIDOS
            # passam a representar BONIFICAÇÃO para compatibilidade.
            rows_2025.append([
                competencia, nf["DATA"], nf["ID_NF"], nf["CHAVE"], nf["NUM_NF"],
                nf["SERIE"], nf["ID_PEDIDO"], nf["NUM_PEDIDO"], nf["COD_CLIENTE"],
                nf["CNPJ"], nf["CLIENTE"], nf["VENDEDOR"], nf["VENDEDOR"], "",
                nf["CATEGORIA"], valor_nf, valor_comercial, valor_bonif, 0.0,
                nf["TIPO"], ";".join(sorted(nf["CFOPS"])),
                ";".join(sorted(nf["VENDA"])), ";".join(sorted(nf["BONIF"])),
                ";".join(sorted(nf["PEND"])), nf["QTD"], nf["ITENS_VENDA"],
                nf["ITENS_BONIF"], nf["ITENS_PEND"], len(nf["SKUS"]),
                "SIM", "VENDA_COM_BONIFICACAO" if valor_bonif else "VENDA",
            ])

        rows_2025.sort(key=lambda r: (r[0], r[1], r[4]))

        # Travas antes da escrita.
        faturamento = round(sum(float(r[16] or 0) for r in rows_2025), 2)
        bonificado = round(sum(float(r[17] or 0) for r in rows_2025), 2)

        if len(rows_2025) != 8285:
            return {
                "status": "error", "error": "TRAVA_QTD_NFS_2025",
                "esperado": 8285, "obtido": len(rows_2025),
                "base_vendas_alterada": False,
            }
        if abs(faturamento - 49550637.37) > 0.05:
            return {
                "status": "error", "error": "TRAVA_FATURAMENTO_2025",
                "esperado": 49550637.37, "obtido": faturamento,
                "base_vendas_alterada": False,
            }
        if abs(bonificado - 381442.32) > 0.05:
            return {
                "status": "error", "error": "TRAVA_BONIFICACAO_2025",
                "esperado": 381442.32, "obtido": bonificado,
                "base_vendas_alterada": False,
            }

        # BACKUP COMPLETO antes de tocar na BASE_VENDAS.
        backup_aba = "BASE_VENDAS_BACKUP_2025"
        get_or_create_sheet(principal, backup_aba)
        principal.api.spreadsheets().values().clear(
            spreadsheetId=principal.spreadsheet_id,
            range=f"'{backup_aba}'!A:AE", body={}
        ).execute()
        principal.api.spreadsheets().values().update(
            spreadsheetId=principal.spreadsheet_id,
            range=f"'{backup_aba}'!A1",
            valueInputOption="RAW",
            body={"values": atual},
        ).execute()

        # Valida backup antes da substituição.
        backup_check = principal.get(f"'{backup_aba}'!A1:AE50000")
        if len(backup_check) != len(atual):
            return {
                "status": "error",
                "error": "BACKUP_NAO_VALIDADO_BASE_VENDAS_NAO_ALTERADA",
                "linhas_origem": len(atual),
                "linhas_backup": len(backup_check),
                "base_vendas_alterada": False,
            }

        # Reconstrói BASE: header + 2025 novo + todos os outros anos preservados.
        final_rows = [HEADER_BASE] + rows_2025 + linhas_outros_anos

        principal.api.spreadsheets().values().clear(
            spreadsheetId=principal.spreadsheet_id,
            range="'BASE_VENDAS'!A2:AE", body={}
        ).execute()
        principal.api.spreadsheets().values().update(
            spreadsheetId=principal.spreadsheet_id,
            range="'BASE_VENDAS'!A1",
            valueInputOption="RAW",
            body={"values": final_rows},
        ).execute()

        # Conferência pós-gravação.
        gravado = principal.get("BASE_VENDAS!A1:AE50000")
        objetos = rows_to_objects(gravado)
        linhas_2025_pos = []
        linhas_outros_pos = []
        for obj in objetos:
            dt = parse_data(obj.get("DATA_EMISSAO"))
            comp = clean(obj.get("COMPETENCIA"))
            ano = dt.year if dt else None
            if ano is None and len(comp) >= 4:
                try: ano = int(comp[:4])
                except Exception: ano = None
            if ano == 2025:
                linhas_2025_pos.append(obj)
            else:
                linhas_outros_pos.append(obj)

        fat_pos = round(sum(numero(x.get("VALOR_COMERCIAL")) for x in linhas_2025_pos
                            if clean(x.get("VENDA_VALIDA")).upper() == "SIM"), 2)

        return {
            "status": "ok",
            "message": "BASE_VENDAS 2025 gravada com backup e preservacao dos demais anos.",
            "regra": "VALOR_COMERCIAL = VALOR_NF - bonificacao 5.910/6.910",
            "nfs_2025_gravadas": len(linhas_2025_pos),
            "nfs_2025_canceladas_nao_gravadas": canceladas,
            "faturamento_2025": fat_pos,
            "valor_bonificado_2025": bonificado,
            "linhas_2025_anteriores_substituidas": linhas_2025_anteriores,
            "linhas_outros_anos_preservadas_antes": len(linhas_outros_anos),
            "linhas_outros_anos_preservadas_depois": len(linhas_outros_pos),
            "backup_aba": backup_aba,
            "duplicidades_ignoradas": duplicadas,
            "omie_api_chamada": False,
            "raw_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
            "proximo_passo": "Validar /dashboard/executive-kpis?ano=2025&mes_inicio=1&mes_fim=12&representante=ALL",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": repr(e),
            "omie_api_chamada": False,
            "raw_alterada": False,
            "cursor_2025_alterado": False,
            "cursor_2026_alterado": False,
        }
