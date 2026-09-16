from datetime import datetime, date
import unicodedata

def norm(v):
    s = unicodedata.normalize('NFD', str(v or '').strip().upper())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')

def parse_date(v):
    if isinstance(v, (datetime,date)): return v
    s=str(v or '').strip()
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%d/%m/%Y %H:%M:%S'):
        try: return datetime.strptime(s[:19],fmt)
        except ValueError: pass
    return None

def objects(values):
    if len(values)<3: return []
    headers=values[2]
    return [{headers[i]: row[i] if i<len(row) else '' for i in range(len(headers))} for row in values[3:] if any(str(x).strip() for x in row)]

def cfg(values):
    return {str(x.get('CHAVE')): x.get('VALOR','') for x in objects(values)}

def build_base(pedidos, clientes, vendedores, reps, config):
    cli={str(x.get('COD_CLIENTE')):x for x in clientes}
    ven={str(x.get('COD_VENDEDOR')):x for x in vendedores}
    rep_by_omie={norm(x.get('VENDEDOR_OMIE')):x for x in reps if x.get('VENDEDOR_OMIE')}
    statuses={norm(x) for x in str(config.get('STATUS_PEDIDOS_VALIDOS') or '').split(';') if x.strip()}
    rows=[]
    now=datetime.now().isoformat(timespec='seconds')
    for p in pedidos:
        d=parse_date(p.get('DATA_PEDIDO'))
        if not d: continue
        c=cli.get(str(p.get('COD_CLIENTE')), {})
        v=ven.get(str(p.get('COD_VENDEDOR')), {})
        vendedor=p.get('VENDEDOR_OMIE') or v.get('NOME_VENDEDOR','')
        rep=rep_by_omie.get(norm(vendedor),{})
        valid=True; reason=''
        # V1: status vazio na CONFIG não bloqueia nada. Preservamos o status para revisão posterior.
        if statuses and norm(p.get('STATUS')) not in statuses and norm(p.get('ETAPA')) not in statuses:
            valid=False; reason='STATUS/ETAPA'
        rows.append([d.year,d.month,f'{d.year:04d}-{d.month:02d}',p.get('COD_PEDIDO',''),p.get('NUM_PEDIDO',''),p.get('COD_CLIENTE',''),c.get('CNPJ_CPF',''),c.get('RAZAO_SOCIAL') or c.get('NOME_FANTASIA',''),p.get('COD_VENDEDOR',''),vendedor,rep.get('REP_ID',''),rep.get('NOME_EXIBICAO') or vendedor,float(p.get('VALOR_PEDIDO') or 0),p.get('STATUS') or p.get('ETAPA',''),p.get('CATEGORIA',''),'SIM' if valid else 'NAO',reason,now])
    return rows

def active_portfolio(carteira, rep_id, y, m):
    start=datetime(y,m,1); end=datetime(y+1,1,1) if m==12 else datetime(y,m+1,1)
    out=[]
    for c in carteira:
        if str(c.get('REP_ID'))!=str(rep_id): continue
        di=parse_date(c.get('DATA_INICIO')) or datetime(1900,1,1)
        df=parse_date(c.get('DATA_FIM')) or datetime(2999,12,31)
        if di < end and df >= start: out.append(c)
    return out

def build_kpis(base, carteira):
    groups={}
    for v in base:
        if norm(v.get('VENDA_VALIDA'))!='SIM': continue
        key=(str(v.get('COMPETENCIA')),str(v.get('REP_ID') or v.get('REPRESENTANTE')))
        g=groups.setdefault(key, {'comp':key[0],'rep_id':v.get('REP_ID',''),'rep':v.get('REPRESENTANTE',''),'fat':0.0,'orders':set(),'clients':set()})
        g['fat'] += float(v.get('VALOR') or 0); g['orders'].add(str(v.get('COD_PEDIDO') or v.get('NUM_PEDIDO'))); g['clients'].add(str(v.get('COD_CLIENTE')))
    rows=[]
    for g in sorted(groups.values(), key=lambda x:(x['comp'],x['rep'])):
        y,m=map(int,g['comp'].split('-')); cart=active_portfolio(carteira,g['rep_id'],y,m)
        ids={str(c.get('CLIENTE_ID_OMIE')) for c in cart if c.get('CLIENTE_ID_OMIE')}
        pos=len(g['clients'] & ids); np=len(g['orders']); nc=len(g['clients']); ncart=len(ids)
        rows.append([g['comp'],g['rep_id'],g['rep'],g['fat'],np,nc,ncart,pos,g['fat']/nc if nc else 0,g['fat']/np if np else 0,pos/ncart if ncart else '', 'OK' if ncart else 'SEM CARTEIRA'])
    return rows
