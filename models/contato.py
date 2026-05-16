from database import get_connection


def listar(empresa_id=None, tenant_id=None) -> list:
    conn = get_connection()
    sql = """SELECT c.*, e.nome AS empresa_nome
             FROM contatos c JOIN empresas e ON c.empresa_id = e.id
             WHERE 1=1"""
    params = []
    if tenant_id is not None:
        sql += " AND e.tenant_id = ?"
        params.append(tenant_id)
    if empresa_id:
        sql += " AND c.empresa_id = ?"
        params.append(empresa_id)
    sql += " ORDER BY c.nome"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int, tenant_id=None):
    conn = get_connection()
    sql = """SELECT c.*, e.nome AS empresa_nome
             FROM contatos c JOIN empresas e ON c.empresa_id = e.id
             WHERE c.id = ?"""
    params = [id_]
    if tenant_id is not None:
        sql += " AND e.tenant_id = ?"
        params.append(tenant_id)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    dados = {**dados, "tenant_id": dados.get("tenant_id", 1)}
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO contatos (empresa_id, nome, cargo, email, telefone, tenant_id)
           VALUES (:empresa_id, :nome, :cargo, :email, :telefone, :tenant_id)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def atualizar(id_: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE contatos
           SET empresa_id=:empresa_id, nome=:nome, cargo=:cargo, email=:email, telefone=:telefone
           WHERE id=:id""",
        {**dados, "id": id_},
    )
    conn.commit()
    conn.close()


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM contatos WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
