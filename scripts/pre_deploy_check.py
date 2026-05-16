"""
Roda ANTES de qualquer git push.
Se falhar: NÃO faz push.
"""

import sys
import os

# Garante que o root do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_templates():
    """Verifica sintaxe Jinja2 em todos os templates (raiz e subpastas)."""
    from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

    templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    erros = []

    for dirpath, _, filenames in os.walk(templates_dir):
        for fname in filenames:
            if not fname.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), templates_dir)
            rel = rel.replace("\\", "/")
            try:
                src = open(os.path.join(dirpath, fname), encoding="utf-8").read()
                env.parse(src)
            except TemplateSyntaxError as e:
                erros.append(f"{rel} linha {e.lineno}: {e.message}")
            except Exception as e:
                erros.append(f"{rel}: {str(e)[:80]}")

    return erros


def check_imports():
    """Verifica se app.py importa sem erro."""
    try:
        import app  # noqa: F401
        return []
    except Exception as e:
        return [f"app.py: {str(e)[:100]}"]


def check_queries_criticas():
    """Testa queries críticas do dashboard."""
    from database import get_new_db_connection
    erros = []
    db = get_new_db_connection()

    queries = [
        ("empresas tenant",
         "SELECT COUNT(*) FROM empresas WHERE tenant_id = %s",
         (1,)),
        ("cadencias status",
         "SELECT COUNT(*) FROM cadencias WHERE status = %s AND tenant_id = %s",
         ("pendente", 1)),
        ("oportunidades etapa",
         "SELECT COUNT(*) FROM oportunidades WHERE etapa = %s AND tenant_id = %s",
         ("fechado_ganho", 1)),
        ("radar_alertas",
         "SELECT COUNT(*) FROM radar_alertas WHERE tenant_id = %s",
         (1,)),
    ]

    for nome, query, params in queries:
        try:
            db.execute(query, params)
        except Exception as e:
            erros.append(f"Query {nome}: {str(e)[:80]}")

    db.close()
    return erros


def check_colunas_criticas():
    """Verifica se colunas obrigatórias existem (SQLite-compatible)."""
    from database import get_new_db_connection, _USE_PG
    erros = []
    db = get_new_db_connection()

    colunas_obrigatorias = [
        ("empresas",      "tenant_id"),
        ("empresas",      "status"),
        ("empresas",      "temperatura"),
        ("cadencias",     "tenant_id"),
        ("oportunidades", "etapa"),
        ("oportunidades", "tenant_id"),
        ("prospeccao",    "tenant_id"),
        ("radar_alertas", "tenant_id"),
    ]

    for tabela, coluna in colunas_obrigatorias:
        try:
            if _USE_PG:
                result = db.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = %s",
                    (tabela, coluna)
                ).fetchone()[0]
                if result == 0:
                    erros.append(f"Coluna {tabela}.{coluna} nao existe")
            else:
                info = db.execute(f"PRAGMA table_info({tabela})").fetchall()
                cols = [r["name"] for r in info]
                if coluna not in cols:
                    erros.append(f"Coluna {tabela}.{coluna} nao existe")
        except Exception as e:
            erros.append(f"Verificacao {tabela}.{coluna}: {e}")

    db.close()
    return erros


if __name__ == "__main__":
    print("PRE-DEPLOY CHECK — Krylo CRM")
    print("=" * 50)

    todos_erros = []

    checks = [
        ("Templates Jinja2",   check_templates),
        ("Import app.py",      check_imports),
        ("Queries criticas",   check_queries_criticas),
        ("Colunas obrigatorias", check_colunas_criticas),
    ]

    for nome, check in checks:
        erros = check()
        if erros:
            print(f"FALHOU {nome}:")
            for e in erros:
                print(f"   {e}")
            todos_erros.extend(erros)
        else:
            print(f"OK {nome}")

    print("=" * 50)

    if todos_erros:
        print(f"FALHOU: {len(todos_erros)} problemas encontrados")
        print("NAO faca git push ate corrigir.")
        sys.exit(1)
    else:
        print("APROVADO: sistema pronto para deploy")
        sys.exit(0)
