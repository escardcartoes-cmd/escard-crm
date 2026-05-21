"""SDR — busca leads importados e cria cadências. Sem score, sem filtros externos."""
import logging
from datetime import date, timedelta
from database import get_new_db_connection

logger = logging.getLogger(__name__)

# ── Pitches por segmento: (assunto_email, corpo_email, msg_whatsapp) ─────────

_PITCHES = {
    "saude": (
        "Benefícios de saúde para sua equipe",
        "Olá,\n\nSomos a Escard Cartões e Benefícios. Ajudamos empresas do setor de saúde "
        "a oferecer VR, VA e Wellhub em um único cartão — com menos burocracia e mais vantagens.\n\n"
        "Podemos agendar 15 minutos para mostrar os números?\n\nAbraços,\nEquipe Escard",
        "Oi! Sou da Escard. Ajudamos empresas de saúde como {empresa} a simplificar benefícios. "
        "Posso mostrar como? 👋",
    ),
    "comercio": (
        "Reduza custos com benefícios — proposta para {empresa}",
        "Olá,\n\nSomos a Escard Cartões e Benefícios. Empresas do comércio que usam nosso cartão "
        "reduzem até 20% nos custos administrativos de benefícios.\n\n"
        "Posso mostrar como funciona em 15 minutos?\n\nAbraços,\nEquipe Escard",
        "Oi! Sou da Escard. Ajudamos {empresa} a reduzir custos com VR/VA. Posso mostrar como? 👋",
    ),
    "industria": (
        "Cartão de benefícios para sua equipe industrial",
        "Olá,\n\nSomos a Escard Cartões e Benefícios. Consolidamos VR, VA e combustível em um único "
        "cartão — ideal para empresas industriais com equipes no campo.\n\n"
        "Posso agendar 15 minutos?\n\nAbraços,\nEquipe Escard",
        "Oi! Sou da Escard. Simplificamos benefícios para equipes industriais como a de {empresa}. "
        "Posso mostrar? 👋",
    ),
    "servico": (
        "Benefícios corporativos para {empresa}",
        "Olá,\n\nSomos a Escard Cartões e Benefícios. Ajudamos empresas de serviços a oferecer "
        "VR, VA e outros benefícios em um único cartão moderno.\n\n"
        "Tem 15 minutos para conhecer?\n\nAbraços,\nEquipe Escard",
        "Oi! Sou da Escard. Ajudamos {empresa} a modernizar benefícios. Posso mostrar como? 👋",
    ),
    "tecnologia": (
        "Benefícios que sua equipe de TI merece",
        "Olá,\n\nSomos a Escard. Empresas de tecnologia usam nosso cartão para oferecer "
        "VR, VA e Wellhub com gestão 100% digital — sem papel, sem burocracia.\n\n"
        "Posso mostrar em 15 minutos?\n\nAbraços,\nEquipe Escard",
        "Oi! Sou da Escard. Benefícios modernos para equipes de tech como a de {empresa}. "
        "Posso mostrar? 👋",
    ),
}

_ASSUNTO_GENERICO = "Benefícios corporativos para {empresa}"
_EMAIL_GENERICO = (
    "Olá,\n\n"
    "Somos a Escard Cartões e Benefícios e ajudamos empresas a consolidar VR, VA "
    "e outros benefícios em um único cartão — com economia real e menos burocracia.\n\n"
    "Podemos agendar 15 minutos para mostrar os números?\n\n"
    "Abraços,\nEquipe Escard | Cartões e Benefícios"
)
_WA_GENERICO = (
    "Oi! Tudo bem? Sou da Escard Cartões e Benefícios. "
    "Ajudamos empresas como {empresa} a simplificar benefícios (VR, VA, combustível) "
    "em um único cartão. Posso mostrar como? 👋"
)


def _pitch(nome: str, segmento: str, canal: str) -> str:
    seg = (segmento or "").lower()
    for chave, (assunto, corpo, wa) in _PITCHES.items():
        if chave in seg:
            template = wa if canal == "whatsapp" else corpo
            return template.format(empresa=nome)
    if canal == "whatsapp":
        return _WA_GENERICO.format(empresa=nome)
    return _EMAIL_GENERICO


def _assunto(nome: str, segmento: str) -> str:
    seg = (segmento or "").lower()
    for chave, (assunto, _, __) in _PITCHES.items():
        if chave in seg:
            return assunto.format(empresa=nome)
    return _ASSUNTO_GENERICO.format(empresa=nome)


# ── Pipeline principal ────────────────────────────────────────────────────────

def _criar_cadencia_empresa(emp: dict, tenant_id: int):
    from models.cadencia import criar_etapa
    nome = (emp.get("nome") or emp.get("razao_social") or "Empresa").strip()
    fone = emp.get("telefone") or ""
    email = emp.get("email") or ""
    seg = emp.get("segmento") or ""
    hoje = date.today()

    tem_email = bool(email)
    pitch_email = _pitch(nome, seg, "email") if tem_email else ""
    pitch_wa = _pitch(nome, seg, "whatsapp")[:500]
    assunto = _assunto(nome, seg) if tem_email else ""

    base = {
        "empresa_id": emp.get("id"),
        "empresa_nome": nome,
        "contato_whatsapp": fone,
        "contato_email": email,
        "email_empresa": email,
        "oportunidade_id": None,
        "status": "pendente",
        "tenant_id": tenant_id,
    }

    for etapa, dias, c_email, c_wa, assunto_e, corpo_e, msg_wa in [
        (1,  0, 1, 0, assunto,               pitch_email, ""),
        (2,  3, 1, 0, f"Retorno — {nome}",   pitch_email, ""),
        (3,  7, 0, 1, "",                     "",          pitch_wa),
        (4, 10, 0, 1, "",                     "",          pitch_wa),
        (5, 15, 0, 1, "",                     "",          pitch_wa),
    ]:
        criar_etapa({**base,
            "etapa": etapa,
            "data_acao": (hoje + timedelta(days=dias)).isoformat(),
            "canal_email": c_email if tem_email else 0,
            "canal_whatsapp": c_wa,
            "assunto_email": assunto_e,
            "corpo_email": corpo_e,
            "mensagem_whatsapp": msg_wa,
        })


def executar_sdr(tenant_id: int, max_leads: int = 50) -> dict:
    """Busca leads importados sem cadência e cria 5 etapas para cada um."""
    db = get_new_db_connection()
    criadas = 0
    try:
        empresas = db.execute("""
            SELECT id, nome, email, telefone, segmento
            FROM empresas
            WHERE tenant_id = ?
            AND id NOT IN (
                SELECT empresa_id FROM cadencias
                WHERE empresa_id IS NOT NULL AND tenant_id = ?
            )
            ORDER BY criado_em DESC
            LIMIT ?
        """, (tenant_id, tenant_id, max_leads)).fetchall()

        for emp in empresas:
            try:
                _criar_cadencia_empresa(dict(emp), tenant_id)
                criadas += 1
            except Exception as e:
                logger.error("[SDR] Cadência falhou para %s: %s", emp.get("nome"), e)
    except Exception as e:
        logger.error("[SDR] Erro ao buscar leads (tenant=%s): %s", tenant_id, e, exc_info=True)
    finally:
        db.close()

    return {"leads_aprovados": criadas, "cadencias_criadas": criadas}


# ── Config ────────────────────────────────────────────────────────────────────

def get_sdr_evolutivo_config(db, tenant_id: int = 1) -> dict:
    defaults = {"max_leads_por_execucao": 20}
    try:
        row = db.execute(
            "SELECT * FROM sdr_evolutivo_config WHERE tenant_id=? LIMIT 1", (tenant_id,)
        ).fetchone()
        if row:
            return {**defaults, **{k: v for k, v in dict(row).items() if v is not None}}
    except Exception:
        pass
    return defaults
