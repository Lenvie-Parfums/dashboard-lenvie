ENDPOINTS = {
    "pedidos": "https://app.omie.com.br/api/v1/produtos/pedido/",
    "clientes": "https://app.omie.com.br/api/v1/geral/clientes/",
    "vendedores": "https://app.omie.com.br/api/v1/geral/vendedores/",
    "produtos": "https://app.omie.com.br/api/v1/geral/produtos/",
}

def pick(obj, *keys):
    for key in keys:
        if isinstance(obj, dict) and obj.get(key) is not None:
            return obj[key]
    return ""

def normalize_clientes(items):
    return [[pick(x,'codigo_cliente_omie','codigo_cliente'), pick(x,'codigo_cliente_integracao'), pick(x,'cnpj_cpf'), pick(x,'razao_social'), pick(x,'nome_fantasia'), pick(x,'cidade'), pick(x,'estado','uf'), pick(x,'inativo'), str(x.get('tags',[])), pick(x,'data_alteracao'), str(x)] for x in items]

def normalize_vendedores(items):
    return [[pick(x,'codigo','codigo_vendedor'), pick(x,'nome','nome_vendedor'), pick(x,'email'), pick(x,'inativo'), str(x)] for x in items]

def normalize_produtos(items):
    return [[pick(x,'codigo_produto'), pick(x,'codigo'), pick(x,'descricao'), pick(x,'descricao_familia','familia'), pick(x,'unidade'), pick(x,'inativo'), str(x)] for x in items]

def normalize_pedidos(items):
    rows=[]
    for p in items:
        cab=p.get('cabecalho') or p
        info=p.get('infoCadastro') or p.get('info_cadastro') or {}
        total=p.get('total_pedido') or p.get('totalPedido') or {}
        rows.append([pick(cab,'codigo_pedido','codigo_pedido_omie'),pick(cab,'numero_pedido'),pick(cab,'data_previsao','data_pedido'),pick(cab,'codigo_cliente'),pick(cab,'codigo_vendedor'),'',pick(total,'valor_total_pedido','valor_total','total_valor'),pick(cab,'etapa'),pick(cab,'status_pedido','status'),pick(cab,'codigo_categoria','categoria'),pick(cab,'codigo_projeto'),pick(info,'dInc','data_inclusao'),pick(info,'dAlt','data_alteracao'),str(p)])
    return rows
