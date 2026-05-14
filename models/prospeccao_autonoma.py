"""
Prospecção Autônoma — motor SDR completo com scoring avançado, filtros,
pitch por IA, criação automática de cadências e sessões com log ao vivo.
"""
import json
import time
import requests
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_connection

_HEADERS = {"User-Agent": "KryloCRM/1.0 SDR-autonomo"}

_sessao_global = {"id": None, "ativo": False, "pausado": False}

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


def carregar_produtos_do_banco(db) -> list:
    try:
        rows = db.execute(
            "SELECT * FROM produtos_krylo WHERE ativo=1 ORDER BY nome"
        ).fetchall()
        if not rows:
            return REGRAS_POR_PRODUTO
        regras = []
        for p in rows:
            cnaes = [c.strip() for c in (p["cnaes_alvo"] or "").split(",") if c.strip()]
            ufs   = [e.strip() for e in (p["estados_alvo"] or "ES,SP").split(",") if e.strip()]
            regras.append({
                "produto":               p["nome"],
                "descricao":             p["descricao"] or "",
                "cnaes":                 cnaes,
                "ufs":                   ufs or ["ES", "SP"],
                "pitch":                 p["pitch_whatsapp"] or "",
                "pitch_email":           p["pitch_email"] or "",
                "beneficios":            p["beneficios"] or "",
                "objecoes":              p["objecoes_comuns"] or "",
                "como_responder":        p["como_responder_objecoes"] or "",
                "score_min_cadencia":    int(p["score_min"] or 6),
                "capital_min":           float(p["capital_min"] or 50000),
                "valor_por_funcionario": float(p["valor_por_funcionario"] or 0),
            })
        return regras if regras else REGRAS_POR_PRODUTO
    except Exception:
        return REGRAS_POR_PRODUTO


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
    score = 0
    motivos = []
    penalidades = []

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

    if empresa.get("telefone"):
        score += 1
        motivos.append("Telefone OK")
    if empresa.get("email"):
        score += 1
        motivos.append("E-mail OK")
    else:
        penalidades.append("Sem e-mail")

    if empresa.get("is_matriz"):
        score += 1
        motivos.append("É matriz")
    else:
        penalidades.append("É filial")

    if "ATIVA" in (empresa.get("situacao") or "").upper():
        score += 1
        motivos.append("Situação ativa")
    else:
        penalidades.append("Inativa/irregular")

    idade = calcular_idade_empresa(empresa.get("data_inicio_atividade"))
    if 2 <= idade <= 20:
        score += 1
        motivos.append(f"Matura ({idade}a)")
    elif idade > 20:
        motivos.append(f"Consolidada ({idade}a)")
    elif idade < 2:
        penalidades.append(f"Muito nova ({idade}a)")

    nat = (empresa.get("natureza_juridica") or "").upper()
    if any(k in nat for k in ["SOCIEDADE ANÔNIMA", "S/A", "S.A", "LTDA", "LIMITADA", "EMPRESÁRIA"]):
        score += 1
        motivos.append("Natureza jurídica OK")

    score = min(10, max(0, score))
    aprovado = score >= int(config.get("score_minimo") or 6)
    return {"score": score, "motivos": motivos, "penalidades": penalidades, "aprovado": aprovado}


def aplicar_filtros_config(empresa: dict, config: dict) -> tuple:
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


def gerar_pitch_ia(db, empresa_nome: str, cnae_desc: str, produto: str, canal: str,
                   beneficios: str = "", objecoes: str = "") -> str:
    try:
        import models.ia_config as ia_mod
        limite = "máximo 150 caracteres" if canal == "whatsapp" else "3-4 frases"
        extra = ""
        if beneficios:
            extra += f"\nBenefícios do produto:\n{beneficios}"
        if objecoes:
            extra += f"\nObjeções comuns e respostas:\n{objecoes}"
        msg = (
            f"Gere uma mensagem de prospecção para {canal} para a empresa '{empresa_nome}' "
            f"(setor: {cnae_desc}). Produto: {produto}. "
            f"Use o nome da empresa, destaque um benefício concreto. {limite}. Sem emojis excessivos."
            + extra
        )
        return ia_mod.chat_com_ia(db, msg)
    except Exception:
        return ""


# ── Sessão e log ao vivo ──────────────────────────────────────────────────────

def criar_sessao(db, config: dict) -> str:
    sessao_id = datetime.now().strftime("%Y%m%d%H%M%S")
    _sessao_global["id"] = sessao_id
    _sessao_global["ativo"] = True
    _sessao_global["pausado"] = False
    try:
        db.execute("""
            INSERT OR IGNORE INTO sdr_sessoes (sessao_id, status, config_snapshot)
            VALUES (?, 'rodando', ?)
        """, (sessao_id, json.dumps(config, default=str)[:500]))
        db.commit()
    except Exception:
        pass
    _log(db, sessao_id, "inicio", "SDR Autônomo iniciado — buscando leads", status="rodando")
    return sessao_id


def finalizar_sessao(db, sessao_id: str, stats: dict):
    _sessao_global["ativo"] = False
    _sessao_global["pausado"] = False
    try:
        db.execute("""
            UPDATE sdr_sessoes SET
              status='concluido',
              encontrados=?, aprovados=?, importados=?,
              cadencias=?, descartados=?, filtrados=?,
              finalizado_em=datetime('now', 'localtime')
            WHERE sessao_id=?
        """, (
            stats.get("encontrados", 0), stats.get("aprovados", 0),
            stats.get("importados", 0), stats.get("cadencias", 0),
            stats.get("descartados", 0), stats.get("filtrados", 0),
            sessao_id,
        ))
        db.commit()
    except Exception:
        pass
    msg = (f"Sessão concluída — {stats.get('importados', 0)} leads importados, "
           f"{stats.get('cadencias', 0)} cadências iniciadas")
    _log(db, sessao_id, "fim", msg, status="concluido")


def atualizar_progresso(db, sessao_id: str, **kwargs):
    if not kwargs or not sessao_id:
        return
    try:
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [sessao_id]
        db.execute(f"UPDATE sdr_sessoes SET {set_clause} WHERE sessao_id=?", values)
        db.commit()
    except Exception:
        pass


def _log(db, sessao_id: str, tipo: str, mensagem: str,
         empresa: str = "", uf: str = "", score: int = 0,
         produto: str = "", status: str = "", capital: float = 0):
    if not sessao_id:
        return
    try:
        db.execute("""
            INSERT INTO sdr_log_ao_vivo
            (sessao_id, tipo, mensagem, empresa, uf, score, produto, status, capital)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sessao_id, tipo, str(mensagem)[:300], str(empresa)[:100],
              str(uf)[:5], int(score or 0), str(produto)[:50],
              str(status)[:20], float(capital or 0)))
        db.commit()
    except Exception:
        pass


def sdr_deve_parar(db, sessao_id: str) -> bool:
    try:
        row = db.execute(
            "SELECT status FROM sdr_sessoes WHERE sessao_id=?", (sessao_id,)
        ).fetchone()
        return bool(row and row["status"] in ("pausado", "cancelado"))
    except Exception:
        return False


# ── Engine principal com log ao vivo ─────────────────────────────────────────

def rodar_prospeccao_autonoma(db=None, config_override: dict = None) -> dict:
    _own_conn = db is None
    if _own_conn:
        db = get_connection()

    try:
        cfg = get_sdr_config(db)
        if config_override:
            cfg.update(config_override)

        # Cria sessão ANTES dos checks para o terminal sempre mostrar algo
        sessao_id = criar_sessao(db, cfg)
        _stats0 = {"encontrados": 0, "aprovados": 0, "importados": 0,
                   "cadencias": 0, "descartados": 0, "filtrados": 0}

        if not cfg.get("ativo", 1):
            _log(db, sessao_id, "info", "SDR desativado — ative o SDR nas configurações para rodar")
            finalizar_sessao(db, sessao_id, _stats0)
            return {"status": "inativo", "sessao_id": sessao_id, **_stats0, "salvos": 0}

        from datetime import timezone, timedelta
        fuso_brasilia = timezone(timedelta(hours=-3))
        hora_atual = datetime.now(fuso_brasilia).hour
        h_ini = int(cfg.get("horario_inicio") or 8)
        h_fim = int(cfg.get("horario_fim") or 18)
        if hora_atual < h_ini or hora_atual >= h_fim:
            motivo = f"Fora do horário ({hora_atual}h, janela {h_ini}h–{h_fim}h)"
            _log(db, sessao_id, "info", f"SDR não rodou: {motivo}")
            finalizar_sessao(db, sessao_id, _stats0)
            return {"status": "fora_horario", "sessao_id": sessao_id, **_stats0,
                    "salvos": 0, "motivo": motivo}

        regras = carregar_produtos_do_banco(db)

        estados_cfg  = [e.strip().upper() for e in cfg.get("estados", "ES,SP").split(",") if e.strip()]
        max_leads    = int(cfg.get("max_leads_por_execucao") or 20)
        produto_foco = cfg.get("produto_foco") or "todos"
        canal_prim   = cfg.get("canal_primario") or "whatsapp"

        stats = {"encontrados": 0, "aprovados": 0, "importados": 0,
                 "cadencias": 0, "descartados": 0, "filtrados": 0}

        for regra in regras:
            if stats["importados"] >= max_leads:
                break

            nome_produto = regra["produto"]
            if produto_foco != "todos" and nome_produto.lower() not in produto_foco.lower():
                continue

            estados_busca = estados_cfg or regra.get("ufs", ["ES", "SP"])
            cnaes_regra   = regra.get("cnaes", [])

            for uf in estados_busca[:3]:
                if stats["importados"] >= max_leads:
                    break

                if sdr_deve_parar(db, sessao_id):
                    _log(db, sessao_id, "pausa", f"SDR pausado durante busca em {uf}", uf=uf)
                    finalizar_sessao(db, sessao_id, stats)
                    return {**stats, "status": "pausado", "sessao_id": sessao_id,
                            "salvos": stats["importados"]}

                cnaes_busca = [c.strip() for c in cfg.get("cnaes", "").split(",") if c.strip()] \
                              or cnaes_regra

                for cnae in cnaes_busca[:2]:
                    if stats["importados"] >= max_leads:
                        break

                    atualizar_progresso(db, sessao_id,
                        produto_atual=nome_produto, estado_atual=uf,
                        ultima_acao=f"Buscando {nome_produto} em {uf} (CNAE {cnae})",
                        encontrados=stats["encontrados"], aprovados=stats["aprovados"],
                        importados=stats["importados"], cadencias=stats["cadencias"],
                        descartados=stats["descartados"], filtrados=stats["filtrados"])

                    _log(db, sessao_id, "busca",
                         f"Buscando empresas de {nome_produto} em {uf}",
                         uf=uf, produto=nome_produto)

                    empresas_lista = []
                    try:
                        url = (f"https://brasilapi.com.br/api/cnpj/v1/search"
                               f"?cnae={cnae}&uf={uf}&limit=10")
                        r = requests.get(url, timeout=15, headers=_HEADERS)
                        if r.status_code == 200:
                            data = r.json()
                            if isinstance(data, list):
                                empresas_lista = data
                    except Exception:
                        pass

                    _log(db, sessao_id, "info",
                         f"API retornou {len(empresas_lista)} empresas para CNAE {cnae} em {uf}",
                         uf=uf, produto=nome_produto)

                    for item in empresas_lista:
                        if stats["importados"] >= max_leads:
                            break

                        if sdr_deve_parar(db, sessao_id):
                            finalizar_sessao(db, sessao_id, stats)
                            return {**stats, "status": "pausado", "sessao_id": sessao_id,
                                    "salvos": stats["importados"]}

                        cnpj = "".join(filter(str.isdigit, str(item.get("cnpj", ""))))
                        if not cnpj or len(cnpj) != 14:
                            continue

                        deve, _ = empresa_deve_ser_recontato(cnpj, cfg, db)
                        if not deve:
                            stats["filtrados"] += 1
                            continue

                        empresa = buscar_por_cnpj_especifico(cnpj)
                        if not empresa:
                            time.sleep(0.5)
                            continue

                        razao   = (empresa.get("razao_social") or "")[:80]
                        capital = float(empresa.get("capital_social") or 0)
                        uf_emp  = empresa.get("uf") or uf
                        stats["encontrados"] += 1

                        atualizar_progresso(db, sessao_id,
                            empresa_atual=razao,
                            ultima_acao=f"Analisando: {razao}",
                            encontrados=stats["encontrados"])

                        _log(db, sessao_id, "encontrado",
                             f"Analisando empresa: {razao}",
                             empresa=razao, uf=uf_emp, produto=nome_produto, capital=capital)

                        aprovado_filtro, motivo_filtro = aplicar_filtros_config(empresa, cfg)
                        if not aprovado_filtro:
                            stats["descartados"] += 1
                            _log(db, sessao_id, "descarte",
                                 f"Descartada: {motivo_filtro}",
                                 empresa=razao, uf=uf_emp, score=0)
                            continue

                        res_score = calcular_score_avancado(empresa, cfg)
                        score     = res_score["score"]
                        stats["aprovados"] += 1

                        _log(db, sessao_id, "score",
                             f"Score {score}/10 — {', '.join(res_score['motivos'][:3])}",
                             empresa=razao, uf=uf_emp, score=score, produto=nome_produto,
                             status="aprovado" if res_score["aprovado"] else "baixo_score",
                             capital=capital)

                        telefone_raw = empresa.get("telefone") or ""
                        telefone = (f"55{telefone_raw}"
                                    if telefone_raw and not telefone_raw.startswith("55")
                                    else telefone_raw) or None
                        email    = empresa.get("email") or None
                        idade    = calcular_idade_empresa(empresa.get("data_inicio_atividade", ""))
                        hoje_str = date.today().isoformat()

                        existente = None
                        try:
                            existente = db.execute(
                                "SELECT id FROM prospeccao_automatica WHERE cnpj=?", (cnpj,)
                            ).fetchone()
                        except Exception:
                            pass

                        try:
                            if existente:
                                db.execute("""
                                    UPDATE prospeccao_automatica
                                    SET score_fit=?, status='novo', tentativas=tentativas+1,
                                        ultima_tentativa=?, produto_alvo=?, motivo_descarte=NULL
                                    WHERE cnpj=?
                                """, (score, hoje_str, nome_produto, cnpj))
                            else:
                                db.execute("""
                                    INSERT INTO prospeccao_automatica
                                    (cnpj, razao_social, municipio, uf, cnae_descricao,
                                     telefone, email, capital_social, score_fit, status,
                                     fonte, idade_empresa, natureza_juridica, porte,
                                     produto_alvo, tentativas, ultima_tentativa)
                                    VALUES (?,?,?,?,?,?,?,?,?,'novo',?,?,?,?,?,1,?)
                                """, (cnpj, razao, empresa.get("municipio", ""), uf_emp,
                                      empresa.get("cnae_descricao", ""),
                                      telefone, email, capital, score,
                                      empresa.get("fonte") or "brasilapi",
                                      idade,
                                      empresa.get("natureza_juridica", ""),
                                      empresa.get("porte", ""),
                                      nome_produto, hoje_str))
                            db.commit()
                            stats["importados"] += 1
                            atualizar_progresso(db, sessao_id, importados=stats["importados"])
                            _log(db, sessao_id, "importado",
                                 f"Salvo na base! Score {score}/10",
                                 empresa=razao, uf=uf_emp, score=score,
                                 produto=nome_produto, status="importado", capital=capital)
                        except Exception:
                            try:
                                db.rollback()
                            except Exception:
                                pass
                            continue

                        # Auto-cadência
                        score_min_cad = regra.get("score_min_cadencia",
                                                   int(cfg.get("score_minimo") or 6))
                        if res_score["aprovado"] and score >= score_min_cad and (telefone or email):
                            try:
                                pitch_base = regra.get("pitch") or ""
                                if pitch_base:
                                    pitch = pitch_base.replace("{empresa}", razao)
                                else:
                                    pitch = gerar_pitch_ia(
                                        db, razao,
                                        empresa.get("cnae_descricao", ""),
                                        nome_produto, canal_prim,
                                        beneficios=regra.get("beneficios", ""),
                                        objecoes=regra.get("objecoes", ""),
                                    )
                                from models.cadencia import criar_etapa
                                criar_etapa({
                                    "empresa_id":        None,
                                    "empresa_nome":      razao,
                                    "contato_whatsapp":  telefone,
                                    "contato_email":     email,
                                    "oportunidade_id":   None,
                                    "etapa":             1,
                                    "data_acao":         (date.today() + timedelta(days=1)).isoformat(),
                                    "mensagem_whatsapp": (pitch or "")[:500],
                                    "assunto_email":     f"Proposta Krylo para {razao}",
                                    "corpo_email":       pitch or "",
                                    "status":            "pendente",
                                    "produto_alvo":      nome_produto,
                                })
                                stats["cadencias"] += 1
                                atualizar_progresso(db, sessao_id, cadencias=stats["cadencias"])
                                db.execute(
                                    "UPDATE prospeccao_automatica SET status='importado' WHERE cnpj=?",
                                    (cnpj,)
                                )
                                db.commit()
                                _log(db, sessao_id, "cadencia",
                                     "Cadência iniciada — WhatsApp+Email agendados",
                                     empresa=razao, uf=uf_emp, score=score,
                                     produto=nome_produto, status="cadencia")
                            except Exception as e:
                                _log(db, sessao_id, "erro",
                                     f"Erro na cadência: {str(e)[:80]}", empresa=razao)

                        time.sleep(1)

        finalizar_sessao(db, sessao_id, stats)

        try:
            db.execute("""
                INSERT INTO sdr_execucoes (encontrados, salvos, cadencias, descartados, log)
                VALUES (?, ?, ?, ?, ?)
            """, (stats["encontrados"], stats["importados"], stats["cadencias"],
                  stats["descartados"], json.dumps({"sessao_id": sessao_id})))
            db.commit()
        except Exception:
            pass

        return {**stats, "status": "concluido", "sessao_id": sessao_id,
                "salvos": stats["importados"]}

    finally:
        if _own_conn:
            try:
                db.close()
            except Exception:
                pass


def status_resumo() -> dict:
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
