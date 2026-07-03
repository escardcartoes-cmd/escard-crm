"""Authentication + session tests."""


def test_login_success(client):
    r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["usuario"] == "testadmin"
    assert body["user"]["perfil"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "WRONG"})
    assert r.status_code == 401


def test_login_missing_fields(client):
    r = client.post("/api/auth/login", json={"usuario": "testadmin"})
    assert r.status_code == 400


def test_login_unknown_user(client):
    r = client.post("/api/auth/login", json={"usuario": "no-such-user", "senha": "x"})
    assert r.status_code == 401


def test_me_unauthenticated(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_me_authenticated(authed_client):
    r = authed_client.get("/api/me")
    assert r.status_code == 200
    assert r.get_json()["usuario"] == "testadmin"


def test_logout(authed_client):
    r = authed_client.get("/api/auth/logout")
    assert r.status_code == 200
    # session cleared → /api/me must reject
    r2 = authed_client.get("/api/me")
    assert r2.status_code == 401
