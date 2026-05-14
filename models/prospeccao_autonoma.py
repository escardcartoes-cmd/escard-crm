"""
Prospecção Autônoma — motor SDR completo com scoring avançado, filtros,
pitch por IA e criação automática de cadências.
Usa ramos_atividade do banco (se houver) ou REGRAS_POR_PRODUTO como fallback.
Respeita sdr_config: ativo, horário, filtros, score mínimo, limites.
"""
import requests
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_connection

_HEADERS = {"User-Agent": "KryloCRM/1.0 SDR-autonomo"}

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


REGRAS_POR_PRODUTO = [
    {
        "produto": "VR",
        "descricao": "Vale refeição para escritórios e indústrias",
        "cnaes": ["6202300", "6204000", "7490104", "6311900"],
        "ufs": ["SP", "MG"],
    },
    {
        "produto": "VA",
        "descricao": "Vale alimentação para empresas com muitos funcionários",
        "cnaes": ["4711302", "4712100", "4781400", "5611201"],
        "ufs": ["SP", "RJ", "MG"],
    },
    {
        "produto": "Combustível",
        "descricao": "Auxílio combustível para equipes externas",
        "cnaes": ["4120400", "4211101", "4930202", "5212500"],
        "ufs": ["ES", "RJ", "BA"],
    },
    {
        "produto": "Saúde",
        "descricao": "Benefícios saúde/bem-estar para colaboradores",
        "cnaes": ["8610101", "8621601", "8650001", "8640202"],
        "ufs": ["SP", "MG", "RJ"],
    },
    {
        "produto": "Cobrança",
        "descricao": "Empresas com carteira de inadimplentes",
        "cnaes": ["6491300", "6492100", "7020400"],
        "ufs": ["ES", "SP", "MG", "RJ"],
    },
    {
        "produto": "RH",
        "descricao": "Empresas de RH e gestão de pessoas",
        "cnaes": ["7810800", "7820500", "7830200"],
        "ufs": ["SP", "RJ", "ES"],
    },
]


def _carregar_regras_do_banco() -> list:
    try:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM ramos_atividade WHERE ativo=1").fetchall()
        conn.close()
        regras = []
        for r in rows:
            cnaes   = [c.strip() for c in (r["cnaes"]   or "").split(",") if c.strip()]
            estados = [e.strip() for e in (r["estados"] or "").split(",") if e.strip()]
            if not cnaes or not estados:
                continue
            regras.append({
                "produto": r["nome"],
                "descricao": r["descricao"] or "",
                "cnaes": cnaes,
                "ufs": estados,
            })
        return regras
    except Exception:
        return []


# ── BrasilAPI lookup ──────────────────────────────────────────────────────────

def _fetch_brasilapi(cnpj: str) -> dict | None:
    try:
        r = requests.get(
            f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
            headers=_HEADERS, timeout=8,
        )
        if r.status_code == 200:
            return ("brasilapi", r.json())
    except Exception:
        pass
    return None


def _fetch_cnpjws(cnpj: str) -> dict | None:
    try:
        r = requests.get(
            f"https://publica.cnpj.ws/cnpj/{cnpj}",
            headers=_HEADERS, timeout=8,
        )
        if r.status_code == 200:
            return ("cnpjws", r.json())
    except Exception:
        pass
    return None


def _normalizar_brasilapi(d: dict) -> dict:
    cap = 0.0
    try:
        cap = float(d.get("capital_social") or 0)
    except Exception:
        pass
    cnae = str(d.get("cnae_fiscal") or "").replace(".", "").replace("-", "")
    tel = (d.get("ddd_telefone_1") or "").replace(" ", "").replace("-", "")
    nat = d.get("natureza_juridica") or ""
    if isinstance(nat, dict):
        nat = nat.get("descricao") or ""
    return {
        "cnpj":               (d.get("cnpj") or "").replace(".", "").replace("/", "").replace("-", ""),
        "razao_social":       (d.get("razao_social") or "").strip(),
        "municipio":          (d.get("municipio") or "").strip(),
        "uf":                 (d.get("uf") or "").upper(),
        "cnae_codigo":        cnae,
        "cnae_descricao":     (d.get("cnae_fiscal_descricao") or "").strip(),
        "telefone":           tel or None,
        "email":              (d.get("email") or "").strip().lower() or None,
        "capital_social":     cap,
        "situacao":           (d.get("descricao_situacao_cadastral") or d.get("situacao_cadastral") or "").upper(),
        "is_matriz":          d.get("identificador_matriz_filial") == 1,
        "data_inicio_atividade": d.get("data_inicio_atividade") or d.get("data_abertura") or "",
        "natureza_juridica":  str(nat).strip(),
        "porte":              (d.get("porte") or "").strip(),
        "fonte":              "brasilapi",
    }


def _normalizar_cnpjws(d: dict) -> dict:
    cap = 0.0
    try:
        cap = float(d.get("capital_social") or 0)
    except Exception:
        pass
    atividade = d.get("atividade_principal") or [{}]
    if isinstance(atividade, dict):
        atividade = [atividade]
    cnae_obj  = atividade[0] if atividade else {}
    cnae      = str(cnae_obj.get("id") or "").replace(".", "").replace("-", "")
    cnae_desc = (cnae_obj.get("descricao") or "").strip()
    tel       = (d.get("telefone_1") or d.get("telefone") or "").replace(" ", "").replace("-", "")
    endereco  = d.get("endereco") or {}
    municipio = ""
    uf        = ""
    if isinstance(endereco, dict):
        municipio = endereco.get("municipio") or ""
        uf        = (endereco.get("uf") or endereco.get("estado") or "").upper()
    nat = d.get("natureza_juridica") or ""
    if isinstance(nat, dict):
        nat = nat.get("descricao") or ""
    porte = d.get("porte") or ""
    if isinstance(porte, dict):
        porte = porte.get("descricao") or ""
    cnpj_raw = (d.get("cnpj") or d.get("ni") or "").replace(".", "").replace("/", "").replace("-", "")
    return {
        "cnpj":               cnpj_raw,
        "razao_social":       (d.get("razao_social") or d.get("nome") or "").strip(),
        "municipio":          municipio,
        "uf":                 uf,
        "cnae_codigo":        cnae,
        "cnae_descricao":     cnae_desc,
        "telefone":           tel or None,
        "email":              (d.get("email") or "").strip().lower() or None,
        "capital_social":     cap,
        "situacao":           str((d.get("situacao") or {}).get("id") if isinstance(d.get("situacao"), dict) else (d.get("situacao") or "")).upper(),
        "is_matriz":          False,
        "data_inicio_atividade": d.get("data_abertura") or "",
        "natureza_juridica":  str(nat).strip(),
        "porte":              str(porte).strip(),
        "fonte":              "cnpjws",
    }


def buscar_por_cnpj_especifico(cnpj: str) -> dict | None:
    """Busca dados completos via BrasilAPI com fallback ReceitaWS."""
    cnpj_clean = cnpj.replace(".", "").replace("/", "").replace("-", "")
    result = _fetch_brasilapi(cnpj_clean)
    if result:
        try:
            return _normalizar_brasilapi(result[1])
        except Exception:
            pass
    result = _fetch_cnpjws(cnpj_clean)
    if result:
        try:
            return _normalizar_cnpjws(result[1])
        except Exception:
            pass
    return None


# ── Scoring ───────────────────────────────────────────────────────────────────

def calcular_idade_empresa(data_abertura) -> int:
    """Retorna idade em anos a partir de uma string de data."""
    if not data_abertura:
        return 0
    try:
        s = str(data_abertura)[:10]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                return max(0, (date.today() - d).days // 365)
            except ValueError:
                continue
    except Exception:
        pass
    return 0


def calcular_score_avancado(empresa: dict, config: dict) -> dict:
    """
    Score 0-10 com 6 critérios ponderados.
    Retorna {score, motivos, penalidades, aprovado}.
    """
    score = 0
    motivos = []
    penalidades = []

    # 1. Capital social (máx 3 pontos)
    cap = float(empresa.get("capital_social") or 0)
    if cap >= 5_000_000:
        score += 3
        motivos.append("Capital ≥ R$5M")
    elif cap >= 500_000:
        score += 2
        motivos.append("Capital ≥ R$500k")
    elif cap >= 100_000:
        score += 1
        motivos.append("Capital ≥ R$100k")
    else:
        penalidades.append("Capital baixo")

    # 2. Canais de contato (máx 2 pontos)
    if empresa.get("telefone"):
        score += 1
        motivos.append("Telefone OK")
    if empresa.get("email"):
        score += 1
        motivos.append("E-mail OK")
    else:
        penalidades.append("Sem e-mail")

    # 3. Matriz (1 ponto)
    if empresa.get("is_matriz"):
        score += 1
        motivos.append("É matriz")
    else:
        penalidades.append("É filial")

    # 4. Situação ATIVA (1 ponto)
    if "ATIVA" in (empresa.get("situacao") or "").upper():
        score += 1
        motivos.append("Situação ativa")
    else:
        penalidades.append("Inativa/irregular")

    # 5. Maturidade 2-20 anos (1 ponto)
    idade = calcular_idade_empresa(empresa.get("data_inicio_atividade"))
    if 2 <= idade <= 20:
        score += 1
        motivos.append(f"Matura ({idade}a)")
    elif idade > 20:
        motivos.append(f"Consolidada ({idade}a)")
    elif idade < 2:
        penalidades.append(f"Muito nova ({idade}a)")

    # 6. Natureza jurídica favorável (1 ponto)
    nat = (empresa.get("natureza_juridica") or "").upper()
    if any(k in nat for k in ["SOCIEDADE ANÔNIMA", "S/A", "S.A", "LTDA", "LIMITADA", "EMPRESÁRIA"]):
        score += 1
        motivos.append("Natureza jurídica OK")

    score = min(10, max(0, score))
    aprovado = score >= int(config.get("score_minimo") or 6)
    return {"score": score, "motivos": motivos, "penalidades": penalidades, "aprovado": aprovado}


def aplicar_filtros_config(empresa: dict, config: dict) -> tuple:
    """
    Aplica filtros do sdr_config.
    Retorna (aprovado: bool, motivo_rejeicao: str).
    """
    if "ATIVA" not in (empresa.get("situacao") or "").upper():
        return (False, f"Situação: {empresa.get('situacao')}")

    cap = float(empresa.get("capital_social") or 0)
    cap_min = float(config.get("capital_social_min") or 50_000)
    if cap < cap_min:
        return (False, f"Capital R${cap:,.0f} < min R${cap_min:,.0f}")

    if int(config.get("tem_telefone") or 0) and not empresa.get("telefone"):
        return (False, "Sem telefone")

    if int(config.get("tem_email") or 0) and not empresa.get("email"):
        return (False, "Sem e-mail")

    tipo_req = (config.get("tipo_empresa") or "").upper()
    if tipo_req == "MATRIZ" and not empresa.get("is_matriz"):
        return (False, "Não é matriz")
    if tipo_req == "FILIAL" and empresa.get("is_matriz"):
        return (False, "É matriz, não filial")

    idade = calcular_idade_empresa(empresa.get("data_inicio_atividade"))
    idade_min = int(config.get("idade_empresa_min") or 0)
    idade_max = int(config.get("idade_empresa_max") or 50)
    if idade < idade_min:
        return (False, f"Muito nova: {idade} < {idade_min}a")
    if idade_max > 0 and idade > idade_max:
        return (False, f"Muito antiga: {idade} > {idade_max}a")

    return (True, "")


def empresa_deve_ser_recontato(cnpj: str, config: dict, db) -> tuple:
    """
    Verifica se a empresa deve ser prospectada/recontactada.
    Retorna (deve: bool, motivo: str).
    """
    try:
        row = db.execute(
            "SELECT status, tentativas, ultima_tentativa FROM prospeccao_automatica WHERE cnpj=?",
            (cnpj,)
        ).fetchone()
    except Exception:
        return (True, "Novo lead")

    if not row:
        return (True, "Novo lead")

    r = dict(row)
    status     = r.get("status") or "novo"
    tentativas = int(r.get("tentativas") or 0)
    max_tent   = int(config.get("max_tentativas_por_empresa") or 3)
    dias_rec   = int(config.get("dias_recontato") or 30)

    if status == "importado":
        return (False, "Já convertido")
    if status == "descartado":
        return (False, "Descartado definitivamente")
    if tentativas >= max_tent:
        return (False, f"Máx tentativas ({tentativas}/{max_tent})")

    ultima = r.get("ultima_tentativa")
    if ultima:
        try:
            d_ultima = datetime.strptime(str(ultima)[:10], "%Y-%m-%d").date()
            dias_passados = (date.today() - d_ultima).days
            if dias_passados < dias_rec:
                prox = (d_ultima + timedelta(days=dias_rec)).strftime("%d/%m/%Y")
                return (False, f"Aguardar até {prox}")
        except Exception:
            pass

    return (True, f"Tentativa {tentativas + 1}")


def gerar_pitch_ia(db, empresa_nome: str, cnae_desc: str, produto: str, canal: str) -> str:
    """Gera pitch personalizado via Claude Haiku."""
    try:
        import models.ia_config as ia_mod
        limite = "máximo 150 caracteres" if canal == "whatsapp" else "3-4 frases"
        msg = (
            f"Gere uma mensagem de prospecção para {canal} para a empresa '{empresa_nome}' "
            f"(setor: {cnae_desc}). Produto: {produto}. "
            f"Use o nome da empresa, destaque um benefício concreto. {limite}. Sem emojis excessivos."
        )
        return ia_mod.chat_com_ia(db, msg)
    except Exception:
        return ""


# ── Engine principal ──────────────────────────────────────────────────────────

def rodar_prospeccao_autonoma(db=None, config_override: dict = None) -> dict:
    """
    Engine SDR: busca seeds via API, filtra, pontua, salva e cria cadências
    para os melhores leads.
    """
    from models.prospeccao_auto import _ALL_SEEDS

    _own_conn = db is None
    if _own_conn:
        db = get_connection()

    try:
        cfg = get_sdr_config(db)
        if config_override:
            cfg.update(config_override)

        if not cfg.get("ativo", 1):
            return {"encontrados": 0, "salvos": 0, "duplicados": 0,
                    "cadencias": 0, "descartados": 0, "motivo": "SDR pausado"}

        hora_atual = datetime.now().hour
        h_ini = int(cfg.get("horario_inicio") or 8)
        h_fim = int(cfg.get("horario_fim") or 18)
        if hora_atual < h_ini or hora_atual >= h_fim:
            return {"encontrados": 0, "salvos": 0, "duplicados": 0,
                    "cadencias": 0, "descartados": 0,
                    "motivo": f"Fora do horário ({hora_atual}h, janela {h_ini}h–{h_fim}h)"}

        regras_banco = _carregar_regras_do_banco()
        regras       = regras_banco if regras_banco else REGRAS_POR_PRODUTO

        estados_cfg   = [e.strip() for e in (cfg.get("estados") or "").split(",") if e.strip()]
        max_leads     = int(cfg.get("max_leads_por_execucao") or 20)
        produto_foco  = cfg.get("produto_foco") or "todos"
        canal_prim    = cfg.get("canal_primario") or "whatsapp"
        score_minimo  = int(cfg.get("score_minimo") or 6)

        # Build CNAE → produto map
        cnaes_alvo: set   = set()
        produto_por_cnae: dict = {}
        for regra in regras:
            prod = regra["produto"] if produto_foco == "todos" else produto_foco
            for c in regra.get("cnaes", []):
                c_clean = str(c).replace(".", "").replace("-", "")
                cnaes_alvo.add(c_clean)
                produto_por_cnae.setdefault(c_clean, prod)

        # Fetch seeds concurrently
        brutos: list = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            fts = {ex.submit(buscar_por_cnpj_especifico, s): s for s in _ALL_SEEDS}
            for ft in as_completed(fts):
                emp = ft.result()
                if emp:
                    brutos.append(emp)

        brutos.sort(key=lambda e: float(e.get("capital_social") or 0), reverse=True)

        total_encontrados = 0
        total_salvos      = 0
        total_duplicados  = 0
        total_descartados = 0
        total_cadencias   = 0
        erros: list       = []

        for emp in brutos:
            if total_salvos >= max_leads:
                break

            emp_uf   = (emp.get("uf") or "").upper()
            emp_cnae = emp.get("cnae_codigo") or ""

            # Filtra UF
            if estados_cfg and emp_uf not in estados_cfg:
                continue

            # Filtra CNAE
            if cnaes_alvo:
                exact  = emp_cnae in cnaes_alvo
                sector = any(emp_cnae[:4] == c[:4] for c in cnaes_alvo if len(c) >= 4)
                if not exact and not sector:
                    continue

            total_encontrados += 1
            cnpj = emp.get("cnpj") or ""
            if not cnpj:
                continue

            # Verifica recontato
            deve, _ = empresa_deve_ser_recontato(cnpj, cfg, db)
            if not deve:
                total_duplicados += 1
                continue

            # Aplica filtros
            aprovado, motivo_filtro = aplicar_filtros_config(emp, cfg)
            if not aprovado:
                total_descartados += 1
                # Registra motivo se já existe no banco
                try:
                    db.execute(
                        "UPDATE prospeccao_automatica SET motivo_descarte=? WHERE cnpj=?",
                        (motivo_filtro, cnpj)
                    )
                    db.commit()
                except Exception:
                    pass
                continue

            # Score avançado
            res_score = calcular_score_avancado(emp, cfg)
            score     = res_score["score"]
            if not res_score["aprovado"]:
                total_descartados += 1
                continue

            produto_alvo = produto_foco if produto_foco != "todos" else produto_por_cnae.get(emp_cnae, "Benefícios Corporativos")
            idade        = calcular_idade_empresa(emp.get("data_inicio_atividade"))
            hoje_str     = date.today().isoformat()

            # Checa se já existe (para UPDATE vs INSERT)
            existente = db.execute(
                "SELECT id FROM prospeccao_automatica WHERE cnpj=?", (cnpj,)
            ).fetchone()

            try:
                if existente:
                    db.execute(
                        """UPDATE prospeccao_automatica
                           SET score_fit=?, status='novo', tentativas=tentativas+1,
                               ultima_tentativa=?, produto_alvo=?, motivo_descarte=NULL
                           WHERE cnpj=?""",
                        (score, hoje_str, produto_alvo, cnpj),
                    )
                else:
                    db.execute(
                        """INSERT INTO prospeccao_automatica
                           (cnpj, razao_social, municipio, uf, cnae_descricao,
                            telefone, email, capital_social, score_fit, status,
                            fonte, idade_empresa, natureza_juridica, porte,
                            produto_alvo, tentativas, ultima_tentativa)
                           VALUES (?,?,?,?,?,?,?,?,?,'novo',?,?,?,?,?,1,?)""",
                        (
                            cnpj,
                            emp.get("razao_social") or "",
                            emp.get("municipio") or "",
                            emp_uf,
                            emp.get("cnae_descricao") or "",
                            emp.get("telefone"),
                            emp.get("email"),
                            float(emp.get("capital_social") or 0),
                            score,
                            emp.get("fonte") or "brasilapi",
                            idade,
                            emp.get("natureza_juridica") or "",
                            emp.get("porte") or "",
                            produto_alvo,
                            hoje_str,
                        ),
                    )
                db.commit()
                total_salvos += 1
            except Exception as e:
                erros.append(f"DB {cnpj}: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

            # Auto-cadência para leads nota ≥ 8
            if score >= 8 and (emp.get("telefone") or emp.get("email")):
                try:
                    pitch = gerar_pitch_ia(
                        db,
                        emp.get("razao_social") or "",
                        emp.get("cnae_descricao") or "",
                        produto_alvo,
                        canal_prim,
                    )
                    data_acao = (date.today() + timedelta(days=1)).isoformat()
                    db.execute(
                        """INSERT INTO cadencias
                           (empresa_nome, contato_whatsapp, contato_email,
                            etapa, data_acao, mensagem_whatsapp,
                            assunto_email, corpo_email, status)
                           VALUES (?,?,?,1,?,?,?,?,'pendente')""",
                        (
                            emp.get("razao_social") or "",
                            emp.get("telefone"),
                            emp.get("email"),
                            data_acao,
                            (pitch or "")[:500],
                            f"Proposta Krylo para {emp.get('razao_social') or ''}",
                            pitch or "",
                        ),
                    )
                    db.commit()
                    total_cadencias += 1
                except Exception as e:
                    erros.append(f"Cadência {cnpj}: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass

        # Registra execução
        try:
            db.execute(
                "INSERT INTO sdr_execucoes (encontrados, salvos, cadencias, descartados, log) VALUES (?,?,?,?,?)",
                (total_encontrados, total_salvos, total_cadencias, total_descartados,
                 "; ".join(erros) if erros else "OK"),
            )
            db.commit()
        except Exception:
            pass

        return {
            "encontrados": total_encontrados,
            "salvos":      total_salvos,
            "duplicados":  total_duplicados,
            "cadencias":   total_cadencias,
            "descartados": total_descartados,
            "erros":       erros,
        }
    finally:
        if _own_conn:
            try:
                db.close()
            except Exception:
                pass


def status_resumo() -> dict:
    """Retorna estatísticas atuais da tabela prospeccao_automatica."""
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='novo'      THEN 1 ELSE 0 END) AS novos,
            SUM(CASE WHEN status='importado' THEN 1 ELSE 0 END) AS importados,
            MAX(importado_em) AS ultima_execucao
        FROM prospeccao_automatica
    """).fetchone()
    conn.close()
    if not row:
        return {"total": 0, "novos": 0, "importados": 0, "ultima_execucao": None}
    return dict(row)
