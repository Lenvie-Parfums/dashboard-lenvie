ENDPOINTS = {
    "pedidos": "https://app.omie.com.br/api/v1/produtos/pedido/",
    "clientes": "https://app.omie.com.br/api/v1/geral/clientes/",
    "vendedores": "https://app.omie.com.br/api/v1/geral/vendedores/",
    "produtos": "https://app.omie.com.br/api/v1/geral/produtos/",
    "nfe": "https://app.omie.com.br/api/v1/produtos/nfconsultar/",
}


def pick(obj, *keys):
    for key in keys:
        if isinstance(obj, dict) and obj.get(key) is not None:
            return obj[key]
    return ""


def normalize_clientes(items):
    return [
        [
            pick(x, "codigo_cliente_omie", "codigo_cliente"),
            pick(x, "codigo_cliente_integracao"),
            pick(x, "cnpj_cpf"),
            pick(x, "razao_social"),
            pick(x, "nome_fantasia"),
            pick(x, "cidade"),
            pick(x, "estado", "uf"),
            pick(x, "inativo"),
            str(x.get("tags", [])),
            pick(x, "data_alteracao"),
            str(x),
        ]
        for x in items
    ]


def normalize_vendedores(items):
    return [
        [
            pick(x, "codigo", "codigo_vendedor"),
            pick(x, "nome", "nome_vendedor"),
            pick(x, "email"),
            pick(x, "inativo"),
            str(x),
        ]
        for x in items
    ]


def normalize_produtos(items):
    return [
        [
            pick(x, "codigo_produto"),
            pick(x, "codigo"),
            pick(x, "descricao"),
            pick(x, "descricao_familia", "familia"),
            pick(x, "unidade"),
            pick(x, "inativo"),
            str(x),
        ]
        for x in items
    ]


def normalize_pedidos(items):
    rows = []

    for p in items:
        cab = p.get("cabecalho") or p
        info = p.get("infoCadastro") or p.get("info_cadastro") or {}
        total = p.get("total_pedido") or p.get("totalPedido") or {}

        rows.append(
            [
                pick(cab, "codigo_pedido", "codigo_pedido_omie"),
                pick(cab, "numero_pedido"),
                pick(cab, "data_previsao", "data_pedido"),
                pick(cab, "codigo_cliente"),
                pick(cab, "codigo_vendedor"),
                "",
                pick(
                    total,
                    "valor_total_pedido",
                    "valor_total",
                    "total_valor",
                ),
                pick(cab, "etapa"),
                pick(cab, "status_pedido", "status"),
                pick(cab, "codigo_categoria", "categoria"),
                pick(cab, "codigo_projeto"),
                pick(info, "dInc", "data_inclusao"),
                pick(info, "dAlt", "data_alteracao"),
                str(p),
            ]
        )

    return rows


# ============================================================
# NF-e
# ============================================================

def normalize_nfe(items):
    """
    Transforma o retorno do ListarNF em uma linha por ITEM da NF.

    Nesta etapa não aplicamos regras comerciais.
    Todos os CFOPs são preservados para análise posterior.
    """

    rows = []

    for nf in items:

        compl = nf.get("compl") or {}
        ide = nf.get("ide") or {}
        dest = nf.get("nfDestInt") or {}
        total = nf.get("total") or {}
        icms_total = total.get("ICMSTot") or {}
        pedido = nf.get("pedido") or {}
        titulos = nf.get("titulos") or []

        # ----------------------------------------------------
        # Vendedor
        # ----------------------------------------------------
        # Algumas NFs não trazem dados em "pedido".
        # O JSON real da Lenvie mostrou nCodVendedor em titulos.
        # ----------------------------------------------------

        vendedor = pick(
            pedido,
            "nIdVendedor",
            "codigo_vendedor",
            "nCodVendedor",
        )

        if not vendedor:
            for titulo in titulos:
                vendedor = pick(
                    titulo,
                    "nCodVendedor",
                    "codigo_vendedor",
                )

                if vendedor:
                    break

        # ----------------------------------------------------
        # Pedido
        # ----------------------------------------------------

        id_pedido = pick(
            compl,
            "nIdPedido",
        )

        numero_pedido = pick(
            pedido,
            "cNumPedido",
            "numero_pedido",
        )

        # ----------------------------------------------------
        # Categoria
        # ----------------------------------------------------

        categoria = pick(
            compl,
            "cCodCateg",
        )

        if not categoria and titulos:
            categoria = pick(
                titulos[0],
                "cCodCateg",
            )

        # ----------------------------------------------------
        # Dados gerais da NF
        # ----------------------------------------------------

        id_nf = pick(
            compl,
            "nIdNF",
        )

        chave_nfe = pick(
            compl,
            "cChaveNFe",
        )

        numero_nf = pick(
            ide,
            "nNF",
        )

        serie = pick(
            ide,
            "serie",
        )

        data_emissao = pick(
            ide,
            "dEmi",
        )

        tipo_nf = pick(
            ide,
            "tpNF",
        )

        cancelada_em = pick(
            ide,
            "dCan",
        )

        cliente_id = pick(
            dest,
            "nCodCli",
        )

        cliente_nome = pick(
            dest,
            "cRazao",
        )

        cliente_documento = pick(
            dest,
            "cnpj_cpf",
        )

        valor_nf = pick(
            icms_total,
            "vNF",
        )

        valor_produtos_nf = pick(
            icms_total,
            "vProd",
        )

        desconto_nf = pick(
            icms_total,
            "vDesc",
        )

        # ----------------------------------------------------
        # Itens
        # ----------------------------------------------------

        detalhes = nf.get("det") or []

        for detalhe in detalhes:

            produto = detalhe.get("prod") or {}
            produto_interno = detalhe.get("nfProdInt") or {}

            rows.append(
                [
                    id_nf,
                    chave_nfe,
                    numero_nf,
                    serie,
                    data_emissao,
                    tipo_nf,
                    cancelada_em,
                    id_pedido,
                    numero_pedido,
                    cliente_id,
                    cliente_documento,
                    cliente_nome,
                    vendedor,
                    categoria,

                    # ITEM
                    pick(
                        produto_interno,
                        "nCodItem",
                    ),
                    pick(
                        produto_interno,
                        "nCodProd",
                    ),
                    pick(
                        produto,
                        "cProd",
                    ),
                    pick(
                        produto,
                        "xProd",
                    ),
                    pick(
                        produto,
                        "CFOP",
                    ),
                    pick(
                        produto,
                        "NCM",
                    ),
                    pick(
                        produto,
                        "qCom",
                    ),
                    pick(
                        produto,
                        "uCom",
                    ),
                    pick(
                        produto,
                        "vUnCom",
                    ),
                    pick(
                        produto,
                        "vProd",
                    ),
                    pick(
                        produto,
                        "vDesc",
                    ),
                    pick(
                        produto,
                        "vFrete",
                    ),
                    pick(
                        produto,
                        "vOutro",
                    ),
                    pick(
                        produto,
                        "vTotItem",
                    ),

                    # TOTAL DA NF
                    valor_produtos_nf,
                    desconto_nf,
                    valor_nf,

                    # RAW temporário
                    "",
                ]
            )

    return rows