"""Definições de planos e verificação de limites para o Krylo SaaS."""
import database

PLANOS = {
    "starter": {
        "nome": "Starter",
        "preco": 97,
        "limite_empresas": 500,
        "limite_usuarios": 2,
        "limite_sdr_leads": 50,
        "tem_radar": False,
        "tem_portal_cliente": False,
        "tem_kia": True,
    },
    "profissional": {
        "nome": "Profissional",
        "preco": 197,
        "limite_empresas": 5000,
        "limite_usuarios": 10,
        "limite_sdr_leads": 500,
        "tem_radar": True,
        "tem_portal_cliente": True,
        "tem_kia": True,
    },
    "enterprise": {
        "nome": "Enterprise",
        "preco": 497,
        "limite_empresas": 999999,
        "limite_usuarios": 999,
        "limite_sdr_leads": 999999,
        "tem_radar": True,
        "tem_portal_cliente": True,
        "tem_kia": True,
        "white_label_total": True,
    },
}


def get_plano(tenant_plano: str) -> dict:
    return PLANOS.get(tenant_plano, PLANOS["starter"])


def verificar_limite(tenant_id: int, recurso: str) -> dict:
    """Verifica se tenant atingiu limite do plano. Retorna {'ok': bool, 'limite': int, 'atual': int}."""
    try:
        conn = database.get_connection()
        row = conn.execute("SELECT plano FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        plano_nome = (row["plano"] if row else None) or "starter"
        plano = get_plano(plano_nome)

        atual = 0
        limite = 999999

        if recurso == "empresas":
            r = conn.execute(
                "SELECT COUNT(*) AS cnt FROM empresas WHERE tenant_id=?", (tenant_id,)
            ).fetchone()
            atual = int(r["cnt"] if r else 0)
            limite = plano["limite_empresas"]

        elif recurso == "usuarios":
            r = conn.execute(
                "SELECT COUNT(*) AS cnt FROM usuarios WHERE tenant_id=? AND ativo=1", (tenant_id,)
            ).fetchone()
            atual = int(r["cnt"] if r else 0)
            limite = plano["limite_usuarios"]

        elif recurso == "sdr_leads":
            r = conn.execute(
                "SELECT COUNT(*) AS cnt FROM prospeccao_automatica WHERE tenant_id=?", (tenant_id,)
            ).fetchone()
            atual = int(r["cnt"] if r else 0)
            limite = plano["limite_sdr_leads"]

        conn.close()
        return {"ok": atual < limite, "limite": limite, "atual": atual, "plano": plano_nome}
    except Exception:
        return {"ok": True, "limite": 999999, "atual": 0, "plano": "enterprise"}


def feature_disponivel(tenant_plano: str, feature: str) -> bool:
    plano = get_plano(tenant_plano)
    return bool(plano.get(feature, False))
