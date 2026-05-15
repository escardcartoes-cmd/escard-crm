"""Mapeia rotas, templates, modelos e tabelas do sistema Krylo CRM."""
import sys
import os
import json
import re

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import database


def mapear_rotas():
    app_path = os.path.join(_root, "app.py")
    rotas = []
    try:
        with open(app_path, encoding="utf-8") as f:
            content = f.read()
        pattern = r'@app\.route\(["\']([^"\']+)["\'](?:,\s*methods=\[([^\]]+)\])?\)'
        for m in re.finditer(pattern, content):
            path = m.group(1)
            methods_raw = m.group(2) or '"GET"'
            methods = re.findall(r'"([^"]+)"|\'([^\']+)\'', methods_raw)
            methods = [mx[0] or mx[1] for mx in methods] or ["GET"]
            rotas.append({"path": path, "methods": methods})
    except Exception as e:
        print(f"[MAPA] Erro ao mapear rotas: {e}")
    return rotas


def mapear_templates():
    templates_dir = os.path.join(_root, "templates")
    templates = []
    try:
        for dirpath, _, files in os.walk(templates_dir):
            for f in files:
                if f.endswith(".html"):
                    rel = os.path.relpath(os.path.join(dirpath, f), templates_dir)
                    templates.append(rel.replace("\\", "/"))
    except Exception as e:
        print(f"[MAPA] Erro ao mapear templates: {e}")
    return sorted(templates)


def mapear_modelos():
    models_dir = os.path.join(_root, "models")
    modelos = []
    try:
        for f in os.listdir(models_dir):
            if f.endswith(".py") and not f.startswith("__"):
                modelos.append(f[:-3])
    except Exception as e:
        print(f"[MAPA] Erro ao mapear modelos: {e}")
    return sorted(modelos)


def mapear_tabelas():
    tabelas = []
    try:
        conn = database.get_connection()
        if database._USE_PG:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            ).fetchall()
            tabelas = [r["table_name"] for r in rows]
        else:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            tabelas = [r["name"] for r in rows]
        conn.close()
    except Exception as e:
        print(f"[MAPA] Erro ao mapear tabelas: {e}")
    return tabelas


def gerar_mapa_completo():
    mapa = {
        "rotas": mapear_rotas(),
        "templates": mapear_templates(),
        "modelos": mapear_modelos(),
        "tabelas": mapear_tabelas(),
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapa_sistema.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=2)
    print(f"[MAPA] Rotas: {len(mapa['rotas'])}, Templates: {len(mapa['templates'])}, "
          f"Modelos: {len(mapa['modelos'])}, Tabelas: {len(mapa['tabelas'])}")
    return mapa


if __name__ == "__main__":
    gerar_mapa_completo()
