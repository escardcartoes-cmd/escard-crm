"""Auto-fix para problemas detectados pelo CQA."""
import sys
import os
import re

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import database


def _r(nome, corrigido, mensagem):
    return {"fix_nome": nome, "corrigido": corrigido, "mensagem": mensagem}


def fix_encoding_templates():
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
                except Exception:
                    pass
        if problemas:
            return _r("fix_encoding_templates", False,
                      f"Encoding corrompido (edição manual necessária): {problemas}")
        return _r("fix_encoding_templates", True, "Nenhum template com encoding corrompido")
    except Exception as e:
        return _r("fix_encoding_templates", False, f"Erro: {e}")


def fix_encoding_banco():
    if not database._USE_PG:
        return _r("fix_encoding_banco", True, "SQLite local — fix de encoding não necessário")
    try:
        conn = database.get_connection()
        cols = [
            ("prospeccao_automatica", "municipio"),
            ("prospeccao_automatica", "razao_social"),
            ("empresas", "cidade"),
            ("empresas", "nome"),
        ]
        corrigidos = 0
        for tabela, col in cols:
            try:
                conn.execute(
                    f"UPDATE {tabela} SET {col} = "
                    f"convert_from(convert_to({col}, 'LATIN1'), 'UTF8') "
                    f"WHERE {col} IS NOT NULL AND {col} ~ '[ÃÂ]'"
                )
                conn.commit()
                corrigidos += 1
            except Exception:
                try: conn.rollback()
                except Exception: pass
        conn.close()
        return _r("fix_encoding_banco", True, f"Encoding verificado em {corrigidos} colunas")
    except Exception as e:
        return _r("fix_encoding_banco", False, f"Erro: {e}")


def fix_cadencias_travadas():
    try:
        conn = database.get_connection()
        if database._USE_PG:
            conn.execute(
                "UPDATE cadencias SET status='cancelado' "
                "WHERE status='pendente' AND data_acao < (NOW() - INTERVAL '30 days')::TEXT"
            )
        else:
            conn.execute(
                "UPDATE cadencias SET status='cancelado' "
                "WHERE status='pendente' AND data_acao < date('now','-30 days')"
            )
        conn.commit()
        conn.close()
        return _r("fix_cadencias_travadas", True, "Cadências antigas canceladas")
    except Exception as e:
        return _r("fix_cadencias_travadas", False, f"Erro: {e}")


def fix_migrations():
    try:
        conn = database.get_connection()
        database.run_migrations(conn)
        conn.close()
        return _r("fix_migrations", True, "Migrations re-executadas com sucesso")
    except Exception as e:
        return _r("fix_migrations", False, f"Erro: {e}")


def rodar_todos_os_fixes():
    fixes = [fix_encoding_templates, fix_encoding_banco, fix_cadencias_travadas, fix_migrations]
    resultados = []
    for fix in fixes:
        try:
            res = fix()
            resultados.append(res)
            emoji = "OK" if res["corrigido"] else "ER"
            print(f"  [{emoji}] {res['fix_nome']}: {res['mensagem']}")
        except Exception as e:
            resultados.append({"fix_nome": fix.__name__, "corrigido": False, "mensagem": f"Exceção: {e}"})
            print(f"  [ER] {fix.__name__}: Excecao: {e}")
    return resultados


if __name__ == "__main__":
    print("=== CQA Auto-Fix ===")
    rodar_todos_os_fixes()
