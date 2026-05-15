import json
import requests
import database

_IBGE_URL = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
_CACHE_TTL_SECONDS = 86400 * 7  # 7 days


def _get_from_db():
    try:
        conn = database.get_connection()
        row = conn.execute(
            "SELECT dados, atualizado_em FROM cnae_cache WHERE id=1"
        ).fetchone()
        conn.close()
        if not row:
            return None, None
        return row["dados"], row["atualizado_em"]
    except Exception:
        return None, None


def _salvar_no_db(dados_json: str):
    import datetime as _dt
    try:
        conn = database.get_connection()
        now = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "INSERT OR REPLACE INTO cnae_cache (id, dados, atualizado_em) VALUES (1, ?, ?)",
            (dados_json, now),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"cnae_cache salvar erro: {e}")


def _cache_fresco(ts: str) -> bool:
    import datetime as _dt
    if not ts:
        return False
    try:
        salvo = _dt.datetime.fromisoformat(str(ts))
        return (_dt.datetime.now() - salvo).total_seconds() < _CACHE_TTL_SECONDS
    except Exception:
        return False


def carregar_todos_cnaes() -> dict:
    """Returns dict keyed by divisão code (first 2 digits), fetched from IBGE API with DB cache."""
    dados_str, ts = _get_from_db()
    if dados_str and _cache_fresco(ts):
        try:
            return json.loads(dados_str)
        except Exception:
            pass

    try:
        r = requests.get(
            _IBGE_URL, timeout=15, headers={"User-Agent": "KryloCRM/1.0"}
        )
        r.raise_for_status()
        subclasses = r.json()
    except Exception as e:
        print(f"IBGE CNAE fetch erro: {e}")
        if dados_str:
            try:
                return json.loads(dados_str)
            except Exception:
                pass
        return {}

    por_divisao: dict = {}
    for sub in subclasses:
        cod = str(sub.get("id", "")).strip()
        if not cod or len(cod) < 2:
            continue
        div_cod = cod[:2]
        try:
            div_nome = sub["classe"]["grupo"]["divisao"]["descricao"]
        except (KeyError, TypeError):
            div_nome = f"Divisão {div_cod}"

        if div_cod not in por_divisao:
            por_divisao[div_cod] = {"nome": div_nome, "itens": []}
        por_divisao[div_cod]["itens"].append(
            {"id": cod, "descricao": sub.get("descricao", "")}
        )

    resultado = dict(sorted(por_divisao.items()))
    _salvar_no_db(json.dumps(resultado, ensure_ascii=False))
    return resultado


def buscar_cnaes(q: str) -> list:
    """Search CNAEs by description or code, returns up to 50 matches."""
    todos = carregar_todos_cnaes()
    q = q.lower().strip()
    resultado = []
    for div_cod, div in todos.items():
        for item in div["itens"]:
            if q in item["descricao"].lower() or q in item["id"]:
                resultado.append(
                    {
                        "id": item["id"],
                        "descricao": item["descricao"],
                        "divisao": div["nome"],
                    }
                )
    return resultado[:50]
