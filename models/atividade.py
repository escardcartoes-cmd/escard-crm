from database import get_connection

TIPOS = ["ligação", "e-mail", "reunião", "visita", "proposta enviada", "outro"]


def listar(
    empresa_id: int | None = None,
    oportunidade_id: int | None = None,
    limit: int = 50,
) -> list:
    conn = get_connection()
    sql = """SELECT a.*,
                    e.nome  AS empresa_nome,
                    o.titulo AS oportunidade_titulo
             FROM atividades a
             LEFT JOIN empresas     e ON a.empresa_id      = e.id
             LEFT JOIN oportunidades o ON a.oportunidade_id = o.id
             WHERE 1=1"""
    params: list = []
    if empresa_id:
        sql += " AND a.empresa_id = ?"
        params.append(empresa_id)
    if oportunidade_id:
        sql += " AND a.oportunidade_id = ?"
        params.append(oportunidade_id)
    sql += " ORDER BY a.data DESC, a.criado_em DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def criar(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO atividades (empresa_id, oportunidade_id, tipo, descricao, data)
           VALUES (:empresa_id, :oportunidade_id, :tipo, :descricao, :data)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM atividades WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
