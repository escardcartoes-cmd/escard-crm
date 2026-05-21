# ESTADO DO PROJETO — Krylo CRM
**Atualizado em:** 2026-05-20 | **Branch:** `master` | **Commits pendentes de push:** 13

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
| Servidor WSGI | Gunicorn — **2 workers, timeout 120s** (atualizado hoje) |
| Email transacional | Brevo via `sib-api-v3-sdk` |
| IA — pitches SDR | Anthropic **Claude Sonnet 4.6** (atualizado hoje de Haiku) |
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

## 3. Todos os commits de 2026-05-20

### 3.1 Segurança — auditoria e correções (tarde)

| Hash | Hora | Descrição |
|------|------|-----------|
| `48fa7f6` | 20:57 | fix: CSRF token em todos os formulários restantes (14 templates, 16 forms) |
| `99ead53` | 20:53 | fix: CSRF token nos formulários críticos (5 templates prioritários) |
| `b0720e8` | 20:52 | fix: SQL injection em prospeccao_autonoma — whitelist de colunas |
| `6366a89` | 20:52 | fix: IDOR em api empresa contato — filtra por tenant_id |
| `61ca651` | 19:58 | feat(sdr): variação A/B nos pitches para evitar mensagens idênticas em lote |
| `6d627c9` | 19:56 | perf(cache): cache de 5 min nos escalares do dashboard por tenant |
| `e4ceb98` | 19:54 | feat(enriquecimento): busca CNAE via receitaws.com.br para empresas importadas |
| `e6b9859` | 19:52 | perf(dashboard): consolida 20+ queries em 4 queries no carregamento |
| `4ccf0b4` | 19:51 | perf(db): adiciona índices compostos nas tabelas de alta frequência |
| `30792f5` | 19:42 | fix(logging): substitui print() por logging estruturado nos módulos críticos |
| `e299612` | 19:39 | fix(infra): adiciona 2 workers e timeout 120s ao Gunicorn |
| `8e1641e` | 19:38 | feat(ai): substitui claude-haiku por claude-sonnet-4-6 nos pitches SDR |
| `40d728d` | 19:28 | fix(security): corrige VULN-01 open redirect e VULN-02 IDOR em oportunidades |
| `5923555` | 19:11 | docs: adiciona diagnóstico técnico completo do sistema (DIAGNOSTICO_KRYLO.md) |

### 3.2 Infraestrutura, email e WhatsApp (tarde)

| Hash | Hora | Descrição |
|------|------|-----------|
| `13c2280` | 18:55 | fix: corrige switch de tenant e cálculo de meta no dashboard |
| `65277b9` | 15:30 | fix: três correções na fila de aprovação WhatsApp |
| `5c300c3` | 15:22 | fix: usa email_remetente do tenant ao enviar emails de cadência |
| `69753b3` | 15:04 | fix: enviar_email_brevo verifica HTTP status antes de marcar como enviado |
| `868c781` | 14:56 | fix: SDR executar — CSRF token, resultado inline e loading no botão |

### 3.3 SDR e geração de pitch (manhã/início de tarde)

| Hash | Hora | Descrição |
|------|------|-----------|
| `e72de03` | 14:49 | fix: aplica .title() no nome da empresa no pitch genérico |
| `cd70024` | 14:24 | fix: pitch genérico quando cnae_codigo vazio — sem produto específico |
| `f1bc538` | 13:37 | fix: cadencia.py — remove cnae_fiscal_descricao (coluna inexistente no PG) |
| `b1659c7` | 10:25 | fix: configurar SDR permanece na página após salvar |
| `4bd317f` | 09:56 | fix: SDR aprovação por email OU telefone sem threshold numérico |
| `69d4b8c` | 09:21 | fix: SDR usa email de contatos + dashboard dinâmico + limpa cadências inválidas |
| `14e2240` | 08:38 | fix: SDR usa tabela produtos_krylo + redirect corrigido |
| `a5d2338` | 07:58 | fix: SDR não captava leads — remove colunas inexistentes e baixa threshold |
| `d15578b` | 07:43 | feat: SDR Evolutivo — cadência 5 toques, produto por CNAE, fonte ambos |

**Total hoje: 27 commits** | **13 ainda não enviados para o Railway**

---

## 4. Bugs corrigidos hoje

### 4.1 Segurança crítica (auditoria AUDITORIA_KRYLO.md)

| # | Vulnerabilidade | Arquivo | Correção |
|---|----------------|---------|---------|
| S1 | **IDOR** em `/api/empresa/<id>/contato` — sem filtro de `tenant_id` | `app.py:3311` | `AND tenant_id=?` em ambas as queries |
| S2 | **SQL Injection** em `atualizar_progresso()` — colunas de `kwargs` concatenadas diretamente | `models/prospeccao_autonoma.py:885` | `_COLUNAS_SDR_SESSAO` (frozenset whitelist com 12 campos) |
| S3 | **CSRF ausente** em formulários críticos | 5 templates | `{{ csrf_token() }}` nos forms de empresas, contatos, oportunidades, financeiro, importar |
| S4 | **CSRF ausente** em todos os demais forms | 14 templates | `{{ csrf_token() }}` nos 16 forms restantes; varredura automatizada confirmou cobertura 100% |
| S5 | **Open Redirect** no login (`?next=` sem validação) | `routes/auth.py:46` | Validação de URL segura |
| S6 | **IDOR** em oportunidades (`buscar_por_id` sem `tenant_id` obrigatório) | `models/oportunidade.py` | `tenant_id` obrigatório na query |

### 4.2 SDR e cadência

| # | Bug | Status |
|---|-----|--------|
| B1 | SDR não captava leads — colunas `cnae_fiscal`, `capital_social`, `data_abertura` inexistentes no PG | ✅ Removido |
| B2 | Threshold de score = 8 impossível (empresas sem dados ricos) | ✅ Substituído por gate: email OR telefone |
| B3 | SDR não buscava email/telefone de contatos vinculados | ✅ COALESCE + subquery corrigida |
| B4 | 100 cadências inválidas no banco de produção | ✅ Deletadas |
| B5 | Pitch genérico quando `cnae_codigo` vazio retornava produto inválido | ✅ Corrigido |
| B6 | Cadência usando `cnae_fiscal_descricao` (coluna inexistente no PG) | ✅ Removido |
| B7 | Aprovação de WhatsApp — 3 problemas na fila | ✅ Corrigidos |
| B8 | SDR após executar não ficava na página — CSRF e loading ausentes | ✅ Corrigido |
| B9 | `configurar SDR` causava resubmissão ao atualizar | ✅ PRG pattern |
| B10 | Remetente hardcoded `contato@krylo.com.br` nos emails | ✅ Usa `email_remetente` do tenant |
| B11 | `enviar_email_brevo()` não verificava HTTP status — marcava enviado mesmo com erro | ✅ Verificação de status |

### 4.3 Performance e infraestrutura

| # | Melhoria | Impacto |
|---|---------|---------|
| P1 | Dashboard: 20+ queries → 4 queries consolidadas | Carregamento ~5× mais rápido |
| P2 | Cache de 5 min nos escalares do dashboard por tenant | Elimina queries desnecessárias |
| P3 | Índices compostos adicionados nas tabelas de alta frequência | JOINs e filtros mais rápidos |
| P4 | Gunicorn: 1 worker síncrono → 2 workers, timeout 120s | Elimina bloqueio de requests concorrentes |
| P5 | `print()` substituído por `logging` estruturado nos módulos SDR | Rastreabilidade em produção |

### 4.4 Funcionalidades novas

| # | Feature | Descrição |
|---|---------|-----------|
| F1 | **Claude Sonnet 4.6** nos pitches SDR | Substitui Haiku — qualidade de texto substancialmente melhor |
| F2 | **Variação A/B** nos pitches | 5 variações rotativas evitam mensagens idênticas em lote |
| F3 | **Enriquecimento CNAE** via receitaws.com.br | Empresas importadas recebem `cnae_codigo` e `cnae_descricao` automaticamente |
| F4 | **Cadência 5 toques** no SDR Evolutivo | D0 email → D3 email → D7 WA → D10 WA → D15 WA |

---

## 5. Estado atual do banco de produção

| Tabela | Registros | Observação |
|--------|-----------|-----------|
| `empresas` | 527 | Dados reais importados, status `prospect`, estado `ES` |
| `contatos` | 533 | 532 com email, 526 com telefone |
| `prospeccao` | 533 | 1:1 com contatos |
| `cadencias` | ~42 | Geradas pelo SDR; antigas inválidas foram deletadas |
| `sdr_log_ao_vivo` | ~2.800 | Crescendo a cada execução — sem política de limpeza |
| `sdr_sessoes` | ~70 | Acumulando |
| `oportunidades` | **0** | Pipeline de vendas não utilizado |
| `atividades` | **0** | Nenhuma atividade manual registrada |
| `rf_empresas` | **0** | Base da Receita Federal vazia — SDR opera via BrasilAPI |
| `prospeccao_automatica` | 0 | SDR autônomo sem dados |
| `clientes_cobranca` | 0 | Módulo de cobrança não utilizado |
| `recebiveis_krylo` | 0 | Módulo financeiro não utilizado |
| `produtos_krylo` | 8 | Vale Refeição, Alimentação, Combustível, Premiação, Welhub, Vidalink, Private Label, Cobrança |

> **Diagnóstico:** O sistema está sendo usado como ferramenta de prospecção e disparo de mensagens — não como CRM de pipeline. `oportunidades = 0` e `atividades = 0` confirmam isso.

---

## 6. Cobertura de segurança atual

| Controle | Status |
|----------|--------|
| CSRF em todos os forms POST | ✅ 100% (verificado por script de varredura) |
| Filtro de `tenant_id` nas queries | ✅ ~97% das rotas (4 rotas de prospecção automática pendentes) |
| `@login_required` em todas as rotas privadas | ✅ OK (portal público por token é intencional) |
| SQL Injection via valores | ✅ Placeholders `?` em todo o código |
| SQL Injection via nomes de coluna | ✅ Whitelist implementada em `atualizar_progresso()` |
| Open Redirect no login | ✅ Corrigido |
| IDOR em oportunidades | ✅ Corrigido |
| IDOR em `/api/empresa/<id>/contato` | ✅ Corrigido hoje |
| Senhas com bcrypt + salt | ✅ OK |
| 2FA disponível | ✅ OK |
| Lockout após 5 tentativas | ✅ OK |
| Rate limiting | ✅ Flask-Limiter ativo |
| `SESSION_COOKIE_SECURE` / `HTTPONLY` / `SAMESITE` | ❌ Não configurados |
| Credenciais no `.env` | ⚠️ **Rotacionar ANTHROPIC_API_KEY, BREVO_API_KEY, DATABASE_URL** |

---

## 7. Variáveis de ambiente do Railway

| Variável | Obrigatória | Status |
|----------|------------|--------|
| `DATABASE_URL` | ✅ Sim | Auto (Railway) |
| `SECRET_KEY` | ✅ Sim | Configurar — chave fixa no `.env` local deve ser rotacionada |
| `ANTHROPIC_API_KEY` | ✅ Sim | **Rotacionar** (chave exposta no `.env` local) |
| `BREVO_API_KEY` | ✅ Sim | **Rotacionar** (idem) |
| `SCHEDULER_OFF` | ⚠️ Recomendado | Setar `1` — sem isso APScheduler roda em cada worker |
| `PORT` | Auto | Railway define automaticamente |
| `APP_URL` | Opcional | Base URL para links do portal do cliente |
| `REDIS_URL` | Opcional | Para rate limiting distribuído (futuro) |

---

## 8. Sprint 2 — Próximos passos

### 8.1 Fazer ANTES do próximo deploy (bloqueadores)

- [ ] **Rotacionar credenciais expostas** — `ANTHROPIC_API_KEY`, `BREVO_API_KEY`, `DATABASE_URL`, `SECRET_KEY` no Railway e gerar novas chaves; atualizar `.env` local
- [ ] **Fazer push** dos 13 commits pendentes → Railway faz deploy automático
- [ ] **Verificar branch no Railway** — confirmar que está monitorando `master`, não `melhoria/modularizar-app`
- [ ] **Setar `SCHEDULER_OFF=1`** no Railway se ainda não estiver — evita APScheduler duplicado

### 8.2 Segurança restante (sprint 2)

- [ ] Adicionar `SESSION_COOKIE_SECURE = True`, `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Strict'` no `app.py`
- [ ] Corrigir as 4 rotas de prospecção automática sem `tenant_id` (`/prospeccao/buscar-automatico` e similares)
- [ ] Implementar rate limiting específico na rota `/portal/<token>` (sem rate limit hoje)
- [ ] Validar CNPJ, email e telefone nos formulários (hoje apenas `.strip()`)

### 8.3 Backup (urgente — 527 empresas sem backup confirmado)

- [ ] Confirmar plano do Railway PostgreSQL — verificar se backup diário está ativo (só no plano Pro)
- [ ] Criar script `scripts/backup.py` que faz `pg_dump` e salva em local seguro
- [ ] Configurar execução diária do backup (Railway cron ou serviço externo)

### 8.4 Base de dados da Receita Federal (diferencial competitivo)

- [ ] Executar `scripts/importar_receita_federal.py` para popular `rf_empresas`
- [ ] Testar SDR com base RF populada — busca por CNAE offline, sem depender de BrasilAPI
- [ ] `cnae_cache` está vazio — cada lookup vai à API externa; implementar cache funcional

### 8.5 Resolver conflito dos dois SDRs

- [ ] Definir oficialmente qual SDR é o principal: **SDR Evolutivo** (recomendado — mais recente) ou **SDR Clássico** (prospeccao_autonoma.py)
- [ ] Deprecar o SDR escolhido para remover; unificar tabelas de log
- [ ] `_normalizar_texto()` duplicada em ambos — mover para `utils.py`

### 8.6 Performance e manutenção

- [ ] Política de limpeza para `sdr_log_ao_vivo` — DELETE de entradas com mais de 30 dias
- [ ] Connection pooling — 3 context processors abrem conexão DB por requisição; usar `flask.g`
- [ ] `flask-sqlalchemy`, `flask-migrate`, `PyPDF2`, `python-docx`, `livereload`, `feedparser` — remover do `requirements.txt` (instalados mas não usados)
- [ ] Implementar sistema de migrations versionado — tabela `schema_versions` + arquivos numerados em `migrations/`

### 8.7 Funcionalidades faltando (roadmap produto)

**Alta prioridade:**
- [ ] **Webhook Brevo** — receber eventos de abertura/clique → atualizar temperatura do lead → acionar próxima etapa da cadência automaticamente
- [ ] **Notificações ao aprovador** — quando uma cadência de WhatsApp entra na fila, notificar o usuário por email (hoje não há nenhum alerta)
- [ ] **Billing real** — integrar Stripe ou Asaas; página de planos atual é mock com link WhatsApp

**Média prioridade:**
- [ ] **Exportação de relatórios PDF/Excel** — pipeline, relatório semanal, cadências
- [ ] **Automações de workflow** — gatilhos "se email aberto → criar tarefa" (engine condicional)
- [ ] **WhatsApp Business API oficial** — substituir `wa.me` manual pela API Meta
- [ ] **Portal do cliente** — rate limiting na rota pública + melhorar experiência

**Baixa prioridade / futuro:**
- [ ] Integração com Google Calendar / Calendly
- [ ] App mobile / PWA
- [ ] API pública documentada com token de acesso
- [ ] Integração LinkedIn para enriquecimento de leads

### 8.8 Qualidade de código

- [ ] Quebrar `app.py` (4.184 linhas) em blueprints por domínio
- [ ] Substituir os ~313 `except Exception: pass` por logging adequado
- [ ] Remover dead code: `views/` (CLI terminal), `main.py`, `extensions.py`
- [ ] Escrever testes — começar pelas funções de score, pitch e criação de cadência

---

## 9. Como fazer deploy

```bash
# Verificar o que vai ser enviado
git log --oneline origin/master..HEAD

# Rodar validação pré-deploy
python scripts/pre_deploy_check.py

# Enviar
git push origin master
# Railway detecta o push e faz deploy automático (~2 min)
```

---

## 10. Estrutura de arquivos relevantes

```
escard-crm-repo/
├── app.py                          # 4.184 linhas — monolito (142 rotas inline)
├── database.py                     # Abstração SQLite/PostgreSQL
├── ai.py                           # Wrapper Anthropic
├── models/
│   ├── prospeccao_autonoma.py      # SDR Clássico (1.512 linhas)
│   ├── sdr_evolutivo.py            # SDR Evolutivo (611 linhas)
│   ├── cadencia.py                 # Criação de etapas de cadência
│   ├── email_service.py            # Brevo
│   ├── usuario.py                  # RBAC (require_perfil)
│   └── ...
├── routes/
│   ├── auth.py                     # Login, 2FA, recuperação de senha
│   ├── empresas.py                 # CRUD empresas
│   ├── contatos.py                 # CRUD contatos
│   └── sdr_evolutivo.py            # Dashboard, executar, configurar
├── templates/                      # 52 arquivos HTML — todos com csrf_token ✅
├── scripts/
│   ├── pre_deploy_check.py         # Validação pré-deploy
│   ├── importar_receita_federal.py # Popular rf_empresas (pendente)
│   └── run_cqa.py                  # Quality assurance automatizado
├── AUDITORIA_KRYLO.md              # Auditoria completa gerada em 2026-05-20
├── DIAGNOSTICO_KRYLO.md            # Diagnóstico técnico detalhado
└── ESTADO_PROJETO_ATUALIZADO.md    # Este arquivo
```

---

## 11. Documentos de referência gerados nesta sessão

| Arquivo | Conteúdo |
|---------|---------|
| `AUDITORIA_KRYLO.md` | Auditoria completa: 149 rotas, 45+ tabelas, segurança, dependências, gaps vs mercado |
| `DIAGNOSTICO_KRYLO.md` | Diagnóstico técnico: arquitetura, performance, SDR, banco, infraestrutura |
| `ESTADO_PROJETO_ATUALIZADO.md` | Este arquivo — estado atual e Sprint 2 |

---

*Gerado em 2026-05-20 após 27 commits e auditoria completa do sistema.*
