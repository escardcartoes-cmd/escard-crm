from datetime import date, timedelta
from database import get_connection


def coletar_semanal() -> dict:
    try:
        conn = get_connection()
        hoje = str(date.today())
        semana_atras = str(date.today() - timedelta(days=7))
        mes_atual = hoje[:7]

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM empresas WHERE criado_em >= ?", (semana_atras,)
        ).fetchone()
        empresas_novas = int((row["cnt"] if row else 0) or 0)

        rows = conn.execute(
            """SELECT etapa, COUNT(*) AS cnt,
                      COALESCE(SUM(valor_estimado), 0) AS total
               FROM oportunidades
               WHERE etapa NOT IN ('fechado_ganho', 'fechado_perdido')
               GROUP BY etapa"""
        ).fetchall()
        ops_abertas = int(sum(r["cnt"] for r in rows))
        pipeline_total = float(sum(r["total"] for r in rows))

        row = conn.execute(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(valor_estimado), 0) AS total
               FROM oportunidades
               WHERE etapa='fechado_ganho' AND criado_em LIKE ?""",
            (mes_atual + "%",),
        ).fetchone()
        deals_fechados = int((row["cnt"] if row else 0) or 0)
        receita_mes = float((row["total"] if row else 0.0) or 0.0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM atividades WHERE criado_em >= ?", (semana_atras,)
        ).fetchone()
        atividades_semana = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cadencias WHERE data_acao = ? AND status='pendente'",
            (hoje,)
        ).fetchone()
        cadencias_hoje = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cadencias WHERE status='pendente'"
        ).fetchone()
        cadencias_ativas = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(valor), 0) AS total
               FROM recebiveis_krylo WHERE status='atrasado'"""
        ).fetchone()
        rec_atrasados_count = int((row["cnt"] if row else 0) or 0)
        rec_atrasados_valor = float((row["total"] if row else 0.0) or 0.0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM portal_acessos WHERE ativo=1"
        ).fetchone()
        portais_ativos = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM radar_mercado WHERE lido=0"
        ).fetchone()
        radar_nao_lidos = int((row["cnt"] if row else 0) or 0)

        top_ops = conn.execute(
            """SELECT o.titulo, e.nome AS empresa_nome,
                      o.valor_estimado, o.etapa, o.proxima_acao_sugerida
               FROM oportunidades o
               JOIN empresas e ON o.empresa_id = e.id
               WHERE o.etapa NOT IN ('fechado_ganho', 'fechado_perdido')
                 AND o.valor_estimado IS NOT NULL
               ORDER BY o.valor_estimado DESC
               LIMIT 3"""
        ).fetchall()

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM clientes_cobranca WHERE status='ativo'"
        ).fetchone()
        clientes_cobranca = int((row["cnt"] if row else 0) or 0)

        conn.close()

        pct_meta = round(min(receita_mes / 100_000 * 100, 100), 1) if receita_mes else 0.0

        return {
            "hoje": hoje,
            "semana_atras": semana_atras,
            "mes_atual": mes_atual,
            "empresas_novas": empresas_novas,
            "ops_abertas": ops_abertas,
            "pipeline_total": pipeline_total,
            "deals_fechados": deals_fechados,
            "receita_mes": receita_mes,
            "pct_meta": pct_meta,
            "atividades_semana": atividades_semana,
            "cadencias_hoje": cadencias_hoje,
            "cadencias_ativas": cadencias_ativas,
            "rec_atrasados_count": rec_atrasados_count,
            "rec_atrasados_valor": rec_atrasados_valor,
            "portais_ativos": portais_ativos,
            "radar_nao_lidos": radar_nao_lidos,
            "top_ops": [dict(r) for r in top_ops],
            "clientes_cobranca": clientes_cobranca,
        }
    except Exception as e:
        print(f'[RELATORIO] Erro em coletar_semanal: {e}')
        return {}


def coletar_dashboard_extra(mes_atual: str) -> dict:
    try:
        conn = get_connection()
        semana_atras = str(date.today() - timedelta(days=7))

        row = conn.execute("SELECT COUNT(*) AS cnt FROM portal_acessos WHERE ativo=1").fetchone()
        portais_ativos = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM recebiveis_krylo WHERE status='atrasado'"
        ).fetchone()
        rec_atrasados_count = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM oportunidades WHERE etapa='fechado_ganho' AND criado_em >= ?",
            (semana_atras,)
        ).fetchone()
        deals_fechados_semana = int((row["cnt"] if row else 0) or 0)

        row = conn.execute(
            "SELECT COALESCE(SUM(valor_estimado), 0) AS total FROM oportunidades"
            " WHERE etapa='fechado_ganho' AND criado_em LIKE ?",
            (mes_atual + "%",)
        ).fetchone()
        receita_mes = float((row["total"] if row else 0.0) or 0.0)

        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cadencias WHERE status='pendente'"
        ).fetchone()
        cadencias_ativas_count = int((row["cnt"] if row else 0) or 0)

        conn.close()

        pct_meta = round(min(receita_mes / 100_000 * 100, 100), 1) if receita_mes else 0.0

        return {
            "portais_ativos": portais_ativos,
            "rec_atrasados_count": rec_atrasados_count,
            "deals_fechados_semana": deals_fechados_semana,
            "receita_mes": receita_mes,
            "pct_meta": pct_meta,
            "cadencias_ativas_count": cadencias_ativas_count,
        }
    except Exception as e:
        print(f'[RELATORIO] Erro em coletar_dashboard_extra: {e}')
        return {}
