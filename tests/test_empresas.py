"""CRUD tests for the empresas resource."""


def test_list_empresas(authed_client):
    r = authed_client.get("/api/empresas")
    assert r.status_code == 200
    body = r.get_json()
    assert "items" in body


def test_create_empresa_minimal(authed_client):
    r = authed_client.post("/api/empresas", json={"nome": "Test Corp Alpha"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["nome"] == "Test Corp Alpha"
    assert body["cnpj"] is None  # Empty CNPJ must not violate UNIQUE
    assert body["status"] == "prospect"


def test_create_two_empresas_without_cnpj(authed_client):
    """Regression: empty CNPJ used to trigger UNIQUE constraint failure across rows."""
    r1 = authed_client.post("/api/empresas", json={"nome": "Corp One"})
    r2 = authed_client.post("/api/empresas", json={"nome": "Corp Two"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["id"] != r2.get_json()["id"]


def test_create_empresa_missing_nome(authed_client):
    r = authed_client.post("/api/empresas", json={})
    assert r.status_code == 400


def test_update_empresa(authed_client):
    r = authed_client.post("/api/empresas", json={"nome": "Before"})
    eid = r.get_json()["id"]
    r2 = authed_client.put(f"/api/empresas/{eid}", json={"status": "cliente"})
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "cliente"


def test_update_empresa_normalizes_empty_cnpj(authed_client):
    r = authed_client.post("/api/empresas", json={"nome": "CnpjTest", "cnpj": "12345"})
    eid = r.get_json()["id"]
    r2 = authed_client.put(f"/api/empresas/{eid}", json={"cnpj": "   "})
    assert r2.status_code == 200
    assert r2.get_json()["cnpj"] is None


def test_delete_empresa(authed_client):
    r = authed_client.post("/api/empresas", json={"nome": "Deletable"})
    eid = r.get_json()["id"]
    r2 = authed_client.delete(f"/api/empresas/{eid}")
    assert r2.status_code == 200
    r3 = authed_client.get(f"/api/empresas/{eid}")
    assert r3.status_code == 404


def test_empresas_requires_auth(client):
    r = client.get("/api/empresas")
    assert r.status_code == 401
