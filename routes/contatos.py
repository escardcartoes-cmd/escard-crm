from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
import models.contato as cont_model
import models.empresa as emp_model
from models.usuario import require_perfil

contatos_bp = Blueprint('contatos', __name__)


def _tid() -> int:
    return int(session.get("tenant_id") or 1)


@contatos_bp.route("/contatos")
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


@contatos_bp.route("/contatos/novo", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def contatos_novo():
    tid = _tid()
    if request.method == "POST":
        cont_model.criar(_form_contato(request.form))
        flash("Contato cadastrado.", "success")
        return redirect(url_for("contatos.contatos_lista"))
    return render_template("contatos/form.html", contato=None,
                           empresas=emp_model.listar(tenant_id=tid),
                           action=url_for("contatos.contatos_novo"))


@contatos_bp.route("/contatos/<int:id>/editar", methods=["GET", "POST"])
@login_required
@require_perfil('vendedor')
def contatos_editar(id):
    tid = _tid()
    c = cont_model.buscar_por_id(id, tenant_id=tid)
    if not c:
        flash("Contato não encontrado.", "danger")
        return redirect(url_for("contatos.contatos_lista"))
    if request.method == "POST":
        cont_model.atualizar(id, _form_contato(request.form))
        flash("Contato atualizado.", "success")
        return redirect(url_for("contatos.contatos_lista"))
    return render_template("contatos/form.html", contato=c,
                           empresas=emp_model.listar(tenant_id=tid),
                           action=url_for("contatos.contatos_editar", id=id))


@contatos_bp.route("/contatos/<int:id>/excluir", methods=["POST"])
@login_required
@require_perfil('vendedor')
def contatos_excluir(id):
    cont_model.excluir(id)
    flash("Contato excluído.", "success")
    return redirect(url_for("contatos.contatos_lista"))


def _form_contato(f):
    return dict(
        empresa_id=int(f.get("empresa_id")),
        nome=f.get("nome", "").strip(),
        cargo=f.get("cargo", "").strip() or None,
        email=f.get("email", "").strip() or None,
        telefone=f.get("telefone", "").strip() or None,
    )
