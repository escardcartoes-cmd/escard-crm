from database import get_connection

PRODUTOS = [
    "Alimentação",
    "Refeição",
    "Combustível",
    "Cultura",
    "Saúde",
    "Private Label",
]

TICKET_MEDIO = {
    "Alimentação": 350,
    "Refeição": 550,
    "Combustível": 200,
    "Cultura": 50,
    "Saúde": 80,
    "Private Label": 200,
}


def listar_oportunidades() -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, nome, num_funcionarios, valor_mensal, produtos_ativos,
                  tipo_cartao, nome_private_label, telefone, email, segmento, porte
           FROM empresas
           WHERE cliente_ativo = 1 OR status = 'cliente'
           ORDER BY COALESCE(num_funcionarios, 0) DESC"""
    ).fetchall()
    conn.close()
    resultado = []
    for r in rows:
        row = dict(r)
        ativos = [p.strip() for p in (row.get("produtos_ativos") or "").split(",") if p.strip()]
        faltando = [p for p in PRODUTOS if p not in ativos]
        funcs = row.get("num_funcionarios") or 0
        potencial = sum(TICKET_MEDIO[p] * funcs for p in faltando) if funcs else 0
        row["produtos_ativos_lista"] = ativos
        row["produtos_faltando"] = faltando
        row["potencial_mensal"] = potencial
        resultado.append(row)
    resultado.sort(key=lambda x: x["potencial_mensal"], reverse=True)
    return resultado


def potencial_total() -> float:
    try:
        return sum(r["potencial_mensal"] for r in listar_oportunidades())
    except Exception:
        return 0.0


def atualizar_dados_comerciais(empresa_id: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE empresas
           SET produtos_ativos=:produtos_ativos, num_funcionarios=:num_funcionarios,
               cliente_ativo=:cliente_ativo, valor_mensal=:valor_mensal,
               tipo_cartao=:tipo_cartao, nome_private_label=:nome_private_label
           WHERE id=:id""",
        {**dados, "id": empresa_id},
    )
    conn.commit()
    conn.close()
