"""2FA challenge flow tests."""


def _enable_2fa_for_user(user_id: int, canal: str = "email"):
    import database
    conn = database.get_connection()
    conn.execute(
        "UPDATE usuarios SET dois_fatores_ativo=1, dois_fatores_canal=? WHERE id=?",
        (canal, user_id),
    )
    conn.commit()


def _disable_2fa_for_user(user_id: int):
    import database
    conn = database.get_connection()
    conn.execute(
        "UPDATE usuarios SET dois_fatores_ativo=0, codigo_2fa=NULL, codigo_2fa_expira=NULL WHERE id=?",
        (user_id,),
    )
    conn.commit()


def test_login_without_2fa_returns_user(client):
    r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("user") is not None
    assert body.get("needs_2fa") is None


def test_login_with_2fa_returns_challenge(client):
    _enable_2fa_for_user(999)
    try:
        r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("needs_2fa") is True
        assert body.get("canal") == "email"
        assert "•" in body.get("destino_mascarado", "") or "@" in body.get("destino_mascarado", "")
        # user NÃO deve estar autenticado ainda
        r2 = client.get("/api/me")
        assert r2.status_code == 401
    finally:
        _disable_2fa_for_user(999)


def test_2fa_verify_with_wrong_code(client):
    _enable_2fa_for_user(999)
    try:
        client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
        r = client.post("/api/auth/2fa/verify", json={"codigo": "000000"})
        assert r.status_code == 401
    finally:
        _disable_2fa_for_user(999)


def test_2fa_verify_without_pending_login_fails(client):
    r = client.post("/api/auth/2fa/verify", json={"codigo": "123456"})
    assert r.status_code == 400


def test_2fa_verify_with_correct_code_completes_login(client):
    import database
    _enable_2fa_for_user(999)
    try:
        client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
        # Recupera código gerado pelo backend
        conn = database.get_connection()
        row = conn.execute("SELECT codigo_2fa FROM usuarios WHERE id=999").fetchone()
        codigo = dict(row).get("codigo_2fa") if row else None
        assert codigo, "Backend não gerou código"

        r = client.post("/api/auth/2fa/verify", json={"codigo": codigo})
        assert r.status_code == 200
        assert r.get_json().get("user", {}).get("usuario") == "testadmin"
        # /api/me agora responde
        r2 = client.get("/api/me")
        assert r2.status_code == 200
    finally:
        _disable_2fa_for_user(999)
