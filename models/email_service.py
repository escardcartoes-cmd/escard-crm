"""
Email de onboarding via Brevo — reutiliza a mesma BREVO_API_KEY do SDR
mas com remetentes separados para não misturar com e-mails de cadência.
"""
import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

BREVO_API_KEY  = os.environ.get("BREVO_API_KEY") or os.environ.get("SENDINBLUE_API_KEY", "")
EMAIL_ONBOARDING = os.environ.get("EMAIL_ONBOARDING", "onboarding@escardcartoes.com.br")
EMAIL_SUPORTE    = os.environ.get("EMAIL_SUPORTE",    "suporte@escardcartoes.com.br")
BASE_URL         = os.environ.get("BASE_URL", "https://web-production-7599a.up.railway.app")


def _get_brevo_client():
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    return sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )


def enviar_email_boas_vindas(tenant, email_destino, nome_responsavel,
                              senha_temp, link_acesso):
    """Envia e-mail de boas-vindas para novo tenant via Brevo."""
    cor = tenant.get("cor_primaria", "#C5A089")
    plataforma = tenant.get("nome_plataforma", "Krylo")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:40px;">
  <div style="max-width:600px;margin:0 auto;background:white;border-radius:12px;
              overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1)">

    <div style="background:{cor};padding:40px;text-align:center;">
      <h1 style="color:white;margin:0;font-size:28px;">
        {plataforma} esta pronto!
      </h1>
      <p style="color:rgba(255,255,255,0.9);margin:10px 0 0 0;">
        Sua plataforma de CRM inteligente foi configurada
      </p>
    </div>

    <div style="padding:40px;">
      <p style="font-size:18px;color:#333;">
        Ola, <strong>{nome_responsavel}</strong>!
      </p>
      <p style="color:#555;line-height:1.6;">
        Sua plataforma <strong>{plataforma}</strong> esta pronta.
        Complete o setup em 10 minutos e seu SDR ja pode prospectar hoje mesmo.
      </p>

      <div style="background:#f8f8f8;border-radius:8px;padding:24px;margin:24px 0;">
        <h3 style="margin:0 0 16px 0;color:#333;">Seus dados de acesso:</h3>
        <p style="margin:8px 0;">
          <strong>Link:</strong>
          <a href="{link_acesso}" style="color:{cor};">{link_acesso}</a>
        </p>
        <p style="margin:8px 0;"><strong>Email:</strong> {email_destino}</p>
        <p style="margin:8px 0;">
          <strong>Senha temporaria:</strong>
          <code style="background:#e8e8e8;padding:2px 8px;border-radius:4px;">{senha_temp}</code>
        </p>
      </div>

      <h3 style="color:#333;">O que fazer agora (10 minutos):</h3>
      <div style="border-left:3px solid {cor};padding-left:16px;">
        <p style="margin:8px 0;"><strong>Passo 1</strong> — Acesse e troque sua senha</p>
        <p style="margin:8px 0;"><strong>Passo 2</strong> — Complete o wizard de configuracao</p>
        <p style="margin:8px 0;"><strong>Passo 3</strong> — Configure o SDR com seus filtros</p>
        <p style="margin:8px 0;"><strong>Passo 4</strong> — Rode sua primeira prospeccao</p>
      </div>

      <div style="text-align:center;margin:32px 0;">
        <a href="{link_acesso}"
           style="background:{cor};color:white;padding:16px 40px;border-radius:8px;
                  text-decoration:none;font-size:18px;font-weight:bold;display:inline-block;">
          Acessar minha plataforma &rarr;
        </a>
      </div>

      <p style="color:#888;font-size:13px;text-align:center;">
        Duvidas? Fale com a KIA dentro da plataforma.
      </p>
    </div>

    <div style="background:#f8f8f8;padding:20px;text-align:center;">
      <p style="color:#aaa;font-size:12px;margin:0;">
        {plataforma} — CRM Inteligente
      </p>
    </div>
  </div>
</body>
</html>"""

    try:
        if BREVO_API_KEY:
            api = _get_brevo_client()
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": email_destino, "name": nome_responsavel}],
                sender={"email": EMAIL_ONBOARDING, "name": plataforma},
                subject=f"Sua plataforma {plataforma} esta pronta!",
                html_content=html,
            )
            api.send_transac_email(send_smtp_email)
            print(f"[EMAIL] Boas-vindas enviado para {email_destino}")
            return True
        else:
            os.makedirs("logs", exist_ok=True)
            safe = email_destino.replace("@", "_at_").replace(".", "_")
            with open(f"logs/email_boasvindas_{safe}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[EMAIL] BREVO_API_KEY nao configurada — salvo em logs/")
            return True
    except ApiException as e:
        print(f"[EMAIL] Erro Brevo: {e}")
        return False


def enviar_email_dica(email_destino, nome, assunto, html_corpo,
                      nome_plataforma="Krylo"):
    """Envia dica diaria de onboarding via Brevo."""
    try:
        if not BREVO_API_KEY:
            print("[EMAIL DICA] Sem API key — pulando")
            return False
        api = _get_brevo_client()
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email_destino, "name": nome}],
            sender={"email": EMAIL_ONBOARDING, "name": nome_plataforma},
            subject=assunto,
            html_content=html_corpo,
        )
        api.send_transac_email(send_smtp_email)
        print(f"[EMAIL DICA] Enviado para {email_destino}")
        return True
    except ApiException as e:
        print(f"[EMAIL DICA] Erro: {e}")
        return False
