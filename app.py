import os
import csv
import io
import json
import time
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv(override=True)

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import database
import models.empresa as emp_model
import models.contato as cont_model
import models.oportunidade as op_model
import models.atividade as atv_model
import models.prospeccao as prosp_model
import models.usuario as user_model
from models.usuario import require_perfil, PERFIS, PERFIL_LABELS
import ai

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "krylo-crm-2024")
app.permanent_session_lifetime = timedelta(hours=8)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar o CRM."
login_manager.login_message_category = "danger"

@login_manager.user_loader
def load_user(user_id):
    return user_model.buscar_por_id(int(user_id))

_START_TIME = str(time.time())

database.init_db()
user_model.criar_admin_se_necessario()


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
    return render_template(
        "dashboard.html",
        status_counts=status_counts,
        estagio_counts=estagio_counts,
        pipeline_val=pipeline_val,
        atividades=atividades,
        total_empresas=total_empresas,
        clientes=clientes,
        em_aberto=em_aberto,
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
    return render_template("empresas/lista.html", empresas=todas, q=q, status=status)


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

        contexto = _central_ia_context()
        system   = _IA_SYSTEM_PROMPT
        if contexto:
            system += f"\n\nBase de conhecimento disponível:\n{contexto}"

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
