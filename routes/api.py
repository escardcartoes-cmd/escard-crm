"""
REST API — consumed by the Next.js frontend.
All routes return JSON. CSRF exempt (protected by CORS + SameSite cookies).
"""
from flask import Blueprint, jsonify, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
import models.usuario as user_model
import models.empresa as emp_model
import models.contato as cont_model
import models.oportunidade as op_model
import models.atividade as atv_model
import models.cadencia as cad_model
import models.prospeccao as prosp_model
import models.tenant as tenant_model
import models.audit as audit
import database
from functools import wraps


def require_perfil(*perfis):
    """Decorator: bloqueia acesso se current_user não tiver um dos perfis exigidos."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not current_user.is_authenticated:
                return jsonify(error="Autenticação necessária"), 401
            user_perfil = getattr(current_user, "perfil", None)
            if user_perfil not in perfis:
                audit.log("access.denied", resource=fn.__name__, metadata={"required": list(perfis), "got": user_perfil})
                return jsonify(error="Permissão insuficiente"), 403
            return fn(*a, **kw)
        return wrapper
    return deco

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _login_rate_limit():
    """Per-endpoint stricter limit for authentication attempts (anti brute-force)."""
    return "10 per minute; 30 per hour"


def _user_dict(u) -> dict:
    return {
        "id": u.id,
        "nome": u.nome,
        "email": u.email,
        "usuario": u.usuario,
        "perfil": u.perfil,
        "tenant_id": getattr(u, "tenant_id", 1),
    }


# ── AUTH ─────────────────────────────────────────────────────────────────────

@api_bp.post("/auth/login")
def auth_login():
    data = request.get_json(silent=True) or request.form
    usuario_str = (data.get("usuario") or "").strip()
    senha = data.get("senha") or ""
    if not usuario_str or not senha:
        return jsonify(error="Campos obrigatórios."), 400

    u_raw = user_model.buscar_dict_por_usuario(usuario_str)
    if u_raw and user_model.verificar_bloqueio(u_raw):
        return jsonify(error="Conta bloqueada. Aguarde 15 minutos."), 403

    u = user_model.autenticar(usuario_str, senha)
    if not u:
        if u_raw and u_raw.get("ativo"):
            user_model.registrar_tentativa_falha(u_raw["id"])
        audit.log("auth.login_failed", metadata={"usuario": usuario_str})
        return jsonify(error="Usuário ou senha incorretos."), 401

    user_model.resetar_tentativas(u.id)
    login_user(u, remember=True)
    session["tenant_id"] = getattr(u, "tenant_id", 1) or 1
    audit.log("auth.login_success", user_id=u.id, user_email=u.email, tenant_id=session["tenant_id"])
    return jsonify(user=_user_dict(u))


@api_bp.get("/auth/logout")
@login_required
def auth_logout():
    logout_user()
    return jsonify(ok=True)


@api_bp.post("/auth/forgot-password")
def auth_forgot_password():
    """Kick off password recovery. Always returns ok — never leaks account existence."""
    data = request.get_json(silent=True) or {}
    contato = (data.get("contato") or "").strip()
    if not contato:
        return jsonify(error="Informe e-mail ou telefone."), 400
    try:
        user_model.iniciar_recuperacao_senha(contato)
    except Exception:
        current_app.logger.exception("forgot-password failed")
    # Uniform response prevents enumeration
    return jsonify(ok=True, message="Se a conta existe, um código foi enviado.")


@api_bp.post("/auth/reset-password")
def auth_reset_password():
    """Complete password recovery with the code delivered to the user."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    codigo = (data.get("codigo") or "").strip()
    nova_senha = data.get("nova_senha") or ""
    if not (email and codigo and nova_senha):
        return jsonify(error="Campos obrigatórios: email, codigo, nova_senha"), 400
    if len(nova_senha) < 6:
        return jsonify(error="Senha deve ter pelo menos 6 caracteres."), 400
    ok, msg = user_model.verificar_recuperacao_e_trocar_senha(email, codigo, nova_senha)
    if not ok:
        return jsonify(error=msg), 400
    return jsonify(ok=True, message="Senha alterada. Faça login com a nova senha.")


@api_bp.get("/me")
@login_required
def me():
    d = _user_dict(current_user)
    # Include 2FA + security fields for the profile screen
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute(
        "SELECT dois_fatores_ativo, dois_fatores_canal, telefone FROM usuarios WHERE id=?",
        (current_user.id,),
    ).fetchone()
    if row:
        r = dict(row)
        d["dois_fatores_ativo"] = bool(r.get("dois_fatores_ativo"))
        d["dois_fatores_canal"] = r.get("dois_fatores_canal") or "email"
        d["telefone"] = r.get("telefone") or ""
    return jsonify(d)


@api_bp.put("/me/security")
@login_required
def me_security_update():
    """Toggle 2FA + pick delivery channel (email or whatsapp)."""
    data = request.get_json(silent=True) or {}
    ativo = 1 if data.get("dois_fatores_ativo") else 0
    canal = (data.get("dois_fatores_canal") or "email").strip().lower()
    if canal not in ("email", "whatsapp"):
        return jsonify(error="Canal inválido. Use 'email' ou 'whatsapp'."), 400
    conn = database.get_connection()
    if ativo and canal == "whatsapp":
        row = conn.execute(
            "SELECT telefone FROM usuarios WHERE id=?", (current_user.id,)
        ).fetchone()
        if not row or not (dict(row).get("telefone") or "").strip():
            return jsonify(error="Cadastre um telefone antes de habilitar 2FA via WhatsApp."), 400
    conn.execute(
        "UPDATE usuarios SET dois_fatores_ativo=?, dois_fatores_canal=? WHERE id=?",
        (ativo, canal, current_user.id),
    )
    conn.commit()
    return jsonify(ok=True, dois_fatores_ativo=bool(ativo), dois_fatores_canal=canal)


# ── DASHBOARD ────────────────────────────────────────────────────────────────

@api_bp.get("/dashboard")
@login_required
def dashboard():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    try:
        def scalar(sql, *params):
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return 0
            r = dict(row)
            return list(r.values())[0] or 0

        def qs(sql, *params):
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

        stats = {
            # Prospecção
            "prospects_sdr": scalar(
                "SELECT COUNT(*) c FROM prospeccao WHERE tenant_id=?", tid),
            "em_cadencia": scalar(
                "SELECT COUNT(*) c FROM cadencias WHERE tenant_id=?", tid),
            # Pipeline
            "pipeline_total": scalar(
                "SELECT COALESCE(SUM(valor_estimado),0) v FROM oportunidades WHERE tenant_id=? AND etapa NOT IN ('fechado','perdido')", tid),
            "oportunidades_ativas": scalar(
                "SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=? AND etapa NOT IN ('fechado','perdido')", tid),
            "fechados_mes": scalar(
                "SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=? AND etapa='fechado'", tid),
            "receita_mes": scalar(
                "SELECT COALESCE(SUM(valor_estimado),0) v FROM oportunidades WHERE tenant_id=? AND etapa='fechado'", tid),
            # Cartões (domínio principal Krylo)
            "clientes_ativos": scalar(
                "SELECT COUNT(*) c FROM empresas WHERE tenant_id=? AND cliente_ativo=1", tid),
            "cartoes_emitidos": scalar(
                "SELECT COALESCE(SUM(num_cartoes),0) v FROM oportunidades WHERE tenant_id=? AND etapa='fechado'", tid),
            "mrr": scalar(
                "SELECT COALESCE(SUM(valor_mensal),0) v FROM empresas WHERE tenant_id=? AND cliente_ativo=1", tid),
            "cartoes_pipeline": scalar(
                "SELECT COALESCE(SUM(num_cartoes),0) v FROM oportunidades WHERE tenant_id=? AND etapa NOT IN ('fechado','perdido')", tid),
        }

        meta_row = conn.execute(
            "SELECT valor_meta, nome FROM metas WHERE tenant_id=? AND ativo=1 ORDER BY id DESC LIMIT 1", (tid,)
        ).fetchone()
        if meta_row:
            mr = dict(meta_row)
            stats.update({
                "meta_valor": mr.get("valor_meta") or 100000,
                "meta_nome": mr.get("nome") or "Meta principal",
                "faturado_90d": stats["receita_mes"],
            })
        else:
            stats.update({"meta_valor": 100000, "meta_nome": "Meta principal", "faturado_90d": 0})

        from datetime import datetime
        stats["mes_atual"] = datetime.now().strftime("%Y-%m")

        cadencias_hoje = qs(
            "SELECT c.id, c.empresa_nome, c.etapa, c.data_acao FROM cadencias c "
            "WHERE c.tenant_id=? AND DATE(c.data_acao)<=DATE('now') LIMIT 10", tid
        )
        stats["cadencias_hoje"] = cadencias_hoje

        ops_paradas = qs(
            "SELECT o.id, o.titulo, o.etapa, o.valor_estimado, e.nome empresa_nome "
            "FROM oportunidades o LEFT JOIN empresas e ON o.empresa_id=e.id "
            "WHERE o.tenant_id=? AND o.etapa NOT IN ('fechado','perdido') "
            "AND (o.dias_sem_contato IS NULL OR o.dias_sem_contato > 7) LIMIT 5", tid
        )
        stats["oportunidades_paradas"] = ops_paradas

    except Exception as e:
        print(f"[API/dashboard] {e}")
        stats = {"error": str(e)}

    return jsonify(stats)


# ── EMPRESAS ─────────────────────────────────────────────────────────────────

@api_bp.get("/empresas")
@login_required
def empresas_list():
    tid = session.get("tenant_id", 1)
    q = request.args.get("q", "")
    status = request.args.get("status", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    conn = database.get_connection()
    where = ["e.tenant_id=?"]
    params: list = [tid]
    if q:
        where.append("(e.nome LIKE ? OR e.cnpj LIKE ? OR e.cidade LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status:
        where.append("e.status=?")
        params.append(status)

    sql = f"""
        SELECT e.*, COUNT(DISTINCT o.id) num_oportunidades,
               COUNT(DISTINCT c.id) num_contatos
        FROM empresas e
        LEFT JOIN oportunidades o ON o.empresa_id=e.id AND o.etapa NOT IN ('fechado','perdido')
        LEFT JOIN contatos c ON c.empresa_id=e.id
        WHERE {' AND '.join(where)}
        GROUP BY e.id ORDER BY e.nome LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, params + [per_page, offset]).fetchall()
    total = (conn.execute(
        f"SELECT COUNT(*) c FROM empresas e WHERE {' AND '.join(where)}", params
    ).fetchone() or {"c": 0})["c"] or 0

    return jsonify(items=[dict(r) for r in rows], total=total, page=page, per_page=per_page)


@api_bp.get("/empresas/<int:eid>")
@login_required
def empresa_detail(eid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute("SELECT * FROM empresas WHERE id=? AND tenant_id=?", (eid, tid)).fetchone()
    if not row:
        return jsonify(error="Não encontrada"), 404
    empresa = dict(row)
    empresa["contatos"] = [dict(r) for r in conn.execute(
        "SELECT * FROM contatos WHERE empresa_id=? ORDER BY nome", (eid,)).fetchall()]
    empresa["oportunidades"] = [dict(r) for r in conn.execute(
        "SELECT * FROM oportunidades WHERE empresa_id=? ORDER BY criado_em DESC", (eid,)).fetchall()]
    return jsonify(empresa)


@api_bp.post("/empresas")
@login_required
def empresa_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    required = ["nome"]
    for f in required:
        if not data.get(f):
            return jsonify(error=f"Campo obrigatório: {f}"), 400
    conn = database.get_connection()
    # Unique fields must be NULL when empty (empty string violates UNIQUE across rows)
    cnpj_val = (data.get("cnpj") or "").strip() or None
    conn.execute(
        "INSERT INTO empresas (nome, cnpj, segmento, porte, status, telefone, email, cidade, estado, "
        "tipo_cartao, nome_private_label, num_funcionarios, valor_mensal, produtos_ativos, cliente_ativo, tenant_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["nome"], cnpj_val, data.get("segmento",""), data.get("porte",""),
         data.get("status","prospect"), data.get("telefone",""), data.get("email",""),
         data.get("cidade",""), data.get("estado",""),
         data.get("tipo_cartao",""), data.get("nome_private_label",""),
         data.get("num_funcionarios"), data.get("valor_mensal"),
         data.get("produtos_ativos",""), data.get("cliente_ativo", 0), tid)
    )
    conn.commit()
    eid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    row = conn.execute("SELECT * FROM empresas WHERE id=?", (eid,)).fetchone()
    return jsonify(dict(row)), 201


@api_bp.put("/empresas/<int:eid>")
@login_required
def empresa_update(eid):
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM empresas WHERE id=? AND tenant_id=?", (eid, tid)).fetchone():
        return jsonify(error="Não encontrada"), 404
    fields = ["nome","cnpj","segmento","porte","status","telefone","email","cidade","estado",
              "tipo_cartao","nome_private_label","num_funcionarios","valor_mensal","produtos_ativos","cliente_ativo"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify(error="Nenhum campo para atualizar"), 400
    # Empty CNPJ must be NULL (UNIQUE constraint)
    if "cnpj" in updates:
        updates["cnpj"] = (updates["cnpj"] or "").strip() or None
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE empresas SET {set_clause} WHERE id=? AND tenant_id=?",
                 list(updates.values()) + [eid, tid])
    conn.commit()
    row = conn.execute("SELECT * FROM empresas WHERE id=?", (eid,)).fetchone()
    return jsonify(dict(row))


@api_bp.delete("/empresas/<int:eid>")
@login_required
def empresa_delete(eid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM empresas WHERE id=? AND tenant_id=?", (eid, tid)).fetchone():
        return jsonify(error="Não encontrada"), 404
    conn.execute("DELETE FROM empresas WHERE id=? AND tenant_id=?", (eid, tid))
    conn.commit()
    return jsonify(ok=True)


# ── CONTATOS ─────────────────────────────────────────────────────────────────

@api_bp.get("/contatos")
@login_required
def contatos_list():
    tid = session.get("tenant_id", 1)
    q = request.args.get("q", "")
    empresa_id = request.args.get("empresa_id")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    conn = database.get_connection()
    where = ["c.tenant_id=?"]
    params: list = [tid]
    if q:
        where.append("(c.nome LIKE ? OR c.email LIKE ? OR c.cargo LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if empresa_id:
        where.append("c.empresa_id=?")
        params.append(empresa_id)

    sql = f"""SELECT c.*, e.nome empresa_nome FROM contatos c
              LEFT JOIN empresas e ON c.empresa_id=e.id
              WHERE {' AND '.join(where)} ORDER BY c.nome LIMIT ? OFFSET ?"""
    rows = conn.execute(sql, params + [per_page, offset]).fetchall()
    total = (conn.execute(
        f"SELECT COUNT(*) c FROM contatos c WHERE {' AND '.join(where)}", params
    ).fetchone() or {"c": 0})["c"] or 0
    return jsonify(items=[dict(r) for r in rows], total=total)


@api_bp.get("/contatos/<int:cid>")
@login_required
def contato_detail(cid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute(
        "SELECT c.*, e.nome empresa_nome FROM contatos c "
        "LEFT JOIN empresas e ON c.empresa_id=e.id WHERE c.id=? AND c.tenant_id=?", (cid, tid)
    ).fetchone()
    if not row:
        return jsonify(error="Não encontrado"), 404
    return jsonify(dict(row))


@api_bp.post("/contatos")
@login_required
def contato_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    if not data.get("nome"):
        return jsonify(error="Nome obrigatório"), 400
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO contatos (nome, cargo, email, telefone, empresa_id, tenant_id) VALUES (?,?,?,?,?,?)",
        (data["nome"], data.get("cargo",""), data.get("email",""),
         data.get("telefone",""), data.get("empresa_id"), tid)
    )
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    row = conn.execute("SELECT c.*, e.nome empresa_nome FROM contatos c LEFT JOIN empresas e ON c.empresa_id=e.id WHERE c.id=?", (cid,)).fetchone()
    return jsonify(dict(row)), 201


@api_bp.put("/contatos/<int:cid>")
@login_required
def contato_update(cid):
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM contatos WHERE id=? AND tenant_id=?", (cid, tid)).fetchone():
        return jsonify(error="Não encontrado"), 404
    fields = ["nome","cargo","email","telefone","empresa_id"]
    updates = {f: data[f] for f in fields if f in data}
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE contatos SET {set_clause} WHERE id=? AND tenant_id=?",
                 list(updates.values()) + [cid, tid])
    conn.commit()
    row = conn.execute("SELECT c.*, e.nome empresa_nome FROM contatos c LEFT JOIN empresas e ON c.empresa_id=e.id WHERE c.id=?", (cid,)).fetchone()
    return jsonify(dict(row))


@api_bp.delete("/contatos/<int:cid>")
@login_required
def contato_delete(cid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM contatos WHERE id=? AND tenant_id=?", (cid, tid)).fetchone():
        return jsonify(error="Não encontrado"), 404
    conn.execute("DELETE FROM contatos WHERE id=? AND tenant_id=?", (cid, tid))
    conn.commit()
    return jsonify(ok=True)


# ── OPORTUNIDADES ────────────────────────────────────────────────────────────

ETAPAS = ["prospect", "contato", "proposta", "negociacao", "fechado", "perdido"]

@api_bp.get("/oportunidades")
@login_required
def oportunidades_list():
    tid = session.get("tenant_id", 1)
    q = request.args.get("q", "")
    etapa = request.args.get("etapa", "")
    empresa_id = request.args.get("empresa_id")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 100))
    offset = (page - 1) * per_page

    conn = database.get_connection()
    where = ["o.tenant_id=?"]
    params: list = [tid]
    if q:
        where.append("(o.titulo LIKE ? OR e.nome LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if etapa:
        where.append("o.etapa=?")
        params.append(etapa)
    if empresa_id:
        where.append("o.empresa_id=?")
        params.append(empresa_id)

    sql = f"""SELECT o.*, e.nome empresa_nome FROM oportunidades o
              LEFT JOIN empresas e ON o.empresa_id=e.id
              WHERE {' AND '.join(where)} ORDER BY o.criado_em DESC LIMIT ? OFFSET ?"""
    rows = conn.execute(sql, params + [per_page, offset]).fetchall()
    total = (conn.execute(
        f"SELECT COUNT(*) c FROM oportunidades o LEFT JOIN empresas e ON o.empresa_id=e.id WHERE {' AND '.join(where)}", params
    ).fetchone() or {"c": 0})["c"] or 0
    return jsonify(items=[dict(r) for r in rows], total=total)


@api_bp.post("/oportunidades")
@login_required
def oportunidade_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    if not data.get("titulo"):
        return jsonify(error="Título obrigatório"), 400
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO oportunidades (titulo, empresa_id, etapa, valor_estimado, num_cartoes, responsavel, previsao_fechamento, notas, tenant_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (data["titulo"], data.get("empresa_id"), data.get("etapa","prospect"),
         data.get("valor_estimado",0), data.get("num_cartoes",0),
         data.get("responsavel",""), data.get("previsao_fechamento"),
         data.get("notas",""), tid)
    )
    conn.commit()
    oid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    row = conn.execute("SELECT o.*, e.nome empresa_nome FROM oportunidades o LEFT JOIN empresas e ON o.empresa_id=e.id WHERE o.id=?", (oid,)).fetchone()
    return jsonify(dict(row)), 201


@api_bp.put("/oportunidades/<int:oid>")
@login_required
def oportunidade_update(oid):
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM oportunidades WHERE id=? AND tenant_id=?", (oid, tid)).fetchone():
        return jsonify(error="Não encontrada"), 404
    fields = ["titulo","empresa_id","etapa","valor_estimado","num_cartoes","responsavel","previsao_fechamento","notas"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify(error="Nenhum campo para atualizar"), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE oportunidades SET {set_clause} WHERE id=? AND tenant_id=?",
                 list(updates.values()) + [oid, tid])
    conn.commit()
    row = conn.execute("SELECT o.*, e.nome empresa_nome FROM oportunidades o LEFT JOIN empresas e ON o.empresa_id=e.id WHERE o.id=?", (oid,)).fetchone()
    return jsonify(dict(row))


@api_bp.delete("/oportunidades/<int:oid>")
@login_required
def oportunidade_delete(oid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM oportunidades WHERE id=? AND tenant_id=?", (oid, tid)).fetchone():
        return jsonify(error="Não encontrada"), 404
    conn.execute("DELETE FROM oportunidades WHERE id=? AND tenant_id=?", (oid, tid))
    conn.commit()
    return jsonify(ok=True)


# ── PIPELINE (kanban view) ───────────────────────────────────────────────────

@api_bp.get("/pipeline")
@login_required
def pipeline():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    rows = conn.execute(
        "SELECT o.*, e.nome empresa_nome FROM oportunidades o "
        "LEFT JOIN empresas e ON o.empresa_id=e.id "
        "WHERE o.tenant_id=? AND o.etapa NOT IN ('perdido') ORDER BY o.criado_em DESC", (tid,)
    ).fetchall()
    by_etapa: dict = {e: [] for e in ETAPAS if e != "perdido"}
    for r in rows:
        etapa = r["etapa"]
        if etapa in by_etapa:
            by_etapa[etapa].append(dict(r))
    return jsonify(by_etapa)


# ── ATIVIDADES ───────────────────────────────────────────────────────────────

@api_bp.get("/atividades")
@login_required
def atividades_list():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    rows = conn.execute(
        "SELECT a.*, e.nome empresa_nome, o.titulo op_titulo FROM atividades a "
        "LEFT JOIN empresas e ON a.empresa_id=e.id "
        "LEFT JOIN oportunidades o ON a.oportunidade_id=o.id "
        "WHERE a.tenant_id=? ORDER BY a.data ASC LIMIT 100", (tid,)
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@api_bp.post("/atividades")
@login_required
def atividade_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json()
    if not data.get("tipo"):
        return jsonify(error="Tipo obrigatório"), 400
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO atividades (tipo, descricao, data, empresa_id, oportunidade_id, tenant_id) "
        "VALUES (?,?,?,?,?,?)",
        (data["tipo"], data.get("descricao",""), data.get("data"),
         data.get("empresa_id"), data.get("oportunidade_id"), tid)
    )
    conn.commit()
    aid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    row = conn.execute("SELECT * FROM atividades WHERE id=?", (aid,)).fetchone()
    return jsonify(dict(row)), 201


# ── CADÊNCIAS ────────────────────────────────────────────────────────────────

@api_bp.get("/cadencias")
@login_required
def cadencias_list():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    rows = conn.execute(
        "SELECT * FROM cadencias WHERE tenant_id=? ORDER BY criado_em DESC LIMIT 100", (tid,)
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


# ── USUÁRIOS ─────────────────────────────────────────────────────────────────

@api_bp.get("/usuarios")
@login_required
def usuarios_list():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    rows = conn.execute(
        "SELECT id, nome, email, usuario, perfil, ativo, criado_em FROM usuarios WHERE tenant_id=? ORDER BY nome", (tid,)
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@api_bp.post("/usuarios/convidar")
@require_perfil("admin", "super_admin")
def usuario_convidar():
    """Cria usuário desativado + gera token de convite + envia email com link."""
    import secrets as _sec
    from datetime import datetime, timedelta
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip().lower()
    usuario_str = (data.get("usuario") or "").strip().lower()
    perfil = (data.get("perfil") or "vendedor").strip()

    if not all([nome, email, usuario_str]):
        return jsonify(error="Campos obrigatórios: nome, email, usuario"), 400
    if perfil not in ("admin", "gerente", "vendedor", "visualizador"):
        return jsonify(error="Perfil inválido"), 400

    conn = database.get_connection()
    if conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone():
        return jsonify(error=f"E-mail {email} já cadastrado"), 400
    if conn.execute("SELECT id FROM usuarios WHERE usuario=?", (usuario_str,)).fetchone():
        return jsonify(error=f"Usuário {usuario_str} já em uso"), 400

    token = _sec.token_urlsafe(32)
    expira = (datetime.now() + timedelta(days=7)).isoformat(sep=" ", timespec="seconds")
    # Placeholder senha_hash — obrigatória no schema mas invalidada pelo convite
    ph = "!" + _sec.token_hex(20)
    conn.execute(
        "INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, ativo, tenant_id, convite_token, convite_expira) "
        "VALUES (?,?,?,?,?, 0, ?,?,?)",
        (nome, email, usuario_str, ph, perfil, tid, token, expira)
    )
    conn.commit()
    uid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    import os
    base = os.environ.get("APP_URL", "https://krylo-crm.vercel.app").rstrip("/")
    link = f"{base}/aceitar-convite?token={token}"
    try:
        from models.cadencia import enviar_email_brevo
        corpo = (
            f"<p>Olá {nome},</p>"
            f"<p>Você foi convidado(a) para o Krylo CRM.</p>"
            f"<p><a href=\"{link}\" style=\"background:#4F46E5;color:#fff;padding:10px 18px;"
            f"border-radius:8px;text-decoration:none;\">Aceitar convite</a></p>"
            f"<p>Link válido por 7 dias. Se não funcionar, cole no navegador:<br>{link}</p>"
        )
        r = enviar_email_brevo(
            destinatario_email=email,
            destinatario_nome=nome,
            assunto=f"Convite para Krylo CRM",
            corpo=corpo,
            tenant_id=tid,
        )
        email_status = r.get("status", "unknown")
    except Exception as e:
        current_app.logger.exception("send invite email failed")
        email_status = "erro"

    audit.log("usuario.convidado", resource="usuario", resource_id=uid,
              metadata={"email": email, "perfil": perfil, "email_status": email_status})
    return jsonify(ok=True, user_id=uid, link=link, email_status=email_status), 201


@api_bp.get("/convite/<token>")
def convite_verify(token):
    """Público — valida token de convite; retorna user pra frontend mostrar form."""
    from datetime import datetime
    conn = database.get_connection()
    row = conn.execute(
        "SELECT id, nome, email, usuario, perfil, convite_expira, convite_aceito_em "
        "FROM usuarios WHERE convite_token=?", (token,)
    ).fetchone()
    if not row:
        return jsonify(error="Convite inválido ou já usado"), 404
    r = dict(row)
    if r.get("convite_aceito_em"):
        return jsonify(error="Convite já foi aceito. Faça login."), 400
    try:
        if datetime.fromisoformat(r["convite_expira"]) < datetime.now():
            return jsonify(error="Convite expirado. Peça um novo."), 400
    except Exception:
        pass
    return jsonify(nome=r["nome"], email=r["email"], usuario=r["usuario"], perfil=r["perfil"])


@api_bp.post("/convite/<token>/aceitar")
def convite_accept(token):
    """Público — usuário define senha própria + ativa a conta."""
    import bcrypt as _bc
    from datetime import datetime
    data = request.get_json() or {}
    senha = data.get("senha") or ""
    if len(senha) < 8:
        return jsonify(error="Senha deve ter pelo menos 8 caracteres"), 400

    conn = database.get_connection()
    row = conn.execute(
        "SELECT id, convite_expira, convite_aceito_em FROM usuarios WHERE convite_token=?",
        (token,)
    ).fetchone()
    if not row:
        return jsonify(error="Convite inválido"), 404
    r = dict(row)
    if r.get("convite_aceito_em"):
        return jsonify(error="Convite já foi aceito"), 400
    try:
        if datetime.fromisoformat(r["convite_expira"]) < datetime.now():
            return jsonify(error="Convite expirado"), 400
    except Exception:
        pass

    senha_hash = _bc.hashpw(senha.encode(), _bc.gensalt()).decode()
    conn.execute(
        "UPDATE usuarios SET senha_hash=?, ativo=1, convite_aceito_em=?, "
        "convite_token=NULL, tentativas_login=0, bloqueado_ate=NULL WHERE id=?",
        (senha_hash, datetime.now().isoformat(sep=" ", timespec="seconds"), r["id"])
    )
    conn.commit()
    audit.log("usuario.convite_aceito", resource="usuario", resource_id=r["id"])
    return jsonify(ok=True, message="Conta ativada. Faça login com sua nova senha.")


@api_bp.post("/usuarios")
@require_perfil("admin", "super_admin")
def usuario_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    required = ["nome", "email", "usuario", "senha", "perfil"]
    for f in required:
        if not data.get(f):
            return jsonify(error=f"Campo obrigatório: {f}"), 400
    if data["perfil"] not in ("admin", "gerente", "vendedor", "visualizador"):
        return jsonify(error="Perfil inválido"), 400

    import bcrypt
    senha_hash = bcrypt.hashpw(data["senha"].encode(), bcrypt.gensalt()).decode()
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, ativo, tenant_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (data["nome"], data["email"], data["usuario"], senha_hash,
             data["perfil"], 1 if data.get("ativo", 1) else 0, tid)
        )
        conn.commit()
        uid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        row = conn.execute(
            "SELECT id, nome, email, usuario, perfil, ativo FROM usuarios WHERE id=?", (uid,)
        ).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        msg = str(e)
        if "UNIQUE" in msg.upper() or "unique" in msg:
            return jsonify(error="Usuário ou e-mail já existe"), 409
        return jsonify(error=msg), 500


@api_bp.put("/usuarios/<int:uid>")
@require_perfil("admin", "super_admin")
def usuario_update(uid):
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM usuarios WHERE id=? AND tenant_id=?", (uid, tid)).fetchone():
        return jsonify(error="Não encontrado"), 404

    fields = ["nome", "email", "usuario", "perfil", "ativo"]
    updates = {f: data[f] for f in fields if f in data}

    # Senha opcional
    if data.get("senha"):
        import bcrypt
        updates["senha_hash"] = bcrypt.hashpw(data["senha"].encode(), bcrypt.gensalt()).decode()

    if not updates:
        return jsonify(error="Nada para atualizar"), 400

    set_clause = ", ".join(f"{k}=?" for k in updates)
    try:
        conn.execute(f"UPDATE usuarios SET {set_clause} WHERE id=? AND tenant_id=?",
                     list(updates.values()) + [uid, tid])
        conn.commit()
        row = conn.execute(
            "SELECT id, nome, email, usuario, perfil, ativo FROM usuarios WHERE id=?", (uid,)
        ).fetchone()
        return jsonify(dict(row))
    except Exception as e:
        msg = str(e)
        if "UNIQUE" in msg.upper():
            return jsonify(error="Usuário ou e-mail já existe"), 409
        return jsonify(error=msg), 500


@api_bp.delete("/usuarios/<int:uid>")
@require_perfil("admin", "super_admin")
def usuario_delete(uid):
    tid = session.get("tenant_id", 1)
    if uid == getattr(current_user, "id", None):
        return jsonify(error="Não é possível excluir o próprio usuário"), 400
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM usuarios WHERE id=? AND tenant_id=?", (uid, tid)).fetchone():
        return jsonify(error="Não encontrado"), 404
    # Soft delete via ativo=0
    conn.execute("UPDATE usuarios SET ativo=0 WHERE id=? AND tenant_id=?", (uid, tid))
    conn.commit()
    return jsonify(ok=True)


# ── PROFILE / TENANT ─────────────────────────────────────────────────────────

@api_bp.put("/me")
@login_required
def me_update():
    """Usuário atualiza próprio perfil."""
    data = request.get_json() or {}
    uid = current_user.id
    conn = database.get_connection()

    fields = ["nome", "email"]
    updates = {f: data[f] for f in fields if f in data}

    if data.get("nova_senha"):
        if not data.get("senha_atual"):
            return jsonify(error="Senha atual obrigatória"), 400
        import bcrypt
        row = conn.execute("SELECT senha_hash FROM usuarios WHERE id=?", (uid,)).fetchone()
        if not bcrypt.checkpw(data["senha_atual"].encode(), dict(row)["senha_hash"].encode()):
            return jsonify(error="Senha atual incorreta"), 401
        updates["senha_hash"] = bcrypt.hashpw(data["nova_senha"].encode(), bcrypt.gensalt()).decode()

    if not updates:
        return jsonify(error="Nada para atualizar"), 400

    set_clause = ", ".join(f"{k}=?" for k in updates)
    try:
        conn.execute(f"UPDATE usuarios SET {set_clause} WHERE id=?",
                     list(updates.values()) + [uid])
        conn.commit()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500


@api_bp.get("/tenant")
@login_required
def tenant_get():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    if not row:
        return jsonify(error="Tenant não encontrado"), 404
    return jsonify(dict(row))


@api_bp.put("/tenant")
@login_required
def tenant_update():
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    conn = database.get_connection()
    fields = ["nome_empresa", "nome_plataforma", "cor_primaria", "cor_secundaria", "logo_url"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return jsonify(error="Nada para atualizar"), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE tenants SET {set_clause} WHERE id=?",
                 list(updates.values()) + [tid])
    conn.commit()
    row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    return jsonify(dict(row))


# ── INTEGRAÇÕES por tenant (Brevo + WhatsApp) ────────────────────────────────

INTEG_FIELDS = [
    "brevo_api_key", "brevo_sender_email", "brevo_sender_nome",
    "whatsapp_provider", "whatsapp_api_key", "whatsapp_instance_id", "whatsapp_sender_numero",
]

WHATSAPP_PROVIDERS = ["", "zapi", "meta_cloud", "twilio", "evolution", "360dialog"]


def _mask(v):
    if not v: return None
    s = str(v)
    if len(s) < 8: return "•" * len(s)
    return s[:4] + "•" * (len(s) - 8) + s[-4:]


@api_bp.get("/integracoes")
@login_required
def integracoes_get():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute("SELECT * FROM tenant_config WHERE tenant_id=?", (tid,)).fetchone()
    d = dict(row) if row else {}
    out = {}
    for f in INTEG_FIELDS:
        v = d.get(f)
        # Mascara credenciais no retorno; frontend recebe preview mas nunca a key real
        if f in ("brevo_api_key", "whatsapp_api_key", "whatsapp_instance_id"):
            out[f] = _mask(v)
            out[f + "_configured"] = bool(v)
        else:
            out[f] = v
    return jsonify(out)


@api_bp.put("/integracoes")
@login_required
def integracoes_update():
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    updates = {}
    for f in INTEG_FIELDS:
        if f in data:
            v = (data[f] or "").strip()
            # Preserva credencial existente se frontend enviar string mascarada (contém •)
            if f in ("brevo_api_key", "whatsapp_api_key", "whatsapp_instance_id") and "•" in v:
                continue
            updates[f] = v or None
    if updates.get("whatsapp_provider") and updates["whatsapp_provider"] not in WHATSAPP_PROVIDERS:
        return jsonify(error=f"Provider inválido. Use um de: {', '.join(WHATSAPP_PROVIDERS[1:])}"), 400
    if not updates:
        return jsonify(error="Nada para atualizar"), 400

    conn = database.get_connection()
    # Garante linha em tenant_config
    conn.execute("INSERT OR IGNORE INTO tenant_config (tenant_id) VALUES (?)", (tid,))
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE tenant_config SET {set_clause} WHERE tenant_id=?",
                 list(updates.values()) + [tid])
    conn.commit()
    return jsonify(ok=True, message="Integrações salvas.")


@api_bp.get("/integracoes/status")
@login_required
def integracoes_status():
    """Status das credenciais globais (env vars) + preview mascarado."""
    import os
    def _preview(v: str) -> str | None:
        if not v: return None
        if len(v) <= 8: return "•" * len(v)
        return v[:4] + "•••" + v[-4:]

    def _card(name: str, servico: str) -> dict:
        v = os.environ.get(name, "")
        return {"configurada": bool(v), "servico": servico, "preview": _preview(v)}

    return jsonify(
        anthropic=_card("ANTHROPIC_API_KEY", "IA Claude (chat + geração de emails)"),
        brevo=_card("BREVO_API_KEY", "Envio de emails transacionais"),
        cron_token=_card("CRON_TOKEN", "Autenticação do scheduler"),
        brevo_webhook=_card("BREVO_WEBHOOK_SECRET", "Verificação de webhooks Brevo"),
        whatsapp=_card("KRYLO_WHATSAPP", "Número remetente (E.164)"),
        email_remetente=_card("EMAIL_ONBOARDING", "Endereço de remetente padrão"),
    )


@api_bp.post("/integracoes/testar/email")
@login_required
def integracoes_testar_email():
    """Envia email de teste para o usuário logado."""
    import os
    dest = getattr(current_user, "email", None)
    if not dest:
        return jsonify(error="Usuário sem email cadastrado."), 400
    tid = session.get("tenant_id", 1)
    try:
        from models.cadencia import enviar_email_brevo
        r = enviar_email_brevo(
            destinatario_email=dest,
            destinatario_nome=getattr(current_user, "nome", "") or "Usuário",
            assunto="Teste de integração Krylo",
            corpo="Este é um email de teste enviado pelo Krylo CRM.\n\nSe você recebeu, a integração com Brevo está funcionando.",
            tenant_id=tid,
        )
        if r.get("status") == "enviado":
            return jsonify(ok=True, destinatario=dest, message_id=r.get("id"))
        return jsonify(ok=False, error=f"Falhou: {r.get('status')}", destinatario=dest), 400
    except Exception as e:
        current_app.logger.exception("email test failed")
        return jsonify(error=str(e)), 500


@api_bp.post("/integracoes/testar/ia")
@login_required
def integracoes_testar_ia():
    """Ping mínimo pra Claude."""
    try:
        import models.ia_config as ia_mod
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        resposta = ia_mod.chat_com_ia(conn, "Responda apenas: OK", [], "", tid)
        return jsonify(ok=True, resposta=(resposta or "")[:100])
    except Exception as e:
        current_app.logger.exception("IA test failed")
        return jsonify(error=str(e)), 500


@api_bp.post("/integracoes/brevo/testar")
@login_required
def integracoes_brevo_testar():
    """Valida credencial Brevo consultando /v3/account."""
    tid = session.get("tenant_id", 1)
    import os, requests
    conn = database.get_connection()
    row = conn.execute("SELECT brevo_api_key FROM tenant_config WHERE tenant_id=?", (tid,)).fetchone()
    key = (dict(row).get("brevo_api_key") if row else None) or os.environ.get("BREVO_API_KEY", "")
    if not key:
        return jsonify(ok=False, error="Nenhuma chave Brevo configurada."), 400
    try:
        r = requests.get("https://api.brevo.com/v3/account", headers={"api-key": key}, timeout=10)
        if r.status_code != 200:
            return jsonify(ok=False, error=f"Brevo respondeu {r.status_code}: {r.text[:200]}"), 400
        acc = r.json()
        return jsonify(ok=True, email=acc.get("email"), plano=acc.get("plan", [{}])[0].get("type"))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


# ── IA ───────────────────────────────────────────────────────────────────────

def _build_crm_snapshot(conn, tid: int) -> str:
    """Live snapshot of the tenant's CRM state, injected into the IA system prompt."""
    def scalar(sql, *params):
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        return list(dict(row).values())[0] or 0

    stats = {
        "empresas_total":     scalar("SELECT COUNT(*) c FROM empresas WHERE tenant_id=?", tid),
        "empresas_clientes":  scalar("SELECT COUNT(*) c FROM empresas WHERE tenant_id=? AND status='cliente'", tid),
        "empresas_prospects": scalar("SELECT COUNT(*) c FROM empresas WHERE tenant_id=? AND status='prospect'", tid),
        "contatos":           scalar("SELECT COUNT(*) c FROM contatos WHERE tenant_id=?", tid),
        "oportunidades_ativas": scalar(
            "SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=? AND etapa NOT IN ('fechado','perdido','fechado_ganho','fechado_perdido')", tid),
        "pipeline_valor": scalar(
            "SELECT COALESCE(SUM(valor_estimado),0) v FROM oportunidades WHERE tenant_id=? AND etapa NOT IN ('fechado','perdido','fechado_ganho','fechado_perdido')", tid),
        "cadencias_ativas": scalar(
            "SELECT COUNT(*) c FROM cadencias WHERE tenant_id=? AND status='pendente'", tid),
    }
    return (
        "SNAPSHOT DO CRM (dados reais do tenant, use como fonte de verdade):\n"
        f"- Empresas cadastradas: {stats['empresas_total']} "
        f"(clientes: {stats['empresas_clientes']}, prospects: {stats['empresas_prospects']})\n"
        f"- Contatos: {stats['contatos']}\n"
        f"- Oportunidades ativas: {stats['oportunidades_ativas']} "
        f"(valor total no pipeline: R$ {stats['pipeline_valor']:,.2f})\n"
        f"- Cadências pendentes: {stats['cadencias_ativas']}\n"
    )


@api_bp.post("/ia/chat")
@login_required
def api_ia_chat():
    """Wrapper para /ia/chat fora do CSRF."""
    try:
        import models.ia_config as ia_mod
        body = request.get_json() or {}
        mensagem = (body.get("mensagem") or "").strip()
        historico = body.get("historico") or []
        contexto_extra = (body.get("contexto") or "").strip()
        if not mensagem:
            return jsonify(error="Mensagem vazia"), 400
        conn = database.get_connection()
        tid = session.get("tenant_id", 1)
        snapshot = _build_crm_snapshot(conn, tid)
        contexto = snapshot + ("\n\n" + contexto_extra if contexto_extra else "")
        resposta = ia_mod.chat_com_ia(conn, mensagem, historico, contexto, tid)
        return jsonify(resposta=resposta)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify(error=str(e)), 500


# ── SIDEBAR COUNTS ───────────────────────────────────────────────────────────

@api_bp.get("/sidebar/counts")
@login_required
def sidebar_counts():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    def c(sql, *p):
        r = conn.execute(sql, p).fetchone()
        return (dict(r) or {}).get("c", 0) or 0
    return jsonify({
        "fila_whatsapp": c(
            "SELECT COUNT(*) c FROM cadencias WHERE tenant_id=? AND canal_whatsapp=1 "
            "AND (whatsapp_aprovado_em IS NULL AND (whatsapp_status IS NULL OR whatsapp_status<>'rejeitado'))", tid),
        "cadencias_hoje": c(
            "SELECT COUNT(*) c FROM cadencias WHERE tenant_id=? AND DATE(data_acao)<=DATE('now')", tid),
        "atividades_pendentes": c(
            "SELECT COUNT(*) c FROM atividades WHERE tenant_id=? AND DATE(data)<=DATE('now')", tid),
    })


# ── SDR ──────────────────────────────────────────────────────────────────────

# ── LEADS IMPORT ─────────────────────────────────────────────────────────────

@api_bp.post("/leads/importar/preview")
@login_required
def leads_preview():
    """Preview de mapeamento de CSV/XLSX."""
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(error="Nenhum arquivo enviado."), 400

    # Importa funções helper do app.py
    from app import _EXTS_ACEITAS, _ler_arquivo, _auto_mapear
    ext = arquivo.filename.lower().rsplit(".", 1)[-1] if "." in arquivo.filename else ""
    if ext not in _EXTS_ACEITAS:
        return jsonify(error=f"Formato .{ext} não suportado. Use .csv, .xlsx ou .xls."), 400
    try:
        raw = arquivo.stream.read()
        colunas, linhas = _ler_arquivo(raw, arquivo.filename)
        mapa = _auto_mapear(colunas)
        return jsonify(colunas=colunas, preview=linhas[:10], mapeamento_sugerido=mapa)
    except Exception as e:
        return jsonify(error=str(e)), 500


@api_bp.post("/leads/importar/confirmar")
@login_required
def leads_confirmar():
    """Importa leads do arquivo com mapeamento informado."""
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify(error="Arquivo não encontrado."), 400
    from app import _ler_arquivo, _processar_linhas
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
        tid = session.get("tenant_id", 1)
        importados, ignorados = _processar_linhas(linhas, mapa, tenant_id=tid)
        return jsonify(
            ok=True, importados=importados, ignorados=ignorados,
            mensagem=f"{importados} lead(s) importado(s)." + (f" {ignorados} ignorado(s)." if ignorados else "")
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


# ── CADÊNCIAS ────────────────────────────────────────────────────────────────

@api_bp.post("/cadencias/iniciar")
@login_required
def cadencia_iniciar():
    """Cria nova cadência para uma empresa."""
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    empresa_id = data.get("empresa_id")
    if not empresa_id:
        return jsonify(error="empresa_id obrigatório"), 400

    conn = database.get_connection()
    emp = conn.execute("SELECT * FROM empresas WHERE id=? AND tenant_id=?", (empresa_id, tid)).fetchone()
    if not emp:
        return jsonify(error="Empresa não encontrada"), 404
    emp_dict = dict(emp)

    try:
        conn.execute(
            "INSERT INTO cadencias (empresa_id, empresa_nome, contato_whatsapp, contato_email, "
            "etapa, data_acao, status, canal_email, canal_whatsapp, tenant_id) "
            "VALUES (?,?,?,?,?,DATE('now'),?,?,?,?)",
            (
                empresa_id,
                emp_dict["nome"],
                data.get("whatsapp", emp_dict.get("telefone", "")),
                data.get("email", emp_dict.get("email", "")),
                data.get("etapa", "D0"),
                "pendente",
                1 if data.get("canal_email", True) else 0,
                1 if data.get("canal_whatsapp", True) else 0,
                tid,
            )
        )
        conn.commit()
        cid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        return jsonify(ok=True, id=cid, mensagem="Cadência iniciada"), 201
    except Exception as e:
        return jsonify(error=str(e)), 500


@api_bp.post("/cadencias/<int:cid>/concluir")
@login_required
def cadencia_concluir(cid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    conn.execute("UPDATE cadencias SET status='concluida' WHERE id=? AND tenant_id=?", (cid, tid))
    conn.commit()
    return jsonify(ok=True)


@api_bp.post("/cadencias/<int:cid>/cancelar")
@login_required
def cadencia_cancelar(cid):
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    conn.execute("UPDATE cadencias SET status='cancelada' WHERE id=? AND tenant_id=?", (cid, tid))
    conn.commit()
    return jsonify(ok=True)


# ── WHATSAPP APPROVAL ────────────────────────────────────────────────────────

@api_bp.post("/whatsapp/<int:cid>/aprovar")
@login_required
def whatsapp_aprovar(cid):
    """Aprova mensagem WhatsApp da fila de aprovação."""
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute("SELECT id FROM cadencias WHERE id=? AND tenant_id=?", (cid, tid)).fetchone()
    if not row:
        return jsonify(error="Não encontrada"), 404
    conn.execute(
        "UPDATE cadencias SET whatsapp_status='aprovado', whatsapp_aprovado_em=datetime('now') "
        "WHERE id=? AND tenant_id=?", (cid, tid)
    )
    conn.commit()
    return jsonify(ok=True)


@api_bp.post("/whatsapp/<int:cid>/rejeitar")
@login_required
def whatsapp_rejeitar(cid):
    """Rejeita mensagem WhatsApp."""
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    row = conn.execute("SELECT id FROM cadencias WHERE id=? AND tenant_id=?", (cid, tid)).fetchone()
    if not row:
        return jsonify(error="Não encontrada"), 404
    conn.execute(
        "UPDATE cadencias SET whatsapp_status='rejeitado' WHERE id=? AND tenant_id=?", (cid, tid)
    )
    conn.commit()
    return jsonify(ok=True)


# ── METAS ────────────────────────────────────────────────────────────────────

@api_bp.get("/metas")
@login_required
def metas_list():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    rows = conn.execute(
        "SELECT * FROM metas WHERE tenant_id=? ORDER BY ativo DESC, id DESC", (tid,)
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@api_bp.post("/metas")
@login_required
def meta_create():
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    if not data.get("nome") or not data.get("valor_meta"):
        return jsonify(error="nome e valor_meta obrigatórios"), 400
    conn = database.get_connection()
    # Desativa metas atuais se esta é a nova ativa
    if data.get("ativo", 1):
        conn.execute("UPDATE metas SET ativo=0 WHERE tenant_id=?", (tid,))
    conn.execute(
        "INSERT INTO metas (tenant_id, nome, valor_meta, data_inicio, data_fim, tipo, ativo) "
        "VALUES (?,?,?,?,?,?,?)",
        (tid, data["nome"], float(data["valor_meta"]),
         data.get("data_inicio"), data.get("data_fim"),
         data.get("tipo", "receita"), 1 if data.get("ativo", 1) else 0)
    )
    conn.commit()
    mid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    return jsonify(ok=True, id=mid), 201


@api_bp.put("/metas/<int:mid>")
@login_required
def meta_update(mid):
    tid = session.get("tenant_id", 1)
    data = request.get_json() or {}
    conn = database.get_connection()
    if not conn.execute("SELECT id FROM metas WHERE id=? AND tenant_id=?", (mid, tid)).fetchone():
        return jsonify(error="Não encontrada"), 404
    if data.get("ativo"):
        conn.execute("UPDATE metas SET ativo=0 WHERE tenant_id=? AND id<>?", (tid, mid))
    fields = ["nome", "valor_meta", "data_inicio", "data_fim", "tipo", "ativo"]
    updates = {f: data[f] for f in fields if f in data}
    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE metas SET {set_clause} WHERE id=? AND tenant_id=?",
                     list(updates.values()) + [mid, tid])
        conn.commit()
    return jsonify(ok=True)


# ── BULK OPERATIONS ──────────────────────────────────────────────────────────

@api_bp.post("/empresas/excluir-lote")
@login_required
def empresas_excluir_lote():
    tid = session.get("tenant_id", 1)
    ids = (request.get_json() or {}).get("ids", [])
    if not ids:
        return jsonify(error="ids obrigatórios"), 400
    conn = database.get_connection()
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"DELETE FROM empresas WHERE id IN ({placeholders}) AND tenant_id=?",
        list(ids) + [tid]
    )
    conn.commit()
    return jsonify(ok=True, excluidos=len(ids))


@api_bp.post("/oportunidades/excluir-lote")
@login_required
def oportunidades_excluir_lote():
    tid = session.get("tenant_id", 1)
    ids = (request.get_json() or {}).get("ids", [])
    if not ids:
        return jsonify(error="ids obrigatórios"), 400
    conn = database.get_connection()
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"DELETE FROM oportunidades WHERE id IN ({placeholders}) AND tenant_id=?",
        list(ids) + [tid]
    )
    conn.commit()
    return jsonify(ok=True, excluidos=len(ids))


@api_bp.post("/sdr/rodar")
@login_required
def sdr_rodar():
    """Dispara a prospecção autônoma SDR em background."""
    tid = session.get("tenant_id", 1)
    try:
        import threading
        from models.prospeccao_autonoma import rodar_prospeccao_autonoma
        conn = database.get_connection()
        def _run():
            rodar_prospeccao_autonoma(conn, config_override={"tenant_id": tid})
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return jsonify(status="iniciado", mensagem="SDR iniciado em background")
    except Exception as e:
        return jsonify(error=str(e)), 500


@api_bp.get("/sdr/stats")
@login_required
def sdr_stats():
    tid = session.get("tenant_id", 1)
    conn = database.get_connection()
    def count(sql, *p):
        row = conn.execute(sql, p).fetchone()
        return (dict(row) or {}).get("c", 0) or 0
    return jsonify({
        "leads_com_cadencia": count("SELECT COUNT(*) c FROM prospeccao WHERE tenant_id=?", tid),
        "ecosistema_leads": count("SELECT COUNT(*) c FROM prospeccao WHERE tenant_id=?", tid),
        "cadencias_criadas": count("SELECT COUNT(*) c FROM cadencias WHERE tenant_id=?", tid),
        "prospectado": count("SELECT COUNT(*) c FROM prospeccao WHERE tenant_id=?", tid),
        "email_enviado": count("SELECT COUNT(*) c FROM cadencias WHERE tenant_id=? AND canal_email=1", tid),
        "whatsapp_enviado": count("SELECT COUNT(*) c FROM cadencias WHERE tenant_id=? AND canal_whatsapp=1", tid),
        "reuniao": count("SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=? AND etapa='negociacao'", tid),
        "fechou": count("SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=? AND etapa='fechado'", tid),
    })




# ── ADMIN KRYLO (super_admin apenas) ─────────────────────────────────────────

@api_bp.get("/admin/tenants")
@require_perfil("super_admin")
def admin_tenants_list():
    """Lista todos os tenants com contagens rápidas."""
    conn = database.get_connection()
    rows = conn.execute("""
        SELECT t.*,
               (SELECT COUNT(*) FROM usuarios  WHERE tenant_id=t.id) AS usuarios_count,
               (SELECT COUNT(*) FROM empresas  WHERE tenant_id=t.id) AS empresas_count,
               (SELECT COUNT(*) FROM oportunidades WHERE tenant_id=t.id AND etapa NOT IN ('fechado','perdido','fechado_ganho','fechado_perdido')) AS oport_ativas
        FROM tenants t
        ORDER BY t.id DESC
    """).fetchall()
    return jsonify(items=[dict(r) for r in rows])


@api_bp.get("/admin/tenants/<int:tid>")
@require_perfil("super_admin")
def admin_tenant_get(tid):
    conn = database.get_connection()
    t = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    if not t:
        return jsonify(error="Tenant não encontrado"), 404
    usuarios = conn.execute(
        "SELECT id, nome, email, usuario, perfil, ativo, criado_em FROM usuarios WHERE tenant_id=? ORDER BY id",
        (tid,)
    ).fetchall()
    stats = {
        "empresas":      conn.execute("SELECT COUNT(*) c FROM empresas WHERE tenant_id=?", (tid,)).fetchone()[0],
        "contatos":      conn.execute("SELECT COUNT(*) c FROM contatos WHERE tenant_id=?", (tid,)).fetchone()[0],
        "oportunidades": conn.execute("SELECT COUNT(*) c FROM oportunidades WHERE tenant_id=?", (tid,)).fetchone()[0],
        "cadencias":     conn.execute("SELECT COUNT(*) c FROM cadencias WHERE tenant_id=?", (tid,)).fetchone()[0],
    }
    return jsonify(tenant=dict(t), usuarios=[dict(u) for u in usuarios], stats=stats)


@api_bp.post("/admin/tenants")
@require_perfil("super_admin")
def admin_tenant_create():
    """Cria tenant + primeiro admin do cliente numa call."""
    data = request.get_json() or {}
    nome_empresa = (data.get("nome_empresa") or "").strip()
    slug = (data.get("slug") or "").strip().lower()
    plano = (data.get("plano") or "starter").strip()
    admin_nome = (data.get("admin_nome") or "").strip()
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_usuario = (data.get("admin_usuario") or "").strip().lower()
    admin_senha = data.get("admin_senha") or ""

    if not all([nome_empresa, slug, admin_nome, admin_email, admin_usuario, admin_senha]):
        return jsonify(error="Campos obrigatórios: nome_empresa, slug, admin_{nome,email,usuario,senha}"), 400
    if len(admin_senha) < 8:
        return jsonify(error="Senha do admin deve ter pelo menos 8 caracteres"), 400

    import bcrypt as _bc
    conn = database.get_connection()
    # Verifica unicidade slug
    if conn.execute("SELECT id FROM tenants WHERE slug=?", (slug,)).fetchone():
        return jsonify(error=f"Slug '{slug}' já em uso"), 400
    if conn.execute("SELECT id FROM usuarios WHERE email=?", (admin_email,)).fetchone():
        return jsonify(error=f"E-mail '{admin_email}' já cadastrado"), 400
    if conn.execute("SELECT id FROM usuarios WHERE usuario=?", (admin_usuario,)).fetchone():
        return jsonify(error=f"Usuário '{admin_usuario}' já em uso"), 400

    conn.execute(
        "INSERT INTO tenants (slug, nome_empresa, plano, ativo) VALUES (?,?,?,1)",
        (slug, nome_empresa, plano)
    )
    conn.commit()
    tid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    senha_hash = _bc.hashpw(admin_senha.encode(), _bc.gensalt()).decode()
    conn.execute(
        "INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, ativo, tenant_id) "
        "VALUES (?,?,?,?, 'admin', 1, ?)",
        (admin_nome, admin_email, admin_usuario, senha_hash, tid)
    )
    conn.commit()
    audit.log("admin.tenant_create", resource="tenant", resource_id=tid,
              metadata={"nome_empresa": nome_empresa, "slug": slug, "plano": plano, "admin_email": admin_email})
    row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    return jsonify(tenant=dict(row)), 201


@api_bp.put("/admin/tenants/<int:tid>/suspender")
@require_perfil("super_admin")
def admin_tenant_suspender(tid):
    """Suspende/reativa acesso do tenant."""
    data = request.get_json() or {}
    ativo = 1 if data.get("ativo", False) else 0
    conn = database.get_connection()
    conn.execute("UPDATE tenants SET ativo=? WHERE id=?", (ativo, tid))
    # Também desativa/reativa todos usuários do tenant
    conn.execute("UPDATE usuarios SET ativo=? WHERE tenant_id=?", (ativo, tid))
    conn.commit()
    audit.log("admin.tenant_" + ("reativar" if ativo else "suspender"),
              resource="tenant", resource_id=tid)
    row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    return jsonify(dict(row) if row else {"error": "não encontrado"})


@api_bp.get("/admin/audit")
@require_perfil("super_admin", "admin")
def admin_audit():
    """Consulta audit log (admin do tenant vê só o próprio; super_admin vê tudo se sem filtro)."""
    perfil = getattr(current_user, "perfil", "")
    tid_filtro = request.args.get("tenant_id", type=int)
    action = request.args.get("action")
    limit = min(int(request.args.get("limit", 100) or 100), 500)

    if perfil == "super_admin":
        # Se super_admin não passar tenant_id, retorna todos
        tid = tid_filtro
    else:
        # admin do tenant: sempre trancado ao próprio tenant
        tid = session.get("tenant_id", 1)

    return jsonify(items=audit.query(tenant_id=tid, action_prefix=action, limit=limit))


# ── LGPD ─────────────────────────────────────────────────────────────────────

_LGPD_TABLES = [
    ("tenants",       "id=?"),
    ("tenant_config", "tenant_id=?"),
    ("usuarios",      "tenant_id=?"),
    ("empresas",      "tenant_id=?"),
    ("contatos",      "tenant_id=?"),
    ("oportunidades", "tenant_id=?"),
    ("cadencias",     "tenant_id=?"),
    ("atividades",    "tenant_id=?"),
    ("prospeccao",    "tenant_id=?"),
    ("metas",         "tenant_id=?"),
    ("audit_log",     "tenant_id=?"),
]


@api_bp.get("/lgpd/export")
@require_perfil("admin", "super_admin")
def lgpd_export():
    """LGPD art. 18 — retorna todos os dados do tenant em um único JSON."""
    tid = session.get("tenant_id", 1)
    # super_admin pode passar ?tenant_id=X pra baixar de outro tenant
    if getattr(current_user, "perfil", "") == "super_admin":
        tid_q = request.args.get("tenant_id", type=int)
        if tid_q:
            tid = tid_q
    conn = database.get_connection()
    dump = {}
    for tbl, where in _LGPD_TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {tbl} WHERE {where}", (tid,)).fetchall()
            dump[tbl] = [dict(r) for r in rows]
        except Exception as e:
            dump[tbl] = {"error": str(e)}
    audit.log("lgpd.export", resource="tenant", resource_id=tid,
              metadata={"rows": {k: (len(v) if isinstance(v, list) else 0) for k, v in dump.items()}})
    from flask import Response
    import json as _json
    body = _json.dumps({"tenant_id": tid, "generated_at": __import__("datetime").datetime.now().isoformat(), "data": dump},
                        indent=2, ensure_ascii=False, default=str)
    return Response(
        body, mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="lgpd-export-tenant-{tid}.json"'},
    )


@api_bp.delete("/lgpd/tenant/<int:tid>")
@require_perfil("super_admin")
def lgpd_tenant_delete(tid):
    """LGPD art. 18 — remove PERMANENTEMENTE todos os dados de um tenant.

    Requer confirmação explícita: body JSON { "confirmar": "<slug do tenant>" }.
    Não é reversível.
    """
    data = request.get_json() or {}
    conn = database.get_connection()
    t = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
    if not t:
        return jsonify(error="Tenant não encontrado"), 404
    t = dict(t)
    if data.get("confirmar") != t.get("slug"):
        return jsonify(error=f'Envie {{"confirmar":"{t.get("slug")}"}} para confirmar.'), 400
    if tid == 1:
        return jsonify(error="Tenant #1 é protegido"), 400

    counts = {}
    for tbl, where in _LGPD_TABLES:
        try:
            r = conn.execute(f"DELETE FROM {tbl} WHERE {where}", (tid,))
            counts[tbl] = getattr(r, "rowcount", -1)
        except Exception as e:
            counts[tbl] = f"error: {e}"
    conn.commit()
    audit.log("lgpd.tenant_delete", resource="tenant", resource_id=tid,
              metadata={"slug": t.get("slug"), "nome": t.get("nome_empresa"), "counts": counts})
    return jsonify(ok=True, tenant=t.get("slug"), counts=counts)
