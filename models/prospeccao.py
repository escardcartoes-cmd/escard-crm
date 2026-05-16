import json
from database import get_connection

STATUS_LIST = ["pendente", "mensagem_enviada", "respondeu", "convertido"]
STATUS_LABELS = {
    "pendente":          "Pendente",
    "mensagem_enviada":  "Mensagem Enviada",
    "respondeu":         "Respondeu",
    "convertido":        "Convertido",
}


def listar(score_min=None, score_max=None, status=None, tenant_id=1):
    conn = get_connection()
    sql = """
        SELECT p.*,
               c.nome     AS contato_nome,
               c.cargo,
               c.telefone AS contato_telefone,
               c.email    AS contato_email,
               e.nome     AS empresa_nome,
               e.segmento,
               e.porte
        FROM prospeccao p
        JOIN contatos c ON p.contato_id = c.id
        JOIN empresas e ON p.empresa_id  = e.id
        WHERE p.tenant_id = ?
    """
    params = [tenant_id]
    if score_min is not None:
        sql += " AND p.score >= ?"
        params.append(score_min)
    if score_max is not None:
        sql += " AND p.score <= ?"
        params.append(score_max)
    if status:
        sql += " AND p.status = ?"
        params.append(status)
    sql += " ORDER BY p.score DESC, p.criado_em DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_):
    conn = get_connection()
    row = conn.execute("""
        SELECT p.*,
               c.nome     AS contato_nome,
               c.cargo,
               c.telefone AS contato_telefone,
               c.email    AS contato_email,
               e.nome     AS empresa_nome,
               e.segmento,
               e.porte
        FROM prospeccao p
        JOIN contatos c ON p.contato_id = c.id
        JOIN empresas e ON p.empresa_id  = e.id
        WHERE p.id = ?
    """, (id_,)).fetchone()
    conn.close()
    return row


def buscar_por_contato(contato_id, tenant_id=1):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM prospeccao WHERE contato_id = ? AND tenant_id = ?",
        (contato_id, tenant_id)
    ).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT OR IGNORE INTO prospeccao (contato_id, empresa_id, status, tenant_id)
           VALUES (:contato_id, :empresa_id, :status, :tenant_id)""",
        dados,
    )
    conn.commit()
    last = cur.lastrowid
    if not last:
        row = conn.execute(
            "SELECT id FROM prospeccao WHERE contato_id = ? AND tenant_id = ?",
            (dados["contato_id"], dados.get("tenant_id", 1))
        ).fetchone()
        last = row["id"] if row else 0
    conn.close()
    return last


def salvar_score(id_: int, score: int, justificativa: str, pontos_fortes: list, pontos_fracos: list):
    conn = get_connection()
    conn.execute(
        """UPDATE prospeccao
           SET score=?, score_justificativa=?, score_pontos_fortes=?, score_pontos_fracos=?,
               atualizado_em=datetime('now','localtime')
           WHERE id=?""",
        (score, justificativa, json.dumps(pontos_fortes), json.dumps(pontos_fracos), id_),
    )
    conn.commit()
    conn.close()


def salvar_whatsapp(id_: int, msg: str):
    conn = get_connection()
    conn.execute(
        "UPDATE prospeccao SET msg_whatsapp=?, atualizado_em=datetime('now','localtime') WHERE id=?",
        (msg, id_),
    )
    conn.commit()
    conn.close()


def salvar_email(id_: int, assunto: str, corpo: str):
    conn = get_connection()
    conn.execute(
        """UPDATE prospeccao
           SET msg_email_assunto=?, msg_email_corpo=?, atualizado_em=datetime('now','localtime')
           WHERE id=?""",
        (assunto, corpo, id_),
    )
    conn.commit()
    conn.close()


def salvar_status(id_: int, status: str):
    conn = get_connection()
    conn.execute(
        "UPDATE prospeccao SET status=?, atualizado_em=datetime('now','localtime') WHERE id=?",
        (status, id_),
    )
    conn.commit()
    conn.close()


def excluir(id_: int):
    conn = get_connection()
    conn.execute("DELETE FROM prospeccao WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def contar_por_status(tenant_id=1) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS total FROM prospeccao WHERE tenant_id = ? GROUP BY status",
        (tenant_id,)
    ).fetchall()
    conn.close()
    return {r["status"]: r["total"] for r in rows}


def listar_ids_para_exportacao(ids: list, tenant_id=1) -> list:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT p.*,
                   c.nome     AS contato_nome,
                   c.cargo,
                   c.telefone AS contato_telefone,
                   c.email    AS contato_email,
                   e.nome     AS empresa_nome
            FROM prospeccao p
            JOIN contatos c ON p.contato_id = c.id
            JOIN empresas e ON p.empresa_id  = e.id
            WHERE p.id IN ({placeholders}) AND p.tenant_id = ?
            ORDER BY p.score DESC, p.criado_em DESC""",
        ids + [tenant_id],
    ).fetchall()
    conn.close()
    return rows
