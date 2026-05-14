"""
Wrapper Brevo (ex-Sendinblue) para envio de e-mails transacionais.
Requer BREVO_API_KEY no ambiente.
"""
import os
import textwrap

SENDER_EMAIL = "noreply@krylo.com.br"
SENDER_NAME  = "Krylo Benefícios"


def _api():
    import sib_api_v3_sdk
    key = os.environ.get("BREVO_API_KEY", "")
    if not key:
        raise ValueError("BREVO_API_KEY não configurada — adicione nas variáveis de ambiente")
    cfg = sib_api_v3_sdk.Configuration()
    cfg.api_key["api-key"] = key
    return sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(cfg))


def _texto_para_html(texto: str) -> str:
    """Converte texto plano em HTML simples com parágrafos."""
    paragrafos = [p.strip() for p in texto.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragrafos)


def enviar_email(para_email: str, para_nome: str, assunto: str, corpo: str) -> str:
    """
    Envia e-mail transacional via Brevo.
    corpo pode ser texto plano ou HTML — detecta automaticamente.
    Retorna message_id do Brevo.
    """
    import sib_api_v3_sdk

    html = corpo if "<p>" in corpo or "<br" in corpo else _texto_para_html(corpo)
    email_obj = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": para_email, "name": para_nome or para_email}],
        sender={"name": SENDER_NAME, "email": SENDER_EMAIL},
        subject=assunto,
        html_content=html,
    )
    resp = _api().send_transac_email(email_obj)
    return getattr(resp, "message_id", "") or ""


def verificar_aberturas(message_ids: list) -> set:
    """
    Consulta o Brevo e retorna o subconjunto de message_ids que foram abertos.
    Silencia erros individuais para não interromper o fluxo.
    """
    if not message_ids:
        return set()
    api = _api()
    abertos = set()
    for mid in message_ids:
        try:
            result = api.get_email_event_report(
                limit=10,
                offset=0,
                message_id=mid,
                event="opened",
            )
            if result and getattr(result, "events", None):
                abertos.add(mid)
        except Exception:
            pass
    return abertos
