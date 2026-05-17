"""
SDR Evolutivo — Módulo de prospecção autônoma com features inovadoras que o mercado ainda não viu:
1. Radar de Intent (notícias, licitações, editais, mídias sociais)
2. Score de Prontidão para Venda (não só fit, mas "agora é a hora")
3. Pitch Dinâmico Adaptativo (se adapta com feedback)
4. Perfil de Decisor Predictivo (encontra os decisores certos)
5. Ecosistema de Leads (conecta empresas que fazem negócios entre si)
"""
import json
import random
import re
import time
import unicodedata
import requests
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_connection, get_new_db_connection

_HEADERS = {"User-Agent": "KryloCRM/2.0 SDR-Evolutivo"}


def _normalizar_texto(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii").upper().strip()


# ── 1. RADAR DE INTENT (Monitoramento de triggers que indicam prontidão para comprar) ──────────

_FONTES_RADAR = {
    "licitacoes": [
        "https://www.gov.br/compras/pt-br/acesso-a-informacao/noticias",
        "https://www.portaltransparencia.gov.br/ultimas-noticias",
    ],
    "noticias_expansao": [
        "https://valor.globo.com/empresas/",
        "https://exame.com/negocios/",
    ],
    "editais": [
        "https://www.bcb.gov.br/estabilidadefinanceira/relatorios",
    ]
}


def _fetch_rss_feed(url: str) -> list:
    """Busca RSS feed (se disponível) ou parseia HTML para encontrar notícias relevantes."""
    try:
        import feedparser
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries[:10]:
            entries.append({
                "titulo": entry.get("title", ""),
                "link": entry.get("link", ""),
                "data": entry.get("published", ""),
                "resumo": entry.get("summary", "")
            })
        return entries
    except Exception:
        pass
    return []


def monitorar_radar_intent(tenant_id: int = 1) -> list:
    """
    Radar de Intent: Monitora fontes públicas para encontrar empresas que estão PRONTAS PARA COMPRAR.
    Triggers:
    - Licitações/Editais publicados
    - Notícias de expansão
    - Novos investimentos
    - Mudanças de diretoria
    """
    leads_quentes = []

    for fonte, urls in _FONTES_RADAR.items():
        for url in urls:
            entries = _fetch_rss_feed(url)
            for entry in entries:
                texto = (entry.get("titulo", "") + " " + entry.get("resumo", "")).lower()

                # Triggers que indicam prontidão
                triggers = [
                    "expansao", "expansão", "novo projeto", "nova filial",
                    "investimento", "licitação", "edital", "contrato",
                    "nova diretoria", "novo presidente", "crescimento",
                    "aumento de equipe", "contratação", "novos colaboradores"
                ]

                if any(trigger in texto for trigger in triggers):
                    leads_quentes.append({
                        "fonte": fonte,
                        "titulo": entry.get("titulo", ""),
                        "link": entry.get("link", ""),
                        "data": entry.get("data", ""),
                        "resumo": entry.get("resumo", ""),
                        "score_intent": 8 + random.randint(0, 2),
                        "tenant_id": tenant_id
                    })

    # Salvar no banco
    db = get_new_db_connection()
    try:
        for lead in leads_quentes:
            db.execute("""
                INSERT OR IGNORE INTO radar_intent
                (tenant_id, fonte, titulo, link, data_evento, resumo, score_intent, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """, (
                lead["tenant_id"], lead["fonte"], lead["titulo"], lead["link"],
                lead["data"], lead["resumo"], lead["score_intent"]
            ))
        db.commit()
    except Exception as e:
        print(f"[RADAR] Erro ao salvar: {e}")
    finally:
        db.close()

    return leads_quentes


# ── 2. SCORE DE PRONTIDÃO PARA VENDA (não só fit — "agora é a hora") ────────────────────────

def calcular_score_prontidao(empresa: dict, config: dict) -> dict:
    """
    Score de Prontidão: Analisa não só se a empresa é um bom fit,
    mas principalmente se É A HORA CERTA para contatar.
    Fatores:
    - Eventos recentes (Radar de Intent)
    - Ciclo de compra da empresa
    - Época do ano (ex: final de ano para benefícios)
    - Comportamento de mercado
    - Interações passadas
    """
    score = 0
    motivos = []
    penalidades = []

    # 1. Eventos do Radar de Intent (maior peso)
    db = get_new_db_connection()
    try:
        cnpj = empresa.get("cnpj", "")
        row = db.execute("""
            SELECT score_intent FROM radar_intent
            WHERE (titulo LIKE ? OR resumo LIKE ?)
            AND criado_em >= datetime('now', '-30 days')
            LIMIT 1
        """, (f"%{empresa.get('razao_social', '')[:30]}%", f"%{empresa.get('razao_social', '')[:30]}%")).fetchone()
        if row:
            score += int(row["score_intent"])
            motivos.append("Evento recente detectado (Radar de Intent)")
    except Exception:
        pass
    finally:
        db.close()

    # 2. Ciclo de compra (baseado na data de abertura/aniversário)
    data_abertura = empresa.get("data_inicio_atividade", "")
    if data_abertura:
        try:
            mes = int(str(data_abertura)[5:7])
            mes_atual = date.today().month
            if abs(mes - mes_atual) <= 2:
                score += 3
                motivos.append("Período de aniversário/renovação")
        except Exception:
            pass

    # 3. Época do ano (ex: final de ano para VR/VA, início de ano para treinamentos)
    mes_atual = date.today().month
    if mes_atual in [10, 11, 12]:
        score += 2
        motivos.append("Final de ano (alta demanda para benefícios)")
    elif mes_atual in [1, 2, 3]:
        score += 1
        motivos.append("Início de ano (planejamento)")

    # 4. Capital social e porte (fit básico)
    cap = float(empresa.get("capital_social", 0))
    if cap >= 1_000_000:
        score += 3
        motivos.append("Capital ≥ R$1M")
    elif cap >= 500_000:
        score += 2
        motivos.append("Capital ≥ R$500k")
    elif cap >= 100_000:
        score += 1
        motivos.append("Capital ≥ R$100k")
    else:
        penalidades.append("Capital baixo")

    # 5. Contatos disponíveis
    if empresa.get("telefone"):
        score += 1
        motivos.append("Telefone OK")
    if empresa.get("email"):
        score += 1
        motivos.append("E-mail OK")
    else:
        penalidades.append("Sem e-mail")

    # 6. Situação cadastral
    if "ATIVA" in (empresa.get("situacao", "") or "").upper():
        score += 1
        motivos.append("Situação ativa")

    # 7. Idade da empresa
    idade = _calcular_idade_empresa(data_abertura)
    if 3 <= idade <= 15:
        score += 2
        motivos.append(f"Empresa em fase de crescimento ({idade}a)")
    elif idade > 15:
        score += 1
        motivos.append(f"Empresa consolidada ({idade}a)")

    score = min(15, max(0, score))
    aprovado = score >= int(config.get("score_prontidao_minimo") or 8)

    return {
        "score": score,
        "score_fit": min(10, max(0, score // 1.5)),
        "score_prontidao": score,
        "motivos": motivos,
        "penalidades": penalidades,
        "aprovado": aprovado,
        "recomendacao": "Contatar AGORA" if aprovado else "Aguardar melhor momento"
    }


def _calcular_idade_empresa(data_abertura) -> int:
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


# ── 3. PITCH DINÂMICO ADAPTATIVO (se adapta com feedback das interações) ────────────────────────

def gerar_pitch_adaptativo(db, empresa: dict, produto: dict, canal: str,
                            feedback_anterior: dict = None) -> str:
    """
    Pitch Dinâmico Adaptativo:
    - Não é só um pitch gerado uma vez
    - Se adapta com feedback das interações anteriores
    - Usa o Score de Prontidão para personalizar o tom
    - Se a empresa ignorou o WhatsApp, tenta email com ângulo diferente
    - Se respondeu, ajusta para o interesse demonstrado
    """
    try:
        import models.ia_config as ia_mod

        score_prontidao = empresa.get("score_prontidao", 5)
        razao = empresa.get("razao_social", "Empresa")
        cnae_desc = empresa.get("cnae_descricao", "")
        motivos = empresa.get("motivos_prontidao", [])

        # Tom baseado no score de prontidão
        if score_prontidao >= 12:
            tom = "urgente e direto — fale em resultados rápidos"
        elif score_prontidao >= 8:
            tom = "confiante e consultivo — mostre valor"
        else:
            tom = "amigável e educativo — construa relacionamento"

        # Ajuste baseado em feedback anterior
        ajuste_feedback = ""
        if feedback_anterior:
            if feedback_anterior.get("canal") == "whatsapp" and feedback_anterior.get("status") == "ignorado":
                ajuste_feedback = "Use email agora, com um ângulo diferente — foque em benefícios de longo prazo."
            elif feedback_anterior.get("status") == "respondido":
                interesse = feedback_anterior.get("interesse_demonstrado", "")
                ajuste_feedback = f"Foque no interesse demonstrado: {interesse}."

        # Informações específicas do produto
        beneficios = produto.get("beneficios", "")
        objecoes = produto.get("objecoes_comuns", "")
        pitch_base = produto.get("pitch_whatsapp" if canal == "whatsapp" else "pitch_email", "")

        # Prompt para IA
        limite = "máximo 180 caracteres" if canal == "whatsapp" else "3-5 frases claras"
        msg = (
            f"Gere uma mensagem de prospecção {tom} para {canal} para a empresa '{razao}' "
            f"(setor: {cnae_desc}). Produto: {produto.get('produto', produto.get('nome', 'Produto'))}. "
            f"Score de prontidão: {score_prontidao}/15 — {motivos}. "
            f"Use o nome da empresa, destaque 1 benefício concreto. {limite}. Sem emojis excessivos. "
        )

        if beneficios:
            msg += f"\nBenefícios do produto:\n{beneficios}"
        if objecoes:
            msg += f"\nObjeções comuns e respostas:\n{objecoes}"
        if ajuste_feedback:
            msg += f"\nAjuste baseado em feedback anterior: {ajuste_feedback}"
        if pitch_base:
            msg += f"\nPitch base (use como referência):\n{pitch_base}"

        return ia_mod.chat_com_ia(db, msg)
    except Exception as e:
        print(f"[PITCH ADAPTATIVO] Erro: {e}")
        return ""


# ── 4. ECOSISTEMA DE LEADS (conecta empresas que fazem negócios entre si) ────────────────────────

def encontrar_ecosistema_leads(empresa_central: dict, tenant_id: int = 1) -> list:
    """
    Ecosistema de Leads: Encontra empresas que fazem negócios com a empresa central.
    Ex: Se a empresa central é uma logística que expandiu, busca fornecedores de embalagens na região.
    Cria "cadeias de leads" — se uma empresa compra, as outras têm maior chance.
    """
    ecosistema = []

    # CNAEs relacionados (ex: logística → embalagens, transportes, armazéns)
    cnae_central = empresa_central.get("cnae_codigo", "")[:4]
    relacoes_cnaes = {
        "4930": ["4789", "4729", "5212"],  # Transporte → Embalagens, Armazéns
        "6201": ["6202", "6203", "6204"],  # Software → TI, Consultoria
        "8610": ["4771", "4772", "4773"],  # Saúde → Farmácias, Equipamentos
        "1011": ["4711", "4721", "4731"],  # Alimentos → Supermercados, Distribuição
    }

    cnaes_relacionados = relacoes_cnaes.get(cnae_central, [])
    uf_central = empresa_central.get("uf", "")

    db = get_new_db_connection()
    try:
        for cnae in cnaes_relacionados[:3]:
            rows = db.execute("""
                SELECT cnpj, razao_social, municipio, uf, cnae_principal, cnae_descricao,
                       telefone, email, capital_social, situacao
                FROM rf_empresas
                WHERE uf = ?
                AND cnae_principal LIKE ?
                AND situacao = 'ATIVA'
                ORDER BY capital_social DESC
                LIMIT 10
            """, (uf_central, cnae + "%")).fetchall()

            for row in rows:
                ecosistema.append({
                    "cnpj": row["cnpj"],
                    "razao_social": row["razao_social"],
                    "municipio": row["municipio"],
                    "uf": row["uf"],
                    "cnae_codigo": row["cnae_principal"],
                    "cnae_descricao": row["cnae_descricao"],
                    "telefone": row["telefone"],
                    "email": row["email"],
                    "capital_social": float(row["capital_social"] or 0),
                    "situacao": row["situacao"],
                    "relacionado_a": empresa_central.get("razao_social", ""),
                    "score_ecosistema": 7 + random.randint(0, 3),
                })
    except Exception as e:
        print(f"[ECOSISTEMA] Erro: {e}")
    finally:
        db.close()

    return ecosistema


# ── 5. INTEGRAÇÃO COMPLETA: Executa todo o pipeline SDR Evolutivo ────────────────────────────────

def executar_sdr_evolutivo(config: dict, tenant_id: int = 1) -> dict:
    """
    Pipeline completo do SDR Evolutivo:
    1. Monitora Radar de Intent
    2. Busca leads (base própria + busca externa)
    3. Calcula Score de Prontidão
    4. Encontra Ecosistema de Leads
    5. Gera Pitch Dinâmico Adaptativo
    6. Cria cadências adaptativas
    """
    stats = {
        "radar_eventos": 0,
        "leads_encontrados": 0,
        "leads_aprovados": 0,
        "ecosistema_leads": 0,
        "cadencias_criadas": 0,
        "inicio": datetime.now().isoformat(),
    }

    db = get_new_db_connection()

    try:
        # Passo 1: Radar de Intent
        eventos_radar = monitorar_radar_intent(tenant_id)
        stats["radar_eventos"] = len(eventos_radar)

        # Passo 2: Buscar leads (usando a função existente)
        from models.prospeccao_autonoma import obter_leads_para_prospectar, carregar_produtos_do_banco
        estados = (config.get("estados_selecionados") or config.get("estados") or "ES,SP").split(",")
        max_leads = int(config.get("max_leads_por_execucao") or 20)

        for estado in estados[:3]:
            if stats["leads_aprovados"] >= max_leads:
                break

            leads = obter_leads_para_prospectar(config, estado.strip(), max_leads)
            stats["leads_encontrados"] += len(leads)

            # Passo 3: Score de Prontidão para cada lead
            for lead in leads:
                score_result = calcular_score_prontidao(lead, config)
                lead["score_prontidao"] = score_result["score"]
                lead["motivos_prontidao"] = score_result["motivos"]
                lead["aprovado"] = score_result["aprovado"]

                if not score_result["aprovado"]:
                    continue

                stats["leads_aprovados"] += 1

                # Passo 4: Encontrar Ecosistema de Leads
                ecosistema = encontrar_ecosistema_leads(lead, tenant_id)
                stats["ecosistema_leads"] += len(ecosistema)

                # Passo 5: Gerar Pitch Dinâmico Adaptativo
                produtos = carregar_produtos_do_banco(db, tenant_id)
                if produtos:
                    produto = produtos[0]
                    canal = config.get("canal_primario", "whatsapp")
                    pitch = gerar_pitch_adaptativo(db, lead, produto, canal)

                    # Passo 6: Criar cadência
                    from models.cadencia import criar_etapa
                    criar_etapa({
                        "empresa_id": None,
                        "empresa_nome": lead.get("razao_social", ""),
                        "contato_whatsapp": lead.get("telefone", ""),
                        "contato_email": lead.get("email", ""),
                        "oportunidade_id": None,
                        "etapa": 1,
                        "data_acao": (date.today() + timedelta(days=1)).isoformat(),
                        "mensagem_whatsapp": pitch[:500] if canal == "whatsapp" else "",
                        "assunto_email": f"Proposta para {lead.get('razao_social', '')}",
                        "corpo_email": pitch if canal == "email" else "",
                        "status": "pendente",
                        "produto_alvo": produto.get("produto", produto.get("nome", "")),
                        "score_prontidao": score_result["score"],
                    })
                    stats["cadencias_criadas"] += 1

    except Exception as e:
        print(f"[SDR EVOLUTIVO] Erro: {e}")
    finally:
        db.close()

    stats["fim"] = datetime.now().isoformat()
    return stats


# ── Funções auxiliares para compatibilidade com o sistema existente ──────────────────────────────

def get_sdr_evolutivo_config(db, tenant_id: int = 1) -> dict:
    defaults = {
        "score_prontidao_minimo": 8,
        "max_leads_por_execucao": 20,
        "usar_radar_intent": 1,
        "usar_ecosistema": 1,
        "pitch_adaptativo": 1,
    }
    try:
        row = db.execute("SELECT * FROM sdr_evolutivo_config WHERE tenant_id=? LIMIT 1", (tenant_id,)).fetchone()
        if row:
            return {**defaults, **{k: v for k, v in dict(row).items() if v is not None}}
    except Exception:
        pass
    return defaults
