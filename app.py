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
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

from apscheduler.schedulers.background import BackgroundScheduler

from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
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

from routes.auth import auth_bp
from routes.empresas import empresas_bp
from routes.contatos import contatos_bp
from routes.sdr_evolutivo import sdr_evolutivo_bp

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    import secrets as _sec
    app.secret_key = _sec.token_hex(32)
    print("[AVISO] SECRET_KEY não configurada - usando chave temporária")
app.permanent_session_lifetime = timedelta(hours=8)
app.config["JSON_AS_ASCII"] = False
app.config["WTF_CSRF_ENABLED"] = True

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Faça login para acessar o CRM."
login_manager.login_message_category = "danger"

app.register_blueprint(auth_bp)
app.register_blueprint(empresas_bp)
app.register_blueprint(contatos_bp)
app.register_blueprint(sdr_evolutivo_bp)

@app.context_processor
def _inject_cadencias_badge():
    try:
        radar_nao_lidos = radar_model.contar_nao_lidos()
    except Exception:
        radar_nao_lidos = {"editais": 0, "concorrentes": 0, "total": 0}
    wa_pendentes = 0
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
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
            "cadencias_hoje_count": cad_model.contar_hoje(),
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
    print(f"[STARTUP] init_db error (non-fatal): {_e}")

try:
    user_model.criar_admin_se_necessario()
except Exception as _e:
    print(f"[STARTUP] criar_admin error (non-fatal): {_e}")


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
        print(f"[SCHEDULER] Erro ao listar tenants SDR: {_e}")
        return

    for _trow in _tenant_rows:
        _tid = _trow["tenant_id"]
        _db_sdr = None
        try:
            from models.prospeccao_autonoma import rodar_prospeccao_autonoma, get_sdr_config
            _db_sdr = database.get_new_db_connection()
            _cfg = get_sdr_config(_db_sdr, tenant_id=_tid)
            if not _cfg.get("ativo", 1):
                print(f"[SCHEDULER] tenant {_tid}: SDR pausado, pulando")
                _db_sdr.close(); _db_sdr = None
                continue
            _hora = _dt2.now(_tz(_td(hours=-3))).hour
            if not _cfg.get("sem_restricao_horario") and (
                _hora < int(_cfg.get("horario_inicio") or 8) or
                _hora >= int(_cfg.get("horario_fim") or 18)
            ):
                print(f"[SCHEDULER] tenant {_tid}: Fora do horário ({_hora}h), pulando")
                _db_sdr.close(); _db_sdr = None
                continue
            resultado = rodar_prospeccao_autonoma(_db_sdr, config_override=_cfg)
            print(f"[SCHEDULER] tenant {_tid} resultado: {resultado}")
        except Exception as e:
            print(f"[SCHEDULER] tenant {_tid} ERRO: {e}")
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
        print(f"[SCHEDULER CQA] Erro: {_e}")


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
                print(f"[SCHEDULER] tenant {_tid}: Cadências processadas: {n}")
            e = processar_fila_email(tenant_id=_tid)
            if e:
                print(f"[SCHEDULER] tenant {_tid}: Emails da fila enviados: {e}")
    except Exception as _e:
        print(f"[SCHEDULER CADENCIAS] Erro: {_e}")


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


@app.route("/")
@login_required
def dashboard():
    _log = logging.getLogger(__name__)
    tid = _tid()
    hoje = str(date.today())
    mes_atual = hoje[:7]
    limite_14d = (date.today() - timedelta(days=14)).isoformat()
    meta_inicio_default = "2026-05-15"

    conn = database.get_connection()
    try:
        # QUERY 1: todos os escalares — com cache de 5 minutos por tenant
        _cached = _DASHBOARD_CACHE.get(tid)
        if _cached and (time.time() - _cached["ts"]) < _DASHBOARD_TTL:
            stats = _cached["stats"]
        else:
            stats = dict(conn.execute("""
            SELECT
              (SELECT COALESCE(COUNT(*),0) FROM empresas WHERE tenant_id=?) AS emp_total,
              (SELECT COALESCE(COUNT(*),0) FROM empresas WHERE tenant_id=? AND status='cliente') AS emp_cliente,
              (SELECT COALESCE(COUNT(*),0) FROM empresas WHERE tenant_id=? AND status='prospect') AS emp_prospect,
              (SELECT COALESCE(COUNT(*),0) FROM empresas WHERE tenant_id=? AND status='lead') AS emp_lead,
              (SELECT COALESCE(SUM(valor_estimado),0) FROM oportunidades
               WHERE tenant_id=? AND etapa NOT IN ('fechado_ganho','fechado_perdido')) AS pipeline_val,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades
               WHERE tenant_id=? AND etapa NOT IN ('fechado_ganho','fechado_perdido')) AS ops_abertas,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades WHERE tenant_id=? AND etapa='prospect') AS ops_prospect,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades WHERE tenant_id=? AND etapa='contato') AS ops_contato,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades WHERE tenant_id=? AND etapa='proposta') AS ops_proposta,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades WHERE tenant_id=? AND etapa='negociacao') AS ops_negociacao,
              (SELECT COALESCE(COUNT(*),0) FROM oportunidades WHERE tenant_id=? AND etapa='fechado') AS ops_fechado,
              (SELECT COALESCE(SUM(valor_estimado),0) FROM oportunidades
               WHERE tenant_id=? AND etapa='fechado_ganho' AND criado_em >= ?) AS faturado_90d,
              (SELECT COALESCE(SUM(valor_estimado),0) FROM oportunidades
               WHERE tenant_id=? AND etapa='fechado_ganho' AND criado_em LIKE ?) AS fechados_mes,
              (SELECT COALESCE(COUNT(*),0) FROM prospeccao_automatica WHERE tenant_id=? AND status='novo') AS sdr_novos,
              (SELECT COALESCE(COUNT(*),0) FROM cadencias WHERE tenant_id=? AND status='pendente') AS em_cadencia,
              (SELECT COALESCE(COUNT(*),0) FROM radar_alertas WHERE tenant_id=? AND lido=0) AS radar_nao_lidos,
              (SELECT COALESCE(COUNT(*),0) FROM portal_acessos WHERE tenant_id=? AND ativo=1) AS portais_ativos,
              (SELECT COALESCE(COUNT(*),0) FROM prospeccao_automatica
               WHERE tenant_id=? AND status IN ('pronto','quente')) AS pauto_prontos,
              (SELECT COALESCE(COUNT(*),0) FROM prospeccao_automatica
               WHERE tenant_id=? AND DATE(importado_em)=?) AS pauto_hoje,
              (SELECT COALESCE(valor_meta,100000) FROM metas
               WHERE tenant_id=? AND ativo=1 ORDER BY criado_em DESC LIMIT 1) AS meta_valor,
              (SELECT COALESCE(nome,'Meta Principal') FROM metas
               WHERE tenant_id=? AND ativo=1 ORDER BY criado_em DESC LIMIT 1) AS meta_nome,
              (SELECT data_fim FROM metas
               WHERE tenant_id=? AND ativo=1 ORDER BY criado_em DESC LIMIT 1) AS meta_data_fim,
              (SELECT data_inicio FROM metas
               WHERE tenant_id=? AND ativo=1 ORDER BY criado_em DESC LIMIT 1) AS meta_data_inicio
        """, (
            tid, tid, tid, tid,          # emp_*
            tid, tid,                    # pipeline_val, ops_abertas
            tid, tid, tid, tid, tid,     # ops por etapa
            tid, meta_inicio_default,    # faturado_90d
            tid, mes_atual + "%",        # fechados_mes
            tid, tid,                    # sdr_novos, em_cadencia
            tid, tid,                    # radar_nao_lidos, portais_ativos
            tid, tid, hoje,              # pauto_prontos, pauto_hoje
            tid, tid, tid, tid,          # meta_*
        )).fetchone())
            _DASHBOARD_CACHE[tid] = {"ts": time.time(), "stats": stats}

        # Ajusta datas da meta a partir do banco
        meta_valor = float(stats.get("meta_valor") or 100000)
        meta_nome = stats.get("meta_nome") or "Meta Principal"
        meta_fim_str = str(stats["meta_data_fim"])[:10] if stats.get("meta_data_fim") else "2026-08-13"
        try:
            dias_restantes = max(0, (date.fromisoformat(meta_fim_str) - date.today()).days)
        except Exception:
            dias_restantes = 90

        faturado_90d = float(stats.get("faturado_90d") or 0)
        pct_90d = round(min(faturado_90d / max(meta_valor, 1) * 100, 100), 1)
        ritmo_diario = round((meta_valor - faturado_90d) / max(dias_restantes, 1), 2)

        # QUERY 2: atividades recentes com nome da empresa
        atividades = [dict(r) for r in conn.execute("""
            SELECT a.*, e.nome AS empresa_nome
            FROM atividades a
            LEFT JOIN empresas e ON e.id = a.empresa_id
            WHERE a.tenant_id = ?
            ORDER BY a.criado_em DESC LIMIT 8
        """, (tid,)).fetchall()]

        # QUERY 3: cadências de hoje (lista, precisa de rows)
        cad_hoje = [dict(r) for r in conn.execute("""
            SELECT * FROM cadencias
            WHERE tenant_id=? AND data_acao=? AND status='pendente'
            ORDER BY empresa_nome LIMIT 5
        """, (tid, hoje)).fetchall()]

        # QUERY 4: oportunidades paradas (JOIN necessário para nome da empresa)
        ops_paradas = [dict(r) for r in conn.execute("""
            SELECT o.id, o.titulo, e.nome AS empresa_nome, o.etapa, o.data_ultimo_contato
            FROM oportunidades o
            LEFT JOIN empresas e ON e.id = o.empresa_id
            WHERE o.tenant_id=?
              AND o.etapa NOT IN ('fechado_ganho','fechado_perdido')
              AND (o.data_ultimo_contato IS NULL OR o.data_ultimo_contato < ?)
            ORDER BY o.data_ultimo_contato LIMIT 5
        """, (tid, limite_14d)).fetchall()]

        # QUERY 5: top 5 leads mais quentes (real-time — fora do cache)
        leads_quentes = [dict(r) for r in conn.execute("""
            SELECT id, nome, segmento, score, temperatura, telefone, email
            FROM empresas
            WHERE tenant_id=? AND temperatura='quente'
            ORDER BY score DESC LIMIT 5
        """, (tid,)).fetchall()]

        # QUERY 6: cadências paradas há 3+ dias (real-time — alertas operacionais)
        limite_3d = (date.today() - timedelta(days=3)).isoformat()
        cad_paradas = [dict(r) for r in conn.execute("""
            SELECT empresa_nome, data_acao, etapa, id,
                   CAST(EXTRACT(EPOCH FROM (NOW() - data_acao::timestamp))/86400 AS INTEGER) AS dias_parada
            FROM cadencias
            WHERE tenant_id=? AND status='pendente' AND data_acao < ?
            ORDER BY data_acao ASC LIMIT 10
        """, (tid, limite_3d)).fetchall()]

        conn.close()

        status_counts = {
            "prospect": stats.get("emp_prospect", 0),
            "lead": stats.get("emp_lead", 0),
            "cliente": stats.get("emp_cliente", 0),
        }
        estagio_counts = {
            "prospect": stats.get("ops_prospect", 0),
            "contato": stats.get("ops_contato", 0),
            "proposta": stats.get("ops_proposta", 0),
            "negociacao": stats.get("ops_negociacao", 0),
            "fechado": stats.get("ops_fechado", 0),
        }

        return render_template(
            "dashboard.html",
            status_counts=status_counts,
            estagio_counts=estagio_counts,
            pipeline_val=float(stats.get("pipeline_val") or 0),
            atividades=atividades,
            total_empresas=stats.get("emp_total", 0),
            clientes=stats.get("emp_cliente", 0),
            em_aberto=stats.get("ops_abertas", 0),
            radar=[],
            radar_alerta_count=0,
            potencial_expansao=0,
            cob_resumo={},
            rec_resumo={},
            mes_atual=mes_atual,
            radar_badge={"editais": 0, "concorrentes": 0, "total": stats.get("radar_nao_lidos", 0)},
            portais_ativos=stats.get("portais_ativos", 0),
            rec_atrasados_count=0,
            deals_fechados_semana=0,
            receita_mes=float(stats.get("fechados_mes") or 0),
            pct_meta=pct_90d,
            cadencias_ativas_count=stats.get("em_cadencia", 0),
            top_acao="",
            pauto_resumo={"novos_hoje": stats.get("pauto_hoje", 0), "prontos": stats.get("pauto_prontos", 0)},
            dias_restantes=dias_restantes,
            faturado_90d=faturado_90d,
            pct_90d=pct_90d,
            ritmo_diario=ritmo_diario,
            funil={
                "sdr_novos": stats.get("sdr_novos", 0),
                "em_cadencia": stats.get("em_cadencia", 0),
                "props_abertas": stats.get("ops_abertas", 0),
                "fechados_mes": float(stats.get("fechados_mes") or 0),
            },
            cad_hoje=cad_hoje,
            ops_paradas=ops_paradas,
            leads_quentes=leads_quentes,
            cad_paradas=cad_paradas,
            meta_valor=meta_valor,
            meta_nome=meta_nome,
        )
    except Exception:
        _log.error("[DASHBOARD] Erro critico", exc_info=True)
        try:
            conn.close()
        except Exception:
            pass
        try:
            return render_template("dashboard.html",
                                   mes_atual=str(date.today())[:7],
                                   **_DASHBOARD_FALLBACK)
        except Exception as _fe:
            _log.error("[DASHBOARD] Fallback render falhou", exc_info=True)
            return render_template("erro.html",
                                   titulo="Erro temporário",
                                   mensagem="Não foi possível carregar o dashboard. Tente recarregar a página.",
                                   detalhe=str(_fe)), 500


@app.route("/dashboard")
@login_required
def dashboard_alias():
    params = dict(request.args)
    return redirect(url_for("dashboard", **params))


@app.route("/v2/dashboard")
@login_required
def dashboard_v2():
    return redirect(url_for("dashboard", v=2))


@app.route("/v2/sdr")
@login_required
def sdr_v2():
    return redirect(url_for("sdr_evolutivo.sdr_evolutivo_dashboard", v=2))


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(500)
def erro_500(e):
    import traceback
    print(f"[500] {traceback.format_exc()}")
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Erro interno do servidor"}), 500
    try:
        return redirect(url_for("dashboard"))
    except Exception:
        return """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="3;url=/">
  <style>
    body{background:#0A0A0F;color:#F0F0F5;font-family:Inter,sans-serif;
         display:flex;align-items:center;justify-content:center;height:100vh;
         flex-direction:column;gap:16px}
    .spinner{width:32px;height:32px;border:2px solid #333;border-top-color:#C5A089;
             border-radius:50%;animation:spin 1s linear infinite}
    @keyframes spin{to{transform:rotate(360deg)}}
  </style>
</head>
<body><div class="spinner"></div><p>Reconectando... Aguarde.</p></body>
</html>""", 500


@app.errorhandler(404)
def erro_404(e):
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Rota não encontrada"}), 404
    try:
        return redirect(url_for("dashboard"))
    except Exception:
        return redirect("/")


@app.errorhandler(Exception)
def erro_geral(e):
    import traceback
    print(f"[ERRO GERAL] {traceback.format_exc()}")
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Erro interno do servidor"}), 500
    try:
        return redirect(url_for("dashboard"))
    except Exception:
        return redirect("/")


# ── Metas ─────────────────────────────────────────────────────────────────────

@app.route("/metas/configurar", methods=["GET", "POST"])
@login_required
def metas_configurar():
    try:
        tenant = tenant_model.get_tenant_atual()
        tid    = tenant["id"]
        conn   = database.get_connection()

        if request.method == "POST":
            valor_meta  = float(request.form.get("valor_meta", 100000) or 100000)
            data_inicio = request.form.get("data_inicio") or None
            data_fim    = request.form.get("data_fim") or None
            nome        = request.form.get("nome") or "Meta Principal"

            conn.execute(
                "UPDATE metas SET ativo=0 WHERE tenant_id=?", (tid,)
            )
            conn.execute(
                """INSERT INTO metas (tenant_id, nome, valor_meta, data_inicio, data_fim, ativo)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (tid, nome, valor_meta, data_inicio, data_fim),
            )
            conn.commit()
            conn.close()
            return jsonify({"ok": True, "mensagem": "Meta salva!"})

        meta = conn.execute(
            """SELECT * FROM metas WHERE tenant_id=? AND ativo=1
               ORDER BY criado_em DESC LIMIT 1""",
            (tid,)
        ).fetchone()
        conn.close()

        return render_template(
            "metas_configurar.html",
            meta=dict(meta) if meta else {},
            tenant=tenant,
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "erro": str(e)})


# ── Empresas ──────────────────────────────────────────────────────────────────

@app.route("/empresas")
@login_required
@require_perfil('gerente')
def empresas_lista():
    q      = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    todas  = emp_model.listar(status=status or None, tenant_id=_tid())
    if q:
        ql = q.lower()
        todas = [e for e in todas if ql in e["nome"].lower()
                 or (e["cnpj"] and ql in e["cnpj"])]
    portais = portal_model.listar_todos()
    return render_template("empresas/lista.html", empresas=todas, q=q, status=status, portais=portais)


@app.route("/empresas/nova", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def empresas_nova():
    if request.method == "POST":
        emp_model.criar({**_form_empresa(request.form), "tenant_id": _tid()})
        flash("Empresa cadastrada com sucesso.", "success")
        return redirect(url_for("empresas_lista"))
    return render_template("empresas/form.html", empresa=None,
                           action=url_for("empresas_nova"))


@app.route("/empresas/<int:id>")
@login_required
@require_perfil('gerente')
def empresas_detalhe(id):
    tid = _tid()
    emp = emp_model.buscar_por_id(id, tenant_id=tid)
    if not emp:
        flash("Empresa não encontrada.", "danger")
        return redirect(url_for("empresas_lista"))
    return render_template(
        "empresas/detalhe.html",
        empresa=emp,
        contatos=cont_model.listar(empresa_id=id, tenant_id=tid),
        ops=op_model.listar(empresa_id=id, tenant_id=tid),
        atividades=atv_model.listar(empresa_id=id, limit=10, tenant_id=tid),
        labels=op_model.ESTAGIO_LABELS,
    )


@app.route("/empresas/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def empresas_editar(id):
    emp = emp_model.buscar_por_id(id, tenant_id=_tid())
    if not emp:
        flash("Empresa não encontrada.", "danger")
        return redirect(url_for("empresas_lista"))
    if request.method == "POST":
        emp_model.atualizar(id, _form_empresa(request.form))
        flash("Empresa atualizada.", "success")
        return redirect(url_for("empresas_detalhe", id=id))
    return render_template("empresas/form.html", empresa=emp,
                           action=url_for("empresas_editar", id=id))


@app.route("/empresas/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('gerente')
def empresas_excluir(id):
    emp_model.excluir(id)
    flash("Empresa excluída.", "success")
    return redirect(url_for("empresas_lista"))


@app.route("/empresas/excluir-lote", methods=["POST"])
@login_required
@require_perfil('gerente')
def empresas_excluir_lote():
    ids = (request.json or {}).get("ids", [])
    for id_ in ids:
        emp_model.excluir(id_)
    return jsonify({"ok": True, "excluidos": len(ids)})


def _form_empresa(f):
    produtos = f.getlist("produtos_ativos") or []
    try:
        num_func = int(f.get("num_funcionarios", "") or 0) or None
    except ValueError:
        num_func = None
    try:
        val_mensal = float(f.get("valor_mensal", "").replace(",", ".") or 0) or None
    except ValueError:
        val_mensal = None
    return dict(
        nome=f.get("nome", "").strip(),
        cnpj=f.get("cnpj", "").strip() or None,
        segmento=f.get("segmento", "").strip() or None,
        porte=f.get("porte", "").strip() or None,
        status=f.get("status", "prospect"),
        telefone=f.get("telefone", "").strip() or None,
        email=f.get("email", "").strip() or None,
        cidade=f.get("cidade", "").strip() or None,
        estado=f.get("estado", "").strip() or None,
        produtos_ativos=", ".join(produtos) if produtos else None,
        num_funcionarios=num_func,
        cliente_ativo=1 if f.get("cliente_ativo") else 0,
        valor_mensal=val_mensal,
        tipo_cartao=f.get("tipo_cartao", "").strip() or None,
        nome_private_label=f.get("nome_private_label", "").strip() or None,
    )


# ── Contatos ──────────────────────────────────────────────────────────────────

@app.route("/contatos")
@login_required
def contatos_lista():
    q    = request.args.get("q", "").strip()
    todos = cont_model.listar(tenant_id=_tid())
    if q:
        ql = q.lower()
        todos = [c for c in todos if ql in c["nome"].lower()
                 or (c["email"] and ql in c["email"].lower())
                 or ql in c["empresa_nome"].lower()]
    return render_template("contatos/lista.html", contatos=todos, q=q)


@app.route("/contatos/novo", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def contatos_novo():
    tid = _tid()
    if request.method == "POST":
        cont_model.criar(_form_contato(request.form))
        flash("Contato cadastrado.", "success")
        return redirect(url_for("contatos_lista"))
    return render_template("contatos/form.html", contato=None,
                           empresas=emp_model.listar(tenant_id=tid),
                           action=url_for("contatos_novo"))


@app.route("/contatos/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def contatos_editar(id):
    tid = _tid()
    c = cont_model.buscar_por_id(id, tenant_id=tid)
    if not c:
        flash("Contato não encontrado.", "danger")
        return redirect(url_for("contatos_lista"))
    if request.method == "POST":
        cont_model.atualizar(id, _form_contato(request.form))
        flash("Contato atualizado.", "success")
        return redirect(url_for("contatos_lista"))
    return render_template("contatos/form.html", contato=c,
                           empresas=emp_model.listar(tenant_id=tid),
                           action=url_for("contatos_editar", id=id))


@app.route("/contatos/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def contatos_excluir(id):
    cont_model.excluir(id)
    flash("Contato excluído.", "success")
    return redirect(url_for("contatos_lista"))


def _form_contato(f):
    return dict(
        empresa_id=int(f.get("empresa_id")),
        nome=f.get("nome", "").strip(),
        cargo=f.get("cargo", "").strip() or None,
        email=f.get("email", "").strip() or None,
        telefone=f.get("telefone", "").strip() or None,
    )


# ── Oportunidades ─────────────────────────────────────────────────────────────

@app.route("/oportunidades")
@login_required
def oportunidades_kanban():
    todas      = op_model.listar(tenant_id=_tid())
    by_estagio = {e: [] for e in op_model.ESTAGIOS}
    for o in todas:
        by_estagio.setdefault(o["etapa"] or "prospect", []).append(o)
    return render_template(
        "oportunidades/kanban.html",
        by_estagio=by_estagio,
        estagios=op_model.ESTAGIOS,
        labels=op_model.ESTAGIO_LABELS,
    )


@app.route("/oportunidades/nova", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_nova():
    tid = _tid()
    if request.method == "POST":
        op_model.criar({**_form_oportunidade(request.form), "tenant_id": tid})
        flash("Oportunidade criada.", "success")
        return redirect(url_for("oportunidades_kanban"))
    return render_template(
        "oportunidades/form.html", op=None,
        empresas=emp_model.listar(tenant_id=tid),
        estagios=op_model.ESTAGIOS, labels=op_model.ESTAGIO_LABELS,
        action=url_for("oportunidades_nova"),
        pre_titulo=request.args.get("titulo", ""),
    )


@app.route("/oportunidades/<int:id>")
@login_required
def oportunidades_detalhe(id):
    tid = _tid()
    o = op_model.buscar_por_id(id, tenant_id=tid)
    if not o:
        flash("Oportunidade não encontrada.", "danger")
        return redirect(url_for("oportunidades_kanban"))
    return render_template(
        "oportunidades/detalhe.html",
        op=o,
        atividades=atv_model.listar(oportunidade_id=id, tenant_id=tid),
        labels=op_model.ESTAGIO_LABELS,
        estagios=op_model.ESTAGIOS,
    )


@app.route("/oportunidades/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_editar(id):
    tid = _tid()
    o = op_model.buscar_por_id(id, tenant_id=tid)
    if not o:
        flash("Oportunidade não encontrada.", "danger")
        return redirect(url_for("oportunidades_kanban"))
    if request.method == "POST":
        op_model.atualizar(id, _form_oportunidade(request.form))
        flash("Oportunidade atualizada.", "success")
        return redirect(url_for("oportunidades_detalhe", id=id))
    return render_template(
        "oportunidades/form.html", op=o,
        empresas=emp_model.listar(tenant_id=tid),
        estagios=op_model.ESTAGIOS, labels=op_model.ESTAGIO_LABELS,
        action=url_for("oportunidades_editar", id=id),
    )


@app.route("/oportunidades/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_excluir(id):
    tid = _tid()
    if not op_model.buscar_por_id(id, tenant_id=tid):
        flash("Oportunidade não encontrada.", "danger")
        return redirect(url_for("oportunidades_kanban"))
    op_model.excluir(id)
    flash("Oportunidade excluída.", "success")
    return redirect(url_for("oportunidades_kanban"))


@app.route("/oportunidades/<int:id>/mover", methods=["POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_mover(id):
    tid = _tid()
    novo = request.json.get("etapa") or request.json.get("estagio", "")
    if novo not in op_model.ESTAGIOS:
        return jsonify({"error": "Estágio inválido"}), 400
    o = op_model.buscar_por_id(id, tenant_id=tid)
    if not o:
        return jsonify({"error": "Não encontrado"}), 404
    dados = dict(o)
    dados["etapa"] = novo
    op_model.atualizar(id, dados)
    return jsonify({"ok": True, "etapa": novo, "label": op_model.ESTAGIO_LABELS[novo]})


@app.route("/oportunidades/radar")
@login_required
def oportunidades_radar():
    tid = _tid()
    radar = op_model.listar_radar(tenant_id=tid)
    op_model.salvar_scores_radar(radar)
    return jsonify([
        {
            "id": r["id"],
            "titulo": r["titulo"],
            "empresa": r["empresa_nome"],
            "etapa": r["etapa"],
            "estagio_label": r["estagio_label"],
            "valor": r["valor_estimado"],
            "score": r["score_calc"],
            "dias_sem_contato": r["dias_sem_contato"],
            "proxima_acao": r["proxima_acao"],
        }
        for r in radar
    ])


def _form_oportunidade(f):
    try:
        valor = float(f.get("valor_estimado", "").replace(",", ".") or 0) or None
    except ValueError:
        valor = None
    try:
        cartoes = int(f.get("num_cartoes", "") or 0) or None
    except ValueError:
        cartoes = None
    return dict(
        empresa_id=int(f.get("empresa_id")),
        titulo=f.get("titulo", "").strip(),
        etapa=f.get("etapa") or f.get("estagio", "prospect"),
        valor_estimado=valor,
        num_cartoes=cartoes,
        responsavel=f.get("responsavel", "").strip() or None,
        previsao_fechamento=f.get("previsao_fechamento", "").strip() or None,
        notas=f.get("notas", "").strip() or None,
    )


# ── Pipeline Inteligente ──────────────────────────────────────────────────────

PIPELINE_ETAPAS = ["prospect", "contato", "proposta", "negociacao", "fechado"]
PIPELINE_LABELS = {
    "prospect":   "📋 Prospect",
    "contato":    "📞 Contato Feito",
    "proposta":   "📄 Proposta Enviada",
    "negociacao": "🤝 Em Negociação",
    "fechado":    "✅ Fechado",
}


def _calcular_velocidade(ultima_acao_em):
    import datetime as _dt
    if not ultima_acao_em:
        return 'morto', '💀'
    try:
        ua = _dt.datetime.fromisoformat(str(ultima_acao_em)[:19])
        dias = (_dt.datetime.now() - ua).days
    except Exception:
        return 'morto', '💀'
    if dias <= 7:  return 'acelerando', '🟢'
    if dias <= 14: return 'normal', '🟡'
    if dias <= 30: return 'travado', '🔴'
    return 'morto', '💀'


def _calcular_score_pipeline(oportunidade, porte=''):
    score = 50
    dias_etapa = int(oportunidade.get('dias_etapa') or 0)
    if dias_etapa <= 3:   score += 20
    elif dias_etapa <= 7: score += 10
    elif dias_etapa > 30: score -= 30
    elif dias_etapa > 14: score -= 15
    etapa = oportunidade.get('etapa', 'prospect')
    score += {'prospect': -10, 'contato': 0, 'proposta': 10, 'negociacao': 20}.get(etapa, 0)
    p = (porte or '').upper()
    if 'GRANDE' in p:    score += 10
    elif 'MEDIO' in p:   score += 5
    return max(0, min(100, score))


@app.route("/pipeline")
@login_required
def pipeline_index():
    import datetime as _dt
    tid  = _tid()
    conn = database.get_connection()
    rows = conn.execute("""
        SELECT o.*, e.nome AS empresa_nome, e.cidade AS empresa_cidade,
               e.estado AS empresa_estado, e.porte AS empresa_porte
        FROM oportunidades o
        JOIN empresas e ON o.empresa_id = e.id
        WHERE o.tenant_id = ?
          AND o.etapa NOT IN ('fechado')
        ORDER BY o.criado_em DESC
    """, (tid,)).fetchall()
    conn.close()

    hoje = _dt.datetime.now()
    by_etapa     = {e: [] for e in PIPELINE_ETAPAS}
    total_neg    = 0.0
    score_soma   = 0
    n_scores     = 0
    acelerando   = 0
    travados     = 0

    for raw in rows:
        r = dict(raw)
        ultima_acao = r.get('ultima_acao_em') or r.get('data_ultimo_contato')
        vel_status, vel_emoji = _calcular_velocidade(ultima_acao)

        try:
            ref = str(ultima_acao or r.get('criado_em') or '')[:19]
            ref_dt = _dt.datetime.fromisoformat(ref) if ref else hoje
            dias_etapa = max(0, (hoje - ref_dt).days)
        except Exception:
            dias_etapa = 0

        r['dias_etapa']  = dias_etapa
        r['vel_status']  = vel_status
        r['vel_emoji']   = vel_emoji
        score = int(r.get('score_fechamento') or 0) or _calcular_score_pipeline(r, r.get('empresa_porte', ''))
        r['score_calc']  = score

        etapa = r.get('etapa') or 'prospect'
        if etapa not in by_etapa:
            etapa = 'prospect'
        r['etapa'] = etapa

        if etapa == 'negociacao':
            total_neg += float(r.get('valor_estimado') or 0)

        score_soma += score
        n_scores   += 1
        if vel_status == 'acelerando': acelerando += 1
        elif vel_status == 'travado':  travados   += 1

        by_etapa[etapa].append(r)

    meta        = 100_000.0
    score_medio = round(score_soma / n_scores) if n_scores else 0

    return render_template("pipeline.html",
        by_etapa=by_etapa,
        etapas=PIPELINE_ETAPAS,
        labels=PIPELINE_LABELS,
        total_neg=total_neg,
        meta=meta,
        falta=max(0.0, meta - total_neg),
        score_medio=score_medio,
        acelerando=acelerando,
        travados=travados,
    )


@app.route("/pipeline/mover", methods=["POST"])
@login_required
@require_perfil('vendedor')
def pipeline_mover():
    import datetime as _dt
    dados     = request.json or {}
    op_id     = dados.get("oportunidade_id")
    nova_etapa = dados.get("nova_etapa", "")
    if nova_etapa not in PIPELINE_ETAPAS:
        return jsonify({"error": "Etapa inválida"}), 400
    tid  = _tid()
    conn = database.get_connection()
    op   = conn.execute(
        "SELECT id FROM oportunidades WHERE id = ? AND tenant_id = ?", (op_id, tid)
    ).fetchone()
    if not op:
        conn.close()
        return jsonify({"error": "Oportunidade não encontrada"}), 404
    agora = _dt.datetime.now().isoformat(timespec='seconds')
    conn.execute(
        "UPDATE oportunidades SET etapa = ?, ultima_acao_em = ?, dias_etapa = 0 WHERE id = ?",
        (nova_etapa, agora, op_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "etapa": nova_etapa})


@app.route("/pipeline/proxima-acao/<int:op_id>", methods=["POST"])
@login_required
def pipeline_proxima_acao(op_id):
    tid  = _tid()
    conn = database.get_connection()
    row  = conn.execute("""
        SELECT o.*, e.nome AS empresa_nome, e.cidade AS empresa_cidade,
               e.estado AS empresa_estado, e.segmento AS empresa_segmento
        FROM oportunidades o JOIN empresas e ON o.empresa_id = e.id
        WHERE o.id = ? AND o.tenant_id = ?
    """, (op_id, tid)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Não encontrado"}), 404
    ativs = conn.execute(
        "SELECT tipo, descricao, data FROM atividades WHERE oportunidade_id = ? ORDER BY data DESC LIMIT 5",
        (op_id,),
    ).fetchall()
    conn.close()

    r = dict(row)
    historico = "; ".join(
        f"{a['tipo']}: {a['descricao'] or ''} ({a['data'] or ''})" for a in ativs
    ) or "Sem histórico de contato"

    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        prompt = f"""Você é um consultor comercial especialista em benefícios corporativos.

LEAD: {r.get('empresa_nome')} — {r.get('empresa_cidade','')}/{r.get('empresa_estado','')}
SEGMENTO: {r.get('empresa_segmento') or 'não informado'}
ETAPA DO PIPELINE: {r.get('etapa','prospect')}
TÍTULO: {r.get('titulo','')}
VALOR: R$ {r.get('valor_estimado') or '0'}
HISTÓRICO: {historico}

Sugira em 2 linhas numeradas:
1. O que fazer AGORA (ação específica)
2. O que falar (argumento para esse segmento)

Máximo 40 palavras. Foco em benefícios corporativos: VA, VR, Wellhub, combustível."""
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        sugestao = resp.content[0].text.strip()
    except Exception:
        sugestao = "Entre em contato para reativar o interesse nesta oportunidade."

    return jsonify({"ok": True, "sugestao": sugestao})


# ── Atividades ────────────────────────────────────────────────────────────────

@app.route("/atividades")
@login_required
def atividades_lista():
    tid = _tid()
    tipo_filtro = request.args.get("tipo", "todos")
    atividades = atv_model.listar(limit=100, tenant_id=tid)
    cadencias_hoje = cad_model.listar_hoje(tenant_id=tid)
    conn = database.get_connection()
    radar_items = [dict(r) for r in conn.execute(
        "SELECT *, descricao AS resumo, url_original AS link FROM radar_alertas WHERE lido=0 AND arquivado=0 AND tenant_id=? ORDER BY criado_em DESC LIMIT 20",
        (tid,)
    ).fetchall()]
    conn.close()
    return render_template("atividades/lista.html",
        atividades=atividades,
        cadencias_hoje=cadencias_hoje,
        radar_items=radar_items,
        tipo_filtro=tipo_filtro,
    )


@app.route("/atividades/nova", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def atividades_nova():
    if request.method == "POST":
        emp_id = request.form.get("empresa_id")
        op_id  = request.form.get("oportunidade_id")
        atv_model.criar(dict(
            empresa_id=int(emp_id) if emp_id else None,
            oportunidade_id=int(op_id) if op_id else None,
            tipo=request.form.get("tipo", "outro"),
            descricao=request.form.get("descricao", "").strip() or None,
            data=request.form.get("data", "").strip() or None,
        ))
        flash("Atividade registrada.", "success")
        next_url = request.form.get("next") or url_for("atividades_lista")
        return redirect(next_url)
    tid = _tid()
    empresas      = emp_model.listar(tenant_id=tid)
    oportunidades = op_model.listar(tenant_id=tid)
    pre_empresa   = request.args.get("empresa_id", "")
    pre_op        = request.args.get("oportunidade_id", "")
    next_url      = request.args.get("next", "")
    return render_template(
        "atividades/form.html",
        empresas=empresas, oportunidades=oportunidades,
        tipos=atv_model.TIPOS,
        pre_empresa=pre_empresa, pre_op=pre_op, next_url=next_url,
    )


@app.route("/atividades/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def atividades_excluir(id):
    atv_model.excluir(id)
    flash("Atividade excluída.", "success")
    return redirect(url_for("atividades_lista"))


# ── IA ────────────────────────────────────────────────────────────────────────

@app.route("/ai/score/<int:empresa_id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_score(empresa_id):
    try:
        return jsonify(ai.score_lead(empresa_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/whatsapp/<int:contato_id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_whatsapp(contato_id):
    try:
        return jsonify(ai.gerar_mensagem_whatsapp(contato_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/proxima-acao/<int:op_id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_proxima_acao(op_id):
    try:
        return jsonify(ai.proxima_acao(op_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Leads — helpers ───────────────────────────────────────────────────────────

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1", "iso-8859-1"]
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


def _ler_arquivo(raw: bytes, nome: str) -> tuple:
    ext = nome.lower().rsplit(".", 1)[-1] if "." in nome else "csv"
    if ext == "xlsx":
        return _ler_xlsx_bytes(raw)
    if ext == "xls":
        return _ler_xls_bytes(raw)
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

@app.route("/leads/importar")
@login_required
@require_perfil('gerente')
def leads_importar_form():
    return render_template("leads/importar.html")


@app.route("/leads/importar/preview", methods=["POST"])
@login_required
@require_perfil('gerente')
def leads_importar_preview():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
    ext = arquivo.filename.lower().rsplit(".", 1)[-1] if "." in arquivo.filename else ""
    if ext not in _EXTS_ACEITAS:
        return jsonify({"error": f"Formato .{ext} não suportado. Use .csv, .xlsx ou .xls."}), 400
    try:
        raw = arquivo.stream.read()
        colunas, linhas = _ler_arquivo(raw, arquivo.filename)
        mapa = _auto_mapear(colunas)
        return jsonify({"colunas": colunas, "preview": linhas[:10], "mapeamento_sugerido": mapa})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/leads/importar/confirmar", methods=["POST"])
@login_required
@require_perfil('gerente')
def leads_importar_confirmar():
    try:
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            return jsonify({"erro": "Arquivo não encontrado."}), 400
        mapa = {
            "nome":     request.form.get("map_nome", ""),
            "empresa":  request.form.get("map_empresa", ""),
            "cargo":    request.form.get("map_cargo", ""),
            "telefone": request.form.get("map_telefone", ""),
            "email":    request.form.get("map_email", ""),
            "cidade":   request.form.get("map_cidade", ""),
        }
        raw = arquivo.stream.read()
        _, linhas = _ler_arquivo(raw, arquivo.filename)
        importados, ignorados = _processar_linhas(linhas, mapa, tenant_id=_tid())
        return jsonify({
            "ok": True,
            "importados": importados,
            "ignorados": ignorados,
            "mensagem": (
                f"{importados} lead(s) importado(s) com sucesso."
                + (f" {ignorados} linha(s) ignorada(s) (sem nome ou empresa)." if ignorados else "")
            ),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500


# ── Prospecção ────────────────────────────────────────────────────────────────

@app.route("/prospeccao")
@login_required
def prospeccao_lista():
    tab    = request.args.get("tab", "todos")
    status = request.args.get("status", "")

    score_min = score_max = None
    if tab == "quentes":
        score_min = 70
    elif tab == "mornos":
        score_min, score_max = 40, 69
    elif tab == "frios":
        score_max = 39

    leads  = prosp_model.listar(score_min=score_min, score_max=score_max, status=status or None, tenant_id=_tid())
    counts = prosp_model.contar_por_status(tenant_id=_tid())
    total  = sum(counts.values())
    quentes_count = sum(1 for l in leads if l["score"] is not None and l["score"] >= 70)
    return render_template(
        "leads/prospeccao.html",
        leads=leads, tab=tab, status=status,
        counts=counts, total=total,
        quentes_count=quentes_count,
        status_labels=prosp_model.STATUS_LABELS,
        status_list=prosp_model.STATUS_LIST,
    )


@app.route("/prospeccao/<int:id>/status", methods=["POST"])
@login_required
@require_perfil('vendedor')
def prospeccao_status(id):
    novo = (request.json or {}).get("status", "")
    if novo not in prosp_model.STATUS_LIST:
        return jsonify({"error": "Status inválido"}), 400
    prosp_model.salvar_status(id, novo)
    return jsonify({"ok": True, "status": novo, "label": prosp_model.STATUS_LABELS[novo]})


@app.route("/prospeccao/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def prospeccao_excluir(id):
    prosp_model.excluir(id)
    flash("Lead removido da prospecção.", "success")
    return redirect(url_for("prospeccao_lista"))


@app.route("/prospeccao/excluir-lote", methods=["POST"])
@login_required
@require_perfil('vendedor')
def prospeccao_excluir_lote():
    ids = (request.json or {}).get("ids", [])
    for id_ in ids:
        prosp_model.excluir(id_)
    return jsonify({"ok": True, "excluidos": len(ids)})


@app.route("/prospeccao/exportar")
@login_required
@require_perfil('vendedor')
def prospeccao_exportar():
    ids_raw = request.args.getlist("ids")
    ids = [int(i) for i in ids_raw if i.isdigit()]
    if not ids:
        flash("Selecione pelo menos um lead para exportar.", "danger")
        return redirect(url_for("prospeccao_lista"))

    leads = prosp_model.listar_ids_para_exportacao(ids, tenant_id=_tid())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "nome", "empresa", "cargo", "telefone", "email",
        "score", "status", "msg_whatsapp", "msg_email_assunto", "msg_email_corpo",
    ])
    for l in leads:
        writer.writerow([
            l["contato_nome"], l["empresa_nome"], l["cargo"] or "",
            l["contato_telefone"] or "", l["contato_email"] or "",
            l["score"] if l["score"] is not None else "",
            l["status"],
            l["msg_whatsapp"] or "",
            l["msg_email_assunto"] or "",
            l["msg_email_corpo"] or "",
        ])
    return Response(
        "﻿" + output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


# ── Prospecção automática (BrasilAPI / CNPJ.ws) ──────────────────────────────

@app.route("/prospeccao/automatica")
@login_required
def prospeccao_automatica():
    uf        = request.args.get("uf", "").strip().upper()
    score_min = request.args.get("score_min", None)
    status    = request.args.get("status", "").strip() or None
    try:
        score_min_int = int(score_min) if score_min else None
    except ValueError:
        score_min_int = None
    leads = pauto_model.listar(uf=uf or None, score_min=score_min_int, status=status, tenant_id=_tid())
    return render_template(
        "leads/busca_automatica.html",
        leads=leads,
        uf=uf, score_min=score_min or "", status_filter=status or "",
        cnaes=pauto_model.CNAES_DISPONIVEIS,
        ufs=pauto_model.UFS_DISPONIVEIS,
    )


@app.route("/prospeccao/buscar-automatico", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_buscar_automatico():
    dados  = request.json or {}
    uf     = (dados.get("uf") or "ES").strip().upper()
    cnaes  = dados.get("cnaes") or []
    limite = min(int(dados.get("limite") or 30), 100)
    try:
        resultado = pauto_model.buscar_e_salvar(uf, cnaes, limite, tenant_id=_tid())
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prospeccao/automatica/<int:id>/importar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_importar(id):
    try:
        emp_id = pauto_model.importar(id, tenant_id=_tid())
        return jsonify({"ok": True, "empresa_id": emp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prospeccao/automatica/importar-selecionados", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_importar_lote():
    ids = (request.json or {}).get("ids", [])
    ok = pauto_model.importar_varios(ids, tenant_id=_tid())
    return jsonify({"ok": True, "importados": ok})


@app.route("/prospeccao/automatica/<int:id>/status", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_status(id):
    novo = (request.json or {}).get("status", "")
    if novo not in ("novo", "importado", "descartado"):
        return jsonify({"error": "Status inválido"}), 400
    pauto_model.atualizar_status(id, novo, tenant_id=_tid())
    return jsonify({"ok": True})


@app.route("/prospeccao/autonoma/rodar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_autonoma_rodar():
    from models.prospeccao_autonoma import rodar_prospeccao_autonoma

    def _rodar():
        import traceback
        _db = None
        try:
            _db = database.get_new_db_connection()
            resultado = rodar_prospeccao_autonoma(_db)
            print(f"[SDR-MANUAL] resultado: {resultado}")
        except Exception as e:
            print(f"[SDR-MANUAL] ERRO: {e}")
            traceback.print_exc()
            if _db:
                try: _db.rollback()
                except Exception: pass
        finally:
            if _db:
                try: _db.close()
                except Exception: pass

    threading.Thread(target=_rodar, daemon=True).start()
    return jsonify({"status": "iniciado", "mensagem": "Prospecção rodando em background"})


@app.route("/prospeccao/autonoma/status")
@login_required
def prospeccao_autonoma_status():
    from models.prospeccao_autonoma import status_resumo
    return jsonify(status_resumo())


# ── Cron Job Railway — executa SDR automaticamente ───────────────────────────
# Configuração Railway: Dashboard → seu projeto → Cron Jobs → New Cron Job
#   Schedule:  0 9,14 * * 1-5   (segunda a sexta, 9h e 14h)
#   Command:   curl -s -X POST https://<seu-app>.up.railway.app/cron/executar-sdr
#              -H "X-Cron-Token: $CRON_TOKEN"
# Adicione CRON_TOKEN nas variáveis de ambiente do Railway.

@app.route("/cron/executar-sdr", methods=["GET", "POST"])
def cron_executar_sdr():
    import hmac as _hmac

    cron_token = os.environ.get("CRON_TOKEN", "")
    if not cron_token:
        return jsonify({"error": "CRON_TOKEN não configurado no servidor"}), 503

    token_recebido = (
        request.headers.get("X-Cron-Token", "")
        or request.args.get("token", "")
    )
    if not token_recebido or not _hmac.compare_digest(
        cron_token.encode(), token_recebido.encode()
    ):
        return jsonify({"error": "Token inválido"}), 401

    from models.prospeccao_autonoma import rodar_prospeccao_autonoma

    def _rodar_cron():
        import traceback
        _db = None
        try:
            _db = database.get_new_db_connection()
            resultado = rodar_prospeccao_autonoma(
                _db, config_override={"max_leads_por_execucao": 50}
            )
            app.logger.info("[CRON-SDR] resultado: %s", resultado)
        except Exception as exc:
            app.logger.error("[CRON-SDR] ERRO: %s", exc)
            traceback.print_exc()
            if _db:
                try:
                    _db.rollback()
                except Exception:
                    pass
        finally:
            if _db:
                try:
                    _db.close()
                except Exception:
                    pass

    threading.Thread(target=_rodar_cron, daemon=True).start()
    return jsonify({
        "status": "iniciado",
        "mensagem": "SDR cron rodando em background",
        "max_leads": 50,
    })


# ── Cron Job Railway — backup automático ─────────────────────────────────────
# Configuração Railway: Dashboard → seu projeto → Cron Jobs → New Cron Job
#   Schedule:  0 18 * * 5   (toda sexta-feira às 18h UTC)
#   Command:   curl -s -X POST https://<seu-app>.up.railway.app/cron/backup
#              -H "X-Cron-Token: $CRON_TOKEN"

@app.route("/cron/backup", methods=["POST"])
def cron_backup():
    import hmac as _hmac

    cron_token = os.environ.get("CRON_TOKEN", "")
    if not cron_token:
        return jsonify({"error": "CRON_TOKEN não configurado no servidor"}), 503

    token_recebido = (
        request.headers.get("X-Cron-Token", "")
        or request.args.get("token", "")
    )
    if not token_recebido or not _hmac.compare_digest(
        cron_token.encode(), token_recebido.encode()
    ):
        return jsonify({"error": "Token inválido"}), 401

    def _rodar_backup():
        import traceback
        try:
            import importlib.util, pathlib
            spec = importlib.util.spec_from_file_location(
                "backup",
                pathlib.Path(__file__).parent / "scripts" / "backup.py",
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            rc = mod.main()
            app.logger.info("[CRON-BACKUP] exit code: %s", rc)
        except Exception as exc:
            app.logger.error("[CRON-BACKUP] ERRO: %s", exc)
            traceback.print_exc()

    threading.Thread(target=_rodar_backup, daemon=True).start()
    return jsonify({"status": "iniciado", "mensagem": "Backup iniciado em background"})


# ── Webhook Brevo — rastreamento de emails ────────────────────────────────────
# Configurar no Brevo: Settings → Webhooks → Add → URL: https://<app>/brevo/webhook?secret=<BREVO_WEBHOOK_SECRET>
# Marcar eventos: opened, clicked

@app.route("/brevo/webhook", methods=["POST"])
def brevo_webhook():
    from models.cadencia import atualizar_email_status, atualizar_temperatura_lead

    secret = os.environ.get("BREVO_WEBHOOK_SECRET", "")
    if secret:
        token = (
            request.args.get("secret", "")
            or request.headers.get("X-Sib-Webhook-Secret", "")
            or request.headers.get("X-Brevo-Webhook-Secret", "")
        )
        if not token or not hmac.compare_digest(secret.encode(), token.encode()):
            app.logger.warning("[BREVO-WH] Token inválido — request ignorado")
            return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    event_type = (payload.get("event") or "").lower()
    message_id = (payload.get("message-id") or "").strip()
    email_dest  = (payload.get("email") or "").lower().strip()

    _EVENT_MAP = {
        "opened":  "aberto",
        "clicked": "clicado",
    }
    _TEMP_MAP = {
        "opened":  "email_aberto",
        "clicked": "email_clicado",
    }

    if event_type not in _EVENT_MAP:
        return jsonify({"ok": True, "skipped": event_type}), 200

    novo_status = _EVENT_MAP[event_type]
    evento_temp = _TEMP_MAP[event_type]

    conn = database.get_connection()
    try:
        cad = None
        if message_id:
            cad = conn.execute(
                "SELECT id, empresa_id, tenant_id FROM cadencias WHERE email_brevo_id=?",
                (message_id,),
            ).fetchone()
        if not cad and email_dest:
            cad = conn.execute(
                """SELECT id, empresa_id, tenant_id FROM cadencias
                   WHERE (contato_email=? OR email_empresa=?)
                     AND email_status IN ('enviado','aberto')
                   ORDER BY id DESC LIMIT 1""",
                (email_dest, email_dest),
            ).fetchone()

        if cad:
            atualizar_email_status(cad["id"], novo_status)
            if cad["empresa_id"]:
                atualizar_temperatura_lead(
                    cad["empresa_id"], evento_temp, cad["tenant_id"] or 1
                )
            app.logger.info(
                "[BREVO-WH] %s → cadência %s empresa %s",
                event_type, cad["id"], cad["empresa_id"],
            )
        else:
            app.logger.debug("[BREVO-WH] %s — cadência não encontrada (msg=%s email=%s)",
                             event_type, message_id, email_dest)
    finally:
        conn.close()

    return jsonify({"ok": True}), 200


# ── IA — leads (por lead, chamadas via JS loop) ───────────────────────────────

@app.route("/ai/leads/pontuar/<int:id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_leads_pontuar(id):
    try:
        lead = prosp_model.buscar_por_id(id)
        if not lead:
            return jsonify({"error": "Lead não encontrado"}), 404
        resultado = ai.score_lead(lead["empresa_id"])
        prosp_model.salvar_score(
            id,
            resultado["score"],
            resultado.get("justificativa", ""),
            resultado.get("pontos_fortes", []),
            resultado.get("pontos_fracos", []),
        )
        return jsonify({
            "ok": True, "id": id,
            "score": resultado["score"],
            "justificativa": resultado.get("justificativa"),
            "pontos_fortes": resultado.get("pontos_fortes", []),
            "pontos_fracos": resultado.get("pontos_fracos", []),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/leads/whatsapp/<int:id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_leads_whatsapp(id):
    try:
        resultado = ai.gerar_whatsapp_lead(id)
        prosp_model.salvar_whatsapp(id, resultado["mensagem"])
        return jsonify({"ok": True, "id": id, "mensagem": resultado["mensagem"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/leads/email/<int:id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def ai_leads_email(id):
    try:
        resultado = ai.gerar_email_lead(id)
        prosp_model.salvar_email(id, resultado["assunto"], resultado["corpo"])
        return jsonify({
            "ok": True, "id": id,
            "assunto": resultado["assunto"],
            "corpo": resultado["corpo"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── SDR — Cadências ──────────────────────────────────────────────────────────

@app.route("/cadencias")
@login_required
def cadencias_index():
    from urllib.parse import quote as _quote
    tid = _tid()
    hoje    = cad_model.listar_hoje(tenant_id=tid)
    proximos = cad_model.listar_proximos_dias(7, tenant_id=tid)

    def _limpar_fone(n):
        return "".join(c for c in (n or "") if c.isdigit()).lstrip("55")

    for item in hoje + proximos:
        fone = _limpar_fone(item.get("contato_whatsapp", ""))
        item["wa_url"] = (
            f"https://wa.me/55{fone}?text={_quote(item.get('mensagem_whatsapp') or '')}"
            if fone else ""
        )
        em = item.get("contato_email", "") or ""
        item["mail_url"] = (
            f"mailto:{em}?subject={_quote(item.get('assunto_email') or '')}"
            f"&body={_quote(item.get('corpo_email') or '')}"
            if em else ""
        )
        item["etapa_label"] = cad_model.ETAPA_LABELS.get(item["etapa"], f"Etapa {item['etapa']}")

    return render_template(
        "cadencias/index.html",
        hoje=hoje,
        proximos=proximos,
        hoje_count=len(hoje),
    )


@app.route("/cadencia/iniciar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def cadencia_iniciar():
    import re as _re
    from datetime import date as _date, timedelta as _td
    try:
        dados          = request.json or {}
        empresa_id     = dados.get("empresa_id")
        empresa_nome   = (dados.get("empresa_nome") or "").strip()
        whatsapp       = (dados.get("whatsapp") or "").strip()
        email          = (dados.get("email") or "").strip()
        op_id          = dados.get("oportunidade_id")
        canal_email    = bool(dados.get("canal_email", True))
        canal_whatsapp = bool(dados.get("canal_whatsapp", True))
        tenant_id      = session.get("tenant_id", 1) or 1

        if not empresa_nome:
            return jsonify({"error": "Nome da empresa é obrigatório."}), 400

        import anthropic as _ant
        import models.ia_config as ia_mod
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        _conn_ia = database.get_connection()
        _sys_cad = ia_mod.get_system_prompt(_conn_ia)
        _conn_ia.close()

        prompt = f"""Gere uma cadência de 4 contatos para a empresa "{empresa_nome}".
Retorne SOMENTE um JSON válido, sem markdown, sem explicações:

{{"etapas":[
  {{"etapa":1,"mensagem_whatsapp":"...","assunto_email":"...","corpo_email":"..."}},
  {{"etapa":2,"mensagem_whatsapp":"...","assunto_email":"...","corpo_email":"..."}},
  {{"etapa":3,"mensagem_whatsapp":"...","assunto_email":"...","corpo_email":"..."}},
  {{"etapa":4,"mensagem_whatsapp":"...","assunto_email":"...","corpo_email":"..."}}
]}}

Regras obrigatórias:
- Etapa 1 (hoje): apresentação Krylo, personalizada com "{empresa_nome}", informal e direta, max 3 parágrafos curtos
- Etapa 2 (D+3): follow-up com case de sucesso de empresa do mesmo porte
- Etapa 3 (D+7): proposta de valor específica mencionando alimentação, refeição, combustível ou wellness
- Etapa 4 (D+14): último contato, urgência suave, ofereça demo de 15min

WhatsApp: máx 3 parágrafos, tom pessoal, sem formatação markdown
E-mail: assunto objetivo (max 8 palavras), corpo profissional com cumprimento e assinatura"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            system=_sys_cad,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        etapas = json.loads(raw.strip()).get("etapas", [])

        if empresa_id:
            cad_model.cancelar_por_empresa(int(empresa_id))

        datas = [
            str(_date.today() + _td(days=d))
            for d in (0, 3, 7, 14)
        ]
        ids = []
        for i, et in enumerate(etapas[:4]):
            ids.append(cad_model.criar_etapa({
                "empresa_id":        empresa_id,
                "empresa_nome":      empresa_nome,
                "contato_whatsapp":  whatsapp,
                "contato_email":     email,
                "email_empresa":     email,
                "oportunidade_id":   op_id,
                "etapa":             et.get("etapa", i + 1),
                "data_acao":         datas[i],
                "mensagem_whatsapp": et.get("mensagem_whatsapp", ""),
                "assunto_email":     et.get("assunto_email", ""),
                "corpo_email":       et.get("corpo_email", ""),
                "status":            "pendente",
                "canal_email":       canal_email,
                "canal_whatsapp":    canal_whatsapp,
                "tenant_id":         tenant_id,
            }))

        return jsonify({"ok": True, "ids": ids, "total": len(ids)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/cadencia/<int:id>/concluir", methods=["POST"])
@login_required
@require_perfil("vendedor")
def cadencia_concluir(id):
    cad_model.concluir(id)
    return jsonify({"ok": True})


@app.route("/cadencia/<int:id>/cancelar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def cadencia_cancelar(id):
    cad_model.cancelar(id)
    return jsonify({"ok": True})


@app.route("/cadencia/emails")
@login_required
def cadencia_emails():
    try:
        atualizados = cad_model.sincronizar_aberturas()
    except Exception:
        atualizados = 0
    emails = cad_model.listar_emails_enviados()
    for e in emails:
        e["etapa_label"] = cad_model.ETAPA_LABELS.get(e["etapa"], f"Etapa {e['etapa']}")
    return render_template("cadencias/emails.html", emails=emails, atualizados=atualizados)


# ── Portal do Cliente (rota pública — sem @login_required) ───────────────────

@app.route("/portal/<token>")
def portal_view(token):
    acesso = portal_model.buscar_por_token(token)
    if not acesso:
        return render_template("portal_erro.html"), 404
    portal_model.atualizar_ultimo_acesso(token)
    empresa = emp_model.buscar_por_id(acesso["empresa_id"])
    if not empresa:
        return render_template("portal_erro.html"), 404
    empresa = dict(empresa)
    produtos = [p.strip() for p in (empresa.get("produtos_ativos") or "").split(",") if p.strip()]
    atividades = atv_model.listar(empresa_id=empresa["id"], limit=5)
    return render_template(
        "portal_cliente.html",
        empresa=empresa,
        acesso=acesso,
        produtos=produtos,
        atividades=atividades,
        krylo_whatsapp=os.getenv("KRYLO_WHATSAPP", ""),
    )


@app.route("/portal/gerar/<int:empresa_id>", methods=["POST"])
@login_required
def portal_gerar(empresa_id):
    emp = emp_model.buscar_por_id(empresa_id)
    if not emp:
        return jsonify({"error": "Empresa não encontrada"}), 404
    token = portal_model.gerar_token(empresa_id, emp["nome"])
    base = os.getenv("APP_URL", request.url_root.rstrip("/"))
    link = f"{base}/portal/{token}"
    return jsonify({"ok": True, "token": token, "link": link})


@app.route("/portal/revogar/<int:empresa_id>", methods=["POST"])
@login_required
def portal_revogar(empresa_id):
    portal_model.revogar(empresa_id)
    return jsonify({"ok": True})


# ── Radar de Mercado Inteligente ─────────────────────────────────────────────

@app.route("/radar")
@login_required
def radar():
    try:
        tenant = tenant_model.get_tenant_atual()
        if not tenant:
            tenant = {"id": 1, "nome_empresa": "Krylo", "nome_plataforma": "Krylo"}
        tenant_id = tenant.get("id", 1)
        db = database.get_new_db_connection()

        alertas_raw = db.execute("""
            SELECT * FROM radar_alertas
            WHERE tenant_id = %s AND arquivado = 0
            ORDER BY relevancia DESC, criado_em DESC
            LIMIT 50
        """, (tenant_id,)).fetchall()

        alertas_raw = [dict(a) for a in alertas_raw]
        alertas_ops      = [a for a in alertas_raw if a.get('tipo') in ('edital', 'noticia', 'insight', 'melhoria')]
        alertas_conteudo = [a for a in alertas_raw if a.get('tipo') == 'conteudo']

        insights = db.execute("""
            SELECT * FROM radar_insights
            WHERE tenant_id = %s
            ORDER BY criado_em DESC
            LIMIT 5
        """, (tenant_id,)).fetchall()
        insights = [dict(i) for i in insights]

        config = db.execute(
            "SELECT * FROM radar_config WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        config = dict(config) if config else {}

        nao_lidos = db.execute("""
            SELECT COUNT(*) AS n FROM radar_alertas
            WHERE tenant_id = %s AND lido = 0 AND arquivado = 0
        """, (tenant_id,)).fetchone()["n"]

        db.close()

        return render_template("radar.html",
            alertas_ops=alertas_ops,
            alertas_conteudo=alertas_conteudo,
            insights=insights,
            config=config,
            nao_lidos=nao_lidos,
            tenant=tenant)
    except Exception as e:
        import traceback; traceback.print_exc()
        return render_template("radar.html",
            alertas_ops=[], alertas_conteudo=[],
            insights=[], config={}, nao_lidos=0,
            tenant={}, erro=str(e))


@app.route("/radar/rodar", methods=["POST"])
@login_required
def radar_rodar():
    try:
        tenant = tenant_model.get_tenant_atual()
        if not tenant:
            tenant = {"id": 1}
        total = radar_model.rodar_radar_completo(tenant.get("id", 1))
        return jsonify({"ok": True, "total": total})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/radar/marcar-lido/<int:alerta_id>", methods=["POST"])
@login_required
def radar_marcar_lido(alerta_id):
    try:
        db = database.get_new_db_connection()
        db.execute("UPDATE radar_alertas SET lido=1 WHERE id=%s", (alerta_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/radar/arquivar/<int:alerta_id>", methods=["POST"])
@login_required
def radar_arquivar(alerta_id):
    try:
        db = database.get_new_db_connection()
        db.execute("UPDATE radar_alertas SET arquivado=1 WHERE id=%s", (alerta_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/radar/config/salvar", methods=["POST"])
@login_required
def radar_config_salvar():
    try:
        tenant = tenant_model.get_tenant_atual()
        tenant_id = tenant.get("id", 1) if tenant else 1
        f = request.form
        db = database.get_new_db_connection()
        now_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = db.execute(
            "SELECT id FROM radar_config WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        if existing:
            db.execute("""
                UPDATE radar_config
                SET palavras_chave=%s, estados=%s,
                    monitorar_editais=%s, monitorar_noticias=%s,
                    gerar_conteudo=%s, atualizado_em=%s
                WHERE tenant_id=%s
            """, (
                f.get("palavras_chave", ""),
                f.get("estados", "ES"),
                1 if f.get("monitorar_editais") else 0,
                1 if f.get("monitorar_noticias") else 0,
                1 if f.get("gerar_conteudo") else 0,
                now_str, tenant_id
            ))
        else:
            db.execute("""
                INSERT INTO radar_config
                (tenant_id, palavras_chave, estados, monitorar_editais,
                 monitorar_noticias, gerar_conteudo, ativo)
                VALUES (%s,%s,%s,%s,%s,%s,1)
            """, (
                tenant_id,
                f.get("palavras_chave", ""),
                f.get("estados", "ES"),
                1 if f.get("monitorar_editais") else 0,
                1 if f.get("monitorar_noticias") else 0,
                1 if f.get("gerar_conteudo") else 0,
            ))
        db.commit()
        db.close()
        flash("Configurações salvas!", "success")
    except Exception as e:
        flash(f"Erro: {e}", "danger")
    return redirect(url_for("radar"))


# ── Motor de Expansão ────────────────────────────────────────────────────────

@app.route("/expansao")
@login_required
@require_perfil('gerente')
def expansao_index():
    oportunidades = exp_model.listar_oportunidades()
    potencial = sum(r["potencial_mensal"] for r in oportunidades)
    conn = database.get_connection()
    prods_db = [r["nome"] for r in conn.execute(
        "SELECT nome FROM produtos_krylo WHERE ativo=1 AND tenant_id=%s ORDER BY nome",
        (_tid(),)
    ).fetchall()]
    conn.close()
    produtos = prods_db if prods_db else exp_model.PRODUTOS
    return render_template(
        "expansao/index.html",
        oportunidades=oportunidades,
        potencial=potencial,
        produtos=produtos,
    )


@app.route("/expansao/pitch/<int:empresa_id>", methods=["POST"])
@login_required
@require_perfil('vendedor')
def expansao_pitch(empresa_id):
    import re as _re
    try:
        emp = emp_model.buscar_por_id(empresa_id)
        if not emp:
            return jsonify({"error": "Empresa não encontrada"}), 404
        emp = dict(emp)
        ativos = [p.strip() for p in (emp.get("produtos_ativos") or "").split(",") if p.strip()]
        _conn_prods = database.get_connection()
        _prods_db = [r["nome"] for r in _conn_prods.execute(
            "SELECT nome FROM produtos_krylo WHERE ativo=1 AND tenant_id=%s ORDER BY nome",
            (_tid(),)
        ).fetchall()]
        _conn_prods.close()
        _lista_prods = _prods_db if _prods_db else exp_model.PRODUTOS
        faltando = [p for p in _lista_prods if p not in ativos]
        if not faltando:
            return jsonify({"pitch": "Esta empresa já utiliza todos os produtos Krylo disponíveis!"})
        prompt = f"""Você é um especialista em vendas da Krylo Cartão de Benefícios B2B.
Crie um pitch de upsell personalizado e convincente (máx 3 parágrafos) para a empresa abaixo.
Retorne SOMENTE um JSON válido: {{"pitch": "<texto completo>"}}

Empresa: {emp['nome']}
Segmento: {emp.get('segmento') or 'não informado'} | Porte: {emp.get('porte') or 'não informado'}
Funcionários: {emp.get('num_funcionarios') or 'não informado'}
Produtos atuais: {', '.join(ativos) if ativos else 'nenhum'}
Produtos para oferecer: {', '.join(faltando)}
Valor mensal atual: R$ {emp.get('valor_mensal') or 0:,.0f}

Destaque o benefício principal de cada produto faltando, o impacto para os funcionários e a facilidade de adicionar ao pacote atual. Tom consultivo e direto."""

        import anthropic as _ant, models.ia_config as ia_mod
        _conn_exp = database.get_connection()
        _sys_exp  = ia_mod.get_system_prompt(_conn_exp, tenant_id=_tid())
        _conn_exp.close()
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=_sys_exp,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        result = json.loads(raw.strip())
        return jsonify({"ok": True, "pitch": result.get("pitch", "")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/expansao/salvar/<int:empresa_id>", methods=["POST"])
@login_required
@require_perfil('gerente')
def expansao_salvar(empresa_id):
    dados = request.json or {}
    produtos = dados.get("produtos_ativos", [])
    try:
        num_func = int(dados.get("num_funcionarios") or 0) or None
    except (ValueError, TypeError):
        num_func = None
    try:
        val_mensal = float(dados.get("valor_mensal") or 0) or None
    except (ValueError, TypeError):
        val_mensal = None
    exp_model.atualizar_dados_comerciais(empresa_id, {
        "produtos_ativos": ", ".join(produtos) if isinstance(produtos, list) else produtos,
        "num_funcionarios": num_func,
        "cliente_ativo": 1 if dados.get("cliente_ativo") else 0,
        "valor_mensal": val_mensal,
        "tipo_cartao": (dados.get("tipo_cartao") or "").strip() or None,
        "nome_private_label": (dados.get("nome_private_label") or "").strip() or None,
    })
    return jsonify({"ok": True})


# ── Módulo de Cobrança ────────────────────────────────────────────────────────

@app.route("/cobranca")
@login_required
@require_perfil('gerente')
def cobranca_index():
    clientes = cob_model.listar_clientes()
    resumo = cob_model.resumo()
    mes = request.args.get("mes", str(date.today())[:7])
    relatorios = cob_model.listar_relatorios(mes=mes)
    return render_template(
        "cobranca/index.html",
        clientes=clientes,
        resumo=resumo,
        relatorios=relatorios,
        mes=mes,
        status_list=cob_model.STATUS_CLIENTE,
    )


@app.route("/cobranca/clientes/novo", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def cobranca_cliente_novo():
    if request.method == "POST":
        try:
            pct = float(request.form.get("comissao_pct", "10").replace(",", ".") or 10)
        except ValueError:
            pct = 10
        cob_model.criar_cliente({
            "nome": request.form.get("nome", "").strip(),
            "cnpj": request.form.get("cnpj", "").strip() or None,
            "contato_nome": request.form.get("contato_nome", "").strip() or None,
            "contato_fone": request.form.get("contato_fone", "").strip() or None,
            "contato_email": request.form.get("contato_email", "").strip() or None,
            "comissao_pct": pct,
            "status": request.form.get("status", "ativo"),
        })
        flash("Cliente de cobrança cadastrado.", "success")
        return redirect(url_for("cobranca_index"))
    return render_template("cobranca/form_cliente.html",
                           cliente=None, action=url_for("cobranca_cliente_novo"),
                           status_list=cob_model.STATUS_CLIENTE)


@app.route("/cobranca/clientes/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def cobranca_cliente_editar(id):
    c = cob_model.buscar_cliente(id)
    if not c:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("cobranca_index"))
    if request.method == "POST":
        try:
            pct = float(request.form.get("comissao_pct", "10").replace(",", ".") or 10)
        except ValueError:
            pct = 10
        cob_model.atualizar_cliente(id, {
            "nome": request.form.get("nome", "").strip(),
            "cnpj": request.form.get("cnpj", "").strip() or None,
            "contato_nome": request.form.get("contato_nome", "").strip() or None,
            "contato_fone": request.form.get("contato_fone", "").strip() or None,
            "contato_email": request.form.get("contato_email", "").strip() or None,
            "comissao_pct": pct,
            "status": request.form.get("status", "ativo"),
        })
        flash("Cliente atualizado.", "success")
        return redirect(url_for("cobranca_index"))
    return render_template("cobranca/form_cliente.html",
                           cliente=c, action=url_for("cobranca_cliente_editar", id=id),
                           status_list=cob_model.STATUS_CLIENTE)


@app.route("/cobranca/relatorio/gerar", methods=["POST"])
@login_required
@require_perfil('gerente')
def cobranca_relatorio_gerar():
    try:
        cliente_id = int(request.form.get("cliente_id") or 0)
        mes = request.form.get("mes", str(date.today())[:7])
        total_cobrado = float(request.form.get("total_cobrado", "0").replace(",", ".") or 0)
        total_recuperado = float(request.form.get("total_recuperado", "0").replace(",", ".") or 0)
        obs = request.form.get("observacoes", "").strip()
        cob_model.gerar_relatorio(cliente_id, mes, total_cobrado, total_recuperado, obs)
        flash("Relatório gerado com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao gerar relatório: {e}", "danger")
    return redirect(url_for("cobranca_index", mes=request.form.get("mes", "")))


@app.route("/cobranca/relatorio/<int:id>/marcar-enviado", methods=["POST"])
@login_required
@require_perfil('gerente')
def cobranca_relatorio_enviado(id):
    cob_model.marcar_enviado(id)
    return jsonify({"ok": True})


@app.route("/cobranca/relatorio/<int:id>/registrar-retorno", methods=["POST"])
@login_required
@require_perfil('gerente')
def cobranca_relatorio_retorno(id):
    retorno = (request.json or {}).get("retorno", "").strip()
    if not retorno:
        return jsonify({"error": "Retorno não pode ser vazio"}), 400
    cob_model.registrar_retorno(id, retorno)
    return jsonify({"ok": True})


# ── Recebíveis da Krylo ───────────────────────────────────────────────────────

@app.route("/recebiveis")
@login_required
@require_perfil('gerente')
def recebiveis_index():
    mes = request.args.get("mes", str(date.today())[:7])
    recebiveis = rec_model.listar(mes=mes)
    resumo = rec_model.resumo_mes(mes)
    return render_template(
        "recebiveis/index.html",
        recebiveis=recebiveis,
        resumo=resumo,
        mes=mes,
    )


@app.route("/recebiveis/gerar-mensal", methods=["POST"])
@login_required
@require_perfil('gerente')
def recebiveis_gerar():
    mes = request.form.get("mes", str(date.today())[:7])
    count = rec_model.gerar_mensal(mes)
    flash(f"{count} recebível(eis) gerado(s) para {mes}.", "success")
    return redirect(url_for("recebiveis_index", mes=mes))


@app.route("/recebiveis/<int:id>/pagar", methods=["POST"])
@login_required
@require_perfil('gerente')
def recebiveis_pagar(id):
    rec_model.marcar_pago(id)
    return jsonify({"ok": True})


# ── Financeiro (Cobrança + Recebíveis fundidos) ──────────────────────────────

@app.route("/financeiro")
@login_required
@require_perfil('gerente')
def financeiro_index():
    aba = request.args.get("aba", "cobranca")
    mes = request.args.get("mes", str(date.today())[:7])
    cob_resumo = cob_model.resumo()
    rec_resumo = rec_model.resumo_mes(mes)
    conn = database.get_connection()
    clientes_cob = [dict(r) for r in conn.execute(
        "SELECT * FROM clientes_cobranca ORDER BY nome"
    ).fetchall()]
    recebiveis = [dict(r) for r in conn.execute("""
        SELECT r.*, e.nome AS empresa_nome
        FROM recebiveis_krylo r
        LEFT JOIN empresas e ON e.id = r.empresa_id
        ORDER BY r.vencimento DESC LIMIT 100
    """).fetchall()]
    conn.close()
    return render_template("financeiro.html",
        aba=aba, mes=mes,
        clientes_cob=clientes_cob, recebiveis=recebiveis,
        cob_resumo=cob_resumo, rec_resumo=rec_resumo,
    )


# ── Termômetro de Clientes ────────────────────────────────────────────────────

@app.route("/termometro")
@login_required
@require_perfil('gerente')
def termometro_index():
    conn = database.get_connection()
    hoje_str = date.today().isoformat()
    limite_30 = (date.today() - timedelta(days=30)).isoformat()
    rows = conn.execute("""
        SELECT e.id, e.nome, e.produtos_ativos, e.num_funcionarios,
               e.valor_mensal, e.telefone,
               (SELECT MAX(a2.data) FROM atividades a2 WHERE a2.empresa_id=e.id) AS ultimo_contato,
               (SELECT COUNT(*) FROM cadencias c WHERE c.empresa_id=e.id AND c.status='pendente') AS cadencias_ativas,
               (SELECT COUNT(*) FROM recebiveis_krylo rv WHERE rv.empresa_id=e.id
                AND rv.status='pendente' AND rv.vencimento < :hoje) AS rec_atrasados,
               (SELECT MAX(pa.ultimo_acesso) FROM portal_acessos pa
                WHERE pa.empresa_id=e.id AND pa.ativo=1) AS portal_acesso
        FROM empresas e
        WHERE e.cliente_ativo=1 OR e.status='cliente'
        GROUP BY e.id ORDER BY e.nome
    """, {"hoje": hoje_str}).fetchall()
    conn.close()
    clientes = []
    for r in rows:
        c = dict(r)
        s = 0
        if c.get("ultimo_contato") and c["ultimo_contato"] >= limite_30:
            s += 30
        prods = [p.strip() for p in (c.get("produtos_ativos") or "").split(",") if p.strip()]
        if len(prods) >= 2:
            s += 20
        if int(c.get("cadencias_ativas") or 0) > 0:
            s += 20
        if int(c.get("rec_atrasados") or 0) == 0:
            s += 20
        if c.get("portal_acesso") and c["portal_acesso"] >= limite_30:
            s += 10
        c["score"] = s
        c["prods_lista"] = prods
        c["status_cor"]   = "verde" if s >= 70 else ("amarelo" if s >= 40 else "vermelho")
        c["status_label"] = "Saudável" if s >= 70 else ("Atenção" if s >= 40 else "Crítico")
        clientes.append(c)
    clientes.sort(key=lambda x: x["score"])
    return render_template("termometro.html",
        clientes=clientes,
        criticos=sum(1 for c in clientes if c["status_cor"] == "vermelho"),
        atencao=sum(1 for c in clientes if c["status_cor"] == "amarelo"),
        saudaveis=sum(1 for c in clientes if c["status_cor"] == "verde"),
    )


@app.route("/ai/reativar/<int:empresa_id>", methods=["POST"])
@login_required
def ai_reativar(empresa_id):
    import re as _re
    try:
        conn = database.get_connection()
        emp = conn.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone()
        conn.close()
        if not emp:
            return jsonify({"error": "Empresa não encontrada"}), 404
        emp = dict(emp)
        prompt = f"""Crie uma mensagem curta de reengajamento para WhatsApp (máximo 4 linhas) para reativar contato com:
Empresa: {emp['nome']}
Segmento: {emp.get('segmento') or 'não informado'}

A mensagem deve ser natural, cordial, sem pressão de vendas.
Retorne SOMENTE JSON: {{"mensagem": "<texto>"}}"""
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        result = json.loads(raw.strip())
        return jsonify({"ok": True, "mensagem": result.get("mensagem", "")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Simulador de Proposta ─────────────────────────────────────────────────────

_TICKET_MEDIO = {
    "VA": 550, "VR": 600, "Combustível": 200,
    "Wellhub": 50, "Vidalink": 20, "Premiação": 100,
}

@app.route("/simulador")
@login_required
def simulador_index():
    conn = database.get_connection()
    prods_db = [r["nome"] for r in conn.execute(
        "SELECT nome FROM produtos_krylo WHERE ativo=1 AND tenant_id=%s ORDER BY nome",
        (_tid(),)
    ).fetchall()]
    conn.close()
    produtos = prods_db if prods_db else list(_TICKET_MEDIO.keys())
    return render_template("simulador.html",
        produtos=produtos, ticket_medio=_TICKET_MEDIO)


@app.route("/simulador/gerar", methods=["POST"])
@login_required
def simulador_gerar():
    import re as _re
    try:
        dados = request.json or {}
        empresa  = (dados.get("empresa") or "").strip()
        num_func = int(dados.get("num_funcionarios") or 0)
        produtos = dados.get("produtos") or []
        tipo     = dados.get("tipo", "privado")
        if not empresa or not num_func or not produtos:
            return jsonify({"error": "Preencha empresa, funcionários e pelo menos 1 produto."}), 400
        valores = {p: _TICKET_MEDIO.get(p, 100) * num_func for p in produtos}
        total   = sum(valores.values())
        prompt = f"""Você é consultor da Krylo Cartão de Benefícios B2B.
Gere uma proposta comercial executiva (3 parágrafos) para:
Empresa: {empresa} | Tipo: {tipo} | Funcionários: {num_func}
Produtos: {', '.join(produtos)} | Valor estimado: R$ {total:,.2f}/mês
Retorne SOMENTE JSON válido: {{"proposta": "<texto>"}}
Tom consultivo. Inclua benefícios dos produtos, impacto nos funcionários, chamada para reunião."""
        import anthropic as _ant, models.ia_config as ia_mod
        _c = database.get_connection()
        _sys = ia_mod.get_system_prompt(_c, tenant_id=_tid())
        _c.close()
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1000,
            system=_sys,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        result = json.loads(raw.strip())
        return jsonify({"ok": True, "proposta": result.get("proposta", ""),
                        "valores": valores, "total_mensal": total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Relatório Executivo Semanal ───────────────────────────────────────────────

@app.route("/relatorio/semanal")
@login_required
def relatorio_semanal():
    dados = rel_model.coletar_semanal()
    try:
        proximos_passos = ai.proximos_passos_semanal(dados)
    except Exception:
        proximos_passos = "Configure ANTHROPIC_API_KEY para gerar sugestões de IA."
    return render_template("relatorio_semanal.html", d=dados, proximos_passos=proximos_passos)


@app.route("/relatorio/semanal/json")
@login_required
def relatorio_semanal_json():
    return jsonify(rel_model.coletar_semanal())


# ── Usuários ─────────────────────────────────────────────────────────────────

@app.route("/usuarios")
@login_required
@require_perfil("admin")
def usuarios_lista():
    return render_template(
        "usuarios/lista.html",
        usuarios=user_model.listar(),
        perfil_labels=PERFIL_LABELS,
    )


@app.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
@require_perfil("admin")
def usuarios_novo():
    erro = None
    if request.method == "POST":
        dados, erro = _form_usuario(request.form)
        if not erro:
            try:
                user_model.criar(dados)
                flash("Usuário criado com sucesso.", "success")
                return redirect(url_for("usuarios_lista"))
            except Exception as e:
                erro = "Usuário ou e-mail já existe." if "UNIQUE" in str(e).upper() else str(e)
    return render_template("usuarios/form.html", usuario=None,
                           perfis=PERFIS, perfil_labels=PERFIL_LABELS,
                           action=url_for("usuarios_novo"), erro=erro)


@app.route("/usuarios/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil("admin")
def usuarios_editar(id):
    u = user_model.buscar_por_id(id)
    if not u:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("usuarios_lista"))
    erro = None
    if request.method == "POST":
        dados, erro = _form_usuario(request.form, editando=True)
        if not erro:
            try:
                user_model.atualizar(id, dados)
                flash("Usuário atualizado.", "success")
                return redirect(url_for("usuarios_lista"))
            except Exception as e:
                erro = "Usuário ou e-mail já existe." if "UNIQUE" in str(e).upper() else str(e)
    return render_template("usuarios/form.html", usuario=u,
                           perfis=PERFIS, perfil_labels=PERFIL_LABELS,
                           action=url_for("usuarios_editar", id=id), erro=erro)


@app.route("/usuarios/<int:id>/toggle", methods=["POST"])
@login_required
@require_perfil("admin")
def usuarios_toggle(id):
    if id == current_user.id:
        return jsonify({"error": "Não é possível desativar o próprio usuário."}), 400
    novo = user_model.toggle_ativo(id)
    return jsonify({"ok": True, "ativo": novo})


@app.route("/usuarios/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil("admin")
def usuarios_excluir(id):
    if id == current_user.id:
        flash("Não é possível excluir o próprio usuário.", "danger")
        return redirect(url_for("usuarios_lista"))
    user_model.excluir(id)
    flash("Usuário excluído.", "success")
    return redirect(url_for("usuarios_lista"))


def _form_usuario(f, editando=False):
    nome    = f.get("nome", "").strip()
    email   = f.get("email", "").strip() or None
    usuario = f.get("usuario", "").strip()
    senha   = f.get("senha", "")
    senha2  = f.get("senha2", "")
    perfil  = f.get("perfil", "vendedor")
    ativo   = 1 if f.get("ativo") else 0

    if not nome:
        return None, "Nome é obrigatório."
    if not usuario:
        return None, "Usuário (login) é obrigatório."
    if perfil not in PERFIS:
        return None, "Perfil inválido."
    if not editando and not senha:
        return None, "Senha é obrigatória."
    if senha and senha != senha2:
        return None, "As senhas não coincidem."

    return dict(nome=nome, email=email, usuario=usuario,
                senha=senha, perfil=perfil, ativo=ativo), None


# ── Produtos Krylo — CRUD dinâmico ───────────────────────────────────────────

@app.route("/produtos")
@login_required
def produtos_lista():
    conn = database.get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM produtos_krylo WHERE tenant_id=%s ORDER BY ativo DESC, nome ASC",
        (_tid(),)
    ).fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/produtos/<int:pid>")
@login_required
def produto_detalhe(pid):
    conn = database.get_connection()
    row = conn.execute(
        "SELECT * FROM produtos_krylo WHERE id=%s AND tenant_id=%s", (pid, _tid())
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Não encontrado"}), 404
    return jsonify(dict(row))


@app.route("/produtos/novo", methods=["POST"])
@login_required
@require_perfil("gerente")
def produto_novo():
    try:
        import datetime as _dt
        f = request.json or {}
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn = database.get_connection()
        cur = conn.execute(
            """INSERT INTO produtos_krylo
               (tenant_id, nome, descricao, pitch_whatsapp, pitch_email, cnaes_alvo,
                estados_alvo, capital_min, score_min, valor_por_funcionario,
                palavras_chave, publico_alvo, beneficios, objecoes_comuns,
                como_responder_objecoes, ativo, criado_em, atualizado_em)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                _tid(),
                (f.get("nome") or "").strip(),
                f.get("descricao") or "",
                f.get("pitch_whatsapp") or "",
                f.get("pitch_email") or "",
                f.get("cnaes_alvo") or "",
                f.get("estados_alvo") or "ES,SP",
                float(f.get("capital_min") or 50000),
                int(f.get("score_min") or 6),
                float(f.get("valor_por_funcionario") or 0),
                f.get("palavras_chave") or "",
                f.get("publico_alvo") or "",
                f.get("beneficios") or "",
                f.get("objecoes_comuns") or "",
                f.get("como_responder_objecoes") or "",
                1 if f.get("ativo", True) else 0,
                _agora, _agora,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/produtos/<int:pid>/editar", methods=["POST"])
@login_required
@require_perfil("gerente")
def produto_editar(pid):
    try:
        import datetime as _dt
        f = request.json or {}
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn = database.get_connection()
        conn.execute(
            """UPDATE produtos_krylo SET
               nome=:nome, descricao=:descricao,
               pitch_whatsapp=:pw, pitch_email=:pe,
               cnaes_alvo=:cnaes, estados_alvo=:estados,
               capital_min=:cap, score_min=:score,
               valor_por_funcionario=:vpf,
               palavras_chave=:pk, publico_alvo=:pub,
               beneficios=:ben, objecoes_comuns=:obj,
               como_responder_objecoes=:resp,
               ativo=:ativo, atualizado_em=:at
               WHERE id=:id AND tenant_id=:tid""",
            {
                "nome": (f.get("nome") or "").strip(),
                "descricao": f.get("descricao") or "",
                "pw": f.get("pitch_whatsapp") or "",
                "pe": f.get("pitch_email") or "",
                "cnaes": f.get("cnaes_alvo") or "",
                "estados": f.get("estados_alvo") or "ES,SP",
                "cap": float(f.get("capital_min") or 50000),
                "score": int(f.get("score_min") or 6),
                "vpf": float(f.get("valor_por_funcionario") or 0),
                "pk": f.get("palavras_chave") or "",
                "pub": f.get("publico_alvo") or "",
                "ben": f.get("beneficios") or "",
                "obj": f.get("objecoes_comuns") or "",
                "resp": f.get("como_responder_objecoes") or "",
                "ativo": 1 if f.get("ativo", True) else 0,
                "at": _agora,
                "id": pid,
                "tid": _tid(),
            },
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/produtos/<int:pid>/toggle", methods=["POST"])
@login_required
@require_perfil("gerente")
def produto_toggle(pid):
    try:
        import datetime as _dt
        conn = database.get_connection()
        row = conn.execute(
            "SELECT ativo FROM produtos_krylo WHERE id=%s AND tenant_id=%s", (pid, _tid())
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Não encontrado"}), 404
        novo = 0 if row["ativo"] else 1
        conn.execute(
            "UPDATE produtos_krylo SET ativo=:v, atualizado_em=:t WHERE id=:id AND tenant_id=:tid",
            {"v": novo, "t": _dt.datetime.now().isoformat(sep=" ", timespec="seconds"), "id": pid, "tid": _tid()},
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "ativo": bool(novo)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/produtos/<int:pid>/deletar", methods=["POST"])
@login_required
@require_perfil("admin")
def produto_deletar(pid):
    try:
        conn = database.get_connection()
        conn.execute(
            "DELETE FROM produtos_krylo WHERE id=%s AND tenant_id=%s", (pid, _tid())
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/produtos/gerar-com-ia", methods=["POST"])
@login_required
@require_perfil("gerente")
def produto_gerar_com_ia():
    try:
        import re as _re
        import models.ia_config as ia_mod
        f = request.json or {}
        nome = (f.get("nome") or "").strip()
        descricao = (f.get("descricao") or "").strip()
        if not nome:
            return jsonify({"error": "Nome é obrigatório"}), 400
        conn = database.get_connection()
        system = ia_mod.get_system_prompt(conn, tenant_id=_tid())
        conn.close()
        prompt = (
            f"Você é especialista em vendas B2B de benefícios corporativos.\n"
            f"Com base no produto abaixo, gere conteúdo de vendas em JSON.\n\n"
            f"Produto: {nome}\nDescrição: {descricao or 'não informada'}\n\n"
            "Retorne APENAS este JSON válido (sem markdown, sem explicação):\n"
            '{\n'
            '  "pitch_whatsapp": "mensagem WhatsApp 2 frases informal, use {empresa} como variável",\n'
            '  "pitch_email_assunto": "assunto do email impactante",\n'
            '  "pitch_email_corpo": "corpo do email 4-5 linhas com {empresa} e {nome_contato}",\n'
            '  "publico_alvo": "descrição detalhada de quem se beneficia",\n'
            '  "beneficios": "benefício 1\\nbenfício 2\\nbenfício 3\\nbenfício 4\\nbenfício 5",\n'
            '  "objecoes": "objeção 1|como responder 1\\nobjeção 2|como responder 2\\nobjeção 3|como responder 3",\n'
            '  "palavras_chave": "palavra1,palavra2,palavra3,palavra4",\n'
            '  "cnaes_sugeridos": "1234567,8901234",\n'
            '  "valor_por_funcionario_sugerido": 0\n'
            "}"
        )
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        data = json.loads(raw.strip())
        return jsonify({"ok": True, "dados": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── IA — Painel de Configuração ──────────────────────────────────────────────

@app.route("/ia/config")
@login_required
@require_perfil("gerente")
def ia_config_painel():
    import models.ia_config as ia_mod
    conn = database.get_connection()
    cfg  = ia_mod.get_ia_config(conn, _tid())
    conn.close()
    return render_template("ia_painel.html", cfg=cfg)


@app.route("/ia/config/salvar", methods=["POST"])
@login_required
@require_perfil("gerente")
def ia_config_salvar():
    try:
        f = request.json or {}
        campos = [
            "nome_assistente", "personalidade", "tom", "estrategia",
            "estilo_escrita", "contexto_empresa", "objetivo_principal",
            "restricoes", "saudacao_whatsapp", "saudacao_email", "assinatura_email",
        ]
        conn = database.get_connection()
        import datetime as _dt
        tid = _tid()
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        # Ensure row exists for this tenant
        conn.execute(
            "INSERT OR IGNORE INTO ia_config (tenant_id) VALUES (%s)", (tid,)
        )
        for campo in campos:
            if campo in f:
                conn.execute(
                    f"UPDATE ia_config SET {campo}=:v, atualizado_em=:t WHERE tenant_id=:tid",
                    {"v": f[campo], "t": _agora, "tid": tid},
                )
        conn.commit()
        conn.close()
        return jsonify({"status": "salvo"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ia/chat", methods=["POST"])
@login_required
def ia_chat():
    try:
        import models.ia_config as ia_mod
        body     = request.json or {}
        mensagem = (body.get("mensagem") or "").strip()
        historico = body.get("historico") or []
        contexto  = (body.get("contexto") or "").strip()
        if not mensagem:
            return jsonify({"error": "Mensagem vazia"}), 400
        conn = database.get_connection()
        resposta = ia_mod.chat_com_ia(conn, mensagem, historico, contexto, _tid())
        conn.close()
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ia/testar-pitch", methods=["POST"])
@login_required
def ia_testar_pitch():
    import re as _re
    try:
        import models.ia_config as ia_mod
        import anthropic as _ant
        body    = request.json or {}
        empresa = (body.get("empresa") or "").strip()
        produto = (body.get("produto") or "").strip()
        canal   = (body.get("canal") or "whatsapp").strip()
        if not empresa:
            return jsonify({"error": "Empresa é obrigatória"}), 400

        conn   = database.get_connection()
        system = ia_mod.get_system_prompt(conn, tenant_id=_tid())
        cfg    = ia_mod.get_ia_config(conn, _tid())
        conn.close()

        if canal == "email":
            prompt = (
                f"Crie um e-mail de prospecção para {empresa} sobre {produto or 'benefícios Krylo'}.\n"
                f"Saudação padrão: {cfg.get('saudacao_email','Prezado(a),')}\n"
                f"Assinatura: {cfg.get('assinatura_email','Krylo')}\n"
                "Retorne SOMENTE JSON válido: {\"assunto\": \"...\", \"corpo\": \"...\"}"
            )
        else:
            prompt = (
                f"Crie uma mensagem de WhatsApp de prospecção para {empresa} sobre {produto or 'benefícios Krylo'}.\n"
                f"Saudação padrão: {cfg.get('saudacao_whatsapp','Olá!')}\n"
                "Retorne SOMENTE JSON válido: {\"mensagem\": \"...\"}"
            )

        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp   = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$",          "", raw, flags=_re.MULTILINE)
        return jsonify({"ok": True, "canal": canal, **json.loads(raw.strip())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Central de IA ────────────────────────────────────────────────────────────

_IA_SYSTEM_PROMPT = (
    "Você é a IA consultora da Krylo, empresa de cartão de benefícios B2B. "
    "Conhece profundamente todos os produtos: alimentação, refeição, combustível, "
    "premiação, private label, Welhub (wellness), Vidalink (farmácia), "
    "Viva+ (cultura e lazer), DM Card (carteira administrada). "
    "Ajuda o time comercial a criar argumentos de venda, responder objeções, "
    "sugerir produtos por perfil de empresa, criar textos de prospecção e tirar "
    "dúvidas sobre preços e funcionalidades. "
    "Sempre responde em português, tom consultivo e direto."
)


def _central_ia_context() -> str:
    """Return text from all knowledge-base documents, trimmed to ~8000 chars."""
    conn = database.get_connection()
    tid  = int(session.get("tenant_id") or 1)
    cur  = conn.execute("SELECT nome, tipo, conteudo_texto FROM documentos_ia WHERE tenant_id=? AND conteudo_texto IS NOT NULL AND conteudo_texto != ''", (tid,))
    docs = cur.fetchall()
    conn.close()
    if not docs:
        return ""
    parts = []
    for d in docs:
        trecho = (d["conteudo_texto"] or "")[:2000]
        parts.append(f"[{d['nome']} — {d['tipo']}]\n{trecho}")
    return "\n\n---\n\n".join(parts)[:8000]


def _extrair_texto(raw: bytes, nome: str, mimetype: str) -> str:
    ext = nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if ext == "pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:
            return f"[Erro ao extrair PDF: {e}]"
    if ext in ("docx",):
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            return f"[Erro ao extrair Word: {e}]"
    if ext == "xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                lines.append("\t".join(str(c) if c is not None else "" for c in row))
            wb.close()
            return "\n".join(lines)
        except Exception as e:
            return f"[Erro ao extrair Excel: {e}]"
    if ext == "csv":
        return _decodificar_bytes(raw)[:10000]
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        return f"[Imagem: {nome}]"
    if ext in ("mp4", "mov", "avi", "webm"):
        return f"[Vídeo: {nome}]"
    return _decodificar_bytes(raw)[:10000]


@app.route("/central-ia")
@login_required
def central_ia():
    conn  = database.get_connection()
    cur   = conn.execute("SELECT id, nome, tipo, data_upload, tamanho FROM documentos_ia WHERE tenant_id=? ORDER BY data_upload DESC", (_tid(),))
    docs  = cur.fetchall()
    conn.close()
    return render_template("central_ia.html", documentos=docs, total_docs=len(docs))


@app.route("/central-ia/chat", methods=["POST"])
@login_required
@require_perfil('vendedor')
def central_ia_chat():
    try:
        body     = request.json or {}
        mensagem = (body.get("mensagem") or "").strip()
        historico = body.get("historico") or []
        if not mensagem:
            return jsonify({"error": "Mensagem vazia"}), 400

        import models.ia_config as ia_mod
        contexto_docs = _central_ia_context()
        conn_ia = database.get_connection()
        system  = ia_mod.get_system_prompt(conn_ia, contexto_docs)
        conn_ia.close()

        messages = []
        for h in historico[-20:]:
            role = h.get("role")
            text = h.get("content", "")
            if role in ("user", "assistant") and text:
                messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": mensagem})

        import anthropic as _ant
        client   = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        resposta = response.content[0].text
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/central-ia/upload", methods=["POST"])
@login_required
@require_perfil('vendedor')
def central_ia_upload():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    raw      = arquivo.stream.read()
    tamanho  = len(raw)
    ext      = arquivo.filename.lower().rsplit(".", 1)[-1] if "." in arquivo.filename else "bin"
    conteudo = _extrair_texto(raw, arquivo.filename, arquivo.content_type or "")
    conn = database.get_connection()
    cur  = conn.execute(
        "INSERT INTO documentos_ia (tenant_id, nome, tipo, conteudo_texto, tamanho) VALUES (?, ?, ?, ?, ?)",
        (_tid(), arquivo.filename, ext.upper(), conteudo, tamanho),
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": doc_id, "nome": arquivo.filename, "tipo": ext.upper(), "tamanho": tamanho})


@app.route("/central-ia/documentos")
@login_required
def central_ia_documentos():
    conn = database.get_connection()
    cur  = conn.execute("SELECT id, nome, tipo, data_upload, tamanho FROM documentos_ia WHERE tenant_id=? ORDER BY data_upload DESC", (_tid(),))
    docs = [dict(d) for d in cur.fetchall()]
    conn.close()
    return jsonify(docs)


@app.route("/central-ia/documentos/<int:id>", methods=["DELETE"])
@login_required
@require_perfil('vendedor')
def central_ia_doc_excluir(id):
    conn = database.get_connection()
    conn.execute("DELETE FROM documentos_ia WHERE id = ? AND tenant_id = ?", (id, _tid()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Configurações — Ramos de Atividade ───────────────────────────────────────

@app.route("/configuracoes/ramos")
@login_required
@require_perfil("gerente")
def configuracoes_ramos():
    conn = database.get_connection()
    ramos = [dict(r) for r in conn.execute(
        "SELECT * FROM ramos_atividade WHERE tenant_id=? ORDER BY ativo DESC, nome ASC", (_tid(),)
    ).fetchall()]
    conn.close()
    return render_template("configuracoes_ramos.html", ramos=ramos)


@app.route("/configuracoes/ramos/novo", methods=["POST"])
@login_required
@require_perfil("gerente")
def configuracoes_ramos_novo():
    try:
        f = request.form
        nome        = f.get("nome", "").strip()
        if not nome:
            return jsonify({"error": "Nome é obrigatório"}), 400
        estados_lst = f.getlist("estados")
        conn = database.get_connection()
        conn.execute(
            """INSERT INTO ramos_atividade
                   (tenant_id, nome, descricao, cnaes, pitch, score_min, estados, capital_min, ativo)
               VALUES (:tid, :nome, :descricao, :cnaes, :pitch, :score_min, :estados, :capital_min, 1)""",
            {
                "tid":         _tid(),
                "nome":        nome,
                "descricao":   f.get("descricao", ""),
                "cnaes":       f.get("cnaes", ""),
                "pitch":       f.get("pitch", ""),
                "score_min":   int(f.get("score_min", 6)),
                "estados":     ",".join(estados_lst) if estados_lst else f.get("estados", "ES,SP"),
                "capital_min": int(f.get("capital_min", 100000) or 100000),
            },
        )
        conn.commit()
        conn.close()
        return redirect(url_for("configuracoes_ramos"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/configuracoes/ramos/<int:id>/toggle", methods=["POST"])
@login_required
@require_perfil("gerente")
def configuracoes_ramos_toggle(id):
    conn = database.get_connection()
    row = conn.execute("SELECT ativo FROM ramos_atividade WHERE id=? AND tenant_id=?", (id, _tid())).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Não encontrado"}), 404
    novo = 0 if row["ativo"] else 1
    conn.execute("UPDATE ramos_atividade SET ativo=? WHERE id=? AND tenant_id=?", (novo, id, _tid()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "ativo": novo})


# ── Configurações — Empresa Proprietária ─────────────────────────────────────

@app.route("/configuracoes/empresa")
@login_required
@require_perfil("gerente")
def configuracoes_empresa():
    conn = database.get_connection()
    row  = conn.execute(
        "SELECT * FROM empresa_config WHERE tenant_id=%s LIMIT 1", (_tid(),)
    ).fetchone()
    conn.close()
    return render_template("configuracoes_empresa.html", cfg=dict(row) if row else {})


@app.route("/configuracoes/empresa/salvar", methods=["POST"])
@login_required
@require_perfil("gerente")
def configuracoes_empresa_salvar():
    try:
        import datetime as _dt
        f = request.json or {}
        campos = [
            "nome", "nome_fantasia", "cnpj", "telefone", "whatsapp", "email",
            "site", "instagram", "linkedin", "tiktok", "ramo_atividade",
            "descricao", "missao", "diferenciais", "publico_alvo",
            "produtos_servicos", "regiao_atuacao", "historico",
            "tom_da_marca", "palavras_chave", "concorrentes",
        ]
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn = database.get_connection()
        tid = _tid()
        # Ensure row exists for this tenant
        conn.execute(
            "INSERT OR IGNORE INTO empresa_config (tenant_id) VALUES (%s)", (tid,)
        )
        for campo in campos:
            if campo in f:
                conn.execute(
                    f"UPDATE empresa_config SET {campo}=:v, atualizado_em=:t WHERE tenant_id=:tid",
                    {"v": f[campo], "t": _agora, "tid": tid},
                )
        conn.commit()
        conn.close()
        return jsonify({"status": "salvo"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── SDR Autônomo — Painel e Config ───────────────────────────────────────────

@app.route("/sdr/painel")
@login_required
@require_perfil("gerente")
def sdr_painel():
    return redirect(url_for("sdr_evolutivo.sdr_evolutivo_dashboard"))


@app.route("/sdr/config/salvar", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_config_salvar():
    try:
        import datetime as _dt
        f = request.json or {}
        campos = [
            "estados", "cidades", "cnaes", "capital_social_min", "tipo_empresa",
            "tem_telefone", "tem_email", "score_minimo", "max_leads_por_execucao",
            "canal_primario", "canal_secundario", "horario_inicio", "horario_fim",
            "dias_semana", "intervalo_horas", "max_tentativas_por_empresa",
            "dias_recontato", "excluir_ja_prospectados", "ramos_selecionados", "ativo",
            "funcionarios_min", "funcionarios_max", "idade_empresa_min",
            "idade_empresa_max", "max_cadencias_por_dia", "nome_campanha",
            "modo_busca", "estados_selecionados", "cidades_selecionadas",
            "sem_restricao_horario", "fonte_leads",
        ]
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn = database.get_connection()
        for campo in campos:
            if campo in f:
                conn.execute(
                    f"UPDATE sdr_config SET {campo}=:v, atualizado_em=:t WHERE tenant_id=:tid",
                    {"v": f[campo], "t": _agora, "tid": _tid()},
                )
        conn.commit()
        conn.close()
        return jsonify({"status": "salvo"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sdr/config/toggle", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_config_toggle():
    try:
        import datetime as _dt
        conn = database.get_connection()
        row = conn.execute("SELECT ativo FROM sdr_config WHERE tenant_id=? LIMIT 1", (_tid(),)).fetchone()
        atual = bool(row["ativo"]) if row else True
        novo = 0 if atual else 1
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "UPDATE sdr_config SET ativo=:v, atualizado_em=:t WHERE tenant_id=:tid",
            {"v": novo, "t": _agora, "tid": _tid()},
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "ativo": bool(novo)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sdr/execucoes")
@login_required
def sdr_execucoes_json():
    conn = database.get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM sdr_execucoes WHERE tenant_id=? ORDER BY executado_em DESC LIMIT 10", (_tid(),)
    ).fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/sdr/stats")
@login_required
def sdr_stats():
    try:
        conn = database.get_connection()
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status='novo'       THEN 1 ELSE 0 END), 0) AS novos,
                COALESCE(SUM(CASE WHEN status='importado'  THEN 1 ELSE 0 END), 0) AS importados,
                COALESCE(SUM(CASE WHEN status='descartado' THEN 1 ELSE 0 END), 0) AS descartados
            FROM prospeccao_automatica
        """).fetchone()
        conn.close()
        return jsonify(dict(row) if row else {"total": 0, "novos": 0, "importados": 0, "descartados": 0})
    except Exception as e:
        return jsonify({"total": 0, "novos": 0, "importados": 0, "descartados": 0, "error": str(e)})


@app.route("/api/empresa/<int:empresa_id>/contato")
@login_required
def api_empresa_contato(empresa_id):
    try:
        tid  = _tid()
        conn = database.get_connection()
        row = conn.execute(
            "SELECT telefone, email FROM empresas WHERE id=? AND tenant_id=?",
            (empresa_id, tid)
        ).fetchone()
        telefone = (row["telefone"] or "") if row else ""
        email    = (row["email"]    or "") if row else ""
        if not telefone or not email:
            contato = conn.execute(
                "SELECT telefone, email FROM contatos WHERE empresa_id=? AND tenant_id=? ORDER BY id LIMIT 1",
                (empresa_id, tid)
            ).fetchone()
            if contato:
                telefone = telefone or (contato["telefone"] or "")
                email    = email    or (contato["email"]    or "")
        conn.close()
        return jsonify({"telefone": telefone, "email": email})
    except Exception as e:
        return jsonify({"telefone": "", "email": "", "error": str(e)})


@app.route("/api/cnaes")
@login_required
def api_cnaes():
    try:
        todos = cnaes_model.carregar_todos_cnaes()
        return jsonify(todos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cnaes/busca")
@login_required
def api_cnaes_busca():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        resultado = cnaes_model.buscar_cnaes(q)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sdr/pipeline")
@login_required
def sdr_pipeline():
    try:
        conn = database.get_connection()
        stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='novo'       THEN 1 ELSE 0 END) AS novos,
                SUM(CASE WHEN status='importado'  THEN 1 ELSE 0 END) AS importados,
                SUM(CASE WHEN status='descartado' THEN 1 ELSE 0 END) AS descartados,
                AVG(score_fit) AS score_medio
            FROM prospeccao_automatica
        """).fetchone()
        melhor_uf = conn.execute("""
            SELECT uf, COUNT(*) AS cnt FROM prospeccao_automatica
            WHERE status='importado' GROUP BY uf ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        melhor_prod = conn.execute("""
            SELECT produto_alvo, COUNT(*) AS cnt FROM prospeccao_automatica
            WHERE produto_alvo IS NOT NULL AND produto_alvo != ''
            GROUP BY produto_alvo ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        all_times = conn.execute(
            "SELECT importado_em FROM prospeccao_automatica WHERE importado_em IS NOT NULL LIMIT 500"
        ).fetchall()
        conn.close()

        from collections import Counter
        horas = []
        for r in (all_times or []):
            try:
                ts = str(r["importado_em"])
                h = int(ts[11:13]) if len(ts) > 12 else int(ts.split("T")[-1][:2])
                horas.append(h)
            except Exception:
                pass
        melhor_hora = f"{Counter(horas).most_common(1)[0][0]}h" if horas else "—"

        s = dict(stats) if stats else {}
        total    = int(s.get("total") or 0)
        importados = int(s.get("importados") or 0)
        taxa     = round(importados / total * 100, 1) if total > 0 else 0.0

        return jsonify({
            "total":          total,
            "novos":          int(s.get("novos") or 0),
            "importados":     importados,
            "descartados":    int(s.get("descartados") or 0),
            "score_medio":    round(float(s.get("score_medio") or 0), 1),
            "taxa_conversao": taxa,
            "melhor_uf":      melhor_uf["uf"]          if melhor_uf   else "—",
            "melhor_produto": melhor_prod["produto_alvo"] if melhor_prod else "—",
            "melhor_hora":    melhor_hora,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sdr/otimizar", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_otimizar():
    try:
        import models.ia_config as ia_mod
        conn = database.get_connection()
        execucoes = [dict(r) for r in conn.execute(
            "SELECT encontrados, salvos, cadencias, descartados, executado_em "
            "FROM sdr_execucoes ORDER BY executado_em DESC LIMIT 5"
        ).fetchall()]
        config_row = conn.execute("SELECT * FROM sdr_config WHERE tenant_id=? LIMIT 1", (_tid(),)).fetchone()
        cfg = dict(config_row) if config_row else {}
        stats = [dict(r) for r in conn.execute("""
            SELECT uf, cnae_descricao, COUNT(*) AS total,
                   AVG(score_fit) AS avg_score
            FROM prospeccao_automatica
            GROUP BY uf, cnae_descricao
            ORDER BY total DESC LIMIT 10
        """).fetchall()]
        contexto = (
            f"Histórico de execuções (últimas 5): {execucoes}\n"
            f"Config atual: estados={cfg.get('estados')}, score_min={cfg.get('score_minimo')}, "
            f"max_leads={cfg.get('max_leads_por_execucao')}, "
            f"horário={cfg.get('horario_inicio')}h-{cfg.get('horario_fim')}h\n"
            f"Performance por UF/CNAE: {stats}"
        )
        resposta = ia_mod.chat_com_ia(
            conn,
            "Analise o histórico do SDR autônomo e sugira 3 ajustes específicos nos "
            "filtros para melhorar a taxa de conversão. Seja direto e prático.",
            contexto=contexto,
        )
        conn.close()
        return jsonify({"sugestao": resposta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── SDR — Log ao vivo, pausar, relatório, sessões ────────────────────────────

@app.route("/sdr/log-ao-vivo")
@login_required
def sdr_log_ao_vivo():
    try:
        conn = database.get_connection()
        sessao = conn.execute(
            "SELECT * FROM sdr_sessoes WHERE tenant_id=? ORDER BY iniciado_em DESC LIMIT 1", (_tid(),)
        ).fetchone()
        if not sessao:
            conn.close()
            return jsonify({"ativo": False, "eventos": [], "stats": {
                "encontrados": 0, "aprovados": 0, "importados": 0,
                "cadencias": 0, "descartados": 0, "filtrados": 0,
            }})
        sessao = dict(sessao)
        eventos = [dict(e) for e in conn.execute("""
            SELECT * FROM sdr_log_ao_vivo WHERE sessao_id=?
            ORDER BY criado_em DESC LIMIT 80
        """, (sessao["sessao_id"],)).fetchall()]
        conn.close()
        for e in eventos:
            for k, v in e.items():
                if hasattr(v, 'isoformat'):
                    e[k] = v.isoformat()
        for k, v in sessao.items():
            if hasattr(v, 'isoformat'):
                sessao[k] = v.isoformat()
        return jsonify({
            "ativo":        sessao["status"] == "rodando",
            "status":       sessao["status"],
            "sessao_id":    sessao["sessao_id"],
            "stats": {
                "encontrados": sessao.get("encontrados", 0),
                "aprovados":   sessao.get("aprovados", 0),
                "importados":  sessao.get("importados", 0),
                "cadencias":   sessao.get("cadencias", 0),
                "descartados": sessao.get("descartados", 0),
                "filtrados":   sessao.get("filtrados", 0),
            },
            "produto_atual": sessao.get("produto_atual") or "",
            "estado_atual":  sessao.get("estado_atual") or "",
            "empresa_atual": sessao.get("empresa_atual") or "",
            "ultima_acao":   sessao.get("ultima_acao") or "",
            "iniciado_em":   str(sessao.get("iniciado_em") or ""),
            "finalizado_em": str(sessao.get("finalizado_em")) if sessao.get("finalizado_em") else None,
            "eventos":       eventos,
        })
    except Exception as e:
        return jsonify({"ativo": False, "eventos": [], "error": str(e), "stats": {}}), 500


@app.route("/sdr/pausar", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_pausar():
    try:
        conn = database.get_connection()
        sessao = conn.execute(
            "SELECT sessao_id FROM sdr_sessoes WHERE tenant_id=? AND status='rodando' ORDER BY iniciado_em DESC LIMIT 1", (_tid(),)
        ).fetchone()
        if sessao:
            conn.execute(
                "UPDATE sdr_sessoes SET status='pausado', finalizado_em=datetime('now', 'localtime') WHERE sessao_id=?",
                (sessao["sessao_id"],)
            )
            conn.commit()
        conn.close()
        return jsonify({"status": "pausado"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sdr/relatorio/<sessao_id>")
@login_required
def sdr_relatorio(sessao_id):
    try:
        conn = database.get_connection()
        sessao = conn.execute(
            "SELECT * FROM sdr_sessoes WHERE sessao_id=?", (sessao_id,)
        ).fetchone()
        if not sessao:
            conn.close()
            flash("Sessão não encontrada.", "danger")
            return redirect(url_for("sdr_painel"))
        sessao = dict(sessao)
        eventos = [dict(e) for e in conn.execute("""
            SELECT * FROM sdr_log_ao_vivo WHERE sessao_id=?
            ORDER BY criado_em ASC
        """, (sessao_id,)).fetchall()]
        leads = [dict(r) for r in conn.execute("""
            SELECT * FROM prospeccao_automatica
            WHERE importado_em >= ?
            ORDER BY score_fit DESC LIMIT 100
        """, (str(sessao.get("iniciado_em") or ""),)).fetchall()]
        conn.close()
        for e in eventos:
            for k, v in e.items():
                if hasattr(v, 'isoformat'):
                    e[k] = v.isoformat()
        return render_template("sdr_relatorio.html",
                               sessao=sessao, eventos=eventos, leads=leads)
    except Exception as e:
        flash(f"Erro ao carregar relatório: {e}", "danger")
        return redirect(url_for("sdr_painel"))


@app.route("/sdr/sessoes")
@login_required
def sdr_sessoes_lista():
    try:
        conn = database.get_connection()
        sessoes = [dict(r) for r in conn.execute(
            "SELECT * FROM sdr_sessoes WHERE tenant_id=? ORDER BY iniciado_em DESC LIMIT 20", (_tid(),)
        ).fetchall()]
        conn.close()
        for s in sessoes:
            for k, v in s.items():
                if hasattr(v, 'isoformat'):
                    s[k] = v.isoformat()
        return jsonify(sessoes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── SDR — Fila de aprovação WhatsApp ─────────────────────────────────────────

@app.route("/sdr/fila-aprovacao")
@login_required
@require_perfil("gerente")
def sdr_fila_aprovacao():
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        itens = [dict(r) for r in conn.execute(
            """SELECT * FROM cadencias
               WHERE tenant_id = ?
                 AND canal_whatsapp = 1
                 AND (whatsapp_status IS NULL OR whatsapp_status = 'pendente'
                      OR whatsapp_status = 'aguardando_aprovacao')
                 AND mensagem_whatsapp IS NOT NULL AND mensagem_whatsapp != ''
               ORDER BY data_acao ASC LIMIT 100""",
            (tid,)
        ).fetchall()]
        conn.close()
        for item in itens:
            fone = (item.get("contato_whatsapp") or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            fone = re.sub(r'\D', '', fone)
            from urllib.parse import quote as _q
            item["wa_url"] = f"whatsapp://send?phone=55{fone}&text={_q(item.get('mensagem_whatsapp') or '')}" if fone else ""
        return render_template("sdr_fila_aprovacao.html", itens=itens)
    except Exception as e:
        flash(f"Erro ao carregar fila: {e}", "danger")
        return redirect(url_for("sdr_painel"))


@app.route("/sdr/aprovar/<int:cad_id>", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_aprovar_whatsapp(cad_id):
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        row = conn.execute(
            "SELECT contato_whatsapp, mensagem_whatsapp FROM cadencias WHERE id = ? AND tenant_id = ?",
            (cad_id, tid)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "erro": "Cadência não encontrada"}), 404
        import datetime as _dt_fix
        conn.execute(
            "UPDATE cadencias SET whatsapp_status = 'aprovado', whatsapp_aprovado_em = ? WHERE id = ? AND tenant_id = ?",
            (_dt_fix.datetime.utcnow().isoformat(), cad_id, tid)
        )
        conn.commit()
        fone = re.sub(r'\D', '', str(row["contato_whatsapp"] or ""))
        from urllib.parse import quote as _q
        wa_url = f"whatsapp://send?phone=55{fone}&text={_q(row['mensagem_whatsapp'] or '')}" if fone else ""
        conn.close()
        return jsonify({"ok": True, "wa_url": wa_url})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/sdr/rejeitar/<int:cad_id>", methods=["POST"])
@login_required
@require_perfil("gerente")
def sdr_rejeitar_whatsapp(cad_id):
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        conn.execute(
            "UPDATE cadencias SET whatsapp_status = 'rejeitado' WHERE id = ? AND tenant_id = ?",
            (cad_id, tid)
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/sdr/fila-whatsapp")
@login_required
@require_perfil("gerente")
def sdr_fila_whatsapp():
    try:
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        fila = [dict(r) for r in conn.execute(
            """SELECT c.*, e.nome AS empresa_nome_crm, e.telefone AS telefone_crm,
                      e.score AS score_emp, e.temperatura AS temperatura_emp,
                      e.cidade AS cidade_emp, e.estado AS estado_emp
               FROM cadencias c
               LEFT JOIN empresas e ON e.id = c.empresa_id
               WHERE c.whatsapp_status = 'aguardando_aprovacao'
                 AND c.tenant_id = ?
               ORDER BY COALESCE(e.score, 0) DESC
               LIMIT 100""",
            (tid,)
        ).fetchall()]
        conn.close()
        for item in fila:
            fone = re.sub(r'\D', '', str(item.get("contato_whatsapp") or item.get("telefone_crm") or ""))
            from urllib.parse import quote as _q
            item["wa_url"] = f"https://wa.me/55{fone}?text={_q(item.get('mensagem_whatsapp') or '')}" if fone else ""
        return render_template("fila_whatsapp.html", fila=fila)
    except Exception as e:
        flash(f"Erro ao carregar fila WhatsApp: {e}", "danger")
        return redirect(url_for("sdr_painel"))


# ── Super Admin — Gestão de Tenants ──────────────────────────────────────────

@app.route("/admin")
@login_required
@require_perfil("admin")
def admin_tenants():
    try:
        tenants = tenant_model.listar_tenants()
        total_ativos = sum(1 for t in tenants if t.get("ativo"))
        return render_template("admin_tenants.html",
                               tenants=tenants, total_ativos=total_ativos)
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"Erro admin: {e}", 500


@app.route("/admin/tenant/novo", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_tenant_novo():
    try:
        dados = {
            "nome_empresa":    request.form.get("nome_empresa", "").strip(),
            "nome_plataforma": request.form.get("nome_plataforma", "CRM").strip(),
            "plano":           request.form.get("plano", "starter"),
            "admin_nome":      request.form.get("admin_nome", "Admin").strip(),
            "admin_email":     request.form.get("admin_email", "").strip(),
            "admin_usuario":   request.form.get("admin_usuario", "").strip(),
            "senha_admin":     request.form.get("senha_admin", "krylo2024"),
            "cor_primaria":    request.form.get("cor_primaria", "#4A90D9"),
        }
        if not dados["nome_empresa"]:
            flash("Nome da empresa é obrigatório.", "danger")
            return redirect(url_for("admin_tenants"))
        tenant_id = tenant_model.criar_tenant(dados)
        flash(f"Tenant #{tenant_id} criado. Usuário: {dados['admin_usuario']} / Senha: {dados['senha_admin']}", "success")
        if dados.get("admin_email"):
            try:
                import models.brevo as _brevo_mod
                _plat = dados.get("nome_plataforma", "Krylo")
                _brevo_mod.enviar_email(
                    para_email=dados["admin_email"],
                    para_nome=dados.get("admin_nome", "Admin"),
                    assunto=f"Bem-vindo ao {_plat} CRM — suas credenciais",
                    corpo=(
                        f"<h2>Bem-vindo ao {_plat}!</h2>"
                        f"<p>Olá {dados.get('admin_nome', 'Admin')}, sua conta foi criada com sucesso.</p>"
                        f"<p><strong>Usuário:</strong> {dados['admin_usuario']}<br>"
                        f"<strong>Senha:</strong> {dados['senha_admin']}</p>"
                        f"<p>Acesse o sistema e complete o wizard de configuração inicial.</p>"
                        f"<p>Atenciosamente,<br>Equipe {_plat}</p>"
                    ),
                )
            except Exception as _e_mail:
                print(f"[ONBOARDING] Email boas-vindas falhou: {_e_mail}")
    except Exception as e:
        flash(f"Erro ao criar tenant: {e}", "danger")
    return redirect(url_for("admin_tenants"))


@app.route("/admin/tenant/<int:tenant_id>/entrar", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_tenant_entrar(tenant_id):
    conn = database.get_connection()
    t = conn.execute("SELECT nome_empresa FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    conn.close()
    if not t:
        flash(f"Tenant #{tenant_id} não encontrado.", "danger")
        return redirect(url_for("admin_tenants"))
    # Preserva tenant original para poder voltar
    if not session.get("impersonating"):
        session["original_tenant_id"] = int(session.get("tenant_id") or 1)
    session["tenant_id"] = tenant_id
    session["impersonating"] = True
    flash(f"Visualizando ambiente do tenant: {t['nome_empresa']}.", "info")
    return redirect(url_for("admin_tenants"))


@app.route("/admin/tenant/sair", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_tenant_sair():
    original = int(session.pop("original_tenant_id", 1))
    session.pop("impersonating", None)
    session["tenant_id"] = original
    flash("Voltou ao ambiente Super Admin.", "success")
    return redirect(url_for("admin_tenants"))


@app.route("/admin/tenant/<int:tenant_id>/toggle", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_tenant_toggle(tenant_id):
    conn = database.get_connection()
    row = conn.execute("SELECT ativo FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    if row:
        novo = 0 if row["ativo"] else 1
        conn.execute("UPDATE tenants SET ativo=? WHERE id=?", (novo, tenant_id))
        conn.commit()
    conn.close()
    return redirect(url_for("admin_tenants"))


@app.route("/admin/tenant/<int:tenant_id>/excluir", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_tenant_excluir(tenant_id):
    if tenant_id == 1:
        flash("Não é possível excluir o tenant padrão.", "danger")
        return redirect(url_for("admin_tenants"))
    conn = database.get_connection()
    row = conn.execute("SELECT ativo FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    if not row:
        flash("Tenant não encontrado.", "danger")
        conn.close()
        return redirect(url_for("admin_tenants"))
    if row["ativo"]:
        flash("Desative o tenant antes de excluir.", "danger")
        conn.close()
        return redirect(url_for("admin_tenants"))
    conn.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))
    conn.execute("DELETE FROM usuarios WHERE tenant_id=?", (tenant_id,))
    conn.execute("DELETE FROM tenant_config WHERE tenant_id=?", (tenant_id,))
    conn.commit()
    conn.close()
    flash(f"Tenant #{tenant_id} excluído.", "success")
    return redirect(url_for("admin_tenants"))


@app.route("/admin/importar-rf", methods=["GET", "POST"])
@login_required
@require_perfil("admin")
def admin_importar_rf():
    """Importa base da Receita Federal para o banco local."""
    try:
        if request.method == "POST":
            uf     = request.form.get("uf", "ES").strip().upper()
            limite = max(100, min(int(request.form.get("limite", 10000)), 500000))

            def _importar():
                try:
                    from scripts.importar_receita_federal import (
                        importar_estabelecimentos,
                        baixar_tabela_municipios,
                        baixar_tabela_cnaes,
                    )
                    municipios = baixar_tabela_municipios()
                    cnaes_desc = baixar_tabela_cnaes()
                    resultado = importar_estabelecimentos(
                        uf_filtro=uf,
                        limite=limite,
                        municipios=municipios,
                        cnaes_desc=cnaes_desc,
                    )
                    if resultado == 0:
                        raise Exception("RF retornou 0 empresas — servidores indisponíveis")
                except Exception as e:
                    print(f"[RF] Fallback BrasilAPI: {e}")
                    try:
                        from scripts.importar_receita_federal import importar_via_brasilapi
                        importar_via_brasilapi(uf_filtro=uf, limite=limite)
                    except Exception as e2:
                        print(f"[RF] Erro no fallback BrasilAPI: {e2}")

            t = threading.Thread(target=_importar, daemon=True)
            t.start()
            return jsonify({
                "ok": True,
                "mensagem": (
                    f"Importação de {uf} iniciada em background "
                    f"({limite:,} empresas). Pode levar 20-30 minutos."
                ),
            })

        db = database.get_new_db_connection()
        row = db.execute("SELECT COUNT(*) AS cnt FROM rf_empresas").fetchone()
        total_rf = int(row["cnt"] if row else 0)
        por_uf = db.execute("""
            SELECT uf, COUNT(*) AS total
            FROM rf_empresas
            GROUP BY uf
            ORDER BY total DESC
        """).fetchall()
        db.close()

        return render_template("admin_importar_rf.html",
                               total_rf=total_rf,
                               por_uf=por_uf)
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"Erro: {e}", 500


@app.route("/admin/importar-rf/status")
@login_required
@require_perfil("admin")
def admin_importar_rf_status():
    try:
        db = database.get_new_db_connection()
        row = db.execute("SELECT COUNT(*) AS cnt FROM rf_empresas").fetchone()
        total = int(row["cnt"] if row else 0)
        db.close()
        return jsonify({"total": total})
    except Exception:
        return jsonify({"total": 0})


@app.route("/admin/limpar-cache-dashboard", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_limpar_cache_dashboard():
    _DASHBOARD_CACHE.clear()
    flash("Cache do dashboard limpo.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/enriquecer-cnae", methods=["POST"])
@login_required
@require_perfil("admin")
def admin_enriquecer_cnae():
    """Enriquece empresas sem CNAE via receitaws.com.br (max 20 por chamada, rate-limit 3 req/min)."""
    limite = min(int(request.form.get("limite", 20)), 50)
    resultado = emp_model.enriquecer_cnae_batch(tenant_id=_tid(), limite=limite)
    flash(
        f"Enriquecimento CNAE: {resultado['atualizadas']} atualizadas, "
        f"{resultado['erros']} erros, {resultado['sem_cnpj']} sem CNPJ válido "
        f"(de {resultado['total']} pendentes).",
        "success" if resultado["atualizadas"] > 0 else "warning",
    )
    return redirect(url_for("admin"))


# ── Setup Wizard — Onboarding Multi-tenant ────────────────────────────────────

@app.route("/setup")
@login_required
def setup_wizard():
    t = tenant_model.get_tenant_atual()
    tc = tenant_model.get_tenant_config(t["id"]) if t else {}
    tid = int(t["id"]) if t else 1
    try:
        _db = database.get_connection()
        step3_done = (_db.execute(
            "SELECT COUNT(*) AS n FROM empresas WHERE tenant_id=?", (tid,)
        ).fetchone()["n"] or 0) > 0
        _db.close()
    except Exception:
        step3_done = False
    step1_done = bool(tc.get("email_remetente") or tc.get("email_contato"))
    step2_done = bool(tc.get("produtos_texto"))
    step4_done = bool(t and t.get("configurado"))
    steps = {1: step1_done, 2: step2_done, 3: step3_done, 4: step4_done}
    progress = int(sum(steps.values()) / 4 * 100)
    return render_template("setup_wizard.html", tenant=t, tc=tc,
                           steps=steps, progress=progress)


@app.route("/setup/salvar", methods=["POST"])
@login_required
def setup_salvar():
    t = tenant_model.get_tenant_atual()
    if not t:
        return redirect(url_for("dashboard"))
    try:
        dados = {
            "nome_empresa":    request.form.get("nome_empresa", "").strip(),
            "nome_plataforma": request.form.get("nome_plataforma", "CRM").strip(),
            "ramo_principal":  request.form.get("ramo_principal", "").strip(),
            "produtos_texto":  request.form.get("produtos_texto", "").strip(),
            "diferenciais":    request.form.get("diferenciais", "").strip(),
            "tom_ia":          request.form.get("tom_ia", "profissional"),
            "whatsapp":        request.form.get("whatsapp", "").strip(),
            "email_contato":   request.form.get("email_contato", "").strip(),
            "site":            request.form.get("site", "").strip(),
            "cor_primaria":     request.form.get("cor_primaria", "#C5A089"),
            "cor_secundaria":   request.form.get("cor_secundaria", "#8B6914"),
            "logo_url":         request.form.get("logo_url", "").strip() or None,
            "historico":        request.form.get("historico", "").strip(),
            "concorrentes":     request.form.get("concorrentes", "").strip(),
            "personalidade_ia": request.form.get("personalidade_ia", "").strip(),
        }
        tenant_model.salvar_setup(t["id"], dados)
        # Limpa cache de tenant no g para recarregar
        from flask import g as _g
        if hasattr(_g, "tenant"):
            del _g.tenant
        session["tenant_id"] = t["id"]
        flash("Configuração salva! Bem-vindo ao seu CRM.", "success")
    except Exception as e:
        flash(f"Erro ao salvar configuração: {e}", "danger")
    return redirect(url_for("dashboard"))


@app.route("/setup/step1", methods=["POST"])
@login_required
def setup_step1():
    t = tenant_model.get_tenant_atual()
    if not t:
        return redirect(url_for("setup_wizard"))
    tid = int(t["id"])
    nome_empresa = request.form.get("nome_empresa", "").strip() or t["nome_empresa"]
    logo_url = request.form.get("logo_url", "").strip() or None
    email_remetente = request.form.get("email_remetente", "").strip()
    nome_vendedor = request.form.get("nome_vendedor", "").strip()
    try:
        db = database.get_connection()
        db.execute("UPDATE tenants SET nome_empresa=?, logo_url=? WHERE id=?",
                   (nome_empresa, logo_url, tid))
        db.execute("INSERT OR IGNORE INTO tenant_config (tenant_id) VALUES (?)", (tid,))
        db.execute(
            "UPDATE tenant_config SET email_remetente=?, nome_vendedor=? WHERE tenant_id=?",
            (email_remetente, nome_vendedor, tid),
        )
        db.commit()
        db.close()
        if hasattr(g, "tenant"):
            del g.tenant
        flash("Dados da empresa salvos!", "success")
    except Exception as e:
        flash(f"Erro ao salvar: {e}", "danger")
    return redirect(url_for("setup_wizard"))


@app.route("/setup/step2", methods=["POST"])
@login_required
def setup_step2():
    t = tenant_model.get_tenant_atual()
    if not t:
        return redirect(url_for("setup_wizard"))
    tid = int(t["id"])
    produtos = request.form.getlist("produtos")
    custom = request.form.get("produtos_custom", "").strip()
    partes = [p for p in produtos if p] + ([custom] if custom else [])
    produtos_texto = ", ".join(partes)
    try:
        db = database.get_connection()
        db.execute("INSERT OR IGNORE INTO tenant_config (tenant_id) VALUES (?)", (tid,))
        db.execute("UPDATE tenant_config SET produtos_texto=? WHERE tenant_id=?",
                   (produtos_texto, tid))
        db.commit()
        db.close()
        flash("Produtos configurados!", "success")
    except Exception as e:
        flash(f"Erro ao salvar produtos: {e}", "danger")
    return redirect(url_for("setup_wizard"))


@app.route("/setup/step3", methods=["POST"])
@login_required
def setup_step3():
    flash("Passo de leads marcado como concluído!", "success")
    return redirect(url_for("setup_wizard"))


@app.route("/setup/step4", methods=["POST"])
@login_required
def setup_step4():
    t = tenant_model.get_tenant_atual()
    if not t:
        return redirect(url_for("setup_wizard"))
    tid = int(t["id"])
    try:
        db = database.get_connection()
        db.execute("UPDATE tenants SET configurado=1 WHERE id=?", (tid,))
        db.commit()
        db.close()
        if hasattr(g, "tenant"):
            del g.tenant
        session["tenant_id"] = tid
        flash("Configuração concluída! Bem-vindo ao Krylo CRM.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "danger")
        return redirect(url_for("setup_wizard"))
    return redirect(url_for("dashboard"))


@app.route("/krylo")
def krylo_landing():
    return render_template("krylo_landing.html")


@app.route("/planos")
@login_required
@require_perfil("admin")
def planos_index():
    from models.planos import PLANOS, verificar_limite
    t = tenant_model.get_tenant_atual()
    tid = _tid()
    plano_atual = (t or {}).get("plano", "starter")
    uso = {
        "empresas": verificar_limite(tid, "empresas"),
        "usuarios": verificar_limite(tid, "usuarios"),
        "sdr_leads": verificar_limite(tid, "sdr_leads"),
    }
    return render_template("planos.html", planos=PLANOS, plano_atual=plano_atual, uso=uso, tenant=t)


# ── Ajuda e KIA ────────────────────────────────────────────────────────────────

@app.route("/ajuda")
@login_required
def ajuda_index():
    import json as _json
    artigos_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "artigos_ajuda.json")
    try:
        with open(artigos_path, encoding="utf-8") as f:
            artigos = _json.load(f)
    except Exception:
        artigos = []
    categorias = {
        "primeiros-passos": "Primeiros Passos",
        "sdr":              "SDR Autônomo",
        "cadencias":        "Cadências",
        "empresas":         "Empresas e Leads",
        "dashboard":        "Dashboard e Relatórios",
        "configuracoes":    "Configurações",
        "planos":           "Planos e Cobrança",
    }
    por_categoria = {c: [] for c in categorias}
    for a in artigos:
        cat = a.get("categoria", "")
        if cat in por_categoria:
            por_categoria[cat].append(a)
    return render_template("ajuda.html",
                           artigos=artigos,
                           por_categoria=por_categoria,
                           categorias=categorias)


@app.route("/ajuda/kia", methods=["POST"])
@login_required
def ajuda_kia():
    try:
        import json as _json
        body = request.json or {}
        pergunta = (body.get("mensagem") or body.get("pergunta") or "").strip()
        if not pergunta:
            return jsonify({"error": "Pergunta vazia"}), 400
        historico = body.get("historico") or []

        t = tenant_model.get_tenant_atual()
        nome_plataforma = (t or {}).get("nome_plataforma", "Krylo")

        # Carrega artigos para contexto
        artigos_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "artigos_ajuda.json")
        try:
            with open(artigos_path, encoding="utf-8") as f:
                artigos = _json.load(f)
            base_conhecimento = "\n".join(
                f"- {a['titulo']}: {a['conteudo']}" for a in artigos[:10]
            )
        except Exception:
            base_conhecimento = ""

        system = f"""Você é a KIA, assistente de suporte da plataforma {nome_plataforma}.
Responda perguntas sobre como usar o sistema de CRM de forma direta e didática.

FUNCIONALIDADES PRINCIPAIS:
- SDR Autonomo: prospecta empresas automaticamente por CNAE
- Cadencias: sequencia automatica de mensagens para leads
- Empresas: gestao de prospects e clientes
- Dashboard: metricas e funil de vendas
- Radar de Mercado: monitora concorrentes e editais
- Motor de Expansao: identifica oportunidades de upsell
- Termometro: saude dos clientes
- Simulador: gera propostas em 60 segundos
- CQA: testa e corrige o sistema automaticamente

BASE DE CONHECIMENTO:
{base_conhecimento}

Use sempre o nome "{nome_plataforma}" ao referenciar o sistema. Seja breve (máximo 4 parágrafos)."""

        # Build messages with conversation history (last 10 turns)
        msgs = []
        for h in historico[-10:]:
            role = h.get("role")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": pergunta})

        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=msgs,
        )
        resposta = resp.content[0].text

        # Salva histórico
        if t:
            try:
                conn = database.get_connection()
                conn.execute(
                    "INSERT INTO kia_historico (tenant_id, pergunta, resposta) VALUES (?,?,?)",
                    (t["id"], pergunta[:500], resposta[:2000]),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── CQA — Central de Qualidade Automática ────────────────────────────────────

@app.route("/cqa")
@login_required
@require_perfil("gerente")
def cqa_dashboard():
    conn = database.get_connection()
    if database._USE_PG:
        rows = conn.execute("""
            SELECT DISTINCT ON (check_nome)
                check_nome, status, mensagem, auto_corrigido, executado_em
            FROM cqa_resultados
            ORDER BY check_nome, executado_em DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT check_nome, status, mensagem, auto_corrigido, MAX(executado_em) AS executado_em
            FROM cqa_resultados GROUP BY check_nome ORDER BY check_nome
        """).fetchall()
    alertas = [dict(a) for a in conn.execute(
        "SELECT * FROM cqa_alertas WHERE tenant_id=? AND resolvido=0 ORDER BY criado_em DESC LIMIT 20", (_tid(),)
    ).fetchall()]
    cfg_row = conn.execute(
        "SELECT valor FROM cqa_config WHERE chave='modo_autonomo' AND tenant_id=?", (_tid(),)
    ).fetchone()
    autonomo_ativo = cfg_row["valor"].lower() == "true" if cfg_row else True
    ultimo_repair = conn.execute(
        "SELECT MAX(executado_em) AS t FROM cqa_resultados"
    ).fetchone()
    conn.close()
    resultados = [dict(r) for r in rows]
    erros  = sum(1 for r in resultados if r["status"] == "erro")
    avisos = sum(1 for r in resultados if r["status"] == "aviso")
    oks    = sum(1 for r in resultados if r["status"] == "ok")
    return render_template("cqa_dashboard.html",
                           resultados=resultados, alertas=alertas,
                           erros=erros, avisos=avisos, oks=oks,
                           autonomo_ativo=autonomo_ativo,
                           ultimo_repair=(ultimo_repair["t"] or "—")[:16] if ultimo_repair else "—")


@app.route("/cqa/rodar", methods=["POST"])
@login_required
@require_perfil("gerente")
def cqa_rodar():
    import sys as _sys
    import threading as _th
    def _run():
        try:
            _cqa_root = os.path.dirname(os.path.abspath(__file__))
            if _cqa_root not in _sys.path:
                _sys.path.insert(0, _cqa_root)
            from scripts.run_cqa import rodar_cqa_completo
            rodar_cqa_completo(aplicar_fixes=False, verbose=False)
        except Exception as e:
            print(f"[CQA] Erro ao rodar: {e}")
    _th.Thread(target=_run, daemon=True).start()
    flash("CQA iniciado em background. Aguarde alguns segundos e atualize a página.", "success")
    return redirect(url_for("cqa_dashboard"))


@app.route("/cqa/alerta/<int:alerta_id>/resolver", methods=["POST"])
@login_required
@require_perfil("gerente")
def cqa_alerta_resolver(alerta_id):
    try:
        conn = database.get_connection()
        conn.execute("UPDATE cqa_alertas SET resolvido=1 WHERE id=? AND tenant_id=?", (alerta_id, _tid()))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/cqa/fix/all", methods=["POST"])
@login_required
@require_perfil("gerente")
def cqa_fix_all():
    import sys as _sys
    import threading as _th
    def _run():
        try:
            _cqa_root = os.path.dirname(os.path.abspath(__file__))
            if _cqa_root not in _sys.path:
                _sys.path.insert(0, _cqa_root)
            from scripts.run_cqa import rodar_cqa_completo
            rodar_cqa_completo(aplicar_fixes=True, verbose=False)
        except Exception as e:
            print(f"[CQA] Erro ao rodar fix: {e}")
    _th.Thread(target=_run, daemon=True).start()
    flash("CQA + Auto-Fix iniciado. Aguarde e atualize a página.", "success")
    return redirect(url_for("cqa_dashboard"))


@app.route("/cqa/toggle-autonomo", methods=["POST"])
@login_required
@require_perfil("gerente")
def cqa_toggle_autonomo():
    try:
        ativo = bool(request.json.get("ativo", True))
        conn = database.get_connection()
        if database._USE_PG:
            conn.execute(
                """INSERT INTO cqa_config (tenant_id, chave, valor)
                   VALUES (%s, 'modo_autonomo', %s)
                   ON CONFLICT (tenant_id, chave) DO UPDATE SET valor = %s, atualizado_em = NOW()""",
                (_tid(), str(ativo), str(ativo)),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO cqa_config (tenant_id, chave, valor) VALUES (?, ?, ?)",
                (_tid(), "modo_autonomo", str(ativo)),
            )
        conn.commit()
        conn.close()
        try:
            if ativo:
                scheduler.resume_job("cqa_automatico")
            else:
                scheduler.pause_job("cqa_automatico")
        except Exception:
            pass
        return jsonify({"ok": True, "autonomo": ativo})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        # Werkzeug reinicia o processo filho quando .py muda.
        # Só iniciamos o livereload no processo filho (WERKZEUG_RUN_MAIN="true"),
        # não no processo pai (watcher), para evitar porta duplicada.
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            import threading
            from livereload import Server as _LRServer

            def _start_livereload():
                lr = _LRServer()
                lr.watch("templates/")
                lr.watch("static/css/")
                lr.watch("static/js/")
                lr.serve(port=35729, host="127.0.0.1")

            threading.Thread(target=_start_livereload, daemon=True).start()

        app.run(debug=True, host="0.0.0.0", port=port, use_reloader=True)
    else:
        app.run(host="0.0.0.0", port=port)
