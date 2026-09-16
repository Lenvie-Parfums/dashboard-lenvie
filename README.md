# Lenvie — Painel Comercial V1 (Render + Omie + Google Sheets)

## Arquitetura

- **Render Cron Job:** executa a coleta Omie fora do Apps Script.
- **Render Web Service / FastAPI:** health check, recálculo, sync manual e endpoint de KPIs.
- **Google Sheets:** persistência provisória + backoffice do Comercial.
- **Sem SQL nesta V1.** A migração para banco fica para depois da validação funcional.

## Abas esperadas

`CONFIG`, `DE_PARA_REPS`, `CARTEIRA`, `OMIE_PEDIDOS`, `OMIE_CLIENTES`, `OMIE_VENDEDORES`, `OMIE_PRODUTOS`, `BASE_VENDAS`, `KPI_MENSAL`, `DASHBOARD`, `LOG_ATUALIZACAO`.

## Regras atuais

- `STATUS_PEDIDOS_VALIDOS` vazio **não bloqueia** a carga. Todos os pedidos ficam preservados para análise posterior.
- Ticket médio usa **pedido Omie** provisoriamente.
- CFOP/NF continua pendente para a próxima etapa.
- Positivação só fica completa quando `CARTEIRA` tiver `CLIENTE_ID_OMIE` e `REP_ID`.

## Google Service Account

1. Crie/obtenha uma Service Account no Google Cloud e habilite a Google Sheets API.
2. Copie o JSON da credencial para a variável `GOOGLE_SA_JSON` no Render (uma linha JSON).
3. Compartilhe a planilha Google Sheets com o `client_email` dessa Service Account como **Editor**.
4. Copie o ID da planilha (trecho entre `/d/` e `/edit`) para `GOOGLE_SPREADSHEET_ID`.

## Variáveis no Render

- `APP_KEY_OMIE`
- `APP_SECRET_OMIE`
- `GOOGLE_SPREADSHEET_ID`
- `GOOGLE_SA_JSON`
- `ADMIN_TOKEN` (Web Service; protege sync/recalc manual)

## Deploy

Suba esta pasta para um repositório GitHub e crie os serviços pelo `render.yaml` (Blueprint) ou manualmente.

O cron do exemplo roda `0 9 * * *` em UTC, equivalente a **06:00 em São Paulo quando UTC-3**. Ajuste se necessário.

## Primeira execução

1. Importe `Painel_Comercial_Render_Sheets_V1.xlsx` para o Google Sheets.
2. Configure as variáveis no Render.
3. Compartilhe a planilha com a Service Account.
4. Faça deploy.
5. Abra `/health` no Web Service.
6. No Cron Job, use **Trigger Run** para a primeira carga.
7. Acompanhe `LOG_ATUALIZACAO` e os logs do Render.

## Endpoints

- `GET /health`
- `GET /api/kpis`
- `POST /admin/recalc` com header `X-Admin-Token`
- `POST /admin/sync` com header `X-Admin-Token`

## Observação de volume

A V1 usa o Sheets como persistência. Para escrita, o código limpa e grava cada aba automática em lote, evitando célula por célula. Quando o volume ficar grande, o mesmo backend poderá migrar a persistência para SQL.

## Variáveis usadas no Render existente
Esta versão foi ajustada para usar exatamente estas chaves:
- `APP_KEY_OMIE`
- `APP_SECRET_OMIE`
- `GOOGLE_SA_JSON`
- `GOOGLE_SPREADSHEET_ID`

`ADMIN_TOKEN` é opcional. Se configurado, protege os endpoints administrativos `/admin/sync` e `/admin/recalc`.
