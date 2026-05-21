# ESTADO DO PROJETO — Krylo CRM
**Atualizado em:** 2026-05-21 | **Branch:** `master`

---

## 1. Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Framework web | Flask 3.0+ com Blueprints |
| Autenticação | Flask-Login + bcrypt + 2FA |
| CSRF | Flask-WTF — `WTF_CSRF_ENABLED = True` |
| Banco desenvolvimento | SQLite (`krylo.db`) |
| Banco produção | PostgreSQL — Railway Managed |
| Servidor WSGI | Gunicorn — 2 workers, timeout 120s |
| Email transacional | Brevo via `sib-api-v3-sdk` |
| IA — pitches SDR | Anthropic **Claude Sonnet 4.6** |
| Agendamento | APScheduler (protegido por `SCHEDULER_OFF`) |
| Dados externos | BrasilAPI + CNPJ.ws + receitaws.com.br |

---

## 2. Estrutura de Tenants (produção)

| ID | Slug | Nome | Plano | Uso |
|----|------|------|-------|-----|
| 1 | `krylo` | **Krylo** | enterprise | Tenant master — só o administrador |
| 14 | `liderset` | LiderSet | starter | Tenant de teste |
| 117 | `escard` | **Escard Cartões e Benefícios** | starter | Cliente principal — 527 leads, 533 contatos |

### Usuários

| Usuário | Perfil | Tenant | Senha atual |
|---------|--------|--------|-------------|
| `administrador` | super_admin | Krylo (1) | `Krylo@2026` |
| `polyana` | gerente | Escard (117) | `Escard@2026` |
| `Roberto` | admin | Escard (117) | `Krylo@2026` |

---

## 3. URLs e Acessos

| Recurso | Valor |
|---------|-------|
| Produção | https://web-production-7599a.up.railway.app |
| Landing page Krylo | https://web-production-7599a.up.railway.app/krylo |
| Login | https://web-production-7599a.up.railway.app/login |
| GitHub | https://github.com/escardcartoes-cmd/escard-crm.git |
| Branch Railway | `master` |

---

## 4. Commits de 2026-05-21

### Bloco 1–3 (sprint anterior)

| Hash | Descrição |
|------|-----------|
| `3661410` | fix: tenant_id nas rotas de prospecção automática |
| `17e795c` | feat: script de backup do PostgreSQL |
| `dbddcce` | docs: .env.example |
| `451ac5d` | feat: pitch inteligente por segmento A/B |
| `c803e20` | feat: cron job Railway SDR |
| `dd015cd` | feat: webhook Brevo rastreamento emails |
| `7a171f7` | feat: funil SDR visual |
| `8a7c196` | feat: dashboard executivo com alertas e cache |
| `d90acb4` | fix: super admin troca de tenant |
| `689034d` | feat: wizard onboarding tenant 4 passos |
| `5187893` | feat: backup automático via cron |
| `971535e` | docs: estado projeto pós sprint |

### Separação Krylo/Escard (hoje)

| Hash | Descrição |
|------|-----------|
| `6009a6b` | feat: separa identidade Krylo do tenant Escard |
| `5a72861` | feat: landing page pública do Krylo |
| `74efb64` | feat: configura tenant Escard como cliente |

---

## 5. O que foi feito na separação Krylo/Escard

### 5.1 Banco (produção — sem rollback)

- Tenant id=1 renomeado: slug `escard` → `krylo`, nome "Escard Cartões" → "Krylo"
- Novo tenant id=117 criado: slug `escard`, nome "Escard Cartões e Benefícios"
- Migração completa do tenant 1 → tenant 117:
  - 527 empresas, 533 contatos, 42 cadências
  - 70 sessões SDR, 30 execuções SDR
  - tenant_config, ia_config, empresa_config, sdr_config, sdr_evolutivo_config
- polyana e Roberto movidos para tenant 117
- tenant 1 (Krylo) fica limpo: só o `administrador`
- `tenant_config` Escard: produtos VA/VR/Combustível/Wellhub/Vidalink/Private Label, email remetente roberto@escardcartoes.com.br
- `sdr_evolutivo_config` Escard: score_min=6, max_leads=30, radar_intent=1, ecosistema=1, pitch_adaptativo=1

### 5.2 Código

- `models/tenant.py`: `_TENANT_PADRAO` → slug `krylo`, nome "Krylo", cores azul
- `database.py`: seed do tenant padrão → slug `krylo`
- `app.py`: fallback tenant → "Krylo"; CSV export sem "escard" no nome; rota `/krylo` pública
- `templates/login.html`: `logo-sub` oculto quando `nome_empresa == nome_plataforma` (elimina "Krylo / Krylo" no login master)
- `templates/empresas/lista.html`: download renomeado de `empresas_escard.csv` → `empresas.csv`
- `templates/setup_wizard.html`: placeholder genérico
- `templates/krylo_landing.html`: landing page completa do produto

---

## 6. Landing Page `/krylo`

- Rota pública (sem `@login_required`), bypass do `before_request`
- Seções: hero com métricas, funcionalidades (6 cards), como funciona (4 passos), planos (Starter R$297 / Pro R$697 / Enterprise sob consulta), depoimentos, CTA final
- Design: Inter, paleta azul `#4A90D9`, responsivo (mobile collapse em 768px)
- CTAs linkam para `/login` (plataforma) e WhatsApp (Enterprise/vendas)

---

## 7. Senhas redefinidas (produção)

Senhas redefinidas com bcrypt `$2b$12$` em 2026-05-21:

| Usuário | Senha |
|---------|-------|
| administrador | `Krylo@2026` |
| polyana | `Escard@2026` |
| Roberto | `Krylo@2026` |

---

## 8. Variáveis de Ambiente (Railway)

| Variável | Status |
|----------|--------|
| `DATABASE_URL` | Auto (Railway PostgreSQL) |
| `SECRET_KEY` | Configurar |
| `ANTHROPIC_API_KEY` | Configurar (pitches SDR) |
| `BREVO_API_KEY` | Configurar (emails + webhook) |
| `CRON_TOKEN` | Configurar (protege /cron/executar-sdr e /cron/backup) |
| `BREVO_WEBHOOK_SECRET` | Configurar (protege /brevo/webhook) |
| `SCHEDULER_OFF` | Recomendado: `1` |

---

## 9. Próximos Passos

### 9.1 Deploy imediato

- [ ] `git push origin master` → Railway faz deploy automático
- [ ] Verificar login com as novas senhas após deploy
- [ ] Configurar cron jobs no Railway:
  - SDR: `0 9,14 * * 1-5` → `POST /cron/executar-sdr` com `X-Cron-Token`
  - Backup: `0 18 * * 5` → `POST /cron/backup` com `X-Cron-Token`
- [ ] Configurar webhook no Brevo: Settings → Webhooks → URL `/brevo/webhook?secret=<BREVO_WEBHOOK_SECRET>`, eventos: opened, clicked

### 9.2 Escard — primeiros passos como cliente

- [ ] Login com usuário `Roberto` / `Krylo@2026` no tenant Escard
- [ ] Verificar wizard de onboarding: 527 empresas já importadas (step 3 deve mostrar ✓)
- [ ] Executar SDR Evolutivo manualmente para testar pitches com os novos produtos
- [ ] Testar envio de email de cadência para um lead de teste

### 9.3 Krylo — produto SaaS

- [ ] Atualizar WhatsApp de vendas na landing page (hoje placeholder 5527999999999)
- [ ] `SESSION_COOKIE_SECURE = True` / `HTTPONLY` / `SAMESITE` no app.py
- [ ] Billing real (Stripe ou Asaas) — página de planos hoje é informativa
- [ ] Domínio krylo.com.br apontando para Railway

### 9.4 Qualidade

- [ ] Quebrar `app.py` (~4.300 linhas) em blueprints
- [ ] Limpar `sdr_log_ao_vivo` > 30 dias
- [ ] Base Receita Federal — popular `rf_empresas`

---

## 10. Estrutura de Arquivos Relevantes

```
escard-crm-repo/
├── app.py                          # ~4.300 linhas — 147+ rotas
├── database.py                     # Abstração SQLite/PostgreSQL + migrations
├── models/
│   ├── tenant.py                   # Krylo como _TENANT_PADRAO
│   ├── sdr_evolutivo.py            # Pitch A/B por segmento
│   ├── cadencia.py                 # Cadência 5 toques + temperatura
│   └── brevo.py                    # Email transacional
├── templates/
│   ├── krylo_landing.html          # Landing page pública /krylo
│   ├── setup_wizard.html           # Wizard onboarding 4 passos
│   ├── login.html                  # Sem empresa repetida para Krylo master
│   └── dashboard.html              # Alertas + leads quentes
├── scripts/
│   └── backup.py                   # pg_dump + gzip + rotação
├── .env.example                    # Template de variáveis
└── ESTADO_PROJETO_ATUALIZADO.md    # Este arquivo
```

---

*Atualizado em 2026-05-21 após separação completa Krylo/Escard.*
