"""Testes automáticos do sistema Krylo CRM."""
import sys
import os
import re

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import database


def _r(nome, status, mensagem, detalhes=""):
    return {"check_nome": nome, "status": status, "mensagem": mensagem, "detalhes": detalhes}


def teste_rotas_get():
    app_path = os.path.join(_root, "app.py")
    rotas_esperadas = [
        "/", "/empresas", "/oportunidades", "/atividades", "/sdr/painel",
        "/financeiro", "/termometro", "/simulador", "/cqa",
    ]
    try:
        with open(app_path, encoding="utf-8") as f:
            content = f.read()
        faltando = [r for r in rotas_esperadas if f'"{r}"' not in content and f"'{r}'" not in content]
        if faltando:
            return _r("rotas_get", "aviso", f"Rotas não encontradas: {faltando}")
        return _r("rotas_get", "ok", f"Todas as {len(rotas_esperadas)} rotas principais presentes")
    except Exception as e:
        return _r("rotas_get", "erro", f"Erro ao verificar rotas: {e}")


def teste_encoding_templates():
    templates_dir = os.path.join(_root, "templates")
    bad = re.compile(r'[ÃÂ][\x80-\xBF]')
    problemas = []
    try:
        for dirpath, _, files in os.walk(templates_dir):
            for fname in files:
                if not fname.endswith(".html"):
                    continue
                try:
                    with open(os.path.join(dirpath, fname), encoding="utf-8") as f:
                        if bad.search(f.read()):
                            problemas.append(fname)
                except Exception as e:
                    problemas.append(f"{fname}(erro:{e})")
        if problemas:
            return _r("encoding_templates", "aviso",
                      f"{len(problemas)} template(s) com encoding corrompido",
                      detalhes=", ".join(problemas))
        return _r("encoding_templates", "ok", "Todos os templates com encoding correto")
    except Exception as e:
        return _r("encoding_templates", "erro", f"Erro: {e}")


def teste_banco_de_dados():
    tabelas_esperadas = [
        "empresas", "contatos", "oportunidades", "atividades", "cadencias",
        "prospeccao_automatica", "sdr_config", "sdr_sessoes", "ia_config",
        "cqa_resultados", "cqa_alertas",
    ]
    try:
        conn = database.get_connection()
        if database._USE_PG:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()
            existentes = {r["table_name"] for r in rows}
        else:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            existentes = {r["name"] for r in rows}
        conn.close()
        faltando = [t for t in tabelas_esperadas if t not in existentes]
        if faltando:
            return _r("banco_de_dados", "erro", f"Tabelas faltando: {faltando}",
                      detalhes=f"Encontradas: {len(existentes)}")
        return _r("banco_de_dados", "ok",
                  f"Banco OK — {len(existentes)} tabelas, todas essenciais presentes")
    except Exception as e:
        return _r("banco_de_dados", "erro", f"Falha de conexão: {e}")


def teste_encoding_banco():
    bad = re.compile(r'[ÃÂ][\x80-\xBF]')
    problemas = []
    try:
        conn = database.get_connection()
        for tabela, coluna in [
            ("empresas", "nome"), ("empresas", "cidade"),
            ("prospeccao_automatica", "municipio"),
        ]:
            try:
                rows = conn.execute(
                    f"SELECT {coluna} FROM {tabela} WHERE {coluna} IS NOT NULL LIMIT 200"
                ).fetchall()
                for row in rows:
                    if bad.search(str(row[coluna] or "")):
                        problemas.append(f"{tabela}.{coluna}")
                        break
            except Exception:
                pass
        conn.close()
        if problemas:
            return _r("encoding_banco", "aviso",
                      f"Encoding corrompido em: {', '.join(set(problemas))}")
        return _r("encoding_banco", "ok", "Sem encoding corrompido no banco")
    except Exception as e:
        return _r("encoding_banco", "erro", f"Erro: {e}")


def teste_sdr_engine():
    try:
        from models.prospeccao_autonoma import rodar_prospeccao_autonoma, _SDR_DEFAULTS
        campos = ["estados", "score_minimo", "sem_restricao_horario", "max_leads_por_execucao"]
        faltando = [c for c in campos if c not in _SDR_DEFAULTS]
        if faltando:
            return _r("sdr_engine", "aviso", f"SDR importado mas campos faltando: {faltando}")
        return _r("sdr_engine", "ok", "SDR engine importado corretamente")
    except ImportError as e:
        return _r("sdr_engine", "erro", f"Falha ao importar SDR: {e}")
    except Exception as e:
        return _r("sdr_engine", "erro", f"Erro no SDR: {e}")


def teste_cadencias_travadas():
    try:
        conn = database.get_connection()
        if database._USE_PG:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM cadencias "
                "WHERE status='pendente' AND data_acao < (NOW() - INTERVAL '7 days')::TEXT"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM cadencias "
                "WHERE status='pendente' AND data_acao < date('now','-7 days')"
            ).fetchone()
        conn.close()
        cnt = int(row["cnt"] if row else 0)
        if cnt > 20:
            return _r("cadencias_travadas", "aviso",
                      f"{cnt} cadências pendentes há mais de 7 dias")
        return _r("cadencias_travadas", "ok", f"{cnt} cadências atrasadas (abaixo do limite)")
    except Exception as e:
        return _r("cadencias_travadas", "erro", f"Erro: {e}")


def teste_javascript():
    js_dir = os.path.join(_root, "static", "js")
    problemas = []
    try:
        for fname in os.listdir(js_dir):
            if not fname.endswith(".js"):
                continue
            with open(os.path.join(js_dir, fname), encoding="utf-8") as f:
                content = f.read()
            diff = abs(content.count("{") - content.count("}"))
            if diff > 5:
                problemas.append(f"{fname}(diff={diff})")
        if problemas:
            return _r("javascript", "aviso",
                      f"{len(problemas)} arquivo(s) JS com possíveis erros",
                      detalhes=", ".join(problemas))
        return _r("javascript", "ok", "Arquivos JS sem erros detectados")
    except Exception as e:
        return _r("javascript", "erro", f"Erro: {e}")


def teste_novos_modulos():
    checks = [
        ("templates/termometro.html", "Termômetro"),
        ("templates/simulador.html", "Simulador"),
        ("templates/financeiro.html", "Financeiro"),
        ("templates/cqa_dashboard.html", "CQA"),
    ]
    faltando = [desc for rel, desc in checks if not os.path.exists(os.path.join(_root, rel))]
    if faltando:
        return _r("novos_modulos", "aviso", f"Templates faltando: {faltando}")
    return _r("novos_modulos", "ok", "Todos os novos templates presentes")


def teste_dashboard():
    app_path = os.path.join(_root, "app.py")
    vars_esperadas = ["faturado_90d", "pct_90d", "funil", "cad_hoje", "ops_paradas"]
    try:
        with open(app_path, encoding="utf-8") as f:
            content = f.read()
        faltando = [v for v in vars_esperadas if v not in content]
        if faltando:
            return _r("dashboard", "aviso", f"Variáveis faltando no dashboard: {faltando}")
        return _r("dashboard", "ok", f"Dashboard com todas as {len(vars_esperadas)} variáveis esperadas")
    except Exception as e:
        return _r("dashboard", "erro", f"Erro: {e}")


def teste_multi_tenant():
    tabelas_tenant = ["empresas", "cadencias", "oportunidades", "atividades",
                      "sdr_config", "prospeccao_automatica"]
    try:
        conn = database.get_connection()
        # Check tenants table exists and has at least 1 row
        t_row = conn.execute("SELECT COUNT(*) AS cnt FROM tenants").fetchone()
        n_tenants = int(t_row["cnt"] if t_row else 0)
        if n_tenants == 0:
            conn.close()
            return _r("multi_tenant", "aviso", "Tabela tenants vazia — seed nao rodou?")

        # Check tenant_config table
        tc_row = conn.execute("SELECT COUNT(*) AS cnt FROM tenant_config").fetchone()
        n_tc = int(tc_row["cnt"] if tc_row else 0)

        # Check tenant_id column in each table
        missing_col = []
        for tab in tabelas_tenant:
            try:
                conn.execute(f"SELECT tenant_id FROM {tab} LIMIT 1")
            except Exception:
                missing_col.append(tab)

        conn.close()

        if missing_col:
            return _r("multi_tenant", "erro",
                      f"Coluna tenant_id faltando em: {missing_col}")
        return _r("multi_tenant", "ok",
                  f"Multi-tenant OK — {n_tenants} tenant(s), {n_tc} config(s), tenant_id em todas as tabelas")
    except Exception as e:
        return _r("multi_tenant", "erro", f"Erro: {e}")


def rodar_todos_os_testes():
    testes = [
        teste_rotas_get, teste_encoding_templates, teste_banco_de_dados,
        teste_encoding_banco, teste_sdr_engine, teste_cadencias_travadas,
        teste_javascript, teste_novos_modulos, teste_dashboard, teste_multi_tenant,
    ]
    resultados = []
    for t in testes:
        try:
            res = t()
            resultados.append(res)
            emoji = "OK" if res["status"] == "ok" else ("AV" if res["status"] == "aviso" else "ER")
            print(f"  [{emoji}] {res['check_nome']}: {res['mensagem']}")
        except Exception as e:
            resultados.append(_r(t.__name__, "erro", f"Exceção: {e}"))
            print(f"  [ER] {t.__name__}: Excecao: {e}")
    return resultados


if __name__ == "__main__":
    print("=== CQA Testes ===")
    rs = rodar_todos_os_testes()
    erros = sum(1 for r in rs if r["status"] == "erro")
    avisos = sum(1 for r in rs if r["status"] == "aviso")
    oks = sum(1 for r in rs if r["status"] == "ok")
    print(f"\nResumo: {oks} OK / {avisos} avisos / {erros} erros")
