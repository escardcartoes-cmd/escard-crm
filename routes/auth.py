from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
import database
import models.usuario as user_model
import models.tenant as tenant_model

auth_bp = Blueprint('auth', __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    tenant_login = None
    try:
        slug = request.args.get("t") or request.form.get("t_slug", "")
        if slug:
            tenant_login = tenant_model.get_tenant_by_slug(slug)
        if not tenant_login:
            tenant_login = tenant_model.get_tenant_by_id(1)
    except Exception:
        tenant_login = None

    if request.method == "POST":
        try:
            usuario_str = request.form.get("usuario", "").strip()
            senha       = request.form.get("senha", "")

            u_raw = user_model.buscar_dict_por_usuario(usuario_str)

            if u_raw and user_model.verificar_bloqueio(u_raw):
                flash("Conta bloqueada temporariamente após tentativas excessivas. Aguarde 15 minutos.", "danger")
                return render_template("login.html", tenant_login=tenant_login)

            u = user_model.autenticar(usuario_str, senha)
            if u:
                user_model.resetar_tentativas(u.id)
                if u_raw and u_raw.get('dois_fatores_ativo'):
                    user_model.enviar_codigo_2fa(u_raw)
                    session['pre_auth_user_id'] = u.id
                    session['pre_auth_canal']   = u_raw.get('dois_fatores_canal', 'email')
                    return redirect(url_for('auth.login_2fa'))
                login_user(u, remember=True)
                session["tenant_id"] = getattr(u, "tenant_id", 1) or 1
                next_url = request.args.get("next") or ""
                if next_url and (not next_url.startswith("/") or next_url.startswith("//")):
                    next_url = ""
                return redirect(next_url or url_for("dashboard"))

            if u_raw and u_raw.get('ativo'):
                tentativas = user_model.registrar_tentativa_falha(u_raw['id'])
                if tentativas >= 5:
                    flash("Conta bloqueada por 15 minutos após 5 tentativas incorretas.", "danger")
                else:
                    flash(f"Usuário ou senha incorretos. ({tentativas}/5 tentativas)", "danger")
            else:
                flash("Usuário ou senha incorretos.", "danger")
        except Exception as _e:
            print(f"[LOGIN] Erro: {_e}")
            flash("Erro ao processar login. Tente novamente.", "danger")

    return render_template("login.html", tenant_login=tenant_login)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    try:
        user_id = session.get("pre_auth_user_id")
        if not user_id:
            return redirect(url_for("auth.login"))
        canal = session.get("pre_auth_canal", "email")
        if request.method == "POST":
            codigo = request.form.get("codigo", "").strip()
            if user_model.verificar_codigo_2fa(user_id, codigo):
                user_model.resetar_tentativas(user_id)
                u_obj = user_model.buscar_por_id(user_id)
                session.pop("pre_auth_user_id", None)
                session.pop("pre_auth_canal", None)
                login_user(u_obj, remember=True)
                session["tenant_id"] = getattr(u_obj, "tenant_id", 1) or 1
                return redirect(url_for("dashboard"))
            return render_template("login_2fa.html", erro="Código inválido ou expirado.", canal=canal)
        return render_template("login_2fa.html", canal=canal)
    except Exception as e:
        print(f"[2FA] Erro: {e}")
        return redirect(url_for("auth.login"))


@auth_bp.route("/login/2fa/reenviar", methods=["POST"])
def login_2fa_reenviar():
    user_id = session.get("pre_auth_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    try:
        u_raw = user_model.buscar_dict_por_id(user_id)
        if u_raw:
            user_model.enviar_codigo_2fa(u_raw)
    except Exception as e:
        print(f"[2FA reenviar] Erro: {e}")
    flash("Código reenviado.", "success")
    return redirect(url_for("auth.login_2fa"))


@auth_bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    try:
        if request.method == "POST":
            contato = request.form.get("contato", "").strip()
            user_model.iniciar_recuperacao_senha(contato)
            return render_template("recuperar_senha.html",
                                   sucesso="Se encontrarmos sua conta, enviaremos o código por email.")
        return render_template("recuperar_senha.html")
    except Exception as e:
        print(f"[RECUPERAR] Erro: {e}")
        return render_template("recuperar_senha.html", erro="Erro. Tente novamente.")


@auth_bp.route("/nova-senha", methods=["GET", "POST"])
def nova_senha():
    try:
        if request.method == "POST":
            email    = request.form.get("email", "").strip()
            codigo   = request.form.get("codigo", "").strip()
            nova     = request.form.get("nova_senha", "").strip()
            confirma = request.form.get("confirmar_senha", "").strip()
            if nova != confirma:
                return render_template("nova_senha.html", erro="As senhas não coincidem")
            if len(nova) < 8:
                return render_template("nova_senha.html", erro="Mínimo 8 caracteres")
            ok, msg = user_model.verificar_recuperacao_e_trocar_senha(email, codigo, nova)
            if ok:
                return render_template("nova_senha.html", sucesso="Senha atualizada! Faça login.")
            return render_template("nova_senha.html", erro=msg)
        return render_template("nova_senha.html")
    except Exception as e:
        print(f"[NOVA SENHA] Erro: {e}")
        return render_template("nova_senha.html", erro="Erro. Tente novamente.")
