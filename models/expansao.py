from database import get_connection

PRODUTOS = [
    "Vale Refeição",
    "Vale Alimentação",
    "Combustível",
    "Premiação",
    "Welhub",
    "Vidalink",
    "Private Label",
    "Cobrança",
]

TICKET_MEDIO = {
    "Vale Refeição":   550,
    "Vale Alimentação": 400,
    "Combustível":     300,
    "Premiação":       200,
    "Welhub":          150,
    "Vidalink":        120,
    "Private Label":   500,
    "Cobrança":          0,
    # legado
    "Alimentação": 350,
    "Refeição":    550,
    "Cultura":      50,
    "Saúde":        80,
}


def _carregar_produtos_db(tenant_id: int = 1) -> tuple:
    """Retorna (lista_nomes, ticket_medio_dict) do banco ou fallback."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT nome, valor_por_funcionario FROM produtos_krylo WHERE ativo=1 AND tenant_id=%s ORDER BY nome",
            (tenant_id,)
        ).fetchall()
        conn.close()
        if rows:
            nomes  = [r["nome"] for r in rows]
            ticket = {r["nome"]: float(r["valor_por_funcionario"] or 0) for r in rows}
            return nomes, ticket
    except Exception:
        pass
    return PRODUTOS, TICKET_MEDIO


def listar_oportunidades() -> list:
    produtos_list, ticket_medio = _carregar_produtos_db()
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
        ativos   = [p.strip() for p in (row.get("produtos_ativos") or "").split(",") if p.strip()]
        faltando = [p for p in produtos_list if p not in ativos]
        funcs    = row.get("num_funcionarios") or 0
        potencial = sum(ticket_medio.get(p, 0) * funcs for p in faltando) if funcs else 0
        row["produtos_ativos_lista"] = ativos
        row["produtos_faltando"]     = faltando
        row["potencial_mensal"]      = potencial
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
