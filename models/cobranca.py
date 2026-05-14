from datetime import date
from database import get_connection

STATUS_CLIENTE = ["ativo", "inativo", "pausado"]


def listar_clientes() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM clientes_cobranca ORDER BY nome").fetchall()
    conn.close()
    return rows


def buscar_cliente(id_: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM clientes_cobranca WHERE id = ?", (id_,)).fetchone()
    conn.close()
    return row


def criar_cliente(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO clientes_cobranca
               (nome, cnpj, contato_nome, contato_fone, contato_email,
                comissao_pct, status)
           VALUES
               (:nome, :cnpj, :contato_nome, :contato_fone, :contato_email,
                :comissao_pct, :status)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def atualizar_cliente(id_: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE clientes_cobranca
           SET nome=:nome, cnpj=:cnpj, contato_nome=:contato_nome,
               contato_fone=:contato_fone, contato_email=:contato_email,
               comissao_pct=:comissao_pct, status=:status
           WHERE id=:id""",
        {**dados, "id": id_},
    )
    conn.commit()
    conn.close()


def listar_relatorios(cliente_id=None, mes=None) -> list:
    conn = get_connection()
    sql = """SELECT r.*, c.nome AS cliente_nome, c.comissao_pct
             FROM relatorios_cobranca r
             JOIN clientes_cobranca c ON r.cliente_id = c.id WHERE 1=1"""
    params = []
    if cliente_id:
        sql += " AND r.cliente_id = ?"
        params.append(cliente_id)
    if mes:
        sql += " AND r.mes_referencia = ?"
        params.append(mes)
    sql += " ORDER BY r.mes_referencia DESC, r.criado_em DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def gerar_relatorio(cliente_id: int, mes: str, total_cobrado: float,
                    total_recuperado: float, observacoes: str = "") -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT comissao_pct FROM clientes_cobranca WHERE id = ?", (cliente_id,)
    ).fetchone()
    pct = (row["comissao_pct"] or 10) if row else 10
    comissao_krylo = round(total_recuperado * pct / 100, 2)
    cur = conn.execute(
        """INSERT INTO relatorios_cobranca
               (cliente_id, mes_referencia, total_cobrado, total_recuperado,
                comissao_krylo, observacoes, status)
           VALUES (?, ?, ?, ?, ?, ?, 'rascunho')""",
        (cliente_id, mes, total_cobrado, total_recuperado, comissao_krylo, observacoes),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def registrar_retorno(relatorio_id: int, retorno: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE relatorios_cobranca SET retorno_cliente=?, status='retorno_recebido' WHERE id=?",
        (retorno, relatorio_id),
    )
    conn.commit()
    conn.close()


def marcar_enviado(relatorio_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE relatorios_cobranca SET status='enviado', data_envio=? WHERE id=?",
        (str(date.today()), relatorio_id),
    )
    conn.commit()
    conn.close()


def resumo() -> dict:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM clientes_cobranca WHERE status='ativo'"
    ).fetchone()["n"]
    mes_atual = str(date.today())[:7]
    rel = conn.execute(
        """SELECT COALESCE(SUM(total_recuperado), 0) AS rec,
                  COALESCE(SUM(comissao_krylo), 0) AS com
           FROM relatorios_cobranca WHERE mes_referencia = ?""",
        (mes_atual,),
    ).fetchone()
    acum = conn.execute(
        "SELECT COALESCE(SUM(comissao_krylo), 0) AS total FROM relatorios_cobranca"
    ).fetchone()["total"]
    conn.close()
    return {
        "clientes_ativos": n,
        "recuperado_mes": rel["rec"] if rel else 0,
        "comissao_mes": rel["com"] if rel else 0,
        "comissao_acumulada": acum,
    }
