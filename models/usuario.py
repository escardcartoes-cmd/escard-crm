import bcrypt
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


def criar_admin_se_necessario():
    conn   = get_connection()
    existe = conn.execute(
        "SELECT id FROM usuarios WHERE usuario = ?", ("admin",)
    ).fetchone()
    if not existe:
        conn.execute(
            "INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("Administrador", "admin@krylo.com.br", "admin", _hash("escard2024"), "super_admin", 1),
        )
    else:
        conn.execute(
            "UPDATE usuarios SET perfil = 'super_admin', tenant_id = 1 WHERE usuario = 'admin'"
        )
    conn.commit()
    conn.close()
