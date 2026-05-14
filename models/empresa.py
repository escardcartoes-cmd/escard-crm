from database import get_connection

STATUS = ["prospect", "cliente", "inativo"]
PORTES = ["micro", "pequena", "média", "grande"]


def listar(status: str | None = None) -> list:
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM empresas WHERE status = ? ORDER BY nome", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM empresas ORDER BY nome").fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM empresas WHERE id = ?", (id_,)).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO empresas
               (nome, cnpj, segmento, porte, status, telefone, email, cidade, estado,
                produtos_ativos, num_funcionarios, cliente_ativo, valor_mensal,
                tipo_cartao, nome_private_label)
           VALUES
               (:nome, :cnpj, :segmento, :porte, :status, :telefone, :email, :cidade, :estado,
                :produtos_ativos, :num_funcionarios, :cliente_ativo, :valor_mensal,
                :tipo_cartao, :nome_private_label)""",
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


def contar_por_status() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as total FROM empresas GROUP BY status"
    ).fetchall()
    conn.close()
    return {r["status"]: r["total"] for r in rows}
