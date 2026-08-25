import hmac
import logging
import os
import re
import csv
import io
import json
import time
import threading
import atexit
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()  # sem override — Railway env vars têm precedência sobre .env local

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("krylo")

from apscheduler.schedulers.background import BackgroundScheduler

from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import database
import models.empresa as emp_model
import models.contato as cont_model
import models.oportunidade as op_model
import models.atividade as atv_model
import models.prospeccao as prosp_model
import models.usuario as user_model
import models.cadencia as cad_model
import models.expansao as exp_model
import models.cobranca as cob_model
import models.recebivel as rec_model
import models.radar as radar_model
import models.portal as portal_model
import models.relatorio as rel_model
import models.prospeccao_auto as pauto_model
import models.cnaes as cnaes_model
import models.tenant as tenant_model
import models.planos as planos_model
from models.usuario import require_perfil, PERFIS, PERFIL_LABELS
import ai

from routes.api import api_bp

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
IS_PROD = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("VERCEL") or os.environ.get("PRODUCTION"))

# Sentry — carrega apenas se SENTRY_DSN configurada; falha silenciosa se pacote ausente
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment="production" if IS_PROD else "development",
            send_default_pii=False,
        )
    except Exception as _e:
        print(f"[SENTRY] init falhou (não fatal): {_e}", flush=True)

app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY environment variable must be set in production")
    import secrets as _sec
    app.secret_key = _sec.token_hex(32)
    logger.info("[AVISO] SECRET_KEY não configurada - usando chave temporária (dev only)")
app.permanent_session_lifetime = timedelta(hours=8)
app.config["SESSION_COOKIE_SECURE"] = IS_PROD   # HTTPS-only cookies in prod
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["JSON_AS_ASCII"] = False
app.config["WTF_CSRF_ENABLED"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB upload cap

csrf = CSRFProtect(app)

# CORS: allow same-origin + explicit prod origins. Never wildcard with credentials.
_cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://krylo-crm.vercel.app",
    "https://www.krylo.com.br",
    "https://krylo.com.br",
]
_extra = os.environ.get("CORS_EXTRA_ORIGINS", "")
if _extra:
    _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])
CORS(app, resources={r"/api/*": {"origins": _cors_origins}}, supports_credentials=True)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "300 per hour"],
    headers_enabled=True,
)

# Security headers on every response.
@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if IS_PROD:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
    return resp

login_manager = LoginManager(app)
# Frontend Next.js handles the login page — Flask serves only the JSON API.
# When an unauthenticated request hits an @login_required route, return 401 JSON
# so the SPA can react (redirect to /login on its own).
login_manager.login_message = None

@login_manager.unauthorized_handler
def _unauthorized():
    from flask import request as _req, jsonify as _jsonify, redirect as _redirect
    if _req.path.startswith("/api/") or _req.is_json or "application/json" in _req.headers.get("Accept", ""):
        return _jsonify(error="Autenticação necessária.", login_required=True), 401
    # Any legacy Jinja path — send the user to the Next.js frontend
    return _redirect("https://krylo-crm.vercel.app/login", code=302)

app.register_blueprint(api_bp)
csrf.exempt(api_bp)

# Stricter rate limits on sensitive endpoints (anti brute-force / abuse).
for _endpoint, _rule in [
    ("api.auth_login",           "10 per minute; 30 per hour"),
    ("api.auth_forgot_password", "3 per hour; 10 per day"),
    ("api.auth_reset_password",  "5 per hour; 20 per day"),
    ("api.api_ia_chat",          "60 per hour"),
    ("api.leads_importar_confirmar", "20 per hour"),
    ("api.integracoes_testar_email", "5 per hour"),
    ("api.integracoes_testar_ia",    "10 per hour"),
    ("api.auth_2fa_verify",          "10 per minute; 30 per hour"),
    ("api.auth_2fa_reenviar",        "3 per hour"),
    ("api.usuario_convidar",         "20 per hour"),
    ("api.convite_accept",           "10 per hour"),
]:
    _fn = app.view_functions.get(_endpoint)
    if _fn:
        app.view_functions[_endpoint] = limiter.limit(_rule)(_fn)

@app.context_processor
def _inject_cadencias_badge():
    tid = session.get("tenant_id", 1)
    try:
        radar_nao_lidos = radar_model.contar_nao_lidos(tid)
    except Exception:
        radar_nao_lidos = {"editais": 0, "concorrentes": 0, "total": 0}
    wa_pendentes = 0
    try:
        conn = database.get_connection()
        row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM cadencias
               WHERE tenant_id = ? AND canal_whatsapp = 1
                 AND (whatsapp_status IS NULL OR whatsapp_status = 'pendente'
                      OR whatsapp_status = 'aguardando_aprovacao')
                 AND mensagem_whatsapp IS NOT NULL AND mensagem_whatsapp != ''""",
            (tid,)
        ).fetchone()
        wa_pendentes = int(row["cnt"] if row else 0)
        conn.close()
    except Exception:
        pass
    try:
        return {
            "cadencias_hoje_count": cad_model.contar_hoje(tid),
            "radar_nao_lidos": radar_nao_lidos,
            "wa_pendentes": wa_pendentes,
        }
    except Exception:
        return {"cadencias_hoje_count": 0, "radar_nao_lidos": radar_nao_lidos, "wa_pendentes": wa_pendentes}


@app.context_processor
def inject_globals():
    estados = [
        ("AC","Acre"),("AL","Alagoas"),("AP","Amapá"),("AM","Amazonas"),
        ("BA","Bahia"),("CE","Ceará"),("DF","Distrito Federal"),("ES","Espírito Santo"),
        ("GO","Goiás"),("MA","Maranhão"),("MT","Mato Grosso"),("MS","Mato Grosso do Sul"),
        ("MG","Minas Gerais"),("PA","Pará"),("PB","Paraíba"),("PR","Paraná"),
        ("PE","Pernambuco"),("PI","Piauí"),("RJ","Rio de Janeiro"),("RN","Rio Grande do Norte"),
        ("RS","Rio Grande do Sul"),("RO","Rondônia"),("RR","Roraima"),("SC","Santa Catarina"),
        ("SP","São Paulo"),("SE","Sergipe"),("TO","Tocantins"),
    ]
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        cfg = conn.execute(
            "SELECT nome, nome_fantasia, whatsapp FROM empresa_config WHERE tenant_id=%s LIMIT 1",
            (tid,)
        ).fetchone()
        conn.close()
        return {
            "empresa_nome": cfg["nome"] if cfg else "Krylo",
            "empresa_whatsapp": cfg["whatsapp"] if cfg else "",
            "estados_br": estados,
        }
    except Exception:
        return {"empresa_nome": "Krylo", "empresa_whatsapp": "", "estados_br": estados}


@app.context_processor
def inject_tenant():
    try:
        t = tenant_model.get_tenant_atual()
    except Exception:
        t = None
    if not t:
        t = {
            "id": 1, "slug": "krylo", "nome_empresa": "Krylo",
            "nome_plataforma": "Krylo CRM", "cor_primaria": "#4A90D9",
            "cor_secundaria": "#2C5F8A", "cor_fundo": "#F5F8FF",
            "logo_url": None, "plano": "enterprise", "configurado": 1,
        }
    try:
        plano_info = planos_model.get_plano(t.get("plano", "starter"))
    except Exception:
        plano_info = {"nome": "Enterprise"}
    return {"tenant": t, "plano_info": plano_info}


@app.before_request
def check_tenant_setup():
    _bypass = {
        "login", "logout", "static", "krylo_landing",
        "setup_wizard", "setup_salvar",
        "setup_step1", "setup_step2", "setup_step3", "setup_step4",
        "leads_importar_form", "leads_importar_preview", "leads_importar_confirmar",
        "sdr_evolutivo.sdr_evolutivo_configurar",
        "ajuda_index", "ajuda_kia",
        "login_2fa", "login_2fa_reenviar", "recuperar_senha", "nova_senha",
        "auth.login", "auth.logout", "auth.login_2fa", "auth.login_2fa_reenviar",
        "auth.recuperar_senha", "auth.nova_senha",
    }
    endpoint = request.endpoint or ""
    if endpoint in _bypass or endpoint.startswith("setup") or endpoint.startswith("admin_"):
        return None
    if not current_user.is_authenticated:
        return None
    try:
        t = tenant_model.get_tenant_atual()
        if t and not t.get("configurado"):
            return redirect(url_for("setup_wizard"))
    except Exception:
        pass
    return None


@login_manager.user_loader
def load_user(user_id):
    return user_model.buscar_por_id(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    _api_prefixes = ('/api/', '/ia/', '/central-ia/', '/ajuda/kia',
                     '/ai/', '/sdr-evolutivo/', '/cqa/', '/pipeline/mover',
                     '/pipeline/proxima-acao/', '/oportunidades/', '/cadencias/')
    if (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
        or request.path.startswith(_api_prefixes)
    ):
        return jsonify({"error": "Sessão expirada. Faça login novamente.",
                        "login_required": True}), 401
    return redirect(url_for('auth.login', next=request.url))

_START_TIME = str(time.time())

try:
    database.init_db()
except Exception as _e:
    logger.error(f"[STARTUP] init_db error (non-fatal): {_e}")
try:
    user_model.criar_admin_se_necessario()
except Exception as _e:
    logger.error(f"[STARTUP] criar_admin error (non-fatal): {_e}")
# ── APScheduler — SDR Autônomo ────────────────────────────────────────────────

def _job_prospeccao_autonoma():
    import traceback as _tb
    from datetime import timezone as _tz, timedelta as _td, datetime as _dt2
    try:
        _c = database.get_connection()
        _tenant_rows = _c.execute(
            "SELECT s.tenant_id FROM sdr_config s"
            " JOIN tenants t ON t.id = s.tenant_id WHERE t.ativo = 1"
        ).fetchall()
        _c.close()
    except Exception as _e:
        logger.error(f"[SCHEDULER] Erro ao listar tenants SDR: {_e}")
        return

    for _trow in _tenant_rows:
        _tid = _trow["tenant_id"]
        _db_sdr = None
        try:
            from models.prospeccao_autonoma import rodar_prospeccao_autonoma, get_sdr_config
            _db_sdr = database.get_new_db_connection()
            _cfg = get_sdr_config(_db_sdr, tenant_id=_tid)
            if not _cfg.get("ativo", 1):
                logger.info(f"[SCHEDULER] tenant {_tid}: SDR pausado, pulando")
                _db_sdr.close(); _db_sdr = None
                continue
            _hora = _dt2.now(_tz(_td(hours=-3))).hour
            if not _cfg.get("sem_restricao_horario") and (
                _hora < int(_cfg.get("horario_inicio") or 8) or
                _hora >= int(_cfg.get("horario_fim") or 18)
            ):
                logger.info(f"[SCHEDULER] tenant {_tid}: Fora do horário ({_hora}h), pulando")
                _db_sdr.close(); _db_sdr = None
                continue
            resultado = rodar_prospeccao_autonoma(_db_sdr, config_override=_cfg)
            logger.info(f"[SCHEDULER] tenant {_tid} resultado: {resultado}")
        except Exception as e:
            logger.error(f"[SCHEDULER] tenant {_tid} ERRO: {e}")
            _tb.print_exc()
            if _db_sdr:
                try: _db_sdr.rollback()
                except Exception: pass
        finally:
            if _db_sdr:
                try: _db_sdr.close()
                except Exception: pass
                _db_sdr = None


_sdr_interval = 6  # intervalo padrão; sdr_config por tenant verificado dentro do job

def _job_cqa():
    try:
        import sys as _sys
        _cqa_root = os.path.dirname(os.path.abspath(__file__))
        if _cqa_root not in _sys.path:
            _sys.path.insert(0, _cqa_root)
        from scripts.run_cqa import rodar_cqa_completo
        rodar_cqa_completo(aplicar_fixes=True, verbose=False)
    except Exception as _e:
        logger.error(f"[SCHEDULER CQA] Erro: {_e}")
def _job_processar_cadencias():
    try:
        from models.cadencia import processar_cadencias_pendentes, processar_fila_email
        _c = database.get_connection()
        _tids = [r["id"] for r in _c.execute(
            "SELECT id FROM tenants WHERE ativo = 1"
        ).fetchall()]
        _c.close()
        for _tid in _tids:
            n = processar_cadencias_pendentes(tenant_id=_tid)
            if n:
                logger.info(f"[SCHEDULER] tenant {_tid}: Cadências processadas: {n}")
            e = processar_fila_email(tenant_id=_tid)
            if e:
                logger.info(f"[SCHEDULER] tenant {_tid}: Emails da fila enviados: {e}")
    except Exception as _e:
        logger.error(f"[SCHEDULER CADENCIAS] Erro: {_e}")
scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
scheduler.add_job(
    func=_job_prospeccao_autonoma,
    trigger="interval",
    hours=max(1, _sdr_interval),
    id="prospeccao_autonoma",
    replace_existing=True,
)
scheduler.add_job(
    func=_job_cqa,
    trigger="interval",
    hours=24,
    id="cqa_automatico",
    replace_existing=True,
)
scheduler.add_job(
    func=_job_processar_cadencias,
    trigger="interval",
    hours=1,
    id="processar_cadencias",
    replace_existing=True,
)
scheduler.add_job(
    func=lambda: radar_model.rodar_radar_todos_tenants(),
    trigger="cron",
    hour=7, minute=0,
    id="radar_diario",
    replace_existing=True,
)
if not os.environ.get('SCHEDULER_OFF'):
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))


# ── Tenant helper ─────────────────────────────────────────────────────────────

def _tid() -> int:
    """Retorna o tenant_id da sessão atual (fallback: 1)."""
    return int(session.get("tenant_id") or 1)


# ── Dashboard ─────────────────────────────────────────────────────────────────

_DASHBOARD_CACHE: dict = {}   # {tenant_id: {"ts": float, "stats": dict}}
_DASHBOARD_TTL = 300          # 5 minutos

_DASHBOARD_FALLBACK = dict(
    status_counts={}, estagio_counts={}, pipeline_val=0,
    atividades=[], total_empresas=0, clientes=0, em_aberto=0,
    radar=[], radar_alerta_count=0, potencial_expansao=0,
    cob_resumo={}, rec_resumo={}, radar_badge={"editais": 0, "concorrentes": 0, "total": 0},
    portais_ativos=0, rec_atrasados_count=0, deals_fechados_semana=0,
    receita_mes=0, pct_meta=0, cadencias_ativas_count=0,
    top_acao="", pauto_resumo={"novos_hoje": 0, "prontos": 0},
    dias_restantes=90, faturado_90d=0, pct_90d=0, ritmo_diario=0,
    funil={"sdr_novos": 0, "em_cadencia": 0, "props_abertas": 0, "fechados_mes": 0},
    cad_hoje=[], ops_paradas=[], meta_valor=100000, meta_nome="Meta Principal",
    leads_quentes=[], cad_paradas=[],
)


@app.errorhandler(500)
def erro_500(e):
    import traceback
    logger.error(f"[500] {traceback.format_exc()}")
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Erro interno do servidor"}), 500
    try:
        return render_template("erro.html", mensagem="Erro interno. Tente novamente em instantes.", codigo=500), 500
    except Exception:
        return """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body{background:#0A0A0F;color:#F0F0F5;font-family:Inter,sans-serif;
         display:flex;align-items:center;justify-content:center;height:100vh;
         flex-direction:column;gap:16px}
  </style>
</head>
<body><p>Erro interno. <a href="/" style="color:#C5A089">Voltar</a></p></body>
</html>""", 500


@app.errorhandler(404)
def erro_404(e):
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Rota não encontrada"}), 404
    try:
        return render_template("erro.html", mensagem="Página não encontrada.", codigo=404), 404
    except Exception:
        return "<h1>404</h1><a href='/'>Voltar</a>", 404


@app.errorhandler(Exception)
def erro_geral(e):
    from werkzeug.exceptions import HTTPException
    # Let Flask handle HTTP exceptions (4xx, rate-limit 429, etc.) with their real status
    if isinstance(e, HTTPException):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify(error=e.description), e.code
        return e
    import traceback
    app.logger.exception("Unhandled exception")
    if not IS_PROD:
        logger.error(f"[ERRO GERAL] {traceback.format_exc()}")
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Erro interno do servidor"}), 500
    try:
        return render_template("erro.html", mensagem="Algo deu errado. Tente novamente.", codigo=500), 500
    except Exception:
        return "<h1>Erro</h1><a href='/'>Voltar</a>", 500


# ── Metas ─────────────────────────────────────────────────────────────────────

_EXTS_ACEITAS = {"csv", "txt", "xlsx", "xls"}


def _decodificar_bytes(raw: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _detectar_separador(texto: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(texto[:4096], delimiters=",;|\t")
        return dialect.delimiter
    except csv.Error:
        amostra = "\n".join(texto.splitlines()[:5])
        return ";" if amostra.count(";") >= amostra.count(",") else ","


def _ler_csv_bytes(raw: bytes) -> tuple:
    texto = _decodificar_bytes(raw)
    sep   = _detectar_separador(texto)
    reader = csv.DictReader(io.StringIO(texto), delimiter=sep)
    colunas = [c for c in (reader.fieldnames or []) if c is not None and str(c).strip()]
    linhas  = [
        {str(k): (v or "").strip() for k, v in row.items() if k is not None}
        for row in reader
    ]
    return colunas, linhas


def _ler_xlsx_bytes(raw: bytes) -> tuple:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    colunas = [str(c).strip() for c in rows[0] if c is not None and str(c).strip()]
    linhas  = []
    for row in rows[1:]:
        if all(c is None or str(c).strip() == "" for c in row):
            continue
        d = {}
        for i, col in enumerate(colunas):
            val = row[i] if i < len(row) else None
            if isinstance(val, float) and val == int(val):
                val = int(val)
            d[col] = str(val).strip() if val is not None else ""
        linhas.append(d)
    return colunas, linhas


def _ler_xls_bytes(raw: bytes) -> tuple:
    try:
        import xlrd
    except ImportError:
        raise ValueError("Instale xlrd para importar .xls: pip install xlrd")
    wb = xlrd.open_workbook(file_contents=raw)
    ws = wb.sheet_by_index(0)
    if ws.nrows == 0:
        return [], []
    colunas = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)
               if str(ws.cell_value(0, c)).strip()]
    linhas  = []
    for r in range(1, ws.nrows):
        d = {}
        for i, col in enumerate(colunas):
            val = ws.cell_value(r, i) if i < ws.ncols else ""
            if isinstance(val, float) and val == int(val):
                val = int(val)
            d[col] = str(val).strip() if val != "" else ""
        if any(v for v in d.values()):
            linhas.append(d)
    return colunas, linhas


def _detectar_formato_real(raw: bytes) -> str:
    """Detecta o formato real pelos magic bytes, ignora a extensão do arquivo."""
    head = raw[:8].lstrip(b"\xef\xbb\xbf")  # skip UTF-8 BOM
    if head.startswith(b"PK\x03\x04"):          # ZIP → XLSX
        return "xlsx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):    # OLE2 → XLS legado real
        return "xls"
    if head[:6].lower().startswith((b"<html", b"<!doct", b"<meta", b"<?xml")):
        return "html"
    return "csv"


def _ler_html_bytes(raw: bytes) -> tuple:
    """Fallback: alguns exports do Google Sheets/Excel Online salvam HTML com extensão .xls."""
    try:
        from html.parser import HTMLParser
    except ImportError:
        raise ValueError("Não foi possível ler o arquivo HTML.")
    rows = []
    class TableExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current_row = None
            self.current_cell = []
            self.in_cell = False
        def handle_starttag(self, tag, _attrs):
            if tag == "tr":
                self.current_row = []
            elif tag in ("td", "th"):
                self.in_cell = True
                self.current_cell = []
        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.current_row is not None:
                self.current_row.append("".join(self.current_cell).strip())
                self.in_cell = False
            elif tag == "tr" and self.current_row is not None:
                rows.append(self.current_row)
                self.current_row = None
        def handle_data(self, data):
            if self.in_cell:
                self.current_cell.append(data)
    p = TableExtractor()
    p.feed(raw.decode("utf-8", errors="replace"))
    if not rows:
        raise ValueError("Nenhuma tabela encontrada no HTML.")
    colunas = rows[0]
    linhas = [dict(zip(colunas, r)) for r in rows[1:]]
    return colunas, linhas


def _ler_arquivo(raw: bytes, nome: str) -> tuple:
    ext = nome.lower().rsplit(".", 1)[-1] if "." in nome else "csv"
    real = _detectar_formato_real(raw)

    # Google Sheets / Excel Online salvos como HTML com extensão .xls
    if real == "html":
        return _ler_html_bytes(raw)
    # Extensão mente → usa formato real
    if real == "xlsx":
        return _ler_xlsx_bytes(raw)
    if real == "xls":
        return _ler_xls_bytes(raw)
    if ext == "xlsx" and real != "xlsx":
        raise ValueError(
            "Arquivo com extensão .xlsx mas o conteúdo não é um Excel válido. "
            "Se veio do Google Sheets, use Arquivo → Baixar → Excel (.xlsx) ou CSV (.csv)."
        )
    if ext == "xls" and real not in ("xls", "xlsx"):
        raise ValueError(
            "Arquivo com extensão .xls mas o conteúdo não é um Excel válido. "
            "Reabra no Excel e salve como .xlsx, ou exporte como CSV."
        )
    return _ler_csv_bytes(raw)


def _auto_mapear(colunas: list) -> dict:
    canonical = {
        "nome":     ["nome", "name", "contato", "pessoa"],
        "empresa":  ["empresa", "company", "razao", "razão", "fantasia", "empresa_nome"],
        "cargo":    ["cargo", "role", "titulo", "título", "position", "funcao", "função"],
        "telefone": ["telefone", "tel", "phone", "celular", "whatsapp", "fone"],
        "email":    ["email", "e-mail", "mail"],
        "cidade":   ["cidade", "city", "municipio", "município"],
    }
    resultado  = {}
    cols_lower = {c: str(c).lower().strip() for c in colunas if c is not None}
    for field, keywords in canonical.items():
        for col, col_l in cols_lower.items():
            if any(kw in col_l for kw in keywords):
                resultado[field] = col
                break
    return resultado


def _processar_linhas(linhas: list, mapa: dict, tenant_id: int = 1) -> tuple:
    empresas_cache = {}
    importados = 0
    ignorados  = 0

    for row in linhas:
        def _v(field, _row=row):
            col = mapa.get(field, "")
            return (_row.get(col, "") or "").strip() or None

        nome_contato = _v("nome")
        nome_empresa = _v("empresa")

        if not nome_contato and not nome_empresa:
            ignorados += 1
            continue

        chave_emp = (nome_empresa or "").lower()
        if chave_emp and chave_emp in empresas_cache:
            emp_id = empresas_cache[chave_emp]
        elif nome_empresa:
            emp_id = emp_model.criar({
                "nome": nome_empresa, "cnpj": None, "segmento": None,
                "porte": None, "status": "prospect",
                "telefone": None, "email": None,
                "cidade": _v("cidade"), "estado": None,
                "produtos_ativos": None, "num_funcionarios": None,
                "cliente_ativo": 0, "valor_mensal": None,
                "tipo_cartao": None, "nome_private_label": None,
                "tenant_id": tenant_id,
            })
            empresas_cache[chave_emp] = emp_id
        else:
            ignorados += 1
            continue

        contato_id = cont_model.criar({
            "empresa_id": emp_id,
            "nome": nome_contato or nome_empresa,
            "cargo": _v("cargo"),
            "email": _v("email"),
            "telefone": _v("telefone"),
            "tenant_id": tenant_id,
        })
        prosp_model.criar({
            "contato_id": contato_id,
            "empresa_id": emp_id,
            "status": "pendente",
            "tenant_id": tenant_id,
        })
        importados += 1

    return importados, ignorados


# ── Leads — importar ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1",
            host="0.0.0.0", port=port)

