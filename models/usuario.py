import bcrypt
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import flash, redirect, url_for, request, jsonify
from flask_login import UserMixin, current_user
from database import get_connection

PERFIS = ['super_admin', 'admin', 'gerente', 'vendedor', 'visualizador']
NIVEL  = {'super_admin': 5, 'admin': 4, 'gerente': 3, 'vendedor': 2, 'visualizador': 1}
PERFIL_LABELS = {
    'super_admin':  'Super Admin',
    'admin':        'Admin',
    'gerente':      'Gerente',
    'vendedor':     'Vendedor',
    'visualizador': 'Visualizador',
}


class Usuario(UserMixin):
    def __init__(self, row):
        if not isinstance(row, dict):
            row = dict(row)          # sqlite3.Row → dict
        self.id        = row["id"]
        self.nome      = row["nome"]
        self.email     = row.get("email") or ""
        self.usuario   = row["usuario"]
        self.ativo     = bool(row["ativo"])
        self.perfil    = row.get("perfil") or "admin"
        self.tenant_id = int(row.get("tenant_id") or 1)
        self.criado_em = row.get("criado_em") or ""

    def get_id(self):
        return str(self.id)

    @property
    def nivel(self):
        return NIVEL.get(self.perfil, 0)


def _wants_json():
    return (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    )


def require_perfil(min_perfil: str):
    """Decorator: exige que current_user.perfil tenha nível >= min_perfil."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            nivel_atual = NIVEL.get(getattr(current_user, 'perfil', ''), 0)
            if nivel_atual < NIVEL.get(min_perfil, 0):
                if _wants_json():
                    return jsonify({"error": "Acesso negado. Você não tem permissão para esta área."}), 403
                flash('Acesso negado. Você não tem permissão para esta área.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def _check(senha: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode(), hash_.encode())
    except Exception:
        return False


# ── Queries ───────────────────────────────────────────────────────────────────

def buscar_por_id(id_: int):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE id = ?", (id_,)).fetchone()
    conn.close()
    return Usuario(row) if row else None


def listar():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def autenticar(usuario: str, senha: str):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    if not row or not row["ativo"]:
        return None
    if not _check(senha, row["senha_hash"]):
        return None
    return Usuario(row)


def criar(dados: dict) -> int:
    conn = get_connection()
    cur  = conn.execute(
        "INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, ativo) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (dados["nome"], dados.get("email") or None, dados["usuario"],
         _hash(dados["senha"]), dados.get("perfil", "vendedor"), 1),
    )
    id_ = cur.lastrowid
    conn.commit()
    conn.close()
    return id_


def atualizar(id_: int, dados: dict):
    conn = get_connection()
    if dados.get("senha"):
        conn.execute(
            "UPDATE usuarios SET nome=?, email=?, usuario=?, senha_hash=?, perfil=?, ativo=? WHERE id=?",
            (dados["nome"], dados.get("email") or None, dados["usuario"],
             _hash(dados["senha"]), dados["perfil"], int(dados.get("ativo", 1)), id_),
        )
    else:
        conn.execute(
            "UPDATE usuarios SET nome=?, email=?, usuario=?, perfil=?, ativo=? WHERE id=?",
            (dados["nome"], dados.get("email") or None, dados["usuario"],
             dados["perfil"], int(dados.get("ativo", 1)), id_),
        )
    conn.commit()
    conn.close()


def toggle_ativo(id_: int) -> bool:
    conn  = get_connection()
    conn.execute("UPDATE usuarios SET ativo = 1 - ativo WHERE id = ?", (id_,))
    conn.commit()
    row   = conn.execute("SELECT ativo FROM usuarios WHERE id = ?", (id_,)).fetchone()
    novo  = bool(row["ativo"]) if row else False
    conn.close()
    return novo


def excluir(id_: int):
    conn = get_connection()
    conn.execute("DELETE FROM usuarios WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def buscar_dict_por_usuario(usuario_str: str):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario_str,)).fetchone()
    conn.close()
    return dict(row) if row else None


def buscar_dict_por_id(id_: int):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE id = ?", (id_,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _parse_dt(val):
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return val


def gerar_codigo(tamanho=6):
    return str(secrets.randbelow(10**tamanho)).zfill(tamanho)


def verificar_bloqueio(usuario):
    if not usuario.get('bloqueado_ate'):
        return False
    bloq = _parse_dt(usuario['bloqueado_ate'])
    if bloq is None:
        return False
    return datetime.now() < bloq


def registrar_tentativa_falha(user_id):
    from database import get_new_db_connection
    db = get_new_db_connection()
    u = db.execute("SELECT tentativas_login FROM usuarios WHERE id=%s", (user_id,)).fetchone()
    tentativas = ((dict(u).get('tentativas_login') or 0) if u else 0) + 1
    if tentativas >= 5:
        bloqueado_ate = (datetime.now() + timedelta(minutes=15)).isoformat(sep=' ', timespec='seconds')
        db.execute("UPDATE usuarios SET tentativas_login=%s, bloqueado_ate=%s WHERE id=%s",
                   (tentativas, bloqueado_ate, user_id))
    else:
        db.execute("UPDATE usuarios SET tentativas_login=%s WHERE id=%s", (tentativas, user_id))
    db.commit()
    db.close()
    return tentativas


def resetar_tentativas(user_id):
    from database import get_new_db_connection
    db = get_new_db_connection()
    db.execute("UPDATE usuarios SET tentativas_login=0, bloqueado_ate=NULL WHERE id=%s", (user_id,))
    db.commit()
    db.close()


def enviar_codigo_2fa(usuario):
    from database import get_new_db_connection
    codigo = gerar_codigo(6)
    expira = (datetime.now() + timedelta(minutes=10)).isoformat(sep=' ', timespec='seconds')
    db = get_new_db_connection()
    db.execute("UPDATE usuarios SET codigo_2fa=%s, codigo_2fa_expira=%s WHERE id=%s",
               (codigo, expira, usuario['id']))
    db.commit()
    db.close()
    canal = usuario.get('dois_fatores_canal', 'email')
    if canal == 'whatsapp' and usuario.get('telefone'):
        _enviar_whatsapp_2fa(usuario['telefone'], f"Código Krylo: *{codigo}* — válido 10 minutos.")
    else:
        _enviar_email_2fa(usuario['email'], codigo, usuario.get('nome', ''))
    return codigo


def _enviar_email_2fa(email, codigo, nome):
    import os
    try:
        import sib_api_v3_sdk
    except ImportError:
        print(f'[2FA] Código para {email}: {codigo}')
        return
    BREVO_KEY = os.environ.get('BREVO_API_KEY', '')
    if not BREVO_KEY:
        print(f'[2FA] Código para {email}: {codigo}')
        return
    try:
        config = sib_api_v3_sdk.Configuration()
        config.api_key['api-key'] = BREVO_KEY
        api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(config))
        html = (
            f'<div style="font-family:Arial;max-width:400px;margin:0 auto">'
            f'<h2 style="color:#C5A089">Verificação de acesso</h2>'
            f'<p>Olá <strong>{nome}</strong>,</p>'
            f'<div style="background:#f5f5f5;padding:20px;border-radius:8px;text-align:center;margin:20px 0">'
            f'<div style="font-size:36px;font-weight:bold;letter-spacing:8px;color:#333">{codigo}</div>'
            f'<p style="color:#888;font-size:12px">Válido por 10 minutos</p>'
            f'</div></div>'
        )
        msg = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email, "name": nome}],
            sender={"email": os.environ.get('EMAIL_ONBOARDING', 'escardcartoes@gmail.com'),
                    "name": "Krylo Segurança"},
            subject="Código de verificação — Krylo",
            html_content=html,
        )
        api.send_transac_email(msg)
    except Exception as e:
        print(f'[2FA Email] Erro: {e}')


def _enviar_whatsapp_2fa(telefone, mensagem):
    print(f'[2FA WhatsApp] {telefone}: {mensagem}')


def verificar_codigo_2fa(user_id, codigo_informado):
    from database import get_new_db_connection
    db = get_new_db_connection()
    u = db.execute("SELECT codigo_2fa, codigo_2fa_expira FROM usuarios WHERE id=%s", (user_id,)).fetchone()
    db.close()
    if not u:
        return False
    u = dict(u)
    if not u.get('codigo_2fa'):
        return False
    expira = _parse_dt(u['codigo_2fa_expira'])
    if expira is None or datetime.now() > expira:
        return False
    return u['codigo_2fa'] == codigo_informado.strip()


def iniciar_recuperacao_senha(contato):
    from database import get_new_db_connection
    db = get_new_db_connection()
    u = db.execute(
        "SELECT * FROM usuarios WHERE (email=%s OR telefone=%s) AND ativo=1",
        (contato, contato)
    ).fetchone()
    if not u:
        db.close()
        return True
    u = dict(u)
    codigo = gerar_codigo(6)
    expira = (datetime.now() + timedelta(minutes=30)).isoformat(sep=' ', timespec='seconds')
    db.execute("UPDATE usuarios SET codigo_recuperacao=%s, recuperacao_expira=%s WHERE id=%s",
               (codigo, expira, u['id']))
    db.commit()
    db.close()
    _enviar_email_2fa(u['email'], codigo, u.get('nome', ''))
    if u.get('telefone'):
        _enviar_whatsapp_2fa(u['telefone'],
                             f"Código para redefinir senha Krylo: *{codigo}* — válido 30 minutos.")
    return True


def verificar_recuperacao_e_trocar_senha(email, codigo, nova_senha):
    from database import get_new_db_connection
    db = get_new_db_connection()
    u = db.execute("SELECT * FROM usuarios WHERE email=%s AND ativo=1", (email,)).fetchone()
    if not u:
        db.close()
        return False, 'Usuário não encontrado'
    u = dict(u)
    if not u.get('codigo_recuperacao'):
        db.close()
        return False, 'Nenhuma recuperação solicitada'
    expira = _parse_dt(u['recuperacao_expira'])
    if expira is None or datetime.now() > expira:
        db.close()
        return False, 'Código expirado. Solicite novamente.'
    if u['codigo_recuperacao'] != codigo.strip():
        db.close()
        return False, 'Código incorreto'
    try:
        import bcrypt as _bcrypt
        senha_hash = _bcrypt.hashpw(nova_senha.encode(), _bcrypt.gensalt()).decode()
    except Exception:
        senha_hash = nova_senha
    db.execute(
        "UPDATE usuarios SET senha_hash=%s, codigo_recuperacao=NULL, recuperacao_expira=NULL,"
        " tentativas_login=0, bloqueado_ate=NULL WHERE id=%s",
        (senha_hash, u['id'])
    )
    db.commit()
    db.close()
    return True, 'Senha atualizada com sucesso'


def criar_admin_se_necessario():
    """Garante admin com senha correta, desbloqueado, a cada startup."""
    from database import _USE_PG
    conn = get_connection()
    ph   = _hash("escard2024")
    try:
        if _USE_PG:
            conn.execute(
                """INSERT INTO usuarios
                       (nome, email, usuario, senha_hash, perfil, ativo, tenant_id,
                        tentativas_login, bloqueado_ate)
                   VALUES (%s,%s,%s,%s,'super_admin',TRUE,1,0,NULL)
                   ON CONFLICT (usuario) DO UPDATE
                   SET senha_hash       = EXCLUDED.senha_hash,
                       perfil           = 'super_admin',
                       ativo            = TRUE,
                       tenant_id        = 1,
                       tentativas_login = 0,
                       bloqueado_ate    = NULL""",
                ("Administrador", "admin@krylo.com.br", "admin", ph),
            )
        else:
            existe = conn.execute(
                "SELECT id FROM usuarios WHERE usuario=?", ("admin",)
            ).fetchone()
            if not existe:
                conn.execute(
                    "INSERT INTO usuarios "
                    "(nome,email,usuario,senha_hash,perfil,ativo,tenant_id,tentativas_login) "
                    "VALUES (?,?,?,?,'super_admin',1,1,0)",
                    ("Administrador", "admin@krylo.com.br", "admin", ph),
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET senha_hash=?,perfil='super_admin',ativo=1,"
                    "tentativas_login=0,bloqueado_ate=NULL WHERE usuario='admin'",
                    (ph,),
                )
        conn.commit()
    except Exception as e:
        print(f"[STARTUP] criar_admin erro: {e}")
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
