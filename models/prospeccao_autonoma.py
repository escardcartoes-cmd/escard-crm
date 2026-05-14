"""
Prospecção Autônoma — motor SDR que roda em background via APScheduler.
Usa ramos_atividade do banco (se houver) ou REGRAS_POR_PRODUTO como fallback.
Respeita sdr_config: ativo, horário, intervalo, max_leads_por_execucao.
"""
from database import get_connection
from models.prospeccao_auto import buscar_e_salvar

_SDR_DEFAULTS = {
    "nome_campanha":              "Campanha Principal",
    "ativo":                      1,
    "rodar_continuo":             1,
    "intervalo_horas":            6,
    "estados":                    "ES,SP",
    "cidades":                    "",
    "cnaes":                      "",
    "funcionarios_min":           10,
    "funcionarios_max":           5000,
    "capital_social_min":         50000,
    "tipo_empresa":               "MATRIZ",
    "idade_empresa_min":          0,
    "idade_empresa_max":          50,
    "tem_email":                  0,
    "tem_telefone":               1,
    "situacao_cadastral":         "ATIVA",
    "score_minimo":               6,
    "max_tentativas_por_empresa": 3,
    "dias_recontato":             30,
    "excluir_ja_prospectados":    1,
    "canal_primario":             "whatsapp",
    "canal_secundario":           "email",
    "horario_inicio":             8,
    "horario_fim":                18,
    "dias_semana":                "seg,ter,qua,qui,sex",
    "max_leads_por_execucao":     20,
    "max_cadencias_por_dia":      50,
    "produto_foco":               "todos",
}


def get_sdr_config(db) -> dict:
    """Retorna configuração do SDR do banco, merged com defaults."""
    try:
        row = db.execute("SELECT * FROM sdr_config WHERE id=1").fetchone()
        if row:
            return {**_SDR_DEFAULTS, **{k: v for k, v in dict(row).items() if v is not None}}
    except Exception:
        pass
    return dict(_SDR_DEFAULTS)

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
    Lê sdr_config: verifica ativo, respeita horário, usa max_leads_por_execucao.
    Registra resultado em sdr_execucoes.
    """
    from datetime import datetime

    # Lê configuração do SDR
    try:
        _conn_cfg = get_connection()
        cfg = get_sdr_config(_conn_cfg)
        _conn_cfg.close()
    except Exception:
        cfg = dict(_SDR_DEFAULTS)

    # Checa se está ativo
    if not cfg.get("ativo", 1):
        return {"encontrados": 0, "salvos": 0, "duplicados": 0, "motivo": "SDR pausado"}

    # Respeita horário de operação
    hora_atual = datetime.now().hour
    h_ini = int(cfg.get("horario_inicio") or 8)
    h_fim = int(cfg.get("horario_fim") or 18)
    if hora_atual < h_ini or hora_atual >= h_fim:
        return {"encontrados": 0, "salvos": 0, "duplicados": 0,
                "motivo": f"Fora do horário ({hora_atual}h, janela {h_ini}h-{h_fim}h)"}

    # Determina regras de busca
    regras_banco = _carregar_regras_do_banco()
    regras = regras_banco if regras_banco else REGRAS_POR_PRODUTO

    # Estados do sdr_config têm prioridade sobre regras de ramos
    estados_cfg = [e.strip() for e in (cfg.get("estados") or "").split(",") if e.strip()]
    max_leads = int(cfg.get("max_leads_por_execucao") or 20)

    total_encontrados = 0
    total_salvos      = 0
    total_duplicados  = 0
    erros = []

    for regra in regras:
        ufs = estados_cfg if estados_cfg else regra["ufs"]
        limite_por_uf = max(1, max_leads // max(len(ufs), 1))
        for uf in ufs:
            try:
                resultado = buscar_e_salvar(
                    uf=uf,
                    cnaes=regra["cnaes"],
                    limite=limite_por_uf,
                )
                total_encontrados += resultado.get("encontrados", 0)
                total_salvos      += resultado.get("salvos", 0)
                total_duplicados  += resultado.get("duplicados", 0)
            except Exception as e:
                erros.append(f"{regra['produto']}/{uf}: {e}")

    # Registra execução em sdr_execucoes
    try:
        _conn_log = get_connection()
        _conn_log.execute(
            "INSERT INTO sdr_execucoes (encontrados, salvos, cadencias, descartados, log) VALUES (?, ?, ?, ?, ?)",
            (total_encontrados, total_salvos, 0, 0, "; ".join(erros) if erros else "OK"),
        )
        _conn_log.commit()
        _conn_log.close()
    except Exception:
        pass

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
