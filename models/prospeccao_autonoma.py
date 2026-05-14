"""
Prospecção Autônoma — motor SDR que roda em background via APScheduler.
Usa ramos_atividade do banco (se houver) ou REGRAS_POR_PRODUTO como fallback.
"""
from database import get_connection
from models.prospeccao_auto import buscar_e_salvar

# Fallback fixo — usado quando ramos_atividade está vazio
REGRAS_POR_PRODUTO = [
    {
        "produto": "Alimentação",
        "descricao": "Vale alimentação para empresas com muitos funcionários",
        "cnaes": ["4711302", "4712100", "4781400", "5611201"],
        "ufs": ["SP", "RJ", "MG"],
        "limite_por_uf": 10,
    },
    {
        "produto": "Refeição",
        "descricao": "Vale refeição para escritórios e indústrias",
        "cnaes": ["6202300", "6204000", "7490104", "6311900"],
        "ufs": ["SP", "MG"],
        "limite_por_uf": 10,
    },
    {
        "produto": "Combustível",
        "descricao": "Auxílio combustível para equipes externas",
        "cnaes": ["4120400", "4211101", "4930202", "5212500"],
        "ufs": ["ES", "RJ", "BA"],
        "limite_por_uf": 8,
    },
    {
        "produto": "Saúde",
        "descricao": "Benefícios saúde/bem-estar para colaboradores",
        "cnaes": ["8610101", "8621601", "8650001", "8640202"],
        "ufs": ["SP", "MG", "RJ"],
        "limite_por_uf": 8,
    },
    {
        "produto": "Educação",
        "descricao": "Bolsas e benefícios educacionais",
        "cnaes": ["8591100", "8599604", "8550301", "8541400"],
        "ufs": ["SP", "MG"],
        "limite_por_uf": 8,
    },
    {
        "produto": "RH",
        "descricao": "Empresas de RH e gestão de pessoas",
        "cnaes": ["7810800", "7820500", "7830200"],
        "ufs": ["SP", "RJ", "ES"],
        "limite_por_uf": 10,
    },
]


def _carregar_regras_do_banco() -> list:
    """
    Busca ramos ativos em ramos_atividade e converte para o mesmo formato
    de REGRAS_POR_PRODUTO. Retorna lista vazia se a tabela não existir.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM ramos_atividade WHERE ativo=1"
        ).fetchall()
        conn.close()
        regras = []
        for r in rows:
            cnaes  = [c.strip() for c in (r["cnaes"]   or "").split(",") if c.strip()]
            estados = [e.strip() for e in (r["estados"] or "").split(",") if e.strip()]
            if not cnaes or not estados:
                continue
            regras.append({
                "produto":       r["nome"],
                "descricao":     r["descricao"] or "",
                "cnaes":         cnaes,
                "ufs":           estados,
                "limite_por_uf": 10,
            })
        return regras
    except Exception:
        return []


def rodar_prospeccao_autonoma() -> dict:
    """
    Executa a prospecção autônoma.
    Usa ramos_atividade do banco se disponíveis; caso contrário usa REGRAS_POR_PRODUTO.
    Retorna resumo com totais.
    """
    regras_banco = _carregar_regras_do_banco()
    regras = regras_banco if regras_banco else REGRAS_POR_PRODUTO

    total_encontrados = 0
    total_salvos      = 0
    total_duplicados  = 0
    erros = []

    for regra in regras:
        for uf in regra["ufs"]:
            try:
                resultado = buscar_e_salvar(
                    uf=uf,
                    cnaes=regra["cnaes"],
                    limite=regra["limite_por_uf"],
                )
                total_encontrados += resultado.get("encontrados", 0)
                total_salvos      += resultado.get("salvos", 0)
                total_duplicados  += resultado.get("duplicados", 0)
            except Exception as e:
                erros.append(f"{regra['produto']}/{uf}: {e}")

    return {
        "encontrados":       total_encontrados,
        "salvos":            total_salvos,
        "duplicados":        total_duplicados,
        "regras_executadas": len(regras),
        "fonte":             "banco" if regras_banco else "fallback",
        "erros":             erros,
    }


def status_resumo() -> dict:
    """Retorna estatísticas atuais da tabela prospeccao_automatica."""
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='novo'       THEN 1 ELSE 0 END) AS novos,
            SUM(CASE WHEN status='importado'  THEN 1 ELSE 0 END) AS importados,
            MAX(importado_em) AS ultima_execucao
        FROM prospeccao_automatica
    """).fetchone()
    conn.close()
    if not row:
        return {"total": 0, "novos": 0, "importados": 0, "ultima_execucao": None}
    return dict(row)
