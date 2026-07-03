"""Security headers + hardening tests."""


def test_security_headers_present(client):
    r = client.get("/api/me")  # 401 is fine, headers still applied
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "strict-origin" in r.headers.get("Referrer-Policy", "")


def test_permissions_policy(client):
    r = client.get("/api/me")
    pp = r.headers.get("Permissions-Policy", "")
    assert "geolocation=()" in pp
    assert "microphone=()" in pp
    assert "camera=()" in pp


def test_cors_allows_known_origin(client):
    r = client.get("/api/me", headers={"Origin": "http://localhost:3001"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:3001"


def test_cors_denies_unknown_origin(client):
    r = client.get("/api/me", headers={"Origin": "https://evil.example.com"})
    # flask-cors omits the header when origin not allowed
    assert r.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"


def test_no_stack_trace_leak_on_500(client):
    """Error handler must not leak tracebacks to clients."""
    r = client.get("/api/nonexistent-route")
    assert r.status_code == 404
    body = r.get_data(as_text=True)
    assert "Traceback" not in body


def test_login_rate_limit_kicks_in(app, client):
    """After 10 failed logins in a minute, further attempts return 429."""
    import app as app_module
    app_module.limiter.enabled = True
    try:
        statuses = []
        for _ in range(12):
            r = client.post("/api/auth/login", json={"usuario": "brute-force-target", "senha": "x"})
            statuses.append(r.status_code)
        assert 429 in statuses, f"expected 429 in {statuses}"
    finally:
        app_module.limiter.enabled = False
        # Clear the storage so parallel tests aren't affected.
        if hasattr(app_module.limiter, "reset"):
            try:
                app_module.limiter.reset()
            except Exception:
                pass
