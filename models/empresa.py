from database import get_connection

STATUS = ["prospect", "cliente", "inativo"]
PORTES = ["micro", "pequena", "média", "grande"]


def listar(status=None, tenant_id=None) -> list:
    conn = get_connection()
    sql = "SELECT * FROM empresas WHERE 1=1"
    params = []
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY nome"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int, tenant_id=None):
    conn = get_connection()
    sql = "SELECT * FROM empresas WHERE id = ?"
    params = [id_]
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    dados = {**dados, "tenant_id": dados.get("tenant_id", 1)}
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO empresas
               (nome, cnpj, segmento, porte, status, telefone, email, cidade, estado,
                produtos_ativos, num_funcionarios, cliente_ativo, valor_mensal,
                tipo_cartao, nome_private_label, tenant_id)
           VALUES
               (:nome, :cnpj, :segmento, :porte, :status, :telefone, :email, :cidade, :estado,
                :produtos_ativos, :num_funcionarios, :cliente_ativo, :valor_mensal,
                :tipo_cartao, :nome_private_label, :tenant_id)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def atualizar(id_: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE empresas
           SET nome=:nome, cnpj=:cnpj, segmento=:segmento, porte=:porte,
               status=:status, telefone=:telefone, email=:email, cidade=:cidade, estado=:estado,
               produtos_ativos=:produtos_ativos, num_funcionarios=:num_funcionarios,
               cliente_ativo=:cliente_ativo, valor_mensal=:valor_mensal,
               tipo_cartao=:tipo_cartao, nome_private_label=:nome_private_label
           WHERE id=:id""",
        {**dados, "id": id_},
    )
    conn.commit()
    conn.close()


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM empresas WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def contar_por_status(tenant_id=None) -> dict:
    conn = get_connection()
    if tenant_id is not None:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM empresas WHERE tenant_id=? GROUP BY status",
            (tenant_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM empresas GROUP BY status"
        ).fetchall()
    conn.close()
    return {r["status"]: r["total"] for r in rows}
