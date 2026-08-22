"""Audit log + role enforcement tests."""


def test_login_success_creates_audit_entry(client):
    r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
    assert r.status_code == 200
    import models.audit as audit
    events = audit.query(action_prefix="auth.login_success", limit=5)
    assert any(e.get("user_email") == "test@krylo.local" for e in events)


def test_login_failed_creates_audit_entry(client):
    client.post("/api/auth/login", json={"usuario": "no-such", "senha": "x"})
    import models.audit as audit
    events = audit.query(action_prefix="auth.login_failed", limit=5)
    assert len(events) > 0


def test_admin_tenants_requires_super_admin(authed_client):
    # Test user tem perfil=admin, não super_admin
    r = authed_client.get("/api/admin/tenants")
    assert r.status_code == 403


def test_admin_audit_endpoint_returns_events(authed_client):
    # perfil=admin do tenant tem acesso ao próprio audit
    r = authed_client.get("/api/admin/audit")
    assert r.status_code == 200
    assert "items" in r.get_json()
