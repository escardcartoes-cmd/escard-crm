"""
Pytest fixtures — spin up the Flask app against an isolated SQLite temp DB per test session.
"""
import os
import sys
import tempfile
import pytest
import bcrypt

# Force dev config before importing app.
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
os.environ.pop("RAILWAY_ENVIRONMENT", None)
os.environ.pop("VERCEL", None)
os.environ.pop("PRODUCTION", None)
os.environ["SCHEDULER_OFF"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="session")
def app():
    """Build the Flask app once per session with an isolated on-disk SQLite DB."""
    tmp_dir = tempfile.mkdtemp(prefix="krylo-test-")
    db_path = os.path.join(tmp_dir, "test.db")

    # Point database module at the temp file BEFORE importing the app.
    import database
    database.DB_PATH = db_path
    database._USE_PG = False

    import app as app_module
    flask_app = app_module.app
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        RATELIMIT_ENABLED=False,
    )
    # Explicitly disable Flask-Limiter globally; rate-limit test opts in per-test.
    if hasattr(app_module, "limiter"):
        app_module.limiter.enabled = False

    # Bootstrap schema + a single admin user for tests.
    _seed_admin(db_path)
    yield flask_app


def _seed_admin(db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    # Minimal schema for the tables the tests touch. Rely on the app's own init
    # if it already ran; otherwise create bare tables.
    try:
        import database as db
        real_conn = db.get_connection()
        real_conn.close()
    except Exception:
        pass

    # Insert or refresh admin credentials
    hashed = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode()
    conn.execute("""
        INSERT INTO usuarios (id, nome, email, usuario, senha_hash, perfil, ativo, tenant_id)
        VALUES (999, 'Test Admin', 'test@krylo.local', 'testadmin', ?, 'admin', 1, 1)
        ON CONFLICT(id) DO UPDATE SET senha_hash=excluded.senha_hash, ativo=1, tentativas_login=0, bloqueado_ate=NULL
    """, (hashed,))
    conn.commit()
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authed_client(client):
    """A client that already carries a valid session cookie."""
    r = client.post("/api/auth/login", json={"usuario": "testadmin", "senha": "testpass123"})
    assert r.status_code == 200, f"login setup failed: {r.get_json()}"
    return client
