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
import database

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
        return jsonify(error="Usuário ou senha incorretos."), 401

    user_model.resetar_tentativas(u.id)
    login_user(u, remember=True)
    session["tenant_id"] = getattr(u, "tenant_id", 1) or 1
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
    return jsonify(_user_dict(current_user))


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


@api_bp.post("/usuarios")
@login_required
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
@login_required
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
@login_required
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
