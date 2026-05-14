import os
import csv
import io
import json
import time
import threading
import atexit
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv(override=True)

from apscheduler.schedulers.background import BackgroundScheduler

from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
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
from models.usuario import require_perfil, PERFIS, PERFIL_LABELS
import ai

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "krylo-crm-2024")
app.permanent_session_lifetime = timedelta(hours=8)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar o CRM."
login_manager.login_message_category = "danger"

@app.context_processor
def _inject_cadencias_badge():
    try:
        radar_nao_lidos = radar_model.contar_nao_lidos()
    except Exception:
        radar_nao_lidos = {"editais": 0, "concorrentes": 0, "total": 0}
    try:
        return {
            "cadencias_hoje_count": cad_model.contar_hoje(),
            "radar_nao_lidos": radar_nao_lidos,
        }
    except Exception:
        return {"cadencias_hoje_count": 0, "radar_nao_lidos": radar_nao_lidos}


@app.context_processor
def inject_empresa():
    try:
        conn = database.get_connection()
        cfg = conn.execute(
            "SELECT nome, nome_fantasia, whatsapp FROM empresa_config WHERE id=1"
        ).fetchone()
        conn.close()
        return {
            "empresa_nome": cfg["nome"] if cfg else "Krylo",
            "empresa_whatsapp": cfg["whatsapp"] if cfg else "",
        }
    except Exception:
        return {"empresa_nome": "Krylo", "empresa_whatsapp": ""}


@login_manager.user_loader
def load_user(user_id):
    return user_model.buscar_por_id(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    if (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    ):
        return jsonify({"error": "Sessão expirada. Faça login novamente."}), 401
    return redirect(url_for('login', next=request.url))

_START_TIME = str(time.time())

database.init_db()
user_model.criar_admin_se_necessario()


# ── APScheduler — SDR Autônomo ────────────────────────────────────────────────

def _job_prospeccao_autonoma():
    try:
        from models.prospeccao_autonoma import rodar_prospeccao_autonoma
        resultado = rodar_prospeccao_autonoma()
        print(f"[SCHEDULER] prospeccao_autonoma: {resultado}")
    except Exception as e:
        print(f"[SCHEDULER] Erro: {e}")


scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
scheduler.add_job(
    func=_job_prospeccao_autonoma,
    trigger="interval",
    hours=6,
    id="prospeccao_autonoma",
    replace_existing=True,
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha   = request.form.get("senha", "")
        u = user_model.autenticar(usuario, senha)
        if u:
            login_user(u, remember=True)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Usuário ou senha incorretos.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada.", "success")
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    status_counts  = emp_model.contar_por_status()
    estagio_counts = op_model.contar_por_estagio()
    pipeline_val   = op_model.valor_total_pipeline()
    atividades     = atv_model.listar(limit=8)
    total_empresas = sum(status_counts.values())
    clientes       = status_counts.get("cliente", 0)
    em_aberto      = sum(
        v for k, v in estagio_counts.items()
        if k not in ("fechado_ganho", "fechado_perdido")
    )
    radar = op_model.listar_radar()
    op_model.salvar_scores_radar(radar)
    radar_alerta_count = sum(
        1 for r in radar
        if r.get("dias_sem_contato") is not None and r["dias_sem_contato"] > 7
    )
    potencial_expansao = exp_model.potencial_total()
    cob_resumo = cob_model.resumo()
    mes_atual = str(date.today())[:7]
    rec_resumo = rec_model.resumo_mes(mes_atual)
    radar_badge = radar_model.contar_nao_lidos()
    dash_extra = rel_model.coletar_dashboard_extra(mes_atual)
    top_acao = (radar[0].get("proxima_acao") or "") if radar else ""
    try:
        pauto_resumo = pauto_model.resumo_dashboard()
    except Exception:
        pauto_resumo = {"novos_hoje": 0, "prontos": 0}
    return render_template(
        "dashboard.html",
        status_counts=status_counts,
        estagio_counts=estagio_counts,
        pipeline_val=pipeline_val,
        atividades=atividades,
        total_empresas=total_empresas,
        clientes=clientes,
        em_aberto=em_aberto,
        radar=radar[:5],
        radar_alerta_count=radar_alerta_count,
        potencial_expansao=potencial_expansao,
        cob_resumo=cob_resumo,
        rec_resumo=rec_resumo,
        mes_atual=mes_atual,
        radar_badge=radar_badge,
        portais_ativos=dash_extra["portais_ativos"],
        rec_atrasados_count=dash_extra["rec_atrasados_count"],
        deals_fechados_semana=dash_extra["deals_fechados_semana"],
        receita_mes=dash_extra["receita_mes"],
        pct_meta=dash_extra["pct_meta"],
        cadencias_ativas_count=dash_extra["cadencias_ativas_count"],
        top_acao=top_acao,
        pauto_resumo=pauto_resumo,
    )


# ── Empresas ──────────────────────────────────────────────────────────────────

@app.route("/empresas")
@login_required
@require_perfil('gerente')
def empresas_lista():
    q      = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    todas  = emp_model.listar(status=status or None)
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
        emp_model.criar(_form_empresa(request.form))
        flash("Empresa cadastrada com sucesso.", "success")
        return redirect(url_for("empresas_lista"))
    return render_template("empresas/form.html", empresa=None,
                           action=url_for("empresas_nova"))


@app.route("/empresas/<int:id>")
@login_required
@require_perfil('gerente')
def empresas_detalhe(id):
    emp = emp_model.buscar_por_id(id)
    if not emp:
        flash("Empresa não encontrada.", "danger")
        return redirect(url_for("empresas_lista"))
    return render_template(
        "empresas/detalhe.html",
        empresa=emp,
        contatos=cont_model.listar(empresa_id=id),
        ops=op_model.listar(empresa_id=id),
        atividades=atv_model.listar(empresa_id=id, limit=10),
        labels=op_model.ESTAGIO_LABELS,
    )


@app.route("/empresas/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def empresas_editar(id):
    emp = emp_model.buscar_por_id(id)
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
    todos = cont_model.listar()
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
    if request.method == "POST":
        cont_model.criar(_form_contato(request.form))
        flash("Contato cadastrado.", "success")
        return redirect(url_for("contatos_lista"))
    return render_template("contatos/form.html", contato=None,
                           empresas=emp_model.listar(),
                           action=url_for("contatos_novo"))


@app.route("/contatos/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def contatos_editar(id):
    c = cont_model.buscar_por_id(id)
    if not c:
        flash("Contato não encontrado.", "danger")
        return redirect(url_for("contatos_lista"))
    if request.method == "POST":
        cont_model.atualizar(id, _form_contato(request.form))
        flash("Contato atualizado.", "success")
        return redirect(url_for("contatos_lista"))
    return render_template("contatos/form.html", contato=c,
                           empresas=emp_model.listar(),
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
    todas      = op_model.listar()
    by_estagio = {e: [] for e in op_model.ESTAGIOS}
    for o in todas:
        by_estagio.setdefault(o["estagio"], []).append(o)
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
    if request.method == "POST":
        op_model.criar(_form_oportunidade(request.form))
        flash("Oportunidade criada.", "success")
        return redirect(url_for("oportunidades_kanban"))
    return render_template(
        "oportunidades/form.html", op=None,
        empresas=emp_model.listar(),
        estagios=op_model.ESTAGIOS, labels=op_model.ESTAGIO_LABELS,
        action=url_for("oportunidades_nova"),
        pre_titulo=request.args.get("titulo", ""),
    )


@app.route("/oportunidades/<int:id>")
@login_required
def oportunidades_detalhe(id):
    o = op_model.buscar_por_id(id)
    if not o:
        flash("Oportunidade não encontrada.", "danger")
        return redirect(url_for("oportunidades_kanban"))
    return render_template(
        "oportunidades/detalhe.html",
        op=o,
        atividades=atv_model.listar(oportunidade_id=id),
        labels=op_model.ESTAGIO_LABELS,
        estagios=op_model.ESTAGIOS,
    )


@app.route("/oportunidades/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_editar(id):
    o = op_model.buscar_por_id(id)
    if not o:
        flash("Oportunidade não encontrada.", "danger")
        return redirect(url_for("oportunidades_kanban"))
    if request.method == "POST":
        op_model.atualizar(id, _form_oportunidade(request.form))
        flash("Oportunidade atualizada.", "success")
        return redirect(url_for("oportunidades_detalhe", id=id))
    return render_template(
        "oportunidades/form.html", op=o,
        empresas=emp_model.listar(),
        estagios=op_model.ESTAGIOS, labels=op_model.ESTAGIO_LABELS,
        action=url_for("oportunidades_editar", id=id),
    )


@app.route("/oportunidades/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_excluir(id):
    op_model.excluir(id)
    flash("Oportunidade excluída.", "success")
    return redirect(url_for("oportunidades_kanban"))


@app.route("/oportunidades/<int:id>/mover", methods=["POST"])
@login_required
@require_perfil('vendedor')
def oportunidades_mover(id):
    novo = request.json.get("estagio", "")
    if novo not in op_model.ESTAGIOS:
        return jsonify({"error": "Estágio inválido"}), 400
    o = op_model.buscar_por_id(id)
    if not o:
        return jsonify({"error": "Não encontrado"}), 404
    dados = dict(o)
    dados["estagio"] = novo
    op_model.atualizar(id, dados)
    return jsonify({"ok": True, "estagio": novo, "label": op_model.ESTAGIO_LABELS[novo]})


@app.route("/oportunidades/radar")
@login_required
def oportunidades_radar():
    radar = op_model.listar_radar()
    op_model.salvar_scores_radar(radar)
    return jsonify([
        {
            "id": r["id"],
            "titulo": r["titulo"],
            "empresa": r["empresa_nome"],
            "estagio": r["estagio"],
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
        estagio=f.get("estagio", "lead"),
        valor_estimado=valor,
        num_cartoes=cartoes,
        responsavel=f.get("responsavel", "").strip() or None,
        previsao_fechamento=f.get("previsao_fechamento", "").strip() or None,
        notas=f.get("notas", "").strip() or None,
    )


# ── Atividades ────────────────────────────────────────────────────────────────

@app.route("/atividades")
@login_required
def atividades_lista():
    return render_template("atividades/lista.html",
                           atividades=atv_model.listar(limit=50))


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
    empresas      = emp_model.listar()
    oportunidades = op_model.listar()
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


def _processar_linhas(linhas: list, mapa: dict) -> tuple:
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
        })
        prosp_model.criar({
            "contato_id": contato_id,
            "empresa_id": emp_id,
            "status": "pendente",
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
    arquivo = request.files.get("arquivo")
    if not arquivo:
        flash("Arquivo não encontrado.", "danger")
        return redirect(url_for("leads_importar_form"))
    mapa = {
        "nome":     request.form.get("map_nome", ""),
        "empresa":  request.form.get("map_empresa", ""),
        "cargo":    request.form.get("map_cargo", ""),
        "telefone": request.form.get("map_telefone", ""),
        "email":    request.form.get("map_email", ""),
        "cidade":   request.form.get("map_cidade", ""),
    }
    try:
        raw = arquivo.stream.read()
        _, linhas = _ler_arquivo(raw, arquivo.filename)
        importados, ignorados = _processar_linhas(linhas, mapa)
        msg = f"{importados} lead(s) importado(s) com sucesso."
        if ignorados:
            msg += f" {ignorados} linha(s) ignorada(s) (sem nome ou empresa)."
        flash(msg, "success")
    except Exception as e:
        flash(f"Erro na importação: {e}", "danger")
    return redirect(url_for("prospeccao_lista"))


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

    leads  = prosp_model.listar(score_min=score_min, score_max=score_max, status=status or None)
    counts = prosp_model.contar_por_status()
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

    leads = prosp_model.listar_ids_para_exportacao(ids)
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
        headers={"Content-Disposition": "attachment; filename=leads_escard.csv"},
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
    leads = pauto_model.listar(uf=uf or None, score_min=score_min_int, status=status)
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
        resultado = pauto_model.buscar_e_salvar(uf, cnaes, limite)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prospeccao/automatica/<int:id>/importar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_importar(id):
    try:
        emp_id = pauto_model.importar(id)
        return jsonify({"ok": True, "empresa_id": emp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prospeccao/automatica/importar-selecionados", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_importar_lote():
    ids = (request.json or {}).get("ids", [])
    ok = pauto_model.importar_varios(ids)
    return jsonify({"ok": True, "importados": ok})


@app.route("/prospeccao/automatica/<int:id>/status", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_auto_status(id):
    novo = (request.json or {}).get("status", "")
    if novo not in ("novo", "importado", "descartado"):
        return jsonify({"error": "Status inválido"}), 400
    pauto_model.atualizar_status(id, novo)
    return jsonify({"ok": True})


@app.route("/prospeccao/autonoma/rodar", methods=["POST"])
@login_required
@require_perfil("vendedor")
def prospeccao_autonoma_rodar():
    from models.prospeccao_autonoma import rodar_prospeccao_autonoma

    def _rodar():
        try:
            resultado = rodar_prospeccao_autonoma()
            print(f"[MANUAL] prospeccao_autonoma: {resultado}")
        except Exception as e:
            print(f"[MANUAL] Erro: {e}")

    threading.Thread(target=_rodar, daemon=True).start()
    return jsonify({"status": "iniciado", "mensagem": "Prospecção rodando em background"})


@app.route("/prospeccao/autonoma/status")
@login_required
def prospeccao_autonoma_status():
    from models.prospeccao_autonoma import status_resumo
    return jsonify(status_resumo())


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
    hoje    = cad_model.listar_hoje()
    proximos = cad_model.listar_proximos_dias(7)

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
        dados        = request.json or {}
        empresa_id   = dados.get("empresa_id")
        empresa_nome = (dados.get("empresa_nome") or "").strip()
        whatsapp     = (dados.get("whatsapp") or "").strip()
        email        = (dados.get("email") or "").strip()
        op_id        = dados.get("oportunidade_id")

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
                "oportunidade_id":   op_id,
                "etapa":             et.get("etapa", i + 1),
                "data_acao":         datas[i],
                "mensagem_whatsapp": et.get("mensagem_whatsapp", ""),
                "assunto_email":     et.get("assunto_email", ""),
                "corpo_email":       et.get("corpo_email", ""),
                "status":            "pendente",
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


# ── Radar de Mercado ─────────────────────────────────────────────────────────

@app.route("/radar")
@login_required
def radar_index():
    dados = radar_model.listar()
    badge = radar_model.contar_nao_lidos()
    return render_template(
        "radar/index.html",
        editais=dados["editais"],
        concorrentes=dados["concorrentes"],
        badge=badge,
    )


@app.route("/radar/buscar", methods=["POST"])
@login_required
@require_perfil('vendedor')
def radar_buscar():
    try:
        resultado = radar_model.buscar_feeds()
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/radar/<int:id>/lido", methods=["POST"])
@login_required
def radar_marcar_lido(id):
    radar_model.marcar_lido(id)
    return jsonify({"ok": True})


@app.route("/radar/<int:id>", methods=["DELETE"])
@login_required
@require_perfil('vendedor')
def radar_excluir(id):
    radar_model.excluir(id)
    return jsonify({"ok": True})


@app.route("/radar/analisar-oportunidades", methods=["POST"])
@login_required
@require_perfil("vendedor")
def radar_analisar_oportunidades():
    try:
        import anthropic as _ant, models.ia_config as ia_mod
        conn = database.get_connection()
        itens = [dict(r) for r in conn.execute(
            "SELECT id, tipo, titulo, fonte FROM radar_mercado WHERE lido=0"
        ).fetchall()]
        if not itens:
            conn.close()
            return jsonify({
                "analise": "Nenhuma notícia não lida no radar. Clique em **Buscar agora** primeiro.",
                "oportunidades": 0,
            })
        emp_row = conn.execute(
            "SELECT nome FROM empresa_config WHERE id=1"
        ).fetchone()
        empresa_nome = emp_row["nome"] if emp_row else "Krylo"
        system = ia_mod.get_system_prompt(conn)
        conn.close()

        lista = "\n".join(f"- [{it['tipo']}] {it['titulo']}" for it in itens)
        prompt = (
            f"Analise estas {len(itens)} notícias e alertas de mercado encontrados hoje:\n\n"
            f"{lista}\n\n"
            f"Com base no que você sabe sobre a empresa ({empresa_nome}) e seus produtos/serviços, identifique:\n\n"
            "1. OPORTUNIDADES IMEDIATAS (máximo 3): situações onde a empresa pode agir HOJE para gerar negócio\n"
            "2. AMEAÇAS A MONITORAR (máximo 2): movimentos de mercado que precisam de atenção\n"
            "3. AÇÃO RECOMENDADA: uma ação específica e concreta para executar nas próximas 24h\n\n"
            "Seja direto e específico. Cite os nomes das empresas/situações das notícias.\n"
            "Formato: use markdown com ## para seções."
        )

        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        analise = resp.content[0].text.strip()

        conn2 = database.get_connection()
        conn2.execute(
            "INSERT INTO radar_analises (analise, num_itens_analisados) VALUES (?, ?)",
            (analise, len(itens)),
        )
        conn2.commit()
        conn2.close()

        return jsonify({"analise": analise, "oportunidades": len(itens)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/radar/<int:id>/mensagem", methods=["POST"])
@login_required
@require_perfil('vendedor')
def radar_mensagem(id):
    import re as _re
    try:
        conn = database.get_connection()
        item = conn.execute("SELECT * FROM radar_mercado WHERE id=?", (id,)).fetchone()
        conn.close()
        if not item:
            return jsonify({"error": "Item não encontrado"}), 404
        titulo = item["titulo"] or ""
        prompt = f"""Você é um consultor comercial da Krylo Cartão de Benefícios B2B.
Um concorrente está com problemas. Use isso para gerar uma mensagem de WhatsApp de abordagem.
Retorne SOMENTE um JSON válido: {{"mensagem": "<texto completo>"}}

Notícia: {titulo}

Regras: mensagem curta (máx 4 linhas), mencione o problema do concorrente de forma delicada,
destaque a estabilidade e confiabilidade da Krylo, termine com CTA para uma conversa rápida.
Tom amigável e consultivo, não agressivo."""

        import anthropic as _ant, models.ia_config as ia_mod
        _conn_rad = database.get_connection()
        _sys_rad  = ia_mod.get_system_prompt(_conn_rad)
        _conn_rad.close()
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_sys_rad,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"```\s*$", "", raw, flags=_re.MULTILINE)
        result = json.loads(raw.strip())
        return jsonify({"ok": True, "mensagem": result.get("mensagem", "")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Motor de Expansão ────────────────────────────────────────────────────────

@app.route("/expansao")
@login_required
@require_perfil('gerente')
def expansao_index():
    oportunidades = exp_model.listar_oportunidades()
    potencial = sum(r["potencial_mensal"] for r in oportunidades)
    return render_template(
        "expansao/index.html",
        oportunidades=oportunidades,
        potencial=potencial,
        produtos=exp_model.PRODUTOS,
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
        faltando = [p for p in exp_model.PRODUTOS if p not in ativos]
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
        _sys_exp  = ia_mod.get_system_prompt(_conn_exp)
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


# ── IA — Painel de Configuração ──────────────────────────────────────────────

@app.route("/ia/config")
@login_required
@require_perfil("gerente")
def ia_config_painel():
    import models.ia_config as ia_mod
    conn = database.get_connection()
    cfg  = ia_mod.get_ia_config(conn)
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
        _agora = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        for campo in campos:
            if campo in f:
                conn.execute(
                    f"UPDATE ia_config SET {campo}=:v, atualizado_em=:t WHERE id=1",
                    {"v": f[campo], "t": _agora},
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
        resposta = ia_mod.chat_com_ia(conn, mensagem, historico, contexto)
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
        system = ia_mod.get_system_prompt(conn)
        cfg    = ia_mod.get_ia_config(conn)
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
    cur  = conn.execute("SELECT nome, tipo, conteudo_texto FROM documentos_ia WHERE conteudo_texto IS NOT NULL AND conteudo_texto != ''")
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
    cur   = conn.execute("SELECT id, nome, tipo, data_upload, tamanho FROM documentos_ia ORDER BY data_upload DESC")
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
        "INSERT INTO documentos_ia (nome, tipo, conteudo_texto, tamanho) VALUES (?, ?, ?, ?)",
        (arquivo.filename, ext.upper(), conteudo, tamanho),
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": doc_id, "nome": arquivo.filename, "tipo": ext.upper(), "tamanho": tamanho})


@app.route("/central-ia/documentos")
@login_required
def central_ia_documentos():
    conn = database.get_connection()
    cur  = conn.execute("SELECT id, nome, tipo, data_upload, tamanho FROM documentos_ia ORDER BY data_upload DESC")
    docs = [dict(d) for d in cur.fetchall()]
    conn.close()
    return jsonify(docs)


@app.route("/central-ia/documentos/<int:id>", methods=["DELETE"])
@login_required
@require_perfil('vendedor')
def central_ia_doc_excluir(id):
    conn = database.get_connection()
    conn.execute("DELETE FROM documentos_ia WHERE id = ?", (id,))
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
        "SELECT * FROM ramos_atividade ORDER BY ativo DESC, nome ASC"
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
                   (nome, descricao, cnaes, pitch, score_min, estados, capital_min, ativo)
               VALUES (:nome, :descricao, :cnaes, :pitch, :score_min, :estados, :capital_min, 1)""",
            {
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
    row = conn.execute("SELECT ativo FROM ramos_atividade WHERE id=?", (id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Não encontrado"}), 404
    novo = 0 if row["ativo"] else 1
    conn.execute("UPDATE ramos_atividade SET ativo=? WHERE id=?", (novo, id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "ativo": novo})


# ── Configurações — Empresa Proprietária ─────────────────────────────────────

@app.route("/configuracoes/empresa")
@login_required
@require_perfil("gerente")
def configuracoes_empresa():
    conn = database.get_connection()
    row  = conn.execute("SELECT * FROM empresa_config WHERE id=1").fetchone()
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
        for campo in campos:
            if campo in f:
                conn.execute(
                    f"UPDATE empresa_config SET {campo}=:v, atualizado_em=:t WHERE id=1",
                    {"v": f[campo], "t": _agora},
                )
        conn.commit()
        conn.close()
        return jsonify({"status": "salvo"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Dev ping (usado pelo hot-reload do browser) ───────────────────────────────

@app.route("/dev/ping")
def dev_ping():
    if not app.debug:
        return "", 404
    return jsonify({"t": _START_TIME})


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
