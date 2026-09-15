from __future__ import annotations
import logging, os, sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("db")
DB_PATH = Path(os.getenv("DB_PATH", "/data/dashboard.db"))


def init_db() -> None:
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
                nome TEXT, cnpj TEXT, cidade TEXT, uf TEXT, rep TEXT
            );
            CREATE TABLE IF NOT EXISTS meta (
                mes INTEGER PRIMARY KEY, valor REAL NOT NULL
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
        # Migration: adiciona cancelar_coleta se não existir
        cols = [r[1] for r in conn.execute("PRAGMA table_info(coleta_status)").fetchall()]
        if "cancelar_coleta" not in cols:
            conn.execute("ALTER TABLE coleta_status ADD COLUMN cancelar_coleta INTEGER DEFAULT 0")
            log.info("Migration: coluna cancelar_coleta adicionada")
    # Reseta lock travado de processo anterior
    with _conn() as conn:
        conn.execute("UPDATE coleta_status SET em_andamento=0, cancelar_coleta=0 WHERE id=1 AND em_andamento=1")
    log.info("Banco em %s", DB_PATH)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_faturamento(linhas: list[dict]) -> int:
    if not linhas:
        return 0
    sql = """INSERT OR IGNORE INTO faturamento
        (ano,mes,uf,rep,linha,categoria,fragancia,cod_cliente,item,fat,qtd,chave_nf)
        VALUES (:ano,:mes,:uf,:rep,:linha,:categoria,:fragancia,:cod_cliente,:item,:fat,:qtd,:chave_nf)"""
    with _conn() as conn:
        antes = conn.execute("SELECT COUNT(*) FROM faturamento").fetchone()[0]
        conn.executemany(sql, linhas)
        depois = conn.execute("SELECT COUNT(*) FROM faturamento").fetchone()[0]
    return depois - antes


def upsert_clientes(clientes: list[dict]) -> None:
    sql = "INSERT OR REPLACE INTO clientes (cod_cliente,nome,cnpj,cidade,uf,rep) VALUES (:cod_cliente,:nome,:cnpj,:cidade,:uf,:rep)"
    with _conn() as conn:
        conn.executemany(sql, clientes)


def upsert_meta(metas: dict[int, float]) -> None:
    with _conn() as conn:
        conn.executemany("INSERT OR REPLACE INTO meta (mes,valor) VALUES (?,?)", metas.items())


def set_status(*, em_andamento=None, ultima_coleta=None, data_ini=None,
               data_fim=None, total_nfs=None, total_registros=None, erro=None):
    campos = {}
    if em_andamento is not None: campos["em_andamento"] = em_andamento
    if ultima_coleta is not None: campos["ultima_coleta"] = ultima_coleta
    if data_ini is not None: campos["data_ini"] = data_ini
    if data_fim is not None: campos["data_fim"] = data_fim
    if total_nfs is not None: campos["total_nfs"] = total_nfs
    if total_registros is not None: campos["total_registros"] = total_registros
    if erro is not None: campos["erro"] = erro
    if not campos: return
    set_clause = ", ".join(f"{k} = ?" for k in campos)
    with _conn() as conn:
        conn.execute(f"UPDATE coleta_status SET {set_clause} WHERE id = 1", list(campos.values()))


def set_cancelar(valor: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE coleta_status SET cancelar_coleta = ? WHERE id = 1", (valor,))


def deve_cancelar() -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT cancelar_coleta FROM coleta_status WHERE id = 1").fetchone()
        return bool(row and row[0])


def get_status() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM coleta_status WHERE id = 1").fetchone()
        return dict(row) if row else {}


def get_data_payload() -> dict:
    with _conn() as conn:
        rows_fat = conn.execute("""
            SELECT ano AS y, mes AS m, uf, rep, linha AS lin, categoria AS cat,
                   fragancia AS fr, cod_cliente AS cl, SUM(fat) AS fat, SUM(qtd) AS qtd
            FROM faturamento
            GROUP BY ano, mes, uf, rep, linha, categoria, fragancia, cod_cliente
        """).fetchall()
        rows_item = conn.execute("""
            SELECT ano AS y, mes AS m, uf, rep, linha AS lin, categoria AS cat,
                   fragancia AS fr, item, SUM(fat) AS fat, SUM(qtd) AS qtd
            FROM faturamento
            GROUP BY ano, mes, uf, rep, linha, categoria, fragancia, item
        """).fetchall()
        rows_cli = conn.execute("SELECT nome, cnpj, cidade, uf, rep, cod_cliente FROM clientes ORDER BY nome").fetchall()
        rows_meta = conn.execute("SELECT mes, valor FROM meta").fetchall()

    return {
        "DATA":      [dict(r) for r in rows_fat],
        "ITEM_DATA": [dict(r) for r in rows_item],
        "CLIENTS":   [[r["nome"], r["cnpj"], r["cidade"]] for r in rows_cli],
        "META":      {str(r["mes"]): r["valor"] for r in rows_meta},
        "total_registros": len(rows_fat),
    }
