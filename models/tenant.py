"""Gerenciamento de tenants para o Krylo SaaS multi-tenant."""
import re
from datetime import datetime
from flask import g, session
import database

_TENANT_PADRAO = {
    "id": 1,
    "slug": "escard",
    "nome_empresa": "Escard Cartões",
    "nome_plataforma": "Krylo",
    "logo_url": None,
    "cor_primaria": "#C5A089",
    "cor_secundaria": "#8B6914",
    "cor_fundo": "#FAF8F5",
    "plano": "enterprise",
    "ativo": 1,
    "configurado": 1,
}


def get_tenant_atual():
    """Retorna tenant do usuário logado (via session ou current_user)."""
    if hasattr(g, "tenant") and g.tenant:
        return g.tenant

    # Session tem prioridade (permite impersonação pelo super admin)
    tenant_id = session.get("tenant_id")

    # Fallback: lê tenant_id do usuário Flask-Login
    if not tenant_id:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                tenant_id = getattr(current_user, "tenant_id", 1) or 1
        except Exception:
            pass

    tenant_id = tenant_id or 1

    try:
        conn = database.get_connection()
        row = conn.execute(
            "SELECT * FROM tenants WHERE id = ? AND ativo = 1", (tenant_id,)
        ).fetchone()
        conn.close()
        if row:
            g.tenant = dict(row)
            return g.tenant
    except Exception:
        pass

    g.tenant = dict(_TENANT_PADRAO)
    return g.tenant


def get_tenant_by_id(tenant_id):
    try:
        conn = database.get_connection()
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_tenant_by_slug(slug):
    try:
        conn = database.get_connection()
        row = conn.execute("SELECT * FROM tenants WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_tenant_config(tenant_id):
    try:
        conn = database.get_connection()
        row = conn.execute(
            "SELECT * FROM tenant_config WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def listar_tenants():
    try:
        conn = database.get_connection()
        rows = conn.execute("""
            SELECT t.*,
                (SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id = t.id) AS num_usuarios,
                (SELECT COUNT(*) FROM empresas e WHERE e.tenant_id = t.id) AS num_empresas
            FROM tenants t ORDER BY t.id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def criar_tenant(dados: dict) -> int:
    """Cria novo tenant e usuário admin inicial. Retorna tenant_id."""
    slug = _slugify(dados.get("nome_empresa", "tenant"))
    conn = database.get_connection()
    try:
        # Garante slug único
        base_slug = slug
        i = 2
        while conn.execute("SELECT id FROM tenants WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}{i}"
            i += 1

        cur = conn.execute(
            """INSERT INTO tenants (slug, nome_empresa, nome_plataforma, cor_primaria,
               cor_secundaria, plano, ativo, configurado)
               VALUES (?, ?, ?, ?, ?, ?, 1, 0)""",
            (slug,
             dados.get("nome_empresa", "Nova Empresa"),
             dados.get("nome_plataforma", "CRM"),
             dados.get("cor_primaria", "#4A90D9"),
             dados.get("cor_secundaria", "#2C5F8A"),
             dados.get("plano", "starter")),
        )
        tenant_id = cur.lastrowid
        conn.commit()

        # Config vazia
        conn.execute(
            "INSERT OR IGNORE INTO tenant_config (tenant_id) VALUES (?)", (tenant_id,)
        )
        # Seed ia_config e empresa_config para o novo tenant
        conn.execute(
            "INSERT OR IGNORE INTO ia_config (tenant_id) VALUES (?)", (tenant_id,)
        )
        conn.execute(
            "INSERT OR IGNORE INTO empresa_config (tenant_id) VALUES (?)", (tenant_id,)
        )
        conn.commit()

        # Usuário admin inicial
        import bcrypt as _bc
        senha = dados.get("senha_admin", "krylo2024")
        senha_hash = _bc.hashpw(senha.encode(), _bc.gensalt()).decode()
        conn.execute(
            """INSERT INTO usuarios (nome, email, usuario, senha_hash, perfil, tenant_id, ativo)
               VALUES (?, ?, ?, ?, 'admin', ?, 1)""",
            (dados.get("admin_nome", "Admin"),
             dados.get("admin_email", f"admin@{slug}.com"),
             dados.get("admin_usuario", f"admin_{slug}"),
             senha_hash,
             tenant_id),
        )
        conn.commit()
        conn.close()
        return tenant_id
    except Exception as e:
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        raise e


def salvar_setup(tenant_id: int, dados: dict):
    """Salva dados do setup wizard e marca tenant como configurado."""
    conn = database.get_connection()
    agora = datetime.now().isoformat(sep=" ", timespec="seconds")

    # Atualiza tenant
    conn.execute(
        """UPDATE tenants SET nome_empresa=?, nome_plataforma=?,
           cor_primaria=?, cor_secundaria=?, logo_url=?, configurado=1 WHERE id=?""",
        (dados.get("nome_empresa", ""),
         dados.get("nome_plataforma", "CRM"),
         dados.get("cor_primaria", "#4A90D9"),
         dados.get("cor_secundaria", "#8B6914"),
         dados.get("logo_url") or None,
         tenant_id),
    )

    # Atualiza tenant_config
    conn.execute(
        """INSERT OR IGNORE INTO tenant_config (tenant_id) VALUES (?)""", (tenant_id,)
    )
    conn.execute(
        """UPDATE tenant_config SET ramo_principal=?, produtos_texto=?,
           diferenciais=?, historico=?, concorrentes=?, personalidade_ia=?,
           tom_ia=?, whatsapp=?, email_contato=?,
           site=?, configurado_em=? WHERE tenant_id=?""",
        (dados.get("ramo_principal", ""),
         dados.get("produtos_texto", ""),
         dados.get("diferenciais", ""),
         dados.get("historico", ""),
         dados.get("concorrentes", ""),
         dados.get("personalidade_ia", ""),
         dados.get("tom_ia", "profissional"),
         dados.get("whatsapp", ""),
         dados.get("email_contato", ""),
         dados.get("site", ""),
         agora,
         tenant_id),
    )

    # Atualiza usuário admin se fornecido (sem LIMIT — não suportado em PostgreSQL)
    if dados.get("admin_nome"):
        conn.execute(
            """UPDATE usuarios SET nome=? WHERE id=(
                SELECT id FROM usuarios WHERE tenant_id=? AND perfil='admin' LIMIT 1
            )""",
            (dados["admin_nome"], tenant_id),
        )

    conn.commit()
    conn.close()


def _slugify(texto: str) -> str:
    s = texto.lower().strip()
    s = re.sub(r"[áàãâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[íìîï]", "i", s)
    s = re.sub(r"[óòõôö]", "o", s)
    s = re.sub(r"[úùûü]", "u", s)
    s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40]
