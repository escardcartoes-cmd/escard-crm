from datetime import date, datetime, timedelta
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


def listar(empresa_id=None, estagio=None, tenant_id=None) -> list:
    conn = get_connection()
    sql = """SELECT o.*, e.nome AS empresa_nome
             FROM oportunidades o JOIN empresas e ON o.empresa_id = e.id
             WHERE 1=1"""
    params = []
    if tenant_id is not None:
        sql += " AND o.tenant_id = ?"
        params.append(tenant_id)
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


def buscar_por_id(id_: int, tenant_id=None):
    conn = get_connection()
    sql = """SELECT o.*, e.nome AS empresa_nome
             FROM oportunidades o JOIN empresas e ON o.empresa_id = e.id
             WHERE o.id = ?"""
    params = [id_]
    if tenant_id is not None:
        sql += " AND o.tenant_id = ?"
        params.append(tenant_id)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    dados = {**dados, "tenant_id": dados.get("tenant_id", 1)}
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO oportunidades
               (empresa_id, titulo, estagio, valor_estimado, num_cartoes,
                responsavel, previsao_fechamento, notas, tenant_id)
           VALUES
               (:empresa_id, :titulo, :estagio, :valor_estimado, :num_cartoes,
                :responsavel, :previsao_fechamento, :notas, :tenant_id)""",
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


def valor_total_pipeline(tenant_id=None) -> float:
    conn = get_connection()
    sql = """SELECT COALESCE(SUM(valor_estimado), 0) AS total
             FROM oportunidades
             WHERE estagio NOT IN ('fechado_ganho', 'fechado_perdido')"""
    params = []
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    row = conn.execute(sql, params).fetchone()
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


def _calcular_score(estagio: str, dias: int, valor, teve_reuniao: bool) -> int:
    score = 50
    if teve_reuniao:
        score += 20
    if estagio == "proposta":
        score += 15
    if valor and valor > 5000:
        score += 10
    if dias > 7:
        score -= 15
    if dias > 14:
        score -= 25
    if dias > 30:
        score -= 10
    return max(0, min(100, score))


def _proxima_acao(score: int, dias: int, teve_reuniao: bool) -> str:
    if dias > 30:
        return "Ligar urgente ou arquivar"
    if score < 50 and dias > 14:
        return "Reativar — deal esfriando"
    if score > 75:
        return "Enviar contrato agora"
    if 50 <= score <= 75 and not teve_reuniao:
        return "Agendar reunião"
    if 50 <= score <= 75 and teve_reuniao:
        return "Enviar proposta"
    return "Manter acompanhamento"


def listar_radar(tenant_id=None) -> list:
    sete_dias_atras = str(date.today() - timedelta(days=7))
    conn = get_connection()
    sql = """
        SELECT o.id, o.titulo, o.estagio, o.valor_estimado,
               o.score_fechamento, o.data_ultimo_contato, o.num_interacoes,
               e.nome AS empresa_nome,
               COUNT(a.id) AS interacoes_reais,
               MAX(a.data) AS ultimo_contato_real,
               (SELECT COUNT(*) FROM atividades r
                WHERE r.oportunidade_id = o.id
                  AND r.data >= ?
                  AND r.tipo = ?) AS reunioes_recentes
        FROM oportunidades o
        JOIN empresas e ON o.empresa_id = e.id
        LEFT JOIN atividades a ON a.oportunidade_id = o.id
        WHERE o.estagio NOT IN ('fechado_ganho', 'fechado_perdido')
    """
    params = [sete_dias_atras, "reunião"]
    if tenant_id is not None:
        sql += " AND o.tenant_id = ?"
        params.append(tenant_id)
    sql += """
        GROUP BY o.id, o.titulo, o.estagio, o.valor_estimado, o.score_fechamento,
                 o.data_ultimo_contato, o.num_interacoes, e.nome
        ORDER BY o.criado_em DESC
    """
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    resultado = []
    for raw in rows:
        r = dict(raw)
        ultimo = r["ultimo_contato_real"] or r["data_ultimo_contato"]
        dias = _dias_sem_contato(ultimo)
        teve_reuniao = int(r.get("reunioes_recentes") or 0) > 0
        score = _calcular_score(r["estagio"], dias, r["valor_estimado"], teve_reuniao)
        proxima = _proxima_acao(score, dias, teve_reuniao)
        r.update({
            "score_calc": score,
            "dias_sem_contato": None if dias >= 999 else dias,
            "proxima_acao": proxima,
            "estagio_label": ESTAGIO_LABELS.get(r["estagio"], r["estagio"]),
            "teve_reuniao": teve_reuniao,
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
            """UPDATE oportunidades
               SET score_fechamento = ?, dias_sem_contato = ?, proxima_acao_sugerida = ?
               WHERE id = ?""",
            (r["score_calc"], r["dias_sem_contato"] or 0, r["proxima_acao"], r["id"]),
        )
    conn.commit()
    conn.close()


def contar_por_estagio(tenant_id=None) -> dict:
    conn = get_connection()
    if tenant_id is not None:
        rows = conn.execute(
            "SELECT estagio, COUNT(*) AS total FROM oportunidades WHERE tenant_id=? GROUP BY estagio",
            (tenant_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT estagio, COUNT(*) AS total FROM oportunidades GROUP BY estagio"
        ).fetchall()
    conn.close()
    return {r["estagio"]: r["total"] for r in rows}
