from datetime import date, datetime
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


# ── Deal Radar ────────────────────────────────────────────────────────────────

def _dias_sem_contato(data_str) -> int:
    if not data_str:
        return 999
    try:
        d = datetime.strptime(str(data_str)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return 999


def _calcular_score(estagio: str, dias: int, num_int: int, valor) -> int:
    score = 100
    if dias > 7:
        score -= 20
    if dias > 14:
        score -= 30
    if num_int < 2:
        score -= 20
    if valor and valor > 5000:
        score += 10
    if estagio == "proposta":
        score += 15
    return max(0, min(100, score))


def _proxima_acao(estagio: str, dias: int, num_int: int) -> str:
    if dias >= 999:
        return "Registrar primeiro contato"
    if dias > 14:
        return "Contato urgente — lead em risco de esfriar"
    if estagio == "proposta":
        return "Follow-up da proposta enviada"
    if estagio == "negociacao":
        return "Verificar objeções e definir fechamento"
    if num_int < 2:
        return "Aumentar cadência de contatos"
    if estagio == "lead":
        return "Qualificar e agendar apresentação"
    if estagio == "qualificado":
        return "Preparar e enviar proposta comercial"
    if dias > 7:
        return "Agendar reunião de acompanhamento"
    return "Manter cadência de contatos"


def listar_radar() -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT o.id, o.titulo, o.estagio, o.valor_estimado,
               o.score_fechamento, o.data_ultimo_contato, o.num_interacoes,
               e.nome AS empresa_nome,
               COUNT(a.id) AS interacoes_reais,
               MAX(a.data) AS ultimo_contato_real
        FROM oportunidades o
        JOIN empresas e ON o.empresa_id = e.id
        LEFT JOIN atividades a ON a.oportunidade_id = o.id
        WHERE o.estagio NOT IN ('fechado_ganho', 'fechado_perdido')
        GROUP BY o.id
        ORDER BY o.criado_em DESC
    """).fetchall()
    conn.close()

    resultado = []
    for raw in rows:
        r = dict(raw)
        ultimo = r["ultimo_contato_real"] or r["data_ultimo_contato"]
        num_int = int(r["interacoes_reais"] or 0)
        dias = _dias_sem_contato(ultimo)
        score = _calcular_score(r["estagio"], dias, num_int, r["valor_estimado"])
        r.update({
            "score_calc": score,
            "dias_sem_contato": None if dias >= 999 else dias,
            "proxima_acao": _proxima_acao(r["estagio"], dias, num_int),
            "num_int_calc": num_int,
            "estagio_label": ESTAGIO_LABELS.get(r["estagio"], r["estagio"]),
        })
        resultado.append(r)

    resultado.sort(key=lambda x: x["score_calc"], reverse=True)
    return resultado


def salvar_scores_radar(scores: list) -> None:
    if not scores:
        return
    conn = get_connection()
    for r in scores:
        conn.execute(
            "UPDATE oportunidades SET score_fechamento = ? WHERE id = ?",
            (r["score_calc"], r["id"]),
        )
    conn.commit()
    conn.close()


def contar_por_estagio() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT estagio, COUNT(*) AS total FROM oportunidades GROUP BY estagio"
    ).fetchall()
    conn.close()
    return {r["estagio"]: r["total"] for r in rows}
