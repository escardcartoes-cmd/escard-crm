import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from database import get_connection

_HEADERS = {"User-Agent": "KryloCRM/1.0 prospeccao-auto"}

# National seed list — BrasilAPI validates which CNPJs exist
# Covers banks, tech, retail, industry, health across Brazil
_ALL_SEEDS = [
    "00000000000191", "00360305000104",  # BB, Caixa (DF)
    "60746948000112", "60701190000104", "90400888000142",  # Bradesco, Itaú, Santander (SP)
    "53113791000122", "07526557000100", "18236120000158",  # TOTVS, CI&T, Nubank (SP)
    "16501555000157", "02558157000162", "03235054000100",  # Stone, outros (SP)
    "47960950000121", "61585865000151", "00776574000156",  # MagLu, RaiaDrogasil, Americanas (SP)
    "33000167000101", "33592510000154",                    # Petrobras (RJ), Vale (RJ/ES)
    "02916265000160", "07689002000189",                    # JBS, Embraer (SP)
    "92690289000189", "84429695000111", "75573544000107",  # Gerdau(RS), WEG(SC), Boticário(PR)
    "63554067000198",                                      # Hapvida (CE)
    "12665453000129", "34274233000102", "09658168000149",
    "04070836000136", "06109205000173", "28127603000178",
    "31511283000105", "15394348000154", "05634086000149",
    "10462958000154", "05315333000193", "25448534000186",
    "67620028000138", "61472676000132", "02808708000107",
]

# Human-readable labels for CNAEs offered in the UI
CNAES_DISPONIVEIS = [
    {"code": "7810800",  "label": "Agências de RH"},
    {"code": "6202300",  "label": "Desenvolvimento de software"},
    {"code": "4120400",  "label": "Construção civil"},
    {"code": "4711302",  "label": "Comércio varejista grande porte"},
    {"code": "8610101",  "label": "Serviços de saúde"},
    {"code": "8599604",  "label": "Educação corporativa"},
    {"code": "3290200",  "label": "Indústria geral"},
]

UFS_DISPONIVEIS = ["ES", "SP", "MG", "RJ", "BA"]


# ── API callers ───────────────────────────────────────────────────────────────

def _buscar_brasil_api(cnpj: str) -> dict | None:
    try:
        r = requests.get(
            f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
            headers=_HEADERS, timeout=8
        )
        if r.status_code == 200:
            return {"source": "brasilapi", "data": r.json()}
    except Exception:
        pass
    return None


def _buscar_cnpj_ws(cnpj: str) -> dict | None:
    try:
        r = requests.get(
            f"https://publica.cnpj.ws/cnpj/{cnpj}",
            headers=_HEADERS, timeout=8
        )
        if r.status_code == 200:
            return {"source": "cnpj_ws", "data": r.json()}
    except Exception:
        pass
    return None


def _fetch_one(cnpj: str) -> dict | None:
    result = _buscar_brasil_api(cnpj)
    if result:
        return _normalizar(result)
    result = _buscar_cnpj_ws(cnpj)
    if result:
        return _normalizar(result)
    return None


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalizar(envelope: dict) -> dict | None:
    source = envelope["source"]
    data = envelope["data"]
    try:
        if source == "brasilapi":
            return _norm_brasilapi(data)
        return _norm_cnpj_ws(data)
    except Exception:
        return None


def _norm_brasilapi(d: dict) -> dict:
    situacao = (d.get("descricao_situacao_cadastral") or
                d.get("situacao_cadastral") or "").upper()
    capital = 0.0
    try:
        capital = float(d.get("capital_social") or 0)
    except (ValueError, TypeError):
        pass
    cnae = str(d.get("cnae_fiscal") or "").replace(".", "").replace("-", "")
    tel = (d.get("ddd_telefone_1") or "").replace(" ", "").replace("-", "")
    email = (d.get("email") or "").strip().lower()
    is_matriz = d.get("identificador_matriz_filial") == 1
    cnpj = (d.get("cnpj") or "").replace(".", "").replace("/", "").replace("-", "")
    return {
        "cnpj": cnpj,
        "razao_social": (d.get("razao_social") or "").strip(),
        "municipio": (d.get("municipio") or "").strip(),
        "uf": (d.get("uf") or "").upper(),
        "cnae_codigo": cnae,
        "cnae_descricao": (d.get("cnae_fiscal_descricao") or "").strip(),
        "telefone": tel or None,
        "email": email or None,
        "capital_social": capital,
        "situacao": situacao,
        "is_matriz": is_matriz,
    }


def _norm_cnpj_ws(d: dict) -> dict:
    situacao = (d.get("situacao", {}).get("id") or "").upper()
    if not situacao:
        situacao = (d.get("situacao") or "").upper()
    capital = 0.0
    try:
        capital = float(d.get("capital_social") or 0)
    except (ValueError, TypeError):
        pass
    atividade = (d.get("atividade_principal") or [{}])
    if isinstance(atividade, dict):
        atividade = [atividade]
    cnae = str((atividade[0] if atividade else {}).get("id") or "").replace(".", "").replace("-", "")
    cnae_desc = ((atividade[0] if atividade else {}).get("descricao") or "").strip()
    tel = (d.get("telefone_1") or d.get("telefone") or "").replace(" ", "").replace("-", "")
    email = (d.get("email") or "").strip().lower()
    endereco = d.get("endereco") or {}
    if isinstance(endereco, dict):
        municipio = endereco.get("municipio") or ""
        uf = (endereco.get("uf") or endereco.get("estado") or "").upper()
    else:
        municipio = ""
        uf = ""
    cnpj_raw = d.get("cnpj") or d.get("ni") or ""
    cnpj = cnpj_raw.replace(".", "").replace("/", "").replace("-", "")
    is_matriz = str(d.get("natureza_juridica", {}).get("id") or "").startswith("1") if isinstance(d.get("natureza_juridica"), dict) else False
    return {
        "cnpj": cnpj,
        "razao_social": (d.get("razao_social") or d.get("nome") or "").strip(),
        "municipio": municipio,
        "uf": uf,
        "cnae_codigo": cnae,
        "cnae_descricao": cnae_desc,
        "telefone": tel or None,
        "email": email or None,
        "capital_social": capital,
        "situacao": situacao,
        "is_matriz": is_matriz,
    }


# ── Score ─────────────────────────────────────────────────────────────────────

def _calcular_score(emp: dict) -> int:
    score = 0
    cap = float(emp.get("capital_social") or 0)
    if cap > 5_000_000:
        score += 4
    elif cap > 500_000:
        score += 3
    elif cap > 100_000:
        score += 2
    if emp.get("telefone"):
        score += 2
    if emp.get("email"):
        score += 2
    if emp.get("is_matriz"):
        score += 2
    return min(score, 10)


# ── Dedup ─────────────────────────────────────────────────────────────────────

def _ja_existe(cnpj: str, conn) -> bool:
    if conn.execute(
        "SELECT id FROM prospeccao_automatica WHERE cnpj = ?", (cnpj,)
    ).fetchone():
        return True
    return bool(conn.execute(
        "SELECT id FROM empresas WHERE cnpj = ?", (cnpj,)
    ).fetchone())


# ── Main search ───────────────────────────────────────────────────────────────

def buscar_e_salvar(uf: str, cnaes: list, limite: int = 30) -> dict:
    cnaes_norm = {str(c).replace(".", "").replace("-", "") for c in cnaes}

    # Fetch all seeds concurrently
    resultados = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_one, cnpj): cnpj for cnpj in _ALL_SEEDS}
        for future in as_completed(futures):
            emp = future.result()
            if emp:
                resultados.append(emp)

    # Filter and save (sequential — thread-safe DB access)
    encontrados = 0
    salvos = 0
    duplicados = 0
    conn = get_connection()

    # Sort by capital_social desc so we save the best leads first
    resultados.sort(key=lambda e: float(e.get("capital_social") or 0), reverse=True)

    for emp in resultados:
        if salvos + duplicados >= limite:
            break

        # Filters: active + capital > 50k
        if "ATIVA" not in (emp.get("situacao") or ""):
            continue
        if float(emp.get("capital_social") or 0) <= 50_000:
            continue

        # CNAE filter: match requested codes or 4-digit sector prefix
        if cnaes_norm:
            emp_cnae = emp.get("cnae_codigo") or ""
            exact = emp_cnae in cnaes_norm
            sector = any(emp_cnae[:4] == c[:4] for c in cnaes_norm if len(c) >= 4)
            if not exact and not sector:
                continue

        encontrados += 1
        cnpj_final = emp.get("cnpj") or ""
        if not cnpj_final:
            continue

        if _ja_existe(cnpj_final, conn):
            duplicados += 1
            continue

        score = _calcular_score(emp)
        conn.execute(
            """INSERT INTO prospeccao_automatica
               (cnpj, razao_social, municipio, uf, cnae_descricao,
                telefone, email, capital_social, score_fit, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'novo')""",
            (
                cnpj_final,
                emp.get("razao_social") or "",
                emp.get("municipio") or "",
                emp.get("uf") or uf.upper(),
                emp.get("cnae_descricao") or "",
                emp.get("telefone"),
                emp.get("email"),
                float(emp.get("capital_social") or 0),
                score,
            ),
        )
        conn.commit()
        salvos += 1

    conn.close()
    return {"encontrados": encontrados, "salvos": salvos, "duplicados": duplicados}


# ── Queries ───────────────────────────────────────────────────────────────────

def listar(uf=None, score_min=None, status=None) -> list:
    conn = get_connection()
    sql = "SELECT * FROM prospeccao_automatica WHERE 1=1"
    params = []
    if uf:
        sql += " AND uf = ?"
        params.append(uf.upper())
    if score_min is not None:
        sql += " AND score_fit >= ?"
        params.append(int(score_min))
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY score_fit DESC, importado_em DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def importar(id_: int) -> int:
    import models.empresa as emp_model
    conn = get_connection()
    row = conn.execute("SELECT * FROM prospeccao_automatica WHERE id = ?", (id_,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("Lead não encontrado")
    r = dict(row)
    emp_id = emp_model.criar({
        "nome": r.get("razao_social") or "Empresa",
        "cnpj": r.get("cnpj"),
        "segmento": r.get("cnae_descricao") or None,
        "porte": None,
        "status": "prospect",
        "telefone": r.get("telefone") or None,
        "email": r.get("email") or None,
        "cidade": r.get("municipio") or None,
        "estado": r.get("uf") or None,
        "produtos_ativos": None,
        "num_funcionarios": None,
        "cliente_ativo": 0,
        "valor_mensal": None,
        "tipo_cartao": None,
        "nome_private_label": None,
    })
    conn2 = get_connection()
    conn2.execute("UPDATE prospeccao_automatica SET status='importado' WHERE id=?", (id_,))
    conn2.commit()
    conn2.close()
    return emp_id


def importar_varios(ids: list) -> int:
    ok = 0
    for id_ in ids:
        try:
            importar(int(id_))
            ok += 1
        except Exception:
            pass
    return ok


def atualizar_status(id_: int, status: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE prospeccao_automatica SET status=? WHERE id=?", (status, id_))
    conn.commit()
    conn.close()


def resumo_dashboard() -> dict:
    conn = get_connection()
    hoje = str(date.today())
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM prospeccao_automatica WHERE status='novo' AND importado_em LIKE ?",
        (hoje + "%",)
    ).fetchone()
    novos_hoje = int((row["cnt"] if row else 0) or 0)
    row2 = conn.execute(
        "SELECT COUNT(*) AS cnt FROM prospeccao_automatica WHERE status='novo' AND score_fit >= 7"
    ).fetchone()
    prontos = int((row2["cnt"] if row2 else 0) or 0)
    conn.close()
    return {"novos_hoje": novos_hoje, "prontos": prontos}
