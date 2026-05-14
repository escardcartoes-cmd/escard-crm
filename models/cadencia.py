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

# Etapas em que o e-mail é enviado automaticamente pelo Brevo
ETAPAS_EMAIL_AUTO = {2, 4}


def enviar_email_brevo(
    destinatario_email: str,
    destinatario_nome: str,
    assunto: str,
    corpo: str,
) -> dict:
    """
    Envia e-mail transacional via Brevo usando requests.
    Retorna {"status": "enviado"|"sem_chave"|"erro", "id": message_id_ou_None}.
    """
    api_key = os.getenv("BREVO_API_KEY", "")
    if not api_key:
        return {"status": "sem_chave", "id": None}
    try:
        html = corpo if ("<p>" in corpo or "<br" in corpo) else \
               "".join(f"<p>{p}</p>" for p in corpo.split("\n\n") if p.strip())
        resp = _req.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "sender": {"name": "Krylo CRM", "email": "contato@krylo.com.br"},
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


def criar_etapa(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO cadencias
               (empresa_id, empresa_nome, contato_whatsapp, contato_email,
                oportunidade_id, etapa, data_acao, mensagem_whatsapp,
                assunto_email, corpo_email, status, email_status)
           VALUES
               (:empresa_id, :empresa_nome, :contato_whatsapp, :contato_email,
                :oportunidade_id, :etapa, :data_acao, :mensagem_whatsapp,
                :assunto_email, :corpo_email, :status,
                :email_status)""",
        {**dados, "email_status": "sem_email"},
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    # Envio automático de e-mail para etapas 2 e 4
    etapa = dados.get("etapa")
    email = (dados.get("contato_email") or "").strip()
    if etapa in ETAPAS_EMAIL_AUTO and email:
        _tentar_enviar_email(
            cadencia_id=new_id,
            empresa_nome=dados.get("empresa_nome", ""),
            etapa=etapa,
            para_email=email,
            assunto=dados.get("assunto_email", ""),
            corpo=dados.get("corpo_email", ""),
        )

    return new_id


def _tentar_enviar_email(
    cadencia_id: int,
    empresa_nome: str,
    etapa: int,
    para_email: str,
    assunto: str,
    corpo: str,
) -> None:
    """Gera conteúdo se necessário e envia via Brevo (requests). Silencia erros."""
    try:
        # Gera conteúdo via Claude Haiku se não foi pré-gerado
        if not assunto or not corpo:
            import ai
            gerado = ai.gerar_email_cadencia(empresa_nome=empresa_nome, etapa=etapa)
            assunto = gerado.get("assunto", assunto)
            corpo   = gerado.get("corpo",   corpo)

        resultado = enviar_email_brevo(
            destinatario_email=para_email,
            destinatario_nome=empresa_nome,
            assunto=assunto,
            corpo=corpo,
        )
        novo_status = resultado["status"]   # 'enviado', 'sem_chave' ou 'erro'
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


def listar_hoje() -> list:
    today = str(date.today())
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM cadencias
           WHERE data_acao = ? AND status='pendente'
           ORDER BY empresa_nome ASC, etapa ASC""",
        (today,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def listar_proximos_dias(n: int = 7) -> list:
    tomorrow = str(date.today() + timedelta(days=1))
    cutoff   = str(date.today() + timedelta(days=n))
    conn = get_connection()
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
    """Retorna todas as cadências onde um e-mail foi enviado via Brevo."""
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
    """Consulta eventos 'opened' no Brevo via requests. Retorna set de message_ids abertos."""
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
    """
    Consulta o Brevo para todas as cadências com status='enviado'
    e atualiza para 'aberto' as que foram lidas.
    Retorna quantidade de atualizações.
    """
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
