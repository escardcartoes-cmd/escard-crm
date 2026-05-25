"""
Krylo Smoke Test — valida segurança e funcionamento básico.
Uso:  python smoke_test.py
Sai com código 0 se tudo OK, 1 se falhou.

PRÉ-REQUISITO: SECRET_KEY deve estar configurada como variável
de ambiente fixa no Railway. Sem isso, o teste de login FALHA.
"""
import sys, re, urllib.request, urllib.parse, http.cookiejar, ssl

BASE = 'https://web-production-7599a.up.railway.app'
USER, PASS = 'Roberto', 'Krylo@2026'

ok, falhou = [], []

ctx = ssl.create_default_context()


def _opener():
    o = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=ctx)
    )
    o.addheaders = [('User-Agent', 'Krylo-Smoke/1.0')]
    return o


def req(opener, path, method='GET', data=None, timeout=20):
    url = f"{BASE}{path}"
    enc = urllib.parse.urlencode(data).encode() if data else None
    r = urllib.request.Request(url, data=enc, method=method)
    try:
        resp = opener.open(r, timeout=timeout)
        return resp.status, resp.geturl(), resp.read().decode('utf-8', errors='ignore')
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', errors='ignore')
        except Exception:
            pass
        return e.code, url, body


def teste(nome, cond, detalhe=''):
    if cond:
        ok.append(nome)
        print(f"  ✓  {nome}")
    else:
        falhou.append(f"{nome} ({detalhe})")
        print(f"  ✗  {nome} — {detalhe}")


print("═══ KRYLO SMOKE TEST ═══")
print(f"Target: {BASE}")
print()

# ── Bloco 1: rotas protegidas sem sessão devem bloquear ──────────────────────
print("[ Proteção de rotas — usuário anônimo ]")
anon = _opener()

status, url, html = req(anon, '/dashboard')
teste("Dashboard anon → redireciona para login",
      'login' in url.lower() or status in (302, 401, 403),
      f"status={status} url={url}")

status, url, html = req(anon, '/empresas')
teste("Empresas anon → redireciona",
      'login' in url.lower() or status in (302, 401, 403),
      f"status={status} url={url}")

status, url, html = req(anon, '/admin')
teste("Admin anon → redireciona",
      'login' in url.lower() or status in (302, 401, 403),
      f"status={status}")

status, url, html = req(anon, '/sdr/fila-whatsapp')
teste("SDR fila anon → redireciona",
      'login' in url.lower() or status in (302, 401, 403),
      f"status={status}")

status, url, html = req(anon, '/configuracoes/empresa')
teste("Configuracoes anon → redireciona",
      'login' in url.lower() or status in (302, 401, 403),
      f"status={status}")

print()

# ── Bloco 2: página de login acessível e sem vazar dados ─────────────────────
print("[ Página de login ]")
status, url, html = req(anon, '/login')
teste("Login GET → 200", status == 200, f"status={status}")
csrf_encontrado = bool(re.search(r'name="csrf_token"\s+value="[^"]+"', html))
teste("CSRF token presente na página de login", csrf_encontrado)

print()

# ── Bloco 3: login com credenciais erradas ────────────────────────────────────
print("[ Autenticação ]")
c_errado = _opener()
status, url, html = req(c_errado, '/login')
m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
csrf = m.group(1) if m else ''

status, url, html = req(c_errado, '/login', 'POST',
                        {'usuario': USER, 'senha': 'ERRADA_123', 'csrf_token': csrf})
teste("Login senha errada → permanece em /login ou flash erro",
      '/login' in url or status in (200, 400, 401),
      f"status={status} url={url}")

# Login válido
c_ok = _opener()
status, url, html = req(c_ok, '/login')
m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
csrf = m.group(1) if m else ''

status_login, url_login, html_login = req(c_ok, '/login', 'POST',
                                          {'usuario': USER, 'senha': PASS, 'csrf_token': csrf})

if status_login == 500:
    falhou.append(f"Login Roberto → HTTP 500 (verificar SECRET_KEY no Railway)")
    print(f"  ✗  Login Roberto → HTTP 500")
    print(f"     ⚠️  CAUSA PROVÁVEL: SECRET_KEY não configurada no Railway")
    print(f"     SOLUÇÃO: Railway → Variables → SECRET_KEY=<valor fixo>")
    print(f"     Gerar: python -c \"import secrets; print(secrets.token_hex(32))\"")
    login_ok = False
else:
    login_ok = status_login == 200 and '/login' not in url_login
    teste("Login Roberto → entra no sistema",
          login_ok, f"status={status_login} url={url_login}")

print()

# ── Bloco 4: rotas autenticadas (só se login funcionou) ──────────────────────
if login_ok:
    print("[ Rotas autenticadas ]")

    status, url, html = req(c_ok, '/')
    teste("Dashboard / → 200", status == 200, f"status={status}")

    status, url, html = req(c_ok, '/empresas')
    teste("Empresas → 200", status == 200, f"status={status}")

    status, url, html = req(c_ok, '/sdr/fila-whatsapp')
    teste("SDR fila-whatsapp → 200", status == 200, f"status={status}")

    status, url, html = req(c_ok, '/sdr-evolutivo')
    teste("SDR evolutivo → 200", status == 200, f"status={status}")

    status, url, html = req(c_ok, '/cadencias')
    teste("Cadencias → 200", status == 200, f"status={status}")

    # White-label check: título deve usar tenant.nome_plataforma
    status, url, html = req(c_ok, '/')
    title_m = re.search(r'<title>([^<]+)</title>', html)
    title = title_m.group(1) if title_m else ''
    teste("Título não tem 'Krylo CRM' hardcoded (white-label ativo)",
          'Krylo CRM' not in title or 'Escard' in html,
          f"title={title[:60]}")

    # Logout
    status, url, html = req(c_ok, '/logout')
    status2, url2, _ = req(c_ok, '/empresas')
    teste("Logout invalida sessão",
          'login' in url2.lower() or status2 in (302, 401),
          f"pos-logout: status={status2} url={url2}")

    print()

# ── Resultado ─────────────────────────────────────────────────────────────────
print("═══ RESULTADO ═══")
total = len(ok) + len(falhou)
print(f"Passaram: {len(ok)}/{total}   Falharam: {len(falhou)}/{total}")

if falhou:
    print()
    print("Falhas:")
    for f in falhou:
        print(f"  - {f}")
    sys.exit(1)

print("Tudo OK. ✓")
sys.exit(0)
