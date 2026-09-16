# ============================================================
# OMIE_NF -> BASE_VENDAS
# ============================================================

@app.get("/omie/nfe/build-base-test")
def build_base_test():
    """
    Lê OMIE_NF, classifica cada ITEM pelo CFOP e depois
    consolida UMA LINHA POR NF.

    Regras temporárias de validação:

    VENDA:
    5101, 5102, 6101, 6102, 6401

    EXCLUIR:
    5910, 6910

    Demais CFOPs:
    PENDENTE

    IMPORTANTE:
    Uma NF pode conter venda + bonificação.
    Nesse caso somente os itens de venda entram no
    VALOR_COMERCIAL.
    """

    try:
        sheets = get_sheets_client()

        values = sheets.get("OMIE_NF!A1:AF50000")
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
        # REGRAS TEMPORÁRIAS DE CFOP
        # ----------------------------------------------------

        CFOPS_VENDA = {
            "5101",
            "5102",
            "6101",
            "6102",
            "6401",
        }

        CFOPS_EXCLUIR = {
            "5910",
            "6910",
        }

        # ----------------------------------------------------
        # Conversão segura para número
        # ----------------------------------------------------

        def to_float(value):
            if value in (None, ""):
                return 0.0

            if isinstance(value, (int, float)):
                return float(value)

            text = str(value).strip()

            try:
                return float(text)
            except ValueError:
                pass

            # fallback para números no formato brasileiro
            try:
                return float(
                    text.replace(".", "").replace(",", ".")
                )
            except ValueError:
                return 0.0

        # ----------------------------------------------------
        # Agrupamento por NF
        # ----------------------------------------------------

        nfs = {}

        resumo_itens = {
            "VENDA": 0,
            "EXCLUIDO": 0,
            "PENDENTE": 0,
        }

        cfops_pendentes = set()

        for item in itens:

            id_nf = clean(item.get("ID_NF"))

            if not id_nf:
                continue

            cfop_original = clean(item.get("CFOP"))
            cfop = normalize_cfop(cfop_original)

            # ------------------------------------------------
            # Classificação DO ITEM
            # ------------------------------------------------

            if cfop in CFOPS_VENDA:
                classificacao = "VENDA"

            elif cfop in CFOPS_EXCLUIR:
                classificacao = "EXCLUIDO"

            else:
                classificacao = "PENDENTE"

                if cfop_original:
                    cfops_pendentes.add(cfop_original)

            resumo_itens[classificacao] += 1

            # ------------------------------------------------
            # Valor do item
            #
            # Nesta fase usamos VALOR_PRODUTO - DESCONTO_ITEM.
            #
            # Não usamos VALOR_NF porque ele se repete em cada
            # item da mesma nota.
            # ------------------------------------------------

            valor_produto = to_float(
                item.get("VALOR_PRODUTO")
            )

            desconto_item = to_float(
                item.get("DESCONTO_ITEM")
            )

            valor_liquido_item = (
                valor_produto - desconto_item
            )

            # ------------------------------------------------
            # Criação da NF
            # ------------------------------------------------

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
                    "VALOR_NF": to_float(
                        item.get("VALOR_NF")
                    ),
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

            # ------------------------------------------------
            # Acumulação
            # ------------------------------------------------

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
                    nf["CFOPS_VENDA"].add(
                        cfop_original
                    )

            elif classificacao == "EXCLUIDO":
                nf["ITENS_EXCLUIDOS"] += 1
                nf["VALOR_EXCLUIDO"] += valor_liquido_item

                if cfop_original:
                    nf["CFOPS_EXCLUIDOS"].add(
                        cfop_original
                    )

            else:
                nf["ITENS_PENDENTES"] += 1
                nf["VALOR_PENDENTE"] += valor_liquido_item

                if cfop_original:
                    nf["CFOPS_PENDENTES"].add(
                        cfop_original
                    )

        # ----------------------------------------------------
        # Consolidação por NF
        # ----------------------------------------------------

        rows = []

        resumo_nfs = {
            "SIM": 0,
            "NAO": 0,
            "PENDENTE": 0,
        }

        for nf in nfs.values():

            data = parse_br_date(
                nf["DATA_EMISSAO"]
            )

            competencia = (
                f"{data.year:04d}-{data.month:02d}"
                if data
                else ""
            )

            # ------------------------------------------------
            # Classificação da NF
            #
            # A classificação comercial depende dos ITENS.
            # Não usamos TIPO_NF como filtro principal.
            # ------------------------------------------------

            if nf["DATA_CANCELAMENTO"]:
                venda_valida = "NAO"
                motivo = "NF_CANCELADA"

                # NF cancelada não entra no faturamento
                valor_comercial = 0.0

            elif (
                nf["ITENS_VENDA"] > 0
                and nf["ITENS_PENDENTES"] == 0
            ):
                venda_valida = "SIM"

                if nf["ITENS_EXCLUIDOS"] > 0:
                    motivo = (
                        "VENDA_COM_ITENS_EXCLUIDOS"
                    )
                else:
                    motivo = "VENDA"

                valor_comercial = nf[
                    "VALOR_COMERCIAL"
                ]

            elif nf["ITENS_VENDA"] > 0:
                venda_valida = "PENDENTE"
                motivo = (
                    "VENDA_COM_CFOP_PENDENTE"
                )

                # Mantemos o valor conhecido de venda,
                # mas a NF ainda não está aprovada para KPI.
                valor_comercial = nf[
                    "VALOR_COMERCIAL"
                ]

            elif nf["ITENS_PENDENTES"] > 0:
                venda_valida = "PENDENTE"
                motivo = (
                    "SOMENTE_CFOP_PENDENTE"
                )
                valor_comercial = 0.0

            else:
                venda_valida = "NAO"
                motivo = (
                    "SOMENTE_ITENS_EXCLUIDOS"
                )
                valor_comercial = 0.0

            resumo_nfs[venda_valida] += 1

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

                    round(
                        nf["VALOR_NF"],
                        2,
                    ),

                    round(
                        valor_comercial,
                        2,
                    ),

                    round(
                        nf["VALOR_EXCLUIDO"],
                        2,
                    ),

                    round(
                        nf["VALOR_PENDENTE"],
                        2,
                    ),

                    nf["TIPO_NF"],

                    ";".join(
                        sorted(nf["CFOPS"])
                    ),

                    ";".join(
                        sorted(nf["CFOPS_VENDA"])
                    ),

                    ";".join(
                        sorted(
                            nf["CFOPS_EXCLUIDOS"]
                        )
                    ),

                    ";".join(
                        sorted(
                            nf["CFOPS_PENDENTES"]
                        )
                    ),

                    nf["QTD_ITENS"],
                    nf["ITENS_VENDA"],
                    nf["ITENS_EXCLUIDOS"],
                    nf["ITENS_PENDENTES"],
                    len(nf["SKUS"]),

                    venda_valida,
                    motivo,
                ]
            )

        # ----------------------------------------------------
        # Ordenação
        # ----------------------------------------------------

        rows.sort(
            key=lambda r: (
                r[0],
                r[1],
                r[4],
            )
        )

        # ----------------------------------------------------
        # Cabeçalhos
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Gravação BASE_VENDAS
        # ----------------------------------------------------

        get_or_create_sheet(
            sheets,
            "BASE_VENDAS",
        )

        (
            sheets.api
            .spreadsheets()
            .values()
            .clear(
                spreadsheetId=sheets.spreadsheet_id,
                range="'BASE_VENDAS'!A:AE",
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
                range="'BASE_VENDAS'!A1",
                valueInputOption="RAW",
                body={
                    "values": [headers] + rows
                },
            )
            .execute()
        )

        # ----------------------------------------------------
        # Totais de validação
        # ----------------------------------------------------

        faturamento_aprovado = round(
            sum(
                row[16]
                for row in rows
                if row[29] == "SIM"
            ),
            2,
        )

        faturamento_pendente = round(
            sum(
                row[16]
                for row in rows
                if row[29] == "PENDENTE"
            ),
            2,
        )

        return {
            "status": "ok",
            "message": (
                "BASE_VENDAS reconstruída com "
                "classificação por item/CFOP."
            ),

            "itens_origem": len(itens),
            "nfs_consolidadas": len(rows),

            "itens": resumo_itens,
            "nfs": resumo_nfs,

            "faturamento_aprovado": (
                faturamento_aprovado
            ),

            "faturamento_conhecido_em_nfs_pendentes": (
                faturamento_pendente
            ),

            "cfops_pendentes": sorted(
                cfops_pendentes
            ),

            "aba_destino": "BASE_VENDAS",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }