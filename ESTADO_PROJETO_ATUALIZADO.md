# ESTADO DO PROJETO — Krylo CRM
**Atualizado em:** 2026-05-21 | **Branch:** `master`

---

## 1. Stack Tecnológica (atual)

| Camada | Tecnologia |
|--------|-----------|
| Framework web | Flask 3.0+ com Blueprints |
| Autenticação | Flask-Login + bcrypt + 2FA (email ou WhatsApp) |
| CSRF | Flask-WTF — `WTF_CSRF_ENABLED = True` |
| Rate limiting | Flask-Limiter — 200/dia, 50/hora por IP |
| Banco desenvolvimento | SQLite |
| Banco produção | PostgreSQL — Railway Managed |
| Servidor WSGI | Gunicorn — 2 workers, timeout 120s |
| Email transacional | Brevo via `sib-api-v3-sdk` |
| IA — pitches SDR | Anthropic **Claude Sonnet 4.6** |
| Agendamento | APScheduler BackgroundScheduler (protegido por `SCHEDULER_OFF`) |
| Dados externos | BrasilAPI + CNPJ.ws + receitaws.com.br (CNAE) |
| Abstração de DB | `database.py` com `_PgConn`/`_SqliteConn` (troca `?` por `%s`) |

---

## 2. URLs e Acessos

| Recurso | Valor |
|---------|-------|
| Produção | https://web-production-7599a.up.railway.app |
| Domínio customizado | https://crm.krylo.com.br (**DNS pendente**) |
| GitHub | https://github.com/escardcartoes-cmd/escard-crm.git |
| Branch monitorado Railway | `master` |
| Login CRM | usuário: `admin` / senha: `Krylo@2026` |

---

## 3. Commits de 2026-05-21 (Sprint atual)

### 3.1 Bloco 1 — Segurança e fundações (sprint 2)

| Hash | Descrição |
|------|-----------|
| `3661410` | fix: tenant_id nas rotas de prospecção automática |
| `17e795c` | feat: script de backup do PostgreSQL (Railway) |
| `dbddcce` | docs: adiciona .env.example com template de credenciais |

### 3.2 Bloco 2 — Pitch + Cron + Webhook + Dashboard + Admin

| Hash | Descrição |
|------|-----------|
| `451ac5d` | feat: pitch inteligente por segmento com dor específica |
| `c803e20` | feat: cron job Railway SDR automático |
| `dd015cd` | feat: webhook Brevo para rastreamento de emails |
| `7a171f7` | feat: funil SDR visual com métricas reais |
| `8a7c196` | feat: dashboard executivo com alertas e cache |
| `d90acb4` | fix: super admin troca de tenant |

### 3.3 Bloco 3 — Produto SaaS completo

| Hash | Descrição |
|------|-----------|
| `689034d` | feat: wizard onboarding tenant 4 passos |
| `5187893` | feat: backup automático via cron |

---

## 4. Funcionalidades implementadas nos Blocos 1–3

### 4.1 Segurança e tenant isolation

| Item | Descrição |
|------|-----------|
| IDOR prospecção | 6 funções em `prospeccao_auto.py` recebem `tenant_id` obrigatório; todas as queries filtram por ele |
| `.env.example` | Template com todas as variáveis obrigatórias — nunca commitar `.env` real |
| Backup script | `scripts/backup.py` — `pg_dump` + gzip, rotação dos últimos 7 arquivos |

### 4.2 SDR Inteligente

| Feature | Detalhe |
|---------|---------|
| Pitch por segmento | `_SEGMENTO_MAPA` com 10 segmentos (seguros, representações, corretoras, construção, saúde, varejo, tecnologia, indústria, educação, serviços) — dor específica por segmento |
| WhatsApp 3 linhas | Mensagem direta, sem "Tudo bem?", máximo 3 linhas |
| Email 5 parágrafos | Tom consultivo, 5 parágrafos estruturados |
| Variação A/B | `gerar_pitches_segmento()` retorna `wpp_a`, `wpp_b`, `email_a`, `email_b`; escolha aleatória por empresa |
| Cron job | `POST /cron/executar-sdr` protegido por `CRON_TOKEN` via `hmac.compare_digest`; roda em thread background com `max_leads=50` |
| Railway schedule | `0 9,14 * * 1-5` — segunda a sexta, 9h e 14h |

### 4.3 Rastreamento de emails (Brevo webhook)

| Item | Detalhe |
|------|---------|
| Endpoint | `POST /brevo/webhook?secret=<BREVO_WEBHOOK_SECRET>` |
| Eventos | `opened` → `email_status = 'aberto'` (+2 score), `clicked` → `'clicado'` (+4 score) |
| Temperatura | Chama `atualizar_temperatura_lead()` em tempo real |
| Segurança | `hmac.compare_digest` no query param `secret` |

### 4.4 Funil SDR Visual

6 etapas com contagens reais do banco:
`Prospectado → Email Enviado → WhatsApp Aprovado → Respondeu/Engajou → Reunião → Fechou`

Taxa email→engajou e taxa geral prospectado→fechou calculadas ao vivo.

### 4.5 Dashboard executivo com alertas

- **Top 5 leads quentes**: `WHERE temperatura='quente' ORDER BY score DESC LIMIT 5`
- **Cadências paradas**: `WHERE status='pendente' AND data_acao < 3 dias atrás`
- **Cache 5 min** por tenant nos escalares (`_DASHBOARD_CACHE` com TTL)
- Alertas rodados sem cache (fresh a cada request)

### 4.6 Super Admin — troca de tenant

- `session["impersonating"] = True` + `session["original_tenant_id"]` ao entrar
- Botão "Voltar ao Super Admin" via `POST /admin/tenant/sair`
- Form com CSRF; restaura `tenant_id` original ao sair

### 4.7 Onboarding automático do tenant (Bloco 3)

| Item | Detalhe |
|------|---------|
| Email boas-vindas | Enviado via Brevo ao criar tenant via `/admin/tenant/novo` — contém usuário, senha e instrução de acesso |
| Wizard 4 passos | `/setup` — Empresa (nome, logo, email_remetente, nome_vendedor) → Produtos (checkboxes) → Leads (link CSV) → SDR (link config) |
| Progresso dinâmico | Barra de progresso 0–100%; cada step detectado automaticamente (email_remetente preenchido, produtos_texto preenchido, empresas count > 0, configurado=1) |
| Auto-complete | Step 3 marca-se sozinho quando o tenant importa o primeiro lead; step 4 quando configurar SDR é salvo |
| Pular | Passos 3 e 4 têm botão "Pular por agora" para não bloquear o onboarding |
| DB | Migração: `tenant_config` + `email_remetente TEXT`, `nome_vendedor TEXT` |
| Bypass | `before_request` agora libera `leads_importar_*` e `sdr_evolutivo.sdr_evolutivo_configurar` para tenants em setup |

### 4.8 Backup automático via cron (Bloco 3)

- `POST /cron/backup` protegido por `CRON_TOKEN`
- Carrega `scripts/backup.py` via `importlib` e roda em thread background
- Railway cron: `0 18 * * 5` (toda sexta às 18h UTC)

---

## 5. Variáveis de ambiente do Railway

| Variável | Obrigatória | Uso |
|----------|------------|-----|
| `DATABASE_URL` | ✅ | Auto (Railway PostgreSQL) |
| `SECRET_KEY` | ✅ | Assinatura de sessão Flask |
| `ANTHROPIC_API_KEY` | ✅ | Geração de pitches SDR |
| `BREVO_API_KEY` | ✅ | Envio de emails transacionais + webhook |
| `CRON_TOKEN` | ✅ | Proteção de `/cron/executar-sdr` e `/cron/backup` |
| `BREVO_WEBHOOK_SECRET` | ✅ | Proteção de `/brevo/webhook` |
| `SCHEDULER_OFF` | ⚠️ Recomendado | `1` para desativar APScheduler no Railway (evita worker duplicado) |
| `PORT` | Auto | Railway define automaticamente |

---

## 6. Cobertura de segurança atual

| Controle | Status |
|----------|--------|
| CSRF em todos os forms POST | ✅ 100% |
| Filtro de `tenant_id` nas queries principais | ✅ 100% (incluindo prospecção automática) |
| `@login_required` em todas as rotas privadas | ✅ |
| SQL Injection via valores | ✅ Placeholders `?` em todo o código |
| SQL Injection via nomes de coluna | ✅ Whitelist `_COLUNAS_SDR_SESSAO` |
| Open Redirect no login | ✅ Corrigido |
| IDOR em rotas críticas | ✅ Corrigido |
| Senhas com bcrypt + salt | ✅ |
| 2FA disponível | ✅ |
| Lockout após 5 tentativas | ✅ |
| Cron e webhook com token HMAC | ✅ |
| `SESSION_COOKIE_SECURE` / `HTTPONLY` / `SAMESITE` | ❌ Pendente |

---

## 7. Próximos passos

### 7.1 Deploy imediato

- [ ] `git push origin master` → Railway faz deploy automático
- [ ] Configurar variáveis no Railway: `CRON_TOKEN`, `BREVO_WEBHOOK_SECRET`
- [ ] Criar cron jobs no Railway (SDR: `0 9,14 * * 1-5`, Backup: `0 18 * * 5`)
- [ ] Configurar webhook no Brevo: Settings → Webhooks → URL com `?secret=<BREVO_WEBHOOK_SECRET>`, eventos: opened, clicked

### 7.2 Segurança restante

- [ ] `SESSION_COOKIE_SECURE = True`, `HTTPONLY = True`, `SAMESITE = 'Strict'`
- [ ] Rate limiting específico em `/portal/<token>`

### 7.3 Performance e qualidade

- [ ] Política de limpeza `sdr_log_ao_vivo` — DELETE > 30 dias
- [ ] Quebrar `app.py` (~4.300 linhas) em blueprints por domínio
- [ ] Substituir `except Exception: pass` por logging adequado

### 7.4 Funcionalidades roadmap

- [ ] **Billing real** — Stripe ou Asaas (página de planos hoje é mock)
- [ ] **WhatsApp Business API oficial** — substituir link `wa.me`
- [ ] **Base Receita Federal** — popular `rf_empresas` para busca CNAE offline
- [ ] **Exportação PDF/Excel** de pipeline e relatórios

---

## 8. Estrutura de arquivos relevantes

```
escard-crm-repo/
├── app.py                          # ~4.300 linhas — 145+ rotas
├── database.py                     # Abstração SQLite/PostgreSQL + migrations
├── models/
│   ├── prospeccao_auto.py          # SDR Clássico — tenant_id isolado
│   ├── sdr_evolutivo.py            # SDR Evolutivo — pitch por segmento A/B
│   ├── cadencia.py                 # Cadência 5 toques + temperatura do lead
│   ├── brevo.py                    # Envio de email transacional
│   ├── tenant.py                   # get_tenant_atual, criar_tenant, salvar_setup
│   └── usuario.py                  # RBAC (require_perfil)
├── routes/
│   ├── auth.py                     # Login, 2FA, recuperação de senha
│   ├── empresas.py                 # CRUD empresas
│   └── sdr_evolutivo.py            # Dashboard, executar, configurar, radar
├── templates/
│   ├── setup_wizard.html           # Wizard 4 passos onboarding
│   ├── dashboard.html              # Dashboard executivo com alertas
│   └── sdr_evolutivo/dashboard.html # Funil SDR visual
├── scripts/
│   ├── backup.py                   # pg_dump + gzip + rotação
│   └── pre_deploy_check.py         # Validação pré-deploy
├── .env.example                    # Template de variáveis de ambiente
├── AUDITORIA_KRYLO.md              # Auditoria completa do sistema
└── ESTADO_PROJETO_ATUALIZADO.md    # Este arquivo
```

---

*Atualizado em 2026-05-21 após Blocos 1, 2 e 3 do sprint completo.*
