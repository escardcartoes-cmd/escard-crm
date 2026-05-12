from database import get_connection

ESTAGIOS = ["lead", "qualificado", "proposta", "negociacao", "fechado_ganho", "fechado_perdido"]
ESTAGIO_LABELS = {
    "lead": "Lead",
    "qualificado": "Qualificado",
    "proposta": "Proposta",
    "negociacao": "Negociação",
    "fechado_ganho": "Fechado (Ganho)",
    "fechado_perdido": "Fechado (Perdido)",
}


def listar(empresa_id: int | None = None, estagio: str | None = None) -> list:
    conn = get_connection()
    sql = """SELECT o.*, e.nome AS empresa_nome
             FROM oportunidades o JOIN empresas e ON o.empresa_id = e.id
             WHERE 1=1"""
    params: list = []
    if empresa_id:
        sql += " AND o.empresa_id = ?"
        params.append(empresa_id)
    if estagio:
        sql += " AND o.estagio = ?"
        params.append(estagio)
    sql += " ORDER BY o.criado_em DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int):
    conn = get_connection()
    row = conn.execute(
        """SELECT o.*, e.nome AS empresa_nome
           FROM oportunidades o JOIN empresas e ON o.empresa_id = e.id
           WHERE o.id = ?""",
        (id_,),
    ).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO oportunidades
               (empresa_id, titulo, estagio, valor_estimado, num_cartoes,
                responsavel, previsao_fechamento, notas)
           VALUES
               (:empresa_id, :titulo, :estagio, :valor_estimado, :num_cartoes,
                :responsavel, :previsao_fechamento, :notas)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def atualizar(id_: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE oportunidades
           SET empresa_id=:empresa_id, titulo=:titulo, estagio=:estagio,
               valor_estimado=:valor_estimado, num_cartoes=:num_cartoes,
               responsavel=:responsavel, previsao_fechamento=:previsao_fechamento, notas=:notas
           WHERE id=:id""",
        {**dados, "id": id_},
    )
    conn.commit()
    conn.close()


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM oportunidades WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def valor_total_pipeline() -> float:
    conn = get_connection()
    row = conn.execute(
        """SELECT COALESCE(SUM(valor_estimado), 0) AS total
           FROM oportunidades
           WHERE estagio NOT IN ('fechado_ganho', 'fechado_perdido')"""
    ).fetchone()
    conn.close()
    return row["total"]


def contar_por_estagio() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT estagio, COUNT(*) AS total FROM oportunidades GROUP BY estagio"
    ).fetchall()
    conn.close()
    return {r["estagio"]: r["total"] for r in rows}
