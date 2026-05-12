from database import get_connection


def listar(empresa_id: int | None = None) -> list:
    conn = get_connection()
    if empresa_id:
        rows = conn.execute(
            """SELECT c.*, e.nome AS empresa_nome
               FROM contatos c JOIN empresas e ON c.empresa_id = e.id
               WHERE c.empresa_id = ? ORDER BY c.nome""",
            (empresa_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT c.*, e.nome AS empresa_nome
               FROM contatos c JOIN empresas e ON c.empresa_id = e.id
               ORDER BY c.nome"""
        ).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int):
    conn = get_connection()
    row = conn.execute(
        """SELECT c.*, e.nome AS empresa_nome
           FROM contatos c JOIN empresas e ON c.empresa_id = e.id
           WHERE c.id = ?""",
        (id_,),
    ).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO contatos (empresa_id, nome, cargo, email, telefone)
           VALUES (:empresa_id, :nome, :cargo, :email, :telefone)""",
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
