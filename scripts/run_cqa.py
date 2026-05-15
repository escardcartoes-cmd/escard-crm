"""Runner principal do CQA — executa testes, aplica fixes e salva resultados."""
import sys
import os
from datetime import datetime

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import database


def salvar_resultado(resultados_testes, resultados_fixes):
    try:
        conn = database.get_connection()
        agora = datetime.now().isoformat(sep=" ", timespec="seconds")
        for r in resultados_testes:
            auto_corrigido = 0
            if r["status"] != "ok":
                chave = r["check_nome"].replace("_", "")
                for fix in resultados_fixes:
                    if chave in fix["fix_nome"].replace("_", "") and fix["corrigido"]:
                        auto_corrigido = 1
                        break
            try:
                conn.execute(
                    "INSERT INTO cqa_resultados (check_nome, status, mensagem, auto_corrigido, executado_em)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (r["check_nome"], r["status"], (r["mensagem"] or "")[:500], auto_corrigido, agora),
                )
            except Exception as e:
                print(f"[CQA] Aviso ao salvar resultado {r['check_nome']}: {e}")
                try: conn.rollback()
                except Exception: pass
        try:
            conn.commit()
        except Exception: pass
        for r in resultados_testes:
            if r["status"] in ("erro", "aviso"):
                try:
                    conn.execute(
                        "INSERT INTO cqa_alertas (tipo, check_nome, mensagem, resolvido, criado_em)"
                        " VALUES (?, ?, ?, 0, ?)",
                        (r["status"], r["check_nome"], (r["mensagem"] or "")[:500], agora),
                    )
                except Exception as e:
                    print(f"[CQA] Aviso ao salvar alerta: {e}")
                    try: conn.rollback()
                    except Exception: pass
        try:
            conn.commit()
        except Exception: pass
        conn.close()
        print("[CQA] Resultados salvos no banco")
    except Exception as e:
        print(f"[CQA] Aviso ao salvar resultados: {e}")


def rodar_cqa_completo(aplicar_fixes=True, verbose=True):
    inicio = datetime.now()
    # Ensure DB tables exist (idempotent)
    try:
        database.init_db()
    except Exception as _e:
        if verbose:
            print(f"[CQA] init_db aviso: {_e}")

    if verbose:
        print("=" * 52)
        print("[CQA] Central de Qualidade Automatica")
        print(f"   Inicio: {inicio.strftime('%d/%m/%Y %H:%M:%S')}")
        print("=" * 52)

    from scripts.mapear_sistema import gerar_mapa_completo
    from scripts.cqa_testes import rodar_todos_os_testes
    from scripts.cqa_autofix import rodar_todos_os_fixes

    if verbose:
        print("\n[1/3] Mapeando sistema...")
    try:
        mapa = gerar_mapa_completo()
    except Exception as e:
        print(f"[MAPA] Erro (não crítico): {e}")
        mapa = {}

    if verbose:
        print("\n[2/3] Executando testes...")
    resultados_testes = rodar_todos_os_testes()

    resultados_fixes = []
    if aplicar_fixes:
        if verbose:
            print("\n[3/3] Aplicando auto-fixes...")
        resultados_fixes = rodar_todos_os_fixes()

    salvar_resultado(resultados_testes, resultados_fixes)

    erros  = sum(1 for r in resultados_testes if r["status"] == "erro")
    avisos = sum(1 for r in resultados_testes if r["status"] == "aviso")
    oks    = sum(1 for r in resultados_testes if r["status"] == "ok")
    duracao = (datetime.now() - inicio).total_seconds()

    if verbose:
        print(f"\n{'=' * 52}")
        print(f"[CQA] Concluido em {duracao:.1f}s")
        print(f"   Resultado: {oks} OK / {avisos} avisos / {erros} erros")
        print("=" * 52)

    return {
        "mapa": mapa,
        "testes": resultados_testes,
        "fixes": resultados_fixes,
        "resumo": {"oks": oks, "avisos": avisos, "erros": erros},
        "duracao": duracao,
    }


if __name__ == "__main__":
    resultado = rodar_cqa_completo(aplicar_fixes=True)
    sys.exit(0 if resultado["resumo"]["erros"] == 0 else 1)
