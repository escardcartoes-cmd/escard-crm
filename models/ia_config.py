"""
Configuração centralizada da IA — lida do banco ia_config.
Usado por todas as chamadas Claude no sistema para manter
personalidade, tom e estratégia consistentes.
"""
import os
import anthropic

_DEFAULTS = {
    "nome_assistente":    "Bia",
    "personalidade":      "Profissional, direta e empática. Fala de forma natural e consultiva, nunca como vendedora agressiva.",
    "tom":                "consultivo",
    "estrategia":         "Foco em entender a dor do cliente antes de apresentar solução. Perguntar antes de propor.",
    "estilo_escrita":     "Mensagens curtas no WhatsApp (máximo 2 frases). E-mails formais mas acessíveis. Sem jargões técnicos.",
    "contexto_empresa":   "Krylo é uma empresa de cartão de benefícios B2B oferecendo VR, VA, combustível, premiação, Welhub e Vidalink.",
    "objetivo_principal": "Qualificar leads e agendar reuniões com decisores de RH.",
    "restricoes":         "Nunca mencionar concorrentes. Nunca prometer preços sem consultar o time. Nunca ser insistente após 3 tentativas.",
    "saudacao_whatsapp":  "Olá {nome}! Tudo bem? Sou a Bia da Krylo.",
    "saudacao_email":     "Prezado(a) {nome},",
    "assinatura_email":   "Atenciosamente,\nBia | Consultora Krylo\ncontato@krylo.com.br",
}


def get_empresa_config(db) -> dict:
    """Retorna configuração da empresa proprietária do banco."""
    try:
        row = db.execute("SELECT * FROM empresa_config WHERE id=1").fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return {}


def get_ia_config(db) -> dict:
    """Retorna configuração da IA do banco. db deve ser um objeto de conexão."""
    try:
        row = db.execute("SELECT * FROM ia_config WHERE id=1").fetchone()
        if row:
            return {**_DEFAULTS, **{k: v for k, v in dict(row).items() if v is not None}}
    except Exception:
        pass
    return dict(_DEFAULTS)


def get_system_prompt(db, contexto_adicional: str = "") -> str:
    """Monta o system prompt completo com as configurações da IA."""
    cfg = get_ia_config(db)
    prompt = f"""Você é {cfg['nome_assistente']}, assistente de vendas da Krylo.

PERSONALIDADE:
{cfg['personalidade']}

TOM DE COMUNICAÇÃO:
{cfg['tom']}

ESTRATÉGIA DE VENDAS:
{cfg['estrategia']}

ESTILO DE ESCRITA:
{cfg['estilo_escrita']}

CONTEXTO DA EMPRESA:
{cfg['contexto_empresa']}

OBJETIVO PRINCIPAL:
{cfg['objetivo_principal']}

RESTRIÇÕES ABSOLUTAS:
{cfg['restricoes']}"""

    empresa = get_empresa_config(db)
    if empresa.get("nome"):
        prompt += f"""

SOBRE A EMPRESA QUE VOCÊ REPRESENTA:
Nome: {empresa.get('nome', 'Krylo')}
Ramo: {empresa.get('ramo_atividade', '')}
Descrição: {empresa.get('descricao', '')}
Missão: {empresa.get('missao', '')}
Diferenciais: {empresa.get('diferenciais', '')}
Público-alvo: {empresa.get('publico_alvo', '')}
Produtos/Serviços: {empresa.get('produtos_servicos', '')}
Região: {empresa.get('regiao_atuacao', '')}
Histórico: {empresa.get('historico', '')}
Tom da marca: {empresa.get('tom_da_marca', '')}
Concorrentes: {empresa.get('concorrentes', '')}
Site: {empresa.get('site', '')}
Instagram: {empresa.get('instagram', '')}
LinkedIn: {empresa.get('linkedin', '')}

USE SEMPRE o nome "{empresa.get('nome', 'Krylo')}" ao se referir à empresa."""

    if contexto_adicional:
        prompt += f"\n\nCONTEXTO ADICIONAL:\n{contexto_adicional}"

    return prompt


def get_system_prompt_cached(contexto_adicional: str = "") -> str:
    """
    Versão sem parâmetro db — abre e fecha sua própria conexão.
    Use em models/ que não recebem db como argumento.
    """
    from database import get_connection
    conn = get_connection()
    try:
        return get_system_prompt(conn, contexto_adicional)
    except Exception:
        return _fallback_prompt(contexto_adicional)
    finally:
        conn.close()


def _fallback_prompt(contexto_adicional: str = "") -> str:
    cfg = _DEFAULTS
    prompt = f"""Você é {cfg['nome_assistente']}, assistente de vendas da Krylo.\n{cfg['personalidade']}"""
    if contexto_adicional:
        prompt += f"\n\nCONTEXTO ADICIONAL:\n{contexto_adicional}"
    return prompt


def chat_com_ia(db, mensagem: str, historico: list = None, contexto: str = "") -> str:
    """Envia mensagem para Claude com o system prompt configurado. Retorna texto da resposta."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    system = get_system_prompt(db, contexto)
    msgs = []
    for h in (historico or [])[-20:]:
        role = h.get("role")
        text = h.get("content", "")
        if role in ("user", "assistant") and text:
            msgs.append({"role": role, "content": text})
    msgs.append({"role": "user", "content": mensagem})
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=system,
        messages=msgs,
    )
    return resp.content[0].text
