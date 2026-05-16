import os
import json
import requests
from datetime import datetime, timedelta
from database import get_connection, get_new_db_connection


# ── helpers antigos mantidos (contar_nao_lidos é chamado pelo context processor) ──

def contar_nao_lidos() -> dict:
    try:
        conn = get_connection()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM radar_alertas WHERE lido=0 AND arquivado=0"
            ).fetchone()["n"]
        except Exception:
            total = 0
        conn.close()
        return {"editais": 0, "concorrentes": 0, "total": total}
    except Exception:
        return {"editais": 0, "concorrentes": 0, "total": 0}


# ── Claude helper ─────────────────────────────────────────────────────────────

def _claude(prompt, max_tokens=1000):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    r = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return r.content[0].text.strip()


# ── PARTE 2: gerador de palavras-chave ───────────────────────────────────────

def gerar_palavras_chave_tenant(tenant_id):
    db = get_new_db_connection()
    tenant = db.execute(
        "SELECT * FROM tenants WHERE id = %s", (tenant_id,)
    ).fetchone()
    config_tenant = db.execute(
        "SELECT * FROM tenant_config WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    db.close()

    if not tenant:
        return []

    nome      = tenant['nome_empresa'] if tenant else ''
    ramo      = config_tenant['ramo_principal'] if config_tenant else ''
    produtos  = config_tenant['produtos_texto'] if config_tenant else ''

    prompt = f"""Empresa: {nome}
Ramo: {ramo}
Produtos/Serviços: {produtos}

Gere palavras-chave para monitorar no Google News, PNCP e DOU.
Foco em oportunidades comerciais B2B e licitações no Brasil.

Retorne APENAS JSON:
{{
  "busca_google": ["termo1", "termo2"],
  "busca_editais": ["termo edital 1", "termo edital 2"],
  "concorrentes": ["concorrente1"],
  "tendencias": ["tendencia setor 1"]
}}"""

    try:
        resp = _claude(prompt, 500)
        resp = resp.replace('```json', '').replace('```', '')
        dados = json.loads(resp)
        todas = dados.get('busca_google', []) + dados.get('busca_editais', [])
        palavras_str = ','.join(todas[:15])

        db = get_new_db_connection()
        existing = db.execute(
            "SELECT id FROM radar_config WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if existing:
            db.execute(
                "UPDATE radar_config SET palavras_chave = %s, atualizado_em = %s WHERE tenant_id = %s",
                (palavras_str, now_str, tenant_id)
            )
        else:
            db.execute(
                "INSERT INTO radar_config (tenant_id, palavras_chave, ativo) VALUES (%s, %s, 1)",
                (tenant_id, palavras_str)
            )
        db.commit()
        db.close()
        return todas
    except Exception as e:
        print(f'[RADAR] Palavras-chave erro: {e}')
        return []


# ── PARTE 3: Google News RSS ──────────────────────────────────────────────────

def monitorar_google_news(tenant_id):
    import feedparser

    db = get_new_db_connection()
    config = db.execute(
        "SELECT * FROM radar_config WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()

    if not config or not config['ativo']:
        db.close()
        return 0

    palavras_raw = config['palavras_chave'] or ''
    palavras = [p.strip() for p in palavras_raw.split(',') if p.strip()][:5]
    total = 0

    for palavra in palavras:
        try:
            url = (
                f'https://news.google.com/rss/search?'
                f'q={requests.utils.quote(palavra)}'
                f'&hl=pt-BR&gl=BR&ceid=BR:pt-419'
            )
            feed = feedparser.parse(url)

            for entry in feed.entries[:5]:
                titulo    = (entry.get('title', '') or '')[:300]
                descricao = (entry.get('summary', '') or '')[:500]
                link      = entry.get('link', '') or ''

                if not titulo:
                    continue

                existing = db.execute(
                    "SELECT id FROM radar_alertas WHERE tenant_id = %s AND url_original = %s",
                    (tenant_id, link)
                ).fetchone()
                if existing:
                    continue

                try:
                    db.execute("""
                        INSERT INTO radar_alertas
                        (tenant_id, tipo, titulo, descricao, fonte, url_original,
                         palavras_chave, relevancia)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (tenant_id, 'noticia', titulo, descricao,
                          'Google News', link, palavra, 60))
                    total += 1
                except Exception:
                    pass

            db.commit()
        except Exception as e:
            print(f'[RADAR NEWS] Erro para "{palavra}": {e}')

    db.close()
    return total


# ── PARTE 4: PNCP editais ────────────────────────────────────────────────────

def monitorar_pncp(tenant_id):
    db = get_new_db_connection()
    config = db.execute(
        "SELECT * FROM radar_config WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()

    if not config:
        db.close()
        return 0

    palavras_raw = config['palavras_chave'] or ''
    palavras = [p.strip() for p in palavras_raw.split(',') if p.strip()][:3]
    estados  = [e.strip() for e in (config['estados'] or 'ES').split(',') if e.strip()]

    total    = 0
    data_ini = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
    data_fim = datetime.now().strftime('%Y%m%d')

    for estado in estados[:3]:
        try:
            url = (
                f'https://pncp.gov.br/api/pncp/v1/orgaos/compras'
                f'?dataInicial={data_ini}&dataFinal={data_fim}'
                f'&uf={estado}&pagina=1&tamanhoPagina=50'
            )
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue

            dados = r.json()
            itens = (dados if isinstance(dados, list)
                     else dados.get('data', dados.get('items', [])))

            for item in itens:
                objeto = str(item.get('objeto', item.get('descricao', '')))
                if not any(p.lower() in objeto.lower() for p in palavras):
                    continue

                titulo    = objeto[:300]
                orgao_raw = item.get('orgaoEntidade', {})
                orgao_str = orgao_raw.get('razaoSocial', '') if isinstance(orgao_raw, dict) else str(orgao_raw)
                valor     = float(item.get('valorTotal', 0) or 0)
                url_edital = item.get('linkSistemaOrigem', '')

                existing = db.execute(
                    "SELECT id FROM radar_alertas WHERE tenant_id = %s AND url_original = %s",
                    (tenant_id, url_edital)
                ).fetchone()
                if existing:
                    continue

                try:
                    db.execute("""
                        INSERT INTO radar_alertas
                        (tenant_id, tipo, titulo, descricao, fonte, url_original,
                         valor_estimado, estado, orgao, relevancia)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (tenant_id, 'edital', titulo, objeto[:500],
                          'PNCP', url_edital, valor, estado, orgao_str[:200], 85))
                    total += 1
                except Exception:
                    pass

            db.commit()
        except Exception as e:
            print(f'[RADAR PNCP] Erro {estado}: {e}')

    db.close()
    return total


# ── PARTE 5: IA analisa e gera conteúdo ──────────────────────────────────────

def gerar_insights_e_conteudo(tenant_id):
    db = get_new_db_connection()

    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    alertas = db.execute("""
        SELECT tipo, titulo, descricao, fonte, valor_estimado
        FROM radar_alertas
        WHERE tenant_id = %s
          AND criado_em > %s
          AND conteudo_gerado IS NULL
        ORDER BY relevancia DESC
        LIMIT 10
    """, (tenant_id, cutoff)).fetchall()

    tenant   = db.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
    config_t = db.execute("SELECT * FROM tenant_config WHERE tenant_id = %s", (tenant_id,)).fetchone()

    if not alertas or not tenant:
        db.close()
        return 0

    contexto_alertas = '\n'.join([
        f"- [{(a['tipo'] or '').upper()}] {a['titulo']}: {(a['descricao'] or '')[:100]}"
        for a in alertas
    ])

    nome_empresa = tenant['nome_empresa']
    produtos     = config_t['produtos_texto'] if config_t else ''

    # INSIGHT 1: análise do mercado
    prompt_insight = f"""Você é analista de mercado especialista em benefícios corporativos no Brasil.

EMPRESA: {nome_empresa}
PRODUTOS: {produtos}

DADOS COLETADOS HOJE:
{contexto_alertas}

Analise e responda em JSON:
{{
  "tendencia_principal": "descrição em 1 frase",
  "oportunidade_imediata": "ação concreta para hoje",
  "ameaca_identificada": "risco ou concorrente movimentando",
  "sugestao_produto": "melhoria ou novo produto a considerar",
  "score_mercado": 75
}}"""

    try:
        resp_insight = _claude(prompt_insight, 600)
        resp_insight = resp_insight.replace('```json', '').replace('```', '')
        insight = json.loads(resp_insight)
        db.execute("""
            INSERT INTO radar_insights (tenant_id, tipo, titulo, conteudo, fonte_dados)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            tenant_id, 'analise_mercado',
            insight.get('tendencia_principal', '')[:200],
            json.dumps(insight, ensure_ascii=False),
            f'{len(alertas)} alertas analisados'
        ))
        db.commit()
    except Exception as e:
        print(f'[RADAR INSIGHT] Erro: {e}')

    # CONTEÚDO 2: Post LinkedIn
    prompt_post = f"""Baseado nesses dados de mercado:
{contexto_alertas}

Crie um post para LinkedIn da empresa {nome_empresa} que atua com {produtos}.
- Compartilhe um insight do mercado (sem vender)
- Educativo, gera autoridade
- 150-200 palavras, tom profissional mas humano
- Termine com pergunta para engajamento
- Inclua 3 hashtags relevantes

Retorne APENAS o texto do post."""

    try:
        post_linkedin = _claude(prompt_post, 400)
        db.execute("""
            INSERT INTO radar_alertas
            (tenant_id, tipo, titulo, conteudo_gerado, tipo_conteudo, fonte, relevancia)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, 'conteudo',
            f'Post LinkedIn — {datetime.now().strftime("%d/%m")}',
            post_linkedin, 'post_linkedin', 'IA Krylo', 70
        ))
        db.commit()
    except Exception as e:
        print(f'[RADAR CONTEUDO] LinkedIn erro: {e}')

    # CONTEÚDO 3: Email de pitch
    prompt_email = f"""Baseado na tendência de mercado:
{contexto_alertas[:300]}

Crie email de prospecção para {nome_empresa} que vende {produtos}.
- Mencione algo atual do mercado (urgência real)
- Máx 150 palavras, assunto chamativo, CTA claro

Retorne JSON:
{{"assunto": "...", "corpo": "..."}}"""

    try:
        resp_email = _claude(prompt_email, 400)
        resp_email = resp_email.replace('```json', '').replace('```', '')
        email_data = json.loads(resp_email)
        db.execute("""
            INSERT INTO radar_alertas
            (tenant_id, tipo, titulo, conteudo_gerado, tipo_conteudo, fonte, relevancia)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, 'conteudo',
            f"Email: {email_data.get('assunto', '')}",
            email_data.get('corpo', ''), 'email_pitch', 'IA Krylo', 75
        ))
        db.commit()
    except Exception as e:
        print(f'[RADAR CONTEUDO] Email erro: {e}')

    # CONTEÚDO 4: WhatsApp
    primeiro_titulo = alertas[0]['titulo'] if alertas else 'mercado aquecido'
    prompt_wpp = f"""Crie mensagem WhatsApp de prospecção baseada nessa oportunidade:
{primeiro_titulo}

Empresa: {nome_empresa} | Produto: {produtos}
- Máx 3 parágrafos, mencione algo atual/real
- Não pareça spam, CTA suave

Retorne apenas o texto da mensagem."""

    try:
        wpp = _claude(prompt_wpp, 300)
        db.execute("""
            INSERT INTO radar_alertas
            (tenant_id, tipo, titulo, conteudo_gerado, tipo_conteudo, fonte, relevancia)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, 'conteudo',
            f'WhatsApp — {datetime.now().strftime("%d/%m")}',
            wpp, 'whatsapp', 'IA Krylo', 70
        ))
        db.commit()
    except Exception as e:
        print(f'[RADAR CONTEUDO] WhatsApp erro: {e}')

    db.close()
    return len(alertas)


# ── PARTE 6: runners ──────────────────────────────────────────────────────────

def rodar_radar_completo(tenant_id):
    print(f'[RADAR] Iniciando para tenant {tenant_id}')

    db = get_new_db_connection()
    config = db.execute(
        "SELECT palavras_chave FROM radar_config WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    db.close()

    if not config or not config['palavras_chave']:
        gerar_palavras_chave_tenant(tenant_id)

    n_news   = monitorar_google_news(tenant_id)
    n_pncp   = monitorar_pncp(tenant_id)
    n_insights = gerar_insights_e_conteudo(tenant_id)

    # atualiza ultima_busca
    try:
        db = get_new_db_connection()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "UPDATE radar_config SET ultima_busca = %s WHERE tenant_id = %s",
            (now_str, tenant_id)
        )
        db.commit()
        db.close()
    except Exception:
        pass

    total = n_news + n_pncp
    print(f'[RADAR] Concluído: {n_news} notícias, {n_pncp} editais, {n_insights} insights')
    return total


def rodar_radar_todos_tenants():
    db = get_new_db_connection()
    tenants = db.execute("SELECT id FROM tenants WHERE ativo = 1").fetchall()
    db.close()

    total = 0
    for t in tenants:
        try:
            total += rodar_radar_completo(t['id'])
        except Exception as e:
            print(f'[RADAR] Erro tenant {t["id"]}: {e}')
    return total
