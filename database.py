import os
import re
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
_USE_PG = bool(DATABASE_URL)

if not _USE_PG:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "escard.db")

_SQLITE_DDL = """
    CREATE TABLE IF NOT EXISTS empresas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nome        TEXT    NOT NULL,
        cnpj        TEXT    UNIQUE,
        segmento    TEXT,
        porte       TEXT,
        status      TEXT    NOT NULL DEFAULT 'prospect',
        telefone    TEXT,
        email       TEXT,
        cidade      TEXT,
        estado      TEXT,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS contatos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id  INTEGER NOT NULL,
        nome        TEXT    NOT NULL,
        cargo       TEXT,
        email       TEXT,
        telefone    TEXT,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS oportunidades (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id          INTEGER NOT NULL,
        titulo              TEXT    NOT NULL,
        estagio             TEXT    NOT NULL DEFAULT 'lead',
        valor_estimado      REAL,
        num_cartoes         INTEGER,
        responsavel         TEXT,
        previsao_fechamento TEXT,
        notas               TEXT,
        criado_em           TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS atividades (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id       INTEGER,
        oportunidade_id  INTEGER,
        tipo             TEXT    NOT NULL,
        descricao        TEXT,
        data             TEXT    DEFAULT (date('now', 'localtime')),
        criado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id)      REFERENCES empresas(id)      ON DELETE SET NULL,
        FOREIGN KEY (oportunidade_id) REFERENCES oportunidades(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS prospeccao (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        contato_id           INTEGER NOT NULL UNIQUE,
        empresa_id           INTEGER NOT NULL,
        score                INTEGER,
        score_justificativa  TEXT,
        score_pontos_fortes  TEXT,
        score_pontos_fracos  TEXT,
        status               TEXT    NOT NULL DEFAULT 'pendente',
        msg_whatsapp         TEXT,
        msg_email_assunto    TEXT,
        msg_email_corpo      TEXT,
        criado_em            TEXT    DEFAULT (datetime('now', 'localtime')),
        atualizado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE,
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS documentos_ia (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nome            TEXT    NOT NULL,
        tipo            TEXT    NOT NULL,
        conteudo_texto  TEXT,
        data_upload     TEXT    DEFAULT (datetime('now', 'localtime')),
        tamanho         INTEGER
    );
"""


def _to_pg(sql: str) -> str:
    """Convert SQLite SQL syntax to PostgreSQL."""
    # Named placeholders :name → %(name)s  (must run before ? → %s)
    sql = re.sub(r":([A-Za-z_]\w*)", r"%(\1)s", sql)
    # Positional placeholders
    sql = sql.replace("?", "%s")
    # Date/time functions
    sql = re.sub(r"datetime\s*\([^)]*\)", "NOW()", sql)
    sql = re.sub(r"date\s*\([^)]*\)", "CURRENT_DATE", sql)
    # DDL: AUTOINCREMENT → SERIAL
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    # INSERT OR IGNORE → INSERT … ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE INTO" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class _PgCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cur = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgConn:
    def __init__(self, raw):
        import psycopg2.extras
        self._raw = raw
        self._extras = psycopg2.extras

    def execute(self, sql: str, params=()) -> _PgCursor:
        sql = _to_pg(sql)
        is_insert = sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = self._raw.cursor(cursor_factory=self._extras.RealDictCursor)
        cur.execute(sql, params or None)
        rid = None
        if is_insert:
            row = cur.fetchone()
            if row:
                rid = row.get("id")
        return _PgCursor(cur, rid)

    def executescript(self, sql: str) -> None:
        cur = self._raw.cursor()
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            cur.execute(_to_pg(stmt))
        self._raw.commit()
        cur.close()

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def get_connection():
    if _USE_PG:
        import psycopg2
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return _PgConn(psycopg2.connect(url))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(_SQLITE_DDL)
    conn.commit()
    conn.close()
