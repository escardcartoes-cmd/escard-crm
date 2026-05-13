import bcrypt
from flask_login import UserMixin
from database import get_connection


class Usuario(UserMixin):
    def __init__(self, row):
        self.id        = row["id"]
        self.nome      = row["nome"]
        self.email     = row.get("email") or ""
        self.usuario   = row["usuario"]
        self.ativo     = bool(row["ativo"])

    def get_id(self):
        return str(self.id)


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def _check(senha: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode(), hash_.encode())
    except Exception:
        return False


def buscar_por_id(id_: int):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE id = ?", (id_,)).fetchone()
    conn.close()
    return Usuario(row) if row else None


def buscar_por_usuario(usuario: str):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    conn.close()
    return row


def autenticar(usuario: str, senha: str):
    row = buscar_por_usuario(usuario)
    if not row or not row["ativo"]:
        return None
    if not _check(senha, row["senha_hash"]):
        return None
    return Usuario(row)


def criar_admin_se_necessario():
    conn = get_connection()
    existe = conn.execute(
        "SELECT id FROM usuarios WHERE usuario = ?", ("admin",)
    ).fetchone()
    if not existe:
        conn.execute(
            "INSERT INTO usuarios (nome, email, usuario, senha_hash) VALUES (?, ?, ?, ?)",
            ("Administrador", "admin@escard.com.br", "admin", _hash("escard2024")),
        )
        conn.commit()
    conn.close()
