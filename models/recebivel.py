from datetime import date
from database import get_connection

STATUS = ["pendente", "pago", "atrasado"]


def listar(empresa_id=None, mes=None, status=None) -> list:
    conn = get_connection()
    sql = """SELECT r.*, e.nome AS empresa_nome, e.telefone AS empresa_telefone
             FROM recebiveis_krylo r
             JOIN empresas e ON r.empresa_id = e.id WHERE 1=1"""
    params = []
    if empresa_id:
        sql += " AND r.empresa_id = ?"
        params.append(empresa_id)
    if mes:
        sql += " AND r.mes_referencia = ?"
        params.append(mes)
    if status:
        sql += " AND r.status = ?"
        params.append(status)
    sql += " ORDER BY r.vencimento ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def gerar_mensal(mes: str) -> int:
    """Create receivables for all active paying clients. Returns count created."""
    conn = get_connection()
    clientes = conn.execute(
        """SELECT id, valor_mensal FROM empresas
           WHERE (cliente_ativo = 1 OR status = 'cliente')
             AND valor_mensal IS NOT NULL AND valor_mensal > 0"""
    ).fetchall()
    count = 0
    vencimento = mes + "-10"
    for c in clientes:
        existing = conn.execute(
            "SELECT id FROM recebiveis_krylo WHERE empresa_id = ? AND mes_referencia = ?",
            (c["id"], mes),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO recebiveis_krylo
                       (empresa_id, mes_referencia, valor, vencimento, status)
                   VALUES (?, ?, ?, ?, 'pendente')""",
                (c["id"], mes, c["valor_mensal"], vencimento),
            )
            count += 1
    conn.commit()
    conn.close()
    return count


def marcar_pago(id_: int, data_pagamento: str = None) -> None:
    dp = data_pagamento or str(date.today())
    conn = get_connection()
    conn.execute(
        "UPDATE recebiveis_krylo SET status='pago', data_pagamento=? WHERE id=?",
        (dp, id_),
    )
    conn.commit()
    conn.close()


def resumo_mes(mes: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN status='pago'     THEN valor ELSE 0 END), 0) AS pago,
                  COALESCE(SUM(CASE WHEN status='pendente' THEN valor ELSE 0 END), 0) AS pendente,
                  COALESCE(SUM(CASE WHEN status='atrasado' THEN valor ELSE 0 END), 0) AS atrasado
           FROM recebiveis_krylo WHERE mes_referencia = ?""",
        (mes,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {"total": 0, "pago": 0, "pendente": 0, "atrasado": 0}
