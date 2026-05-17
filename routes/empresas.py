from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required
import models.empresa as emp_model
import models.contato as cont_model
import models.oportunidade as op_model
import models.atividade as atv_model
import models.portal as portal_model
from models.usuario import require_perfil

empresas_bp = Blueprint('empresas', __name__)


def _tid() -> int:
    return int(session.get("tenant_id") or 1)


@empresas_bp.route("/empresas")
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


@empresas_bp.route("/empresas/nova", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def empresas_nova():
    if request.method == "POST":
        emp_model.criar({**_form_empresa(request.form), "tenant_id": _tid()})
        flash("Empresa cadastrada com sucesso.", "success")
        return redirect(url_for("empresas.empresas_lista"))
    return render_template("empresas/form.html", empresa=None,
                           action=url_for("empresas.empresas_nova"))


@empresas_bp.route("/empresas/<int:id>")
@login_required
@require_perfil('gerente')
def empresas_detalhe(id):
    tid = _tid()
    emp = emp_model.buscar_por_id(id, tenant_id=tid)
    if not emp:
        flash("Empresa não encontrada.", "danger")
        return redirect(url_for("empresas.empresas_lista"))
    return render_template(
        "empresas/detalhe.html",
        empresa=emp,
        contatos=cont_model.listar(empresa_id=id, tenant_id=tid),
        ops=op_model.listar(empresa_id=id, tenant_id=tid),
        atividades=atv_model.listar(empresa_id=id, limit=10, tenant_id=tid),
        labels=op_model.ESTAGIO_LABELS,
    )


@empresas_bp.route("/empresas/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def empresas_editar(id):
    emp = emp_model.buscar_por_id(id, tenant_id=_tid())
    if not emp:
        flash("Empresa não encontrada.", "danger")
        return redirect(url_for("empresas.empresas_lista"))
    if request.method == "POST":
        emp_model.atualizar(id, _form_empresa(request.form))
        flash("Empresa atualizada.", "success")
        return redirect(url_for("empresas.empresas_detalhe", id=id))
    return render_template("empresas/form.html", empresa=emp,
                           action=url_for("empresas.empresas_editar", id=id))


@empresas_bp.route("/empresas/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('gerente')
def empresas_excluir(id):
    emp_model.excluir(id)
    flash("Empresa excluída.", "success")
    return redirect(url_for("empresas.empresas_lista"))


@empresas_bp.route("/empresas/excluir-lote", methods=["POST"])
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
