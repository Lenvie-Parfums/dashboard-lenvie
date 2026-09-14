"""
Banco SQLite — armazena os dados coletados do Omie.

Usamos SQLite em vez de Neon/PostgreSQL para:
  - Zero custo
  - Zero configuração
  - Volume (< 200k linhas) cabe bem no SQLite
  - No Render: persista o arquivo em /data (Render Disk) ou use volume montado

Se futuramente precisar de PostgreSQL, basta trocar a connection string
e ajustar os tipos (TEXT → VARCHAR, INTEGER AUTOINCREMENT → SERIAL).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("db")

# No Render com Disk persistente, monte em /data.
# Localmente, usa o diretório corrente.
DB_PATH = Path(os.getenv("DB_PATH", "/data/dashboard.db"))


def init_db() -> None:
    """Cria as tabelas se não existirem. Idempotente."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS faturamento (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ano         INTEGER NOT NULL,
                mes         INTEGER NOT NULL,
                uf          TEXT NOT NULL,
                rep         TEXT NOT NULL,
                linha       TEXT NOT NULL,
                categoria   TEXT NOT NULL,
                fragancia   TEXT NOT NULL,
                cod_cliente INTEGER NOT NULL,
                item        TEXT NOT NULL,
                fat         REAL NOT NULL,
                qtd         REAL NOT NULL,
                chave_nf    TEXT NOT NULL,
                UNIQUE(chave_nf, item, cod_cliente)
            );

            CREATE TABLE IF NOT EXISTS clientes (
                cod_cliente INTEGER PRIMARY KEY,
                nome        TEXT,
                cnpj        TEXT,
                cidade      TEXT,
                uf          TEXT,
                rep         TEXT
            );

            CREATE TABLE IF NOT EXISTS meta (
                mes         INTEGER PRIMARY KEY,
                valor       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS coleta_status (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                ultima_coleta   TEXT,
                data_ini        TEXT,
                data_fim        TEXT,
                total_nfs       INTEGER DEFAULT 0,
                total_registros INTEGER DEFAULT 0,
                em_andamento    INTEGER DEFAULT 0,
                erro            TEXT
            );

            INSERT OR IGNORE INTO coleta_status (id, em_andamento)
            VALUES (1, 0);
        """)
    log.info("Banco inicializado em %s", DB_PATH)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Escrita ────────────────────────────────────────────────────────────────

def upsert_faturamento(linhas: list[dict]) -> int:
    """
    Insere ou ignora (deduplicação por chave_nf + item + cod_cliente).
    Retorna quantas linhas foram inseridas de fato.
    """
    if not linhas:
        return 0
    sql = """
        INSERT OR IGNORE INTO faturamento
            (ano, mes, uf, rep, linha, categoria, fragancia,
             cod_cliente, item, fat, qtd, chave_nf)
        VALUES
            (:ano, :mes, :uf, :rep, :linha, :categoria, :fragancia,
             :cod_cliente, :item, :fat, :qtd, :chave_nf)
    """
    with _conn() as conn:
        antes = conn.execute("SELECT COUNT(*) FROM faturamento").fetchone()[0]
        conn.executemany(sql, linhas)
        depois = conn.execute("SELECT COUNT(*) FROM faturamento").fetchone()[0]
    inseridos = depois - antes
    log.info("upsert_faturamento: %d inseridos / %d tentativas", inseridos, len(linhas))
    return inseridos


def upsert_clientes(clientes: list[dict]) -> None:
    sql = """
        INSERT OR REPLACE INTO clientes (cod_cliente, nome, cnpj, cidade, uf, rep)
        VALUES (:cod_cliente, :nome, :cnpj, :cidade, :uf, :rep)
    """
    with _conn() as conn:
        conn.executemany(sql, clientes)


def upsert_meta(metas: dict[int, float]) -> None:
    """metas = {1: 3285000.0, 2: 3595000.0, ...}"""
    sql = "INSERT OR REPLACE INTO meta (mes, valor) VALUES (?, ?)"
    with _conn() as conn:
        conn.executemany(sql, metas.items())


def set_status(
    *,
    em_andamento: int | None = None,
    ultima_coleta: str | None = None,
    data_ini: str | None = None,
    data_fim: str | None = None,
    total_nfs: int | None = None,
    total_registros: int | None = None,
    erro: str | None = None,
) -> None:
    campos = {}
    if em_andamento is not None:
        campos["em_andamento"] = em_andamento
    if ultima_coleta is not None:
        campos["ultima_coleta"] = ultima_coleta
    if data_ini is not None:
        campos["data_ini"] = data_ini
    if data_fim is not None:
        campos["data_fim"] = data_fim
    if total_nfs is not None:
        campos["total_nfs"] = total_nfs
    if total_registros is not None:
        campos["total_registros"] = total_registros
    if erro is not None:
        campos["erro"] = erro
    if not campos:
        return
    set_clause = ", ".join(f"{k} = ?" for k in campos)
    with _conn() as conn:
        conn.execute(
            f"UPDATE coleta_status SET {set_clause} WHERE id = 1",
            list(campos.values()),
        )


# ── Leitura ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM coleta_status WHERE id = 1").fetchone()
        return dict(row) if row else {}


def get_data_payload() -> dict:
    """
    Monta o payload completo para o frontend:
    {
      "DATA": [...],       # registros de faturamento (sem item — igual ao HTML atual)
      "ITEM_DATA": [...],  # registros com item
      "CLIENTS": [...],    # [[nome, cnpj, cidade], ...]
      "META": {1: x, ...}
    }
    """
    with _conn() as conn:
        # DATA — agrupado por ano/mes/uf/rep/lin/cat/fr/cliente (sem item)
        rows_fat = conn.execute("""
            SELECT
                ano   AS y,
                mes   AS m,
                uf,
                rep,
                linha  AS lin,
                categoria AS cat,
                fragancia  AS fr,
                cod_cliente AS cl,
                SUM(fat) AS fat,
                SUM(qtd) AS qtd
            FROM faturamento
            GROUP BY ano, mes, uf, rep, linha, categoria, fragancia, cod_cliente
        """).fetchall()

        # ITEM_DATA — com item
        rows_item = conn.execute("""
            SELECT
                ano   AS y,
                mes   AS m,
                uf,
                rep,
                linha  AS lin,
                categoria AS cat,
                fragancia  AS fr,
                item,
                SUM(fat) AS fat,
                SUM(qtd) AS qtd
            FROM faturamento
            GROUP BY ano, mes, uf, rep, linha, categoria, fragancia, item
        """).fetchall()

        # CLIENTS
        rows_cli = conn.execute("""
            SELECT nome, cnpj, cidade, uf, rep, cod_cliente
            FROM clientes
            ORDER BY nome
        """).fetchall()

        # META
        rows_meta = conn.execute("SELECT mes, valor FROM meta").fetchall()

    data = [dict(r) for r in rows_fat]
    item_data = [dict(r) for r in rows_item]
    clients = [[r["nome"], r["cnpj"], r["cidade"]] for r in rows_cli]
    meta = {str(r["mes"]): r["valor"] for r in rows_meta}

    return {
        "DATA": data,
        "ITEM_DATA": item_data,
        "CLIENTS": clients,
        "META": meta,
        "total_registros": len(data),
    }
