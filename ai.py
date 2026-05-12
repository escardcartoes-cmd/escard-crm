import json
import os
from dotenv import load_dotenv
load_dotenv(override=True)

import anthropic

MODEL = "claude-sonnet-4-6"
_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key or key == "sua-chave-aqui":
            raise ValueError("Configure ANTHROPIC_API_KEY no arquivo .env")
        _client = anthropic.Anthropic(api_key=key)
    return _client


def _parse_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("Resposta inesperada da IA — tente novamente")
    return json.loads(text[start:end])


def score_lead(empresa_id: int) -> dict:
    import models.empresa as emp_model
    import models.contato as cont_model
    import models.oportunidade as op_model
    import models.atividade as atv_model

    emp = emp_model.buscar_por_id(empresa_id)
    if not emp:
        raise ValueError("Empresa não encontrada")

    contatos  = cont_model.listar(empresa_id=empresa_id)
    ops       = op_model.listar(empresa_id=empresa_id)
    atividades = atv_model.listar(empresa_id=empresa_id, limit=10)
    valores   = [o["valor_estimado"] for o in ops if o["valor_estimado"]]
    estagios  = [o["estagio"] for o in ops]

    prompt = f"""Você é um analista de CRM da Escard, empresa de cartão de benefícios B2B.

Avalie o lead abaixo e retorne SOMENTE um JSON válido, sem texto extra:
{{"score": <0-100>, "justificativa": "<2-3 frases>", "pontos_fortes": ["..."], "pontos_fracos": ["..."]}}

Dados:
- Empresa: {emp['nome']}
- Segmento: {emp['segmento'] or 'não informado'}
- Porte: {emp['porte'] or 'não informado'}
- Status: {emp['status']}
- Contatos cadastrados: {len(contatos)}
- Oportunidades: {len(ops)} — estágios: {estagios}
- Valor total em oportunidades: R$ {sum(valores):,.2f}
- Atividades registradas: {len(atividades)}"""

    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text)


def gerar_mensagem_whatsapp(contato_id: int) -> dict:
    import models.contato as cont_model
    import models.empresa as emp_model
    import models.oportunidade as op_model

    contato = cont_model.buscar_por_id(contato_id)
    if not contato:
        raise ValueError("Contato não encontrado")

    emp = emp_model.buscar_por_id(contato["empresa_id"])
    ops = op_model.listar(empresa_id=emp["id"])
    estagio = ops[0]["estagio"] if ops else "sem negociação ativa"

    prompt = f"""Você é um consultor comercial da Escard, empresa de cartão de benefícios B2B.

Crie uma mensagem de WhatsApp personalizada para o contato abaixo.
Regras: cordial e profissional, máximo 5 linhas, destaque um benefício do cartão Escard relevante para o segmento, termine com call-to-action claro.
Retorne SOMENTE um JSON válido: {{"mensagem": "<texto completo>"}}

Contato: {contato['nome']}, {contato['cargo'] or 'colaborador'} — {emp['nome']}
Segmento: {emp['segmento'] or 'não informado'} | Porte: {emp['porte'] or 'não informado'}
Status: {emp['status']} | Negociação: {estagio}"""

    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text)


def gerar_whatsapp_lead(prospeccao_id: int) -> dict:
    import models.prospeccao as prosp_model

    lead = prosp_model.buscar_por_id(prospeccao_id)
    if not lead:
        raise ValueError("Lead não encontrado")

    pontos_fortes = []
    if lead["score_pontos_fortes"]:
        try:
            pontos_fortes = json.loads(lead["score_pontos_fortes"])
        except Exception:
            pass

    prompt = f"""Você é um consultor comercial da Escard, empresa brasileira de cartão de benefícios B2B.

Produtos Escard: alimentação, refeição, combustível, premiação, Welhub (bem-estar), Vidalink (farmácia), Viva+ (saúde).
Dor do cliente: gerenciar múltiplos cartões de benefícios é caro e complexo.
Tom: consultivo, direto, não agressivo. Empresas ideais: 20 a 20.000 funcionários.

Crie uma mensagem de WhatsApp de primeiro contato para o lead abaixo.
Regras: máximo 5 linhas, identifique e recomende UM produto Escard específico para o segmento, termine com call-to-action claro para uma conversa de 15 minutos.
Retorne SOMENTE um JSON válido: {{"mensagem": "<texto completo>"}}

Contato: {lead["contato_nome"]}, {lead["cargo"] or "cargo não informado"} — {lead["empresa_nome"]}
Segmento: {lead["segmento"] or "não informado"} | Porte: {lead["porte"] or "não informado"}
Score: {lead["score"] if lead["score"] is not None else "não calculado"}
Pontos fortes: {", ".join(pontos_fortes) if pontos_fortes else "não disponível"}"""

    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text)


def gerar_email_lead(prospeccao_id: int) -> dict:
    import models.prospeccao as prosp_model

    lead = prosp_model.buscar_por_id(prospeccao_id)
    if not lead:
        raise ValueError("Lead não encontrado")

    pontos_fortes = []
    if lead["score_pontos_fortes"]:
        try:
            pontos_fortes = json.loads(lead["score_pontos_fortes"])
        except Exception:
            pass

    prompt = f"""Você é um consultor comercial da Escard, empresa brasileira de cartão de benefícios B2B.

Produtos Escard: alimentação, refeição, combustível, premiação, Welhub (bem-estar), Vidalink (farmácia), Viva+ (saúde).
Dor do cliente: gerenciar múltiplos benefícios é caro e burocrático.
Tom: consultivo, profissional, não agressivo.

Crie um e-mail comercial de primeiro contato. Regras: assunto direto com no máximo 10 palavras; corpo com 3 parágrafos curtos (dor específica do segmento → como Escard resolve → CTA para reunião de 15 minutos); recomende UM produto Escard específico para o segmento.
Retorne SOMENTE um JSON válido:
{{"assunto": "<assunto do e-mail>", "corpo": "<corpo completo do e-mail>"}}

Contato: {lead["contato_nome"]}, {lead["cargo"] or "cargo não informado"} — {lead["empresa_nome"]}
Segmento: {lead["segmento"] or "não informado"} | Porte: {lead["porte"] or "não informado"}
Score: {lead["score"] if lead["score"] is not None else "não calculado"}
Pontos fortes: {", ".join(pontos_fortes) if pontos_fortes else "não disponível"}"""

    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text)


def proxima_acao(oportunidade_id: int) -> dict:
    import models.oportunidade as op_model
    import models.empresa as emp_model
    import models.atividade as atv_model

    op = op_model.buscar_por_id(oportunidade_id)
    if not op:
        raise ValueError("Oportunidade não encontrada")

    emp = emp_model.buscar_por_id(op["empresa_id"])
    atividades = atv_model.listar(oportunidade_id=oportunidade_id, limit=5)
    historico = "\n".join(
        f"  - {a['data']}: {a['tipo']} — {a['descricao'] or 'sem descrição'}"
        for a in atividades
    ) or "  (nenhuma atividade registrada)"

    prompt = f"""Você é um coach de vendas B2B especializado em benefícios corporativos.

Sugira a próxima ação concreta que o vendedor deve executar nesta oportunidade.
Retorne SOMENTE um JSON válido:
{{"acao": "<ação específica>", "urgencia": "alta|media|baixa", "prazo": "<hoje|amanhã|X dias|esta semana>", "motivo": "<por que agora>"}}

Oportunidade: {op['titulo']}
Empresa: {emp['nome']} ({emp['segmento'] or 'N/A'}, porte {emp['porte'] or 'N/A'})
Estágio: {op['estagio']} | Valor: R$ {op['valor_estimado'] or 0:,.2f} | Cartões: {op['num_cartoes'] or 'N/A'}
Responsável: {op['responsavel'] or 'N/A'} | Fechamento previsto: {op['previsao_fechamento'] or 'N/A'}
Notas: {op['notas'] or 'sem notas'}
Histórico:
{historico}"""

    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text)
