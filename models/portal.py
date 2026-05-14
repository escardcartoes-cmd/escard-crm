import secrets
from datetime import datetime
from database import get_connection


def gerar_token(empresa_id: int, empresa_nome: str) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM portal_acessos WHERE empresa_id = ?", (empresa_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE portal_acessos SET token_acesso=?, ativo=1, empresa_nome=? WHERE empresa_id=?",
            (token, empresa_nome, empresa_id),
        )
    else:
        conn.execute(
            """INSERT INTO portal_acessos (empresa_id, empresa_nome, token_acesso, ativo)
               VALUES (?, ?, ?, 1)""",
            (empresa_id, empresa_nome, token),
        )
    conn.commit()
    conn.close()
    return token


def revogar(empresa_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE portal_acessos SET ativo=0 WHERE empresa_id=?", (empresa_id,))
    conn.commit()
    conn.close()


def buscar_por_token(token: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM portal_acessos WHERE token_acesso=? AND ativo=1", (token,)
    ).fetchone()
    conn.close()
    return row


def atualizar_ultimo_acesso(token: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE portal_acessos SET ultimo_acesso=? WHERE token_acesso=?",
        (str(datetime.now())[:19], token),
    )
    conn.commit()
    conn.close()


def listar_todos() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM portal_acessos").fetchall()
    conn.close()
    return {r["empresa_id"]: dict(r) for r in rows}
