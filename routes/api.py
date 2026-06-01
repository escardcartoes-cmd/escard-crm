"""
REST API — consumed by the Next.js frontend.
All routes return JSON. CSRF exempt (protected by CORS + SameSite cookies).
"""
from flask import Blueprint, jsonify, request, session
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
    conn.execute(
        "INSERT INTO empresas (nome, cnpj, segmento, porte, status, telefone, email, cidade, estado, "
        "tipo_cartao, nome_private_label, num_funcionarios, valor_mensal, produtos_ativos, cliente_ativo, tenant_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["nome"], data.get("cnpj",""), data.get("segmento",""), data.get("porte",""),
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


# ── SDR ──────────────────────────────────────────────────────────────────────

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
