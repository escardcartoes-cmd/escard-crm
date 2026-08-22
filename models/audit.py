"""
Audit log — registra ações sensíveis (login, mudanças, deleções, super-admin).
Uso: audit.log("empresa.create", resource_id=eid, metadata={"nome": ...})

Silencioso em caso de erro (não bloqueia request).
"""
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def log(
    action: str,
    resource: Optional[str] = None,
    resource_id: Optional[int] = None,
    metadata: Optional[dict] = None,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Registra evento de auditoria. Chame após ações sensíveis."""
    try:
        from flask import request, session
        from flask_login import current_user
        import database

        # Auto-preenche de contexto Flask quando não fornecido
        if tenant_id is None:
            tenant_id = session.get("tenant_id") if session else None
        if user_id is None and current_user and current_user.is_authenticated:
            user_id = getattr(current_user, "id", None)
            if user_email is None:
                user_email = getattr(current_user, "email", None)
        if ip is None and request:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if user_agent is None and request:
            user_agent = (request.headers.get("User-Agent") or "")[:500]

        meta_json = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None

        conn = database.get_connection()
        conn.execute(
            "INSERT INTO audit_log (tenant_id, user_id, user_email, action, resource, "
            "resource_id, metadata, ip, user_agent) VALUES (?,?,?,?,?,?,?,?,?)",
            (tenant_id, user_id, user_email, action, resource, resource_id, meta_json, ip, user_agent),
        )
        conn.commit()
    except Exception as e:
        # Nunca deixa auditoria quebrar o request principal
        logger.warning("audit.log failed action=%s: %s", action, e)


def query(
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action_prefix: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Recupera eventos filtrando por tenant/user/action. Ordenado por mais recente."""
    import database
    conn = database.get_connection()
    where, params = ["1=1"], []
    if tenant_id is not None:
        where.append("tenant_id=?"); params.append(tenant_id)
    if user_id is not None:
        where.append("user_id=?"); params.append(user_id)
    if action_prefix:
        where.append("action LIKE ?"); params.append(action_prefix + "%")
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT * FROM audit_log WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT ?", params
    ).fetchall()
    return [dict(r) for r in rows]
