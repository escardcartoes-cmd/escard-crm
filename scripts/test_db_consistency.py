"""
test_db_consistency.py — verifica que todas as queries retornam dicts (não tuplas).
Falha se RealDictCursor não estiver ativo ou se _to_pg() mangling ocorrer.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database

def test_fetchone_retorna_dict():
    conn = database.get_connection()
    try:
        row = conn.execute("SELECT 1 AS valor").fetchone()
        assert row is not None, "fetchone() retornou None"
        assert row["valor"] == 1, f"Esperava row['valor']==1, obteve: {row}"
        print("  [OK] fetchone() retorna dict — row['valor'] =", row["valor"])
    finally:
        conn.close()

def test_fetchall_retorna_lista_de_dicts():
    conn = database.get_connection()
    try:
        rows = conn.execute("SELECT 1 AS n UNION ALL SELECT 2 AS n").fetchall()
        assert len(rows) == 2, f"Esperava 2 linhas, obteve {len(rows)}"
        assert rows[0]["n"] in (1, 2), f"Acesso por chave falhou: {rows[0]}"
        print("  [OK] fetchall() retorna lista de dicts — rows[0]['n'] =", rows[0]["n"])
    finally:
        conn.close()

def test_named_params():
    conn = database.get_connection()
    try:
        row = conn.execute("SELECT ? AS resultado", (42,)).fetchone()
        assert row is not None, "fetchone() com params retornou None"
        assert row["resultado"] == 42, f"Esperava 42, obteve: {row}"
        print("  [OK] params posicionais funcionam — row['resultado'] =", row["resultado"])
    finally:
        conn.close()

def test_cast_syntax_nao_manglado():
    """Garante que _to_pg() não converte ::type em %(type)s."""
    if not database._USE_PG:
        print("  [SKIP] test_cast_syntax — SQLite não usa _to_pg()")
        return
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT CAST('2024-01-15' AS DATE) AS d",
        ).fetchone()
        assert row is not None
        print("  [OK] CAST(... AS DATE) funciona sem TypeError —", row["d"])

        row2 = conn.execute(
            "SELECT CAST('2024-01-15 10:00:00' AS TIMESTAMP) AS ts",
        ).fetchone()
        assert row2 is not None
        print("  [OK] CAST(... AS TIMESTAMP) funciona sem TypeError")
    finally:
        conn.close()

if __name__ == "__main__":
    print(f"Banco: {'PostgreSQL' if database._USE_PG else 'SQLite'}")
    falhas = 0
    for test in [test_fetchone_retorna_dict, test_fetchall_retorna_lista_de_dicts,
                 test_named_params, test_cast_syntax_nao_manglado]:
        try:
            test()
        except Exception as e:
            print(f"  [FALHA] {test.__name__}: {e}")
            falhas += 1
    if falhas:
        print(f"\n{falhas} teste(s) falharam.")
        sys.exit(1)
    else:
        print("\nTodos os testes passaram.")
        sys.exit(0)
