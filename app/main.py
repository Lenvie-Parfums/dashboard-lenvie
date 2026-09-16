import json
import os
from datetime import datetime

from fastapi import FastAPI

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

@app.get("/omie/nfe/build-base-test")
def build_base_test():
    """
    Lê OMIE_NF e consolida UMA LINHA POR NF.

    IMPORTANTE:
    Nesta fase não classificamos automaticamente
    CFOP como venda/não venda.

    Apenas algumas situações objetivas são marcadas:
    - TIPO_NF diferente de 1
    - NF com data de cancelamento
    - CFOP 5.910 / 6.910

    Os demais registros ficam como PENDENTE_VALIDACAO.
    """

    try:
        sheets = get_sheets_client()

        values = sheets.get(
            "OMIE_NF!A1:AF50000"
        )

        itens = rows_to_objects(values)

        if not itens:
            return {
                "status": "error",
                "error": (
                    "A aba OMIE_NF está vazia. "
                    "Execute primeiro a carga controlada."
                ),
            }

        # ----------------------------------------------------
        # Agrupamento por NF
        # ----------------------------------------------------

        nfs = {}

        for item in itens:
            id_nf = clean(item.get("ID_NF"))

            if not id_nf:
                continue

            if id_nf not in nfs:
                nfs[id_nf] = {
                    "ID_NF": id_nf,
                    "CHAVE_NFE": clean(
                        item.get("CHAVE_NFE")
                    ),
                    "NUM_NF": clean(
                        item.get("NUM_NF")
                    ),
                    "SERIE": clean(
                        item.get("SERIE")
                    ),
                    "DATA_EMISSAO": clean(
                        item.get("DATA_EMISSAO")
                    ),
                    "TIPO_NF": clean(
                        item.get("TIPO_NF")
                    ),
                    "DATA_CANCELAMENTO": clean(
                        item.get("DATA_CANCELAMENTO")
                    ),
                    "ID_PEDIDO": clean(
                        item.get("ID_PEDIDO")
                    ),
                    "NUM_PEDIDO": clean(
                        item.get("NUM_PEDIDO")
                    ),
                    "COD_CLIENTE": clean(
                        item.get("COD_CLIENTE")
                    ),
                    "CNPJ_CPF": clean(
                        item.get("CNPJ_CPF")
                    ),
                    "CLIENTE_NOME": clean(
                        item.get("CLIENTE_NOME")
                    ),
                    "COD_VENDEDOR": clean(
                        item.get("COD_VENDEDOR")
                    ),
                    "CATEGORIA": clean(
                        item.get("CATEGORIA")
                    ),
                    "VALOR_NF": item.get(
                        "VALOR_NF", 0
                    ),
                    "CFOPS": set(),
                    "SKUS": set(),
                    "QTD_ITENS": 0,
                }

            nf = nfs[id_nf]

            cfop = clean(item.get("CFOP"))
            sku = clean(item.get("SKU"))

            if cfop:
                nf["CFOPS"].add(cfop)

            if sku:
                nf["SKUS"].add(sku)

            nf["QTD_ITENS"] += 1

        # ----------------------------------------------------
        # Montagem da BASE_VENDAS
        # ----------------------------------------------------

        rows = []

        resumo_status = {}

        for nf in nfs.values():
            data = parse_br_date(
                nf["DATA_EMISSAO"]
            )

            competencia = (
                f"{data.year:04d}-{data.month:02d}"
                if data
                else ""
            )

            cfops = sorted(nf["CFOPS"])

            cfops_norm = {
                normalize_cfop(x)
                for x in cfops
            }

            tipo_nf = clean(nf["TIPO_NF"])

            venda_valida = "PENDENTE"
            motivo = "PENDENTE_VALIDACAO_CFOP"

            # Entrada
            if tipo_nf and tipo_nf != "1":
                venda_valida = "NAO"
                motivo = "TIPO_NF_NAO_SAIDA"

            # Cancelamento
            elif nf["DATA_CANCELAMENTO"]:
                venda_valida = "NAO"
                motivo = "NF_CANCELADA"

            # Bonificação/remessa 5910/6910
            elif (
                "5910" in cfops_norm
                or "6910" in cfops_norm
            ):
                venda_valida = "NAO"
                motivo = "CFOP_5910_6910"

            resumo_status[venda_valida] = (
                resumo_status.get(
                    venda_valida,
                    0,
                )
                + 1
            )

            rows.append(
                [
                    competencia,
                    nf["DATA_EMISSAO"],
                    nf["ID_NF"],
                    nf["CHAVE_NFE"],
                    nf["NUM_NF"],
                    nf["SERIE"],
                    nf["ID_PEDIDO"],
                    nf["NUM_PEDIDO"],
                    nf["COD_CLIENTE"],
                    nf["CNPJ_CPF"],
                    nf["CLIENTE_NOME"],
                    nf["COD_VENDEDOR"],
                    "",  # REP_ID
                    "",  # REPRESENTANTE
                    nf["CATEGORIA"],
                    nf["VALOR_NF"],
                    nf["TIPO_NF"],
                    ";".join(cfops),
                    nf["QTD_ITENS"],
                    len(nf["SKUS"]),
                    venda_valida,
                    motivo,
                ]
            )

        rows.sort(
            key=lambda r: (
                r[0],
                r[1],
                r[4],
            )
        )

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
            "TIPO_NF",
            "CFOPS",
            "QTD_ITENS",
            "QTD_SKUS",
            "VENDA_VALIDA",
            "MOTIVO_EXCLUSAO",
        ]

        # ----------------------------------------------------
        # Cria BASE_VENDAS se necessário
        # ----------------------------------------------------

        get_or_create_sheet(
            sheets,
            "BASE_VENDAS",
        )

        # Limpa SOMENTE BASE_VENDAS
        (
            sheets.api
            .spreadsheets()
            .values()
            .clear(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS'!A:V",
                body={},
            )
            .execute()
        )

        # Grava base consolidada
        (
            sheets.api
            .spreadsheets()
            .values()
            .update(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS'!A1",
                valueInputOption="RAW",
                body={
                    "values": [headers] + rows
                },
            )
            .execute()
        )

        return {
            "status": "ok",
            "message": (
                "BASE_VENDAS de validação criada "
                "com uma linha por NF."
            ),
            "itens_origem": len(itens),
            "nfs_consolidadas": len(rows),
            "status": {
                "SIM": resumo_status.get("SIM", 0),
                "NAO": resumo_status.get("NAO", 0),
                "PENDENTE": resumo_status.get(
                    "PENDENTE",
                    0,
                ),
            },
            "observacao": (
                "Nenhuma NF pendente foi considerada "
                "venda automaticamente."
            ),
            "aba_destino": "BASE_VENDAS",
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
    return {
        "status": "blocked",
        "message": (
            "Sincronização oficial permanece bloqueada "
            "durante a validação da arquitetura NF-e."
        ),
    }