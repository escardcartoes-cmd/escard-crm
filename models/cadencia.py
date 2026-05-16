import json
import os
import requests as _req
from datetime import date, timedelta
from database import get_connection

ETAPA_LABELS = {
    1: "Apresentação",
    2: "Follow-up (D+3)",
    3: "Proposta de Valor (D+7)",
    4: "Último Contato (D+14)",
}
DIAS_POR_ETAPA = {1: 0, 2: 3, 3: 7, 4: 14}
_ETAPA_KEY = {1: "d0", 2: "d3", 3: "d7", 4: "d14"}


def _brevo_disponivel() -> bool:
    key = os.getenv("BREVO_API_KEY", "")
    return bool(key and len(key) > 10)


def _salvar_email_na_fila(
    destinatario: str,
    nome_destinatario: str,
    assunto: str,
    html: str,
    texto: str = "",
    tenant_id: int = 1,
) -> None:
    try:
        conn = get_connection()
        conn.execute(
            """INSERT INTO email_fila
               (tenant_id, destinatario, nome_destinatario, assunto, html, texto, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pendente')""",
            (tenant_id, destinatario, nome_destinatario or destinatario, assunto, html, texto),
        )
        conn.commit()
        conn.close()
        print(f"[EMAIL FILA] Enfileirado para {destinatario}: {assunto[:50]}")
    except Exception as e:
        print(f"[EMAIL FILA] Erro ao enfileirar: {e}")


def processar_fila_email(tenant_id: int = 1) -> int:
    """Processa emails enfileirados quando Brevo estiver disponível."""
    if not _brevo_disponivel():
        return 0
    conn = get_connection()
    pendentes = [dict(r) for r in conn.execute(
        "SELECT * FROM email_fila WHERE status='pendente' AND tenant_id=? AND tentativas < 3 ORDER BY criado_em ASC LIMIT 20",
        (tenant_id,)
    ).fetchall()]
    conn.close()

    enviados = 0
    for item in pendentes:
        resultado = enviar_email_brevo(
            destinatario_email=item["destinatario"],
            destinatario_nome=item["nome_destinatario"] or "",
            assunto=item["assunto"] or "",
            corpo=item["html"] or item["texto"] or "",
        )
        novo_status = "enviado" if resultado["status"] == "enviado" else "erro"
        agora = str(date.today())
        try:
            conn2 = get_connection()
            conn2.execute(
                "UPDATE email_fila SET status=?, tentativas=tentativas+1, enviado_em=?, erro=? WHERE id=?",
                (novo_status, agora if novo_status == "enviado" else None,
                 None if novo_status == "enviado" else resultado.get("id"), item["id"]),
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass
        if novo_status == "enviado":
            enviados += 1
    return enviados


def enviar_email_brevo(
    destinatario_email: str,
    destinatario_nome: str,
    assunto: str,
    corpo: str,
    nome_remetente: str = "Krylo CRM",
    email_remetente: str = "contato@krylo.com.br",
) -> dict:
    """Envia e-mail transacional via Brevo (requests). Retorna status e message_id."""
    api_key = os.getenv("BREVO_API_KEY", "")
    if not api_key:
        _salvar_email_na_fila(destinatario_email, destinatario_nome, assunto, corpo)
        return {"status": "enfileirado", "id": None}
    try:
        html = corpo if ("<p>" in corpo or "<br" in corpo) else \
               "".join(f"<p>{p}</p>" for p in corpo.split("\n\n") if p.strip())
        resp = _req.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "sender": {"name": nome_remetente, "email": email_remetente},
                "to": [{"email": destinatario_email, "name": destinatario_nome or destinatario_email}],
                "subject": assunto,
                "htmlContent": html or f"<p>{corpo}</p>",
            },
            timeout=10,
        )
        data = resp.json()
        return {"status": "enviado", "id": data.get("messageId", "")}
    except Exception as e:
        print(f"[BREVO] enviar_email_brevo erro: {e}")
        return {"status": "erro", "id": None}


def gerar_email_cadencia(
    empresa_nome: str,
    cnae: str,
    produto: str,
    etapa: str,
    tenant_id: int,
    pitch_whatsapp: str = None,
) -> dict:
    """
    Gera email profissional para cada etapa da cadência via Claude.
    etapa: 'D0', 'D3', 'D7', 'D14'
    Retorna {"assunto": str, "corpo_html": str, "corpo_texto": str}
    """
    from models.ia_config import get_system_prompt_tenant

    etapas_contexto = {
        "D0": {
            "objetivo": "Apresentação inicial — despertar curiosidade, não vender ainda",
            "tom": "cordial e profissional",
            "tamanho": "curto (3-4 parágrafos)",
            "cta": "Solicitar 15 minutos para uma conversa",
        },
        "D3": {
            "objetivo": "Follow-up — reforçar valor, fazer pergunta de dor",
            "tom": "consultivo",
            "tamanho": "muito curto (2-3 parágrafos)",
            "cta": "Responder com disponibilidade de horário",
        },
        "D7": {
            "objetivo": "Proposta de valor — case ou dado concreto",
            "tom": "direto e orientado a resultado",
            "tamanho": "médio (4-5 parágrafos)",
            "cta": "Agendar demonstração",
        },
        "D14": {
            "objetivo": "Última tentativa — criar senso de urgência",
            "tom": "respeitoso mas urgente",
            "tamanho": "curto (2-3 parágrafos)",
            "cta": "Responder sim ou não",
        },
    }

    ctx = etapas_contexto.get(etapa, etapas_contexto["D0"])

    config = ""
    try:
        conn = get_connection()
        config = get_system_prompt_tenant(conn, tenant_id)
        conn.close()
    except Exception:
        pass

    pitch_linha = f"\nMENSAGEM WHATSAPP JÁ ENVIADA: {pitch_whatsapp}" if pitch_whatsapp else ""

    prompt = f"""Gere um email comercial profissional para a etapa {etapa} da cadência.

EMPRESA PROSPECTADA: {empresa_nome}
SEGMENTO: {cnae or 'não informado'}
PRODUTO/SERVIÇO: {produto or 'benefícios corporativos'}
ETAPA: {etapa} — {ctx['objetivo']}
TOM: {ctx['tom']}
TAMANHO: {ctx['tamanho']}
CTA DESEJADO: {ctx['cta']}

CONTEXTO DA EMPRESA VENDEDORA:
{config}
{pitch_linha}

Retorne APENAS um JSON válido, sem markdown, sem explicações:
{{
  "assunto": "Assunto do email (max 60 chars, sem palavras spam)",
  "corpo_html": "<p>HTML completo do email</p>",
  "corpo_texto": "Versão texto puro sem HTML"
}}

O HTML deve ter saudação com nome da empresa, parágrafos com <p>, pontos em <strong>, assinatura profissional."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = response.content[0].text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except Exception as e:
        print(f"[EMAIL CADENCIA] Erro IA: {e}")
        return {
            "assunto": f"Proposta para {empresa_nome}",
            "corpo_html": f"<p>Olá,</p><p>Gostaríamos de apresentar nossa solução para <strong>{empresa_nome}</strong>.</p>",
            "corpo_texto": f"Olá, gostaríamos de apresentar nossa solução para {empresa_nome}.",
        }


def enviar_email_cadencia(cadencia_id: int, etapa_num: int, tenant_id: int) -> bool:
    """
    Gera e envia email da etapa via Brevo. Marca email_d{N}_enviado após sucesso.
    etapa_num: 1=D0, 2=D3, 3=D7, 4=D14
    """
    etapa_str = {1: "D0", 2: "D3", 3: "D7", 4: "D14"}.get(etapa_num, "D0")
    campo_env = f"email_{etapa_str.lower()}_enviado"
    campo_at  = f"email_{etapa_str.lower()}_at"

    conn = get_connection()
    try:
        cad = conn.execute(
            """SELECT c.*, e.email AS email_empresa_db,
                      e.cnae_fiscal_descricao AS cnae
               FROM cadencias c
               LEFT JOIN empresas e ON e.id = c.empresa_id
               WHERE c.id = ?""",
            (cadencia_id,),
        ).fetchone()
        if not cad:
            conn.close()
            return False

        cad = dict(cad)

        if cad.get(campo_env):
            print(f"[EMAIL CADENCIA] {etapa_str} já enviado para cadencia {cadencia_id}")
            conn.close()
            return False

        # Prioridade: email_empresa (campo novo) → contato_email → email da empresa no cadastro
        email_destino = (
            (cad.get("email_empresa") or "").strip()
            or (cad.get("contato_email") or "").strip()
            or (cad.get("email_empresa_db") or "").strip()
        )
        if not email_destino:
            print(f"[EMAIL CADENCIA] Sem email para cadência {cadencia_id}")
            conn.close()
            return False

        t = conn.execute(
            "SELECT nome_plataforma FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        nome_plataforma = (dict(t).get("nome_plataforma") or "Krylo") if t else "Krylo"
        conn.close()

    except Exception as e:
        print(f"[EMAIL CADENCIA] Erro ao buscar cadência: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False

    email_remetente = os.environ.get("EMAIL_ONBOARDING", "contato@krylo.com.br")

    email_data = gerar_email_cadencia(
        empresa_nome=cad.get("empresa_nome") or "",
        cnae=cad.get("cnae") or "",
        produto="",
        etapa=etapa_str,
        tenant_id=tenant_id,
        pitch_whatsapp=cad.get("mensagem_whatsapp"),
    )

    resultado = enviar_email_brevo(
        destinatario_email=email_destino,
        destinatario_nome=cad.get("empresa_nome") or email_destino,
        assunto=email_data["assunto"],
        corpo=email_data["corpo_html"],
        nome_remetente=nome_plataforma,
        email_remetente=email_remetente,
    )

    print(f"[EMAIL CADENCIA] {etapa_str} → {email_destino}: {resultado['status']}")

    agora = str(date.today())
    try:
        conn2 = get_connection()
        conn2.execute(
            f"UPDATE cadencias SET {campo_env}=1, {campo_at}=?, email_status=? WHERE id=?",
            (agora, resultado["status"], cadencia_id),
        )
        conn2.commit()
        conn2.close()
    except Exception as e:
        print(f"[EMAIL CADENCIA] Erro ao atualizar status: {e}")

    return resultado["status"] == "enviado"


def buscar_email_empresa(cnpj: str, nome_empresa: str = "") -> str | None:
    """Busca email da empresa no banco local e, como fallback, na API CNPJ.ws."""
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT email FROM empresas WHERE cnpj = ? AND email IS NOT NULL AND email != ''",
            (cnpj,),
        ).fetchone()
        conn.close()
        if row and row["email"]:
            return row["email"].strip()
    except Exception:
        pass

    try:
        cnpj_limpo = "".join(c for c in str(cnpj or "") if c.isdigit())
        if len(cnpj_limpo) == 14:
            r = _req.get(
                f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}",
                timeout=5,
            )
            if r.status_code == 200:
                email = r.json().get("estabelecimento", {}).get("email")
                if email:
                    return email.lower().strip()
    except Exception:
        pass

    return None


def criar_etapa(dados: dict) -> int:
    # Tenta usar pitch do produto cadastrado para etapa 1 sem mensagem
    if dados.get("etapa") == 1 and not (dados.get("mensagem_whatsapp") or "").strip():
        produto_nome = dados.get("produto_alvo") or ""
        if produto_nome:
            try:
                _c = get_connection()
                _p = _c.execute(
                    "SELECT pitch_whatsapp FROM produtos_krylo WHERE nome=? AND ativo=1",
                    (produto_nome,),
                ).fetchone()
                _c.close()
                if _p and (_p["pitch_whatsapp"] or "").strip():
                    dados = dict(dados)
                    empresa = dados.get("empresa_nome") or ""
                    dados["mensagem_whatsapp"] = _p["pitch_whatsapp"].replace("{empresa}", empresa)
            except Exception:
                pass

    email_empresa = (dados.get("email_empresa") or dados.get("contato_email") or "").strip()
    canal_email   = 1 if dados.get("canal_email", True) else 0
    canal_whatsapp = 1 if dados.get("canal_whatsapp", True) else 0
    tenant_id     = dados.get("tenant_id", 1)

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO cadencias
               (empresa_id, empresa_nome, contato_whatsapp, contato_email,
                oportunidade_id, etapa, data_acao, mensagem_whatsapp,
                assunto_email, corpo_email, status, email_status,
                email_empresa, canal_email, canal_whatsapp, tenant_id)
           VALUES
               (:empresa_id, :empresa_nome, :contato_whatsapp, :contato_email,
                :oportunidade_id, :etapa, :data_acao, :mensagem_whatsapp,
                :assunto_email, :corpo_email, :status, :email_status,
                :email_empresa, :canal_email, :canal_whatsapp, :tenant_id)""",
        {
            **dados,
            "email_status":   dados.get("email_status", "sem_email"),
            "email_empresa":  email_empresa,
            "canal_email":    canal_email,
            "canal_whatsapp": canal_whatsapp,
            "tenant_id":      tenant_id,
        },
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    # Dispara email automático se canal_email ativo e há endereço
    etapa_num = dados.get("etapa", 0)
    if canal_email and email_empresa and etapa_num in (1, 2, 3, 4):
        try:
            enviar_email_cadencia(new_id, etapa_num, tenant_id)
        except Exception as e:
            print(f"[EMAIL CADENCIA] criar_etapa etapa {etapa_num}: {e}")

    return new_id


def _tentar_enviar_email(
    cadencia_id: int,
    empresa_nome: str,
    etapa: int,
    para_email: str,
    assunto: str,
    corpo: str,
) -> None:
    """Legado — gera conteúdo se necessário e envia via Brevo. Silencia erros."""
    try:
        if not assunto or not corpo:
            import ai
            gerado = ai.gerar_email_cadencia(empresa_nome=empresa_nome, etapa=etapa)
            assunto = gerado.get("assunto", assunto)
            corpo   = gerado.get("corpo", corpo)

        resultado = enviar_email_brevo(
            destinatario_email=para_email,
            destinatario_nome=empresa_nome,
            assunto=assunto,
            corpo=corpo,
        )
        novo_status = resultado["status"]
        message_id  = resultado["id"] or ""

        conn = get_connection()
        conn.execute(
            """UPDATE cadencias
               SET assunto_email=:assunto, corpo_email=:corpo,
                   email_status=:es, email_brevo_id=:mid
               WHERE id=:id""",
            {"assunto": assunto, "corpo": corpo, "es": novo_status,
             "mid": message_id, "id": cadencia_id},
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[BREVO] Erro ao processar e-mail para cadência {cadencia_id}: {e}")


def cancelar_por_empresa(empresa_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE cadencias SET status='cancelada' WHERE empresa_id=? AND status='pendente'",
        (empresa_id,),
    )
    conn.commit()
    conn.close()


def listar_hoje(tenant_id=None) -> list:
    today = str(date.today())
    conn = get_connection()
    if tenant_id is not None:
        rows = conn.execute(
            """SELECT * FROM cadencias
               WHERE data_acao = ? AND status='pendente' AND tenant_id = ?
               ORDER BY empresa_nome ASC, etapa ASC""",
            (today, tenant_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM cadencias
               WHERE data_acao = ? AND status='pendente'
               ORDER BY empresa_nome ASC, etapa ASC""",
            (today,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def listar_proximos_dias(n: int = 7, tenant_id=None) -> list:
    tomorrow = str(date.today() + timedelta(days=1))
    cutoff   = str(date.today() + timedelta(days=n))
    conn = get_connection()
    if tenant_id is not None:
        rows = conn.execute(
            """SELECT * FROM cadencias
               WHERE data_acao >= ? AND data_acao <= ? AND status='pendente' AND tenant_id = ?
               ORDER BY data_acao ASC, empresa_nome ASC""",
            (tomorrow, cutoff, tenant_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM cadencias
               WHERE data_acao >= ? AND data_acao <= ? AND status='pendente'
               ORDER BY data_acao ASC, empresa_nome ASC""",
            (tomorrow, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def contar_hoje() -> int:
    today = str(date.today())
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cadencias WHERE data_acao = ? AND status='pendente'",
        (today,),
    ).fetchone()
    conn.close()
    return int(row["n"]) if row else 0


def concluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE cadencias SET status='concluida' WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def cancelar(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE cadencias SET status='cancelada' WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def listar_emails_enviados() -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM cadencias
           WHERE email_status IN ('enviado', 'aberto')
           ORDER BY criado_em DESC""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def atualizar_email_status(id_: int, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE cadencias SET email_status=? WHERE id=?",
        (status, id_),
    )
    conn.commit()
    conn.close()


def _verificar_aberturas_brevo(message_ids: list) -> set:
    api_key = os.getenv("BREVO_API_KEY", "")
    if not api_key or not message_ids:
        return set()
    abertos = set()
    for mid in message_ids:
        try:
            resp = _req.get(
                "https://api.brevo.com/v3/smtp/statistics/events",
                headers={"api-key": api_key},
                params={"messageId": mid, "event": "opened", "limit": 5},
                timeout=8,
            )
            data = resp.json()
            if data.get("events"):
                abertos.add(mid)
        except Exception:
            pass
    return abertos


def sincronizar_aberturas() -> int:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, email_brevo_id FROM cadencias
           WHERE email_status='enviado' AND email_brevo_id IS NOT NULL
             AND email_brevo_id != ''""",
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    ids_map = {r["email_brevo_id"]: r["id"] for r in rows}
    abertos = _verificar_aberturas_brevo(list(ids_map.keys()))

    updated = 0
    for mid in abertos:
        cad_id = ids_map.get(mid)
        if cad_id:
            atualizar_email_status(cad_id, "aberto")
            updated += 1
    return updated


def atualizar_temperatura_lead(empresa_id: int, evento: str, tenant_id: int = 1) -> None:
    """
    Atualiza score e temperatura da empresa baseado em evento de engajamento.
    evento: 'email_aberto', 'email_clicado', 'email_respondido', 'sem_engajamento'
    """
    ajustes = {
        "email_aberto":     +1,
        "email_clicado":    +2,
        "email_respondido": +4,
        "sem_engajamento":  -1,
    }
    delta = ajustes.get(evento, 0)
    if delta == 0:
        return

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT score FROM empresas WHERE id = ?", (empresa_id,)
        ).fetchone()
        score_atual = int(row["score"] if row and row["score"] is not None else 0)
        novo_score = max(0, min(10, score_atual + delta))

        temperatura = "frio"
        if novo_score >= 8:
            temperatura = "quente"
        elif novo_score >= 5:
            temperatura = "morno"

        conn.execute(
            "UPDATE empresas SET score = ?, temperatura = ? WHERE id = ?",
            (novo_score, temperatura, empresa_id),
        )

        if temperatura == "quente":
            conn.execute(
                """UPDATE cadencias SET whatsapp_status = 'aguardando_aprovacao'
                   WHERE empresa_id = ? AND status = 'pendente' AND tenant_id = ?""",
                (empresa_id, tenant_id),
            )
            print(f"[TEMPERATURA] Empresa {empresa_id} ficou QUENTE — adicionada à fila WhatsApp")

        conn.commit()
    except Exception as e:
        print(f"[TEMPERATURA] Erro ao atualizar empresa {empresa_id}: {e}")
    finally:
        conn.close()


def processar_cadencias_pendentes(tenant_id: int = 1) -> int:
    """
    Processa cadências pendentes cuja data_acao já chegou.
    Envia email da etapa atual e cria a próxima (D3→D7→D14).
    """
    from datetime import timedelta

    PROXIMA: dict = {1: (2, 3), 2: (3, 4), 3: (4, 7)}  # etapa → (próxima, dias_offset)

    conn = get_connection()
    hoje = str(date.today())

    pendentes = [dict(r) for r in conn.execute(
        """SELECT * FROM cadencias
           WHERE status = 'pendente'
             AND data_acao <= ?
             AND tenant_id = ?
           ORDER BY data_acao ASC LIMIT 30""",
        (hoje, tenant_id),
    ).fetchall()]

    print(f"[CADÊNCIA] {len(pendentes)} cadências para processar")
    processados = 0

    for cad in pendentes:
        etapa_atual = int(cad.get("etapa") or 1)
        cad_id = cad["id"]
        email = (cad.get("email_empresa") or cad.get("contato_email") or "").strip()

        # Envia email desta etapa (idempotente — ignora se já enviado)
        if email and int(cad.get("canal_email") or 1) and etapa_atual in (1, 2, 3, 4):
            try:
                enviar_email_cadencia(cad_id, etapa_atual, tenant_id)
            except Exception as e:
                print(f"[CADÊNCIA] Erro email cad {cad_id}: {e}")

        # Cria próxima etapa se houver e ainda não existir
        if etapa_atual in PROXIMA:
            proxima_etapa, dias_offset = PROXIMA[etapa_atual]
            proxima_data = (date.today() + timedelta(days=dias_offset)).isoformat()
            empresa_nome = cad.get("empresa_nome") or ""

            try:
                ja_existe = conn.execute(
                    """SELECT id FROM cadencias
                       WHERE empresa_nome = ? AND etapa = ?
                         AND status = 'pendente' AND tenant_id = ?""",
                    (empresa_nome, proxima_etapa, tenant_id),
                ).fetchone()
                if not ja_existe:
                    criar_etapa({
                        "empresa_id":        cad.get("empresa_id"),
                        "empresa_nome":      empresa_nome,
                        "contato_whatsapp":  cad.get("contato_whatsapp"),
                        "contato_email":     cad.get("contato_email"),
                        "oportunidade_id":   cad.get("oportunidade_id"),
                        "etapa":             proxima_etapa,
                        "data_acao":         proxima_data,
                        "mensagem_whatsapp": cad.get("mensagem_whatsapp") or "",
                        "assunto_email":     "",
                        "corpo_email":       "",
                        "status":            "pendente",
                        "email_empresa":     email,
                        "canal_email":       int(cad.get("canal_email") or 1),
                        "canal_whatsapp":    int(cad.get("canal_whatsapp") or 1),
                        "tenant_id":         tenant_id,
                    })
            except Exception as e:
                print(f"[CADÊNCIA] Erro criar etapa {proxima_etapa} para {empresa_nome}: {e}")

        # Marca etapa atual como concluída
        try:
            conn.execute(
                "UPDATE cadencias SET status = 'concluida' WHERE id = ?", (cad_id,)
            )
            conn.commit()
            processados += 1
        except Exception as e:
            print(f"[CADÊNCIA] Erro ao concluir cad {cad_id}: {e}")

    conn.close()
    return processados
