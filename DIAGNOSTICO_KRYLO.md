# DIAGNÓSTICO TÉCNICO — KRYLO CRM
**Data:** 2026-05-20  
**Versão analisada:** branch `master`, commit `13c2280`  
**Analista:** Claude Sonnet 4.6  
**Aviso:** este documento é brutal e honesto por design.

---

## ÍNDICE

1. [Arquitetura Geral](#1-arquitetura-geral)
2. [Banco de Dados](#2-banco-de-dados)
3. [Segurança](#3-segurança)
4. [Performance](#4-performance)
5. [SDR e IA](#5-sdr-e-ia)
6. [UX e Produto](#6-ux-e-produto)
7. [Infraestrutura](#7-infraestrutura)
8. [Comparação com o Mercado](#8-comparação-com-o-mercado)
9. [Prioridades](#9-prioridades-o-que-fazer-primeiro)

---

## 1. ARQUITETURA GERAL

### 1.1 Estrutura de arquivos

```
escard-crm-repo/
├── app.py                  ← 4.184 linhas  ← PROBLEMA CRÍTICO
├── database.py             ← 1.352 linhas
├── ai.py                   ← 268 linhas
├── main.py                 ← MORTO (CLI legado com rich/terminal)
├── extensions.py           ← MORTO (importado de lugar nenhum)
├── migrate_ia.py           ← Script solto na raiz — não pertence aqui
├── models/ (23 arquivos)
│   ├── prospeccao_autonoma.py  ← 1.512 linhas
│   ├── cadencia.py             ← 719 linhas
│   ├── sdr_evolutivo.py        ← 611 linhas
│   └── ...
├── routes/ (5 arquivos)    ← Blueprints: apenas auth, empresas, contatos, sdr_evolutivo
├── views/ (5 arquivos)     ← MORTO (CLI terminal nunca removido)
├── templates/ (29 arquivos)
└── scripts/ (7 arquivos)
```

**Total de rotas em `app.py`: 142**
**Total de rotas em blueprints: ~20**
**Total geral: ~162 rotas**

### 1.2 O problema central: `app.py` é um monolito de 4.184 linhas

Este é o maior problema de arquitetura do sistema. `app.py` contém:
- Inicialização do Flask e todas as extensões
- 3 context processors (todos com abertura de DB)
- Lógica de agendamento (APScheduler)
- 142 rotas com lógica de negócio inline
- Queries SQL diretas misturadas com lógica de apresentação
- Duplicação de código entre rotas similares

Comparação: um projeto Flask saudável de escala equivalente teria `app.py` com ~100 linhas (factory function, registro de blueprints) e toda a lógica em módulos especializados.

### 1.3 Dead code acumulado

| Arquivo/Dir | Status | Problema |
|---|---|---|
| `views/` (5 arquivos) | MORTO | CLI interativo com `rich` — jamais carregado pela web |
| `main.py` | MORTO | Ponto de entrada CLI antigo |
| `extensions.py` | MORTO | Não é importado por ninguém |
| `migrate_ia.py` | SOLTO | Script de migração na raiz do projeto |
| `scripts/run_sdr_verbose.py` | TEMPORÁRIO | Script de teste não commitado |

### 1.4 Dois sistemas SDR paralelos e conflitantes

O sistema tem dois módulos de prospecção simultâneos:
- **`models/prospeccao_autonoma.py`** (1.512 linhas): SDR "clássico", orientado a sessões, com `sdr_sessoes`, `sdr_log_ao_vivo`
- **`models/sdr_evolutivo.py`** (611 linhas): SDR "evolutivo", com Radar de Intent, score de prontidão, ecosistema de leads

Ambos criam cadências, ambos têm configurações separadas (`sdr_config` vs `sdr_evolutivo_config`), ambos usam IA. Não está claro qual é o principal. Isso cria confusão de manutenção e risco de dados duplicados.

### 1.5 Separação de responsabilidades (MVC)

**O que existe:**
- `models/` separado com lógica de negócio — correto
- Blueprints em `routes/` — parcialmente correto (só 4 blueprints)
- Templates com Jinja2 — correto

**O que falta:**
- 142 rotas em `app.py` deveriam ser blueprints
- Lógica de negócio inline nas rotas (queries SQL, cálculos, formatação)
- Zero camada de serviço entre rota e model
- `context_processor` com lógica de DB que pertence a um model

### 1.6 Qualidade do código

| Métrica | Valor | Avaliação |
|---|---|---|
| `except Exception` genéricos | 313 ocorrências | CRÍTICO |
| `SELECT *` | 63 ocorrências | ALTO |
| Linhas em `app.py` | 4.184 | CRÍTICO |
| Dead code rastreado | 4 arquivos/diretórios | MÉDIO |
| TODOs/FIXMEs | 0 | Positivo (ou não há, ou foram ignorados) |
| Comentários de código | Escassos | MÉDIO |

**313 blocos `except Exception` é o sinal mais preocupante.** O padrão dominante é:

```python
try:
    # operação crítica
except Exception:
    pass  # ou return {}
```

Isso significa que erros reais — de SQL, de lógica, de rede — são silenciados e o sistema aparenta funcionar quando na verdade está falhando silenciosamente. A rastreabilidade de bugs é muito baixa.

### 1.7 Escalabilidade da arquitetura

**Atual:** 1 processo Gunicorn, 1 worker (Procfile: `web: gunicorn app:app`)  
**Problema:** APScheduler roda in-process com o servidor web. Se Railway escalar para 2 instâncias, os jobs rodam duplicados.  
**Multi-tenant:** implementação por coluna (`tenant_id`) é correta para a escala atual, mas não escala para centenas de tenants sem sharding.

---

## 2. BANCO DE DADOS

### 2.1 Inventário de tabelas (37 tabelas, produção)

| Tabela | Linhas | Obs |
|---|---|---|
| `empresas` | 527 | Dados reais |
| `contatos` | 533 | Dados reais |
| `prospeccao` | 533 | 1:1 com contatos |
| `cadencias` | 42 | Pouco uso |
| `sdr_log_ao_vivo` | 2.772 | **Sem política de limpeza** |
| `sdr_sessoes` | 70 | Acumulando |
| `radar_mercado` | 30 | OK |
| `radar_alertas` | 25 | OK |
| `oportunidades` | **0** | Pipeline vazio — sistema não está sendo usado como CRM |
| `atividades` | **0** | Nenhuma atividade registrada |
| `rf_empresas` | **0** | Tabela da Receita Federal vazia — SDR não tem base |
| `prospeccao_automatica` | **0** | SDR autônomo sem dados |
| `clientes_cobranca` | **0** | Módulo de cobrança não utilizado |
| `recebiveis_krylo` | **0** | Módulo financeiro não utilizado |
| `email_fila` | 0 | Fila de email vazia (ok, já enviados) |
| `cnae_cache` | 0 | Cache vazio — cada lookup vai à API externa |

**Diagnóstico:** O banco tem 527 empresas mas 0 oportunidades e 0 atividades. O produto está sendo usado apenas para prospecção, não como CRM de pipeline/vendas.

### 2.2 Schema — problemas críticos

**Esquema duplo (SQLite legado vs PostgreSQL):**
`database.py` mantém dois schemas DDL: `_SQLITE_DDL` (legado, sem tenant_id em várias tabelas) e `_PG_DDL` (produção, com tenant_id). A função `run_migrations()` aplica alterações incrementais. Esse padrão não é versionado e é frágil — uma mudança aplicada manualmente em produção sem registro no código causa divergência.

**Tabela `prospeccao` sem tenant_id no schema SQLite:**
```sql
-- _SQLITE_DDL — sem tenant_id!
CREATE TABLE IF NOT EXISTS prospeccao (
    id          INTEGER PRIMARY KEY,
    contato_id  INTEGER NOT NULL UNIQUE,
    empresa_id  INTEGER NOT NULL,
    ...
);
```
O PostgreSQL tem tenant_id (adicionado via migration), mas o schema SQLite de dev não. Testes locais ignoram isolamento multi-tenant.

### 2.3 Índices — análise

**Bem cobertos:**
- Índices de `tenant_id` existem nas principais tabelas
- `rf_empresas` tem 5 índices (CNAE, UF, situação) — bem planejado para quando tiver dados

**Faltando:**

| Tabela | Coluna(s) faltando | Impacto |
|---|---|---|
| `contatos` | `empresa_id` (FK sem índice) | JOIN lento em queries de contatos por empresa |
| `cadencias` | `(tenant_id, canal_whatsapp, whatsapp_status)` composto | Query da fila WhatsApp faz full scan |
| `cadencias` | `(tenant_id, etapa, data_acao)` | Cadências do dia: full scan |
| `empresas` | `(tenant_id, status)` | Filtros por status muito comuns |
| `oportunidades` | `(tenant_id, etapa)` | Pipeline por etapa |
| `sdr_log_ao_vivo` | `sessao_id` | Lookup de log por sessão |
| `prospeccao` | `tenant_id` (se não tiver no PG) | Todo o módulo de prospecção |

### 2.4 Queries problemáticas

**1. N+1 no dashboard:**
O dashboard abre uma conexão separada (`conn_m`) e executa 15+ queries em sequência, incluindo subqueries correlacionadas no mesmo statement. A query do funil comercial usa 5 subselects correlacionados:
```sql
SELECT
  (SELECT COUNT(*) FROM prospeccao_automatica WHERE status='novo' AND tenant_id=?) AS sdr_novos,
  (SELECT COUNT(*) FROM cadencias WHERE status='pendente' AND tenant_id=?) AS em_cadencia,
  ...
```
Funciona, mas cada subselect percorre a tabela inteira. Com volume crescente, isso vai degradar.

**2. `SELECT *` em 63 lugares:**
Isso puxa campos TEXT grandes (pitches, emails, logs) desnecessariamente em listagens. Exemplo em `cadencias`: puxa `corpo_email` (pode ter kilobytes) ao listar a fila de WhatsApp.

**3. `sdr_log_ao_vivo` crescendo sem limite:**
2.772 linhas e crescendo a cada execução do SDR. Sem `DELETE` automático, sem `LIMIT` na inserção, sem arquivo de rotação. Em 6 meses com SDR rodando diário pode chegar a 50k+ linhas.

**4. `cnae_cache` vazio:**
Cada lookup de CNAE vai à API externa (BrasilAPI/CNPJ.ws). Sem cache funcional, o SDR faz requisições repetidas para os mesmos CNAEs.

### 2.5 Integridade referencial

**Problema:** FKs declaradas no SQLite DDL mas o PostgreSQL usa `CREATE TABLE IF NOT EXISTS` sem `FOREIGN KEY` constraints explícitas no DDL PG. PostgreSQL tem FKs apenas onde foram adicionadas manualmente. Sem FKs enforçadas, deleção de empresa pode deixar contatos órfãos.

---

## 3. SEGURANÇA

### 3.1 O que está correto ✓

- **Senhas:** bcrypt com salt automático — correto
- **CSRF:** Flask-WTF com `CSRFProtect(app)` — correto, mas há lacunas (ver 3.3)
- **Rate limiting:** 200/dia, 50/hora por IP
- **Bloqueio de conta:** 5 tentativas → 15 minutos de bloqueio
- **2FA:** opcional, por email ou WhatsApp
- **Session lifetime:** 8 horas
- **Login required:** 157 decoradores em rotas
- **RBAC:** 5 níveis (super_admin → visualizador)
- **`.env` não está no git** (`.gitignore` correto)

### 3.2 Vulnerabilidades críticas

**VULN-01: Open Redirect no login**
```python
# routes/auth.py:46
return redirect(request.args.get("next") or url_for("dashboard"))
```
O parâmetro `next` é aceito sem validação. Um atacante pode forjar:
`/login?next=https://site-malicioso.com` e após login o usuário é redirecionado para fora do sistema. Flask-Login tem `is_safe_url()` para isso — não está sendo usado.

**VULN-02: IDOR potencial em oportunidades**
```python
# models/oportunidade.py
def buscar_por_id(id_: int, tenant_id=None):
    sql = "SELECT * FROM oportunidades WHERE id = ?"
    if tenant_id is not None:
        sql += " AND o.tenant_id = ?"
```
`tenant_id` é **opcional**. Rotas que chamam `buscar_por_id(id)` sem passar `tenant_id` retornam registros de qualquer tenant. Precisa verificar se todas as rotas passam o tenant_id corretamente.

**VULN-03: Session fixation na troca de tenant**
Quando `super_admin` entra num tenant (`admin_tenant_entrar`), apenas `session["tenant_id"]` é atualizado. O `current_user` continua sendo o super_admin. Isso é comportamento intencional de impersonação, mas não há "saída do tenant" explícita que garanta limpeza completa da sessão.

**VULN-04: SECRET_KEY efêmera em ambiente sem env var**
```python
if not app.secret_key:
    app.secret_key = secrets.token_hex(32)
    print("[AVISO] SECRET_KEY não configurada - usando chave temporária")
```
Em Railway, se a variável `SECRET_KEY` não estiver configurada, cada restart do servidor invalida todas as sessões de todos os usuários. O aviso vai para stdout onde ninguém lê. Deveria ser um erro fatal que impede o startup.

### 3.3 CSRF — lacunas identificadas

Antes do fix desta sessão, havia vários formulários POST sem CSRF token. O fix foi aplicado incrementalmente (correção reativa vs. auditoria proativa). Recomenda-se uma varredura completa dos templates para identificar todos os `<form method="post">` sem `{{ csrf_token() }}`.

### 3.4 Exposição de dados sensíveis

| Item | Status | Risco |
|---|---|---|
| `.env` no git | NÃO (gitignore) | ✓ OK |
| Credenciais no Railway env vars | SIM (correto) | ✓ OK |
| `SECRET_KEY` logada no stdout | SIM (`[AVISO]...`) | BAIXO |
| Stack traces expostos ao usuário | NÃO detectado | ✓ OK |
| Senhas em logs | NÃO detectado | ✓ OK |

### 3.5 XSS

Jinja2 faz autoescaping por padrão. Não foram encontrados usos de `| safe` ou `Markup()` com dados de usuário. Risco baixo.

---

## 4. PERFORMANCE

### 4.1 Context processors: 3 conexões DB por requisição

```python
@app.context_processor  # abre 1 conexão DB
def _inject_cadencias_badge(): ...

@app.context_processor  # abre 1 conexão DB
def inject_globals(): ...

@app.context_processor  # indiretamente via get_tenant_atual()
def inject_tenant(): ...
```

**Cada página HTML abre no mínimo 3 conexões de banco** apenas para injetar variáveis globais no template. Isso além das conexões das rotas em si. PostgreSQL tem limite de conexões — o Railway Hobby tem 25 conexões máximas por padrão. Com múltiplos usuários simultâneos, isso pode estourar.

**Solução:** `g` do Flask existe exatamente para isso. Calcule na primeira request e cache no `g`.

### 4.2 Dashboard: a rota mais lenta do sistema

A rota `/` (dashboard) executa em sequência:
1. `emp_model.contar_por_status()` → 1 query
2. `op_model.contar_por_estagio()` → 1 query  
3. `op_model.valor_total_pipeline()` → 1 query
4. `atv_model.listar()` → 1 query
5. `op_model.listar_radar()` → 1 query complexa com JOINs
6. `op_model.salvar_scores_radar()` → N UPDATEs (um por oportunidade)
7. `exp_model.potencial_total()` → 1 query
8. `cob_model.resumo()` → 1+ queries
9. `rec_model.resumo_mes()` → 1+ queries
10. `rel_model.coletar_dashboard_extra()` → 3+ queries
11. `pauto_model.resumo_dashboard()` → 1 query
12. Query de meta → 1 query
13. Query de funil (5 subselects) → 1 query
14. Query de oportunidades paradas → 1 query com JOIN

**Total estimado: 20-25 queries no carregamento do dashboard.** Com 0 oportunidades hoje isso é rápido, mas com 1.000 oportunidades vai degradar.

Além disso, `op_model.salvar_scores_radar()` faz **writes** no carregamento de página — anti-pattern. Score deveria ser calculado assincronamente.

### 4.3 Sem nenhum cache

| O que deveria ter cache | Situação atual |
|---|---|
| Contagem de badges (sidebar) | Nova query a cada request |
| Config do tenant | Nova query a cada request |
| Config da IA | Nova query a cada chamada ao Claude |
| Produtos do tenant | Nova query a cada geração de pitch |
| CNAE lookup | `cnae_cache` existe mas está vazio |

Zero uso de Redis, Memcached, ou mesmo Flask-Caching com backend simples.

### 4.4 APScheduler in-process

O scheduler roda no mesmo processo que o Gunicorn. Problemas:
- Consome memória/CPU do web server
- Com múltiplas instâncias (scale horizontal), os jobs rodam N vezes
- Se o processo cai, os jobs param junto

### 4.5 Assets não otimizados

Não foi possível auditar completamente, mas `base.html` carrega Google Fonts externas (Inter, JetBrains Mono) com 2 preconnects. CSS está em `static/css/style.css`. Sem verificação de minificação ou bundling.

---

## 5. SDR E IA

### 5.1 O problema fundamental: `rf_empresas` está vazia

```
rf_empresas: 0 rows
```

O SDR Autônomo (`prospeccao_autonoma.py`) e o SDR Evolutivo (`sdr_evolutivo.py`) dependem de uma base de empresas da Receita Federal (`rf_empresas`). **Essa tabela está completamente vazia.** 

Isso significa que **toda a lógica de busca por CNAE, filtro por estado, score de prontidão baseado em dados reais — não funciona**. O SDR está buscando empresas via BrasilAPI/CNPJ.ws com CNPJs gerados por padrão, o que é:
1. Extremamente ineficiente (requisições HTTP para cada empresa)
2. Não determinístico (resultados diferentes a cada execução)
3. Limitado por rate limiting das APIs externas
4. Sujeito a falha de rede

A tabela `rf_empresas` tem os índices corretos criados. **O sistema foi projetado para funcionar com a base da RF importada, mas nunca foi populada.**

### 5.2 Dois SDRs — duplicação e confusão

| Aspecto | SDR Autônomo | SDR Evolutivo |
|---|---|---|
| Arquivo | `prospeccao_autonoma.py` (1.512 linhas) | `sdr_evolutivo.py` (611 linhas) |
| Config | `sdr_config` | `sdr_evolutivo_config` |
| Log | `sdr_sessoes` + `sdr_log_ao_vivo` | session["sdr_last_exec"] |
| Cadências criadas | SIM | SIM |
| Status | Parece ser o principal | Mais recente/novo |
| Manutenção | Ambos sendo mantidos | Ambos sendo mantidos |

Risco real: ambos podem criar cadências duplicadas para as mesmas empresas se rodarem ao mesmo tempo.

### 5.3 Qualidade dos pitches gerados

**Problema de modelo:** Todas as chamadas ao Claude usam `claude-haiku-4-5-20251001`, o modelo mais barato e menos capaz. Para pitch de vendas B2B onde o texto precisa ser persuasivo e personalizado, Haiku é insuficiente. Resultado: pitches genéricos que soam automatizados.

**Problema de contexto:** O prompt não inclui informações reais da empresa-alvo (histórico, porte, notícias recentes). Com `cnae_codigo` vazio (situação atual de todas as 527 empresas importadas), 100% dos pitches são o template genérico hardcoded, sem IA.

**Problema do `nome_assistente`:** A `ia_config` do tenant 1 tem `nome_assistente = 'Kia'` (herdado dos defaults `'Bia'` que foi sobrescrito). O sistema foi projetado para "Krylo" como produto, não "Escard". Há resíduos de branding Krylo espalhados em defaults hardcoded.

### 5.4 Lógica de cadência

A cadência tem 5 etapas (D0, D3, D7, D10, D15) com mix de email e WhatsApp. 

**Bugs conhecidos corrigidos nesta sessão:**
- Coluna `cnae_fiscal_descricao` inexistente no PostgreSQL
- Remetente hardcoded `contato@krylo.com.br`
- CSRF ausente na aprovação de WhatsApp
- `enviar_email_brevo()` não verificava status HTTP

**Problemas estruturais pendentes:**
- Sem re-tentativa automática para emails que falharam (apenas `tentativas < 3` na fila)
- `email_status` pode ficar em `'sem_email'` indefinidamente sem alertas
- Cadências D7/D10/D15 (WhatsApp) dependem de aprovação manual — sem notificação ao aprovador
- Sem tracking de abertura de email integrado ao pipeline (Brevo abre → atualiza temperatura do lead)

### 5.5 Integração com Anthropic

- **Modelo usado:** `claude-haiku-4-5-20251001` (mais barato, não ideal para vendas)
- **Sem retry lógica:** se a chamada à API falha, retorna string vazia silenciosamente
- **Sem controle de custo:** nenhum tracking de tokens usados, nenhum alerta de gasto
- **Context window:** prompts podem estar excedendo o esperado sem tratamento de erro específico

### 5.6 Integração com Brevo

- **Antes do fix:** não verificava status HTTP — silenciosamente falhava e marcava como enviado
- **Depois do fix:** verifica status, mas sem retry automático
- **Webhook Brevo:** não implementado — não há como saber se o email foi aberto/clicado
- **Sem tracking de bounce/spam:** emails que batem em spam não são tratados

---

## 6. UX E PRODUTO

### 6.1 O estado real do uso

Os dados do banco contam a história:
- **527 empresas, 533 contatos** — dados importados, não captados via CRM
- **0 oportunidades** — ninguém está usando o pipeline de vendas
- **0 atividades** — nenhuma ligação, email, reunião registrada
- **42 cadências** — todas da prospecção automatizada, não do time
- **0 recebiveis, 0 cobranças** — módulos financeiros nunca utilizados

**O Krylo está sendo usado como uma ferramenta de importação e disparo de mensagens, não como CRM.**

### 6.2 Fluxos quebrados ou incompletos

| Fluxo | Status |
|---|---|
| Login → Dashboard | ✓ Funciona |
| Importar empresas CSV | ✓ Funciona |
| Executar SDR | ✓ Funciona (com limitações de dados) |
| Aprovar mensagem WhatsApp | ✓ Corrigido nesta sessão |
| Criar oportunidade manualmente | ? Não testado |
| Fechar negócio → pipeline | ? Não utilizado |
| Portal do cliente | Existe, 1 acesso registrado |
| Módulo de cobrança | Existe, 0 dados |
| Radar de mercado | Parcialmente funciona |
| Relatório semanal | Existe, depende de dados |
| Configuração de planos | UI existe, sem billing real |

### 6.3 Branding Krylo vs Escard

O sistema foi construído como produto SaaS "Krylo" e está sendo usado pela "Escard Cartões". Há resíduos de branding Krylo espalhados:

- Defaults hardcoded: `"Krylo"`, `"contato@krylo.com.br"`, `"Bia | Consultora Krylo"`
- Título do browser: "Krylo CRM" em vários templates
- `ia_config.contexto_empresa` default menciona "Krylo é uma empresa de cartão de benefícios"
- `_TENANT_PADRAO` em `models/tenant.py` tem `"nome_plataforma": "Krylo"`

Para o tenant Escard, esses defaults aparecem quando a configuração não está preenchida.

### 6.4 O que falta para ser um produto SaaS competitivo

**Crítico (bloqueia uso real):**
- [ ] Onboarding guiado que realmente funciona (setup_wizard existe mas é básico)
- [ ] Billing/cobrança real de planos (apenas UI mock)
- [ ] Notificações push/email para o usuário (aprovação de WA, alertas)
- [ ] Documentação e help in-app

**Importante:**
- [ ] Integração nativa com WhatsApp Business API (não wa.me manual)
- [ ] Timeline de atividades por empresa (existe o model, 0 dados)
- [ ] Funil de vendas utilizável (pipeline visual com drag-and-drop)
- [ ] Relatórios exportáveis (existe estrutura, sem dados)
- [ ] App mobile ou pelo menos PWA

**Diferenciação:**
- [ ] `rf_empresas` populada com dados reais da Receita Federal — isso seria um diferencial enorme
- [ ] Score de prontidão real (não aleatório como está)
- [ ] Integração com LinkedIn para enriquecimento de leads

---

## 7. INFRAESTRUTURA

### 7.1 Railway: configuração atual

- **Plano:** desconhecido (provavelmente Hobby ou Pro)
- **Web service:** 1 instância, Gunicorn sem workers configurados
- **PostgreSQL:** Railway Managed PostgreSQL, conectado via `DATABASE_URL`
- **Variáveis de ambiente:** SECRET_KEY, DATABASE_URL, ANTHROPIC_API_KEY, BREVO_API_KEY

**Risco imediato — Gunicorn sem workers:**
```
# Procfile atual:
web: gunicorn app:app
```
Sem `-w N` para workers, Gunicorn usa **1 worker síncrono**. Isso significa que **1 request lenta bloqueia todos os outros usuários**. O dashboard com 20+ queries bloqueia o servidor para o segundo usuário enquanto carrega.

**Fix simples:**
```
web: gunicorn app:app -w 2 --timeout 120
```

### 7.2 Limites de conexão PostgreSQL

Com 3 context processors cada um abrindo conexão + rotas que abrem suas próprias conexões, cada request usa 3-5 conexões. O Railway PostgreSQL Hobby tem **limite de 25 conexões**. Com 5 usuários simultâneos já se aproxima do limite.

**Não há connection pooling** (PgBouncer, SQLAlchemy pool). Cada `database.get_connection()` abre uma conexão nova via `psycopg2.connect()`.

### 7.3 Logs e monitoramento

- **Logging:** apenas `print()` statements — não há logging estruturado
- **Sem Sentry ou similar:** erros em produção são silenciados pelos 313 blocos `except Exception`
- **Railway logs:** disponíveis no dashboard, mas sem alertas configurados
- **Sem `/health` endpoint:** Railway não consegue verificar se o app está saudável; usa apenas port check TCP

### 7.4 Deploy pipeline

- **CI/CD:** push para `master` → Railway detecta e faz rebuild automático
- **Sem testes automatizados:** zero arquivos `test_*.py` ou `*_test.py`
- **Sem staging:** deploys vão direto para produção
- **Sem feature flags:** mudanças de comportamento vão para todos os usuários imediatamente

### 7.5 Backup do banco

**Não identificado nenhum mecanismo de backup configurado no código ou scripts.** O Railway Managed PostgreSQL inclui backups automáticos diários no plano Pro, mas não no Hobby. Se estiver no Hobby e o banco corromper ou for deletado acidentalmente, os dados de 527 empresas e 533 contatos são perdidos.

### 7.6 Dependências desatualizadas e desnecessárias

`requirements.txt` inclui:
- `flask-sqlalchemy>=3.1.0` — **instalado mas nunca usado** (o sistema usa `psycopg2` direto)
- `livereload>=2.6.0` — ferramenta de dev em produção (inócuo mas desnecessário)
- `python-docx`, `PyPDF2`, `Pillow` — funcionalidades de upload de documentos que parecem incompletas
- `rich>=13.0.0` — library de terminal para o dead code `views/` e `main.py`

---

## 8. COMPARAÇÃO COM O MERCADO

### 8.1 O que o Krylo tem que os concorrentes não têm

| Feature | Krylo | RD Station | Pipedrive | HubSpot |
|---|---|---|---|---|
| SDR autônomo com IA | ✓ (limitado) | ✗ | ✗ | Parcial (pago) |
| Pitch gerado por IA por CNAE | ✓ (quando populado) | ✗ | ✗ | ✗ |
| Radar de intent (licitações/editais) | ✓ (beta) | ✗ | ✗ | ✗ |
| Score de prontidão | ✓ (conceito) | Parcial | ✗ | ✗ |
| Ecosistema de leads (empresas relacionadas) | ✓ (conceito) | ✗ | ✗ | ✗ |
| Multi-tenant SaaS | ✓ | ✓ | ✓ | ✓ |
| Foco no mercado brasileiro (CNPJ, CNAE, RF) | ✓ | ✓ | ✗ | ✗ |

### 8.2 O que os concorrentes têm que o Krylo não tem

| Feature | RD Station CRM | Pipedrive | HubSpot Starter |
|---|---|---|---|
| **Pipeline visual drag-and-drop** | ✓ | ✓ | ✓ |
| **Email tracking (aberturas, cliques)** | ✓ | ✓ | ✓ |
| **Integração WhatsApp Business API** | ✓ (via parceiros) | ✓ | ✓ |
| **App mobile** | ✓ | ✓ | ✓ |
| **Relatórios customizáveis** | ✓ | ✓ | ✓ |
| **Automações de workflow** | ✓ | ✓ | ✓ |
| **Billing/assinatura real** | ✓ | ✓ | ✓ |
| **Notificações em tempo real** | ✓ | ✓ | ✓ |
| **API pública documentada** | ✓ | ✓ | ✓ |
| **Onboarding guiado** | ✓ | ✓ | ✓ |
| **Suporte com SLA** | ✓ | ✓ | ✓ |
| **Testes automatizados** | ✓ | ✓ | ✓ |
| **Uptime SLA** | 99.9% | 99.9% | 99.9% |

### 8.3 Análise honesta de posicionamento

**RD Station CRM (mais relevante para o mercado BR):**
- Preço: ~R$50-200/mês por usuário
- Força: integração com marketing digital, mercado BR, suporte PT-BR
- Krylo vs RD: Krylo tem SDR por IA que RD não tem nativamente, mas RD tem anos de refinamento de UX que Krylo não tem

**Pipedrive:**
- Preço: ~$15-49/usuário/mês
- Força: melhor pipeline visual do mercado, simples de usar
- Krylo vs Pipedrive: Krylo tem prospecção autônoma que Pipedrive não tem, mas o pipeline do Krylo (0 oportunidades usadas) não compete

**HubSpot:**
- Preço: Freemium até R$800+/mês
- Força: ecossistema completo marketing+vendas+suporte
- Krylo vs HubSpot: sem comparação — HubSpot é um produto de ~1.000 pessoas desenvolvendo há 15 anos

### 8.4 Onde o Krylo PODE se diferenciar

O único diferencial real e defensável é a combinação:
1. **Base de dados da Receita Federal integrada** — se `rf_empresas` for populada, o SDR pode prospectar qualquer empresa do Brasil por CNAE com 1 clique
2. **Pitch por IA adaptado ao CNAE** — personalização real em escala
3. **Radar de editais/licitações** — interesse governamental não coberto por nenhum CRM mainstream

**O problema:** nenhum desses diferenciais está funcionando hoje. `rf_empresas` = 0 linhas.

### 8.5 Veredito competitivo

Para uma empresa como Escard Cartões que prospecta B2B no Brasil, o Krylo tem um conceito promissor mas está a 6-12 meses de desenvolvimento de ser competitivo como produto. Para uso interno da Escard como ferramenta proprietária de prospecção, já entrega valor — mas está subutilizado (pipeline vazio, sem atividades).

---

## 9. PRIORIDADES — O QUE FAZER PRIMEIRO

### NÍVEL 1 — Crítico (pode quebrar ou vazar dados)

1. **Corrigir Open Redirect** no login (`request.args.get("next")` sem validação)
2. **Auditar IDOR** em todas as rotas que chamam `buscar_por_id` sem `tenant_id`
3. **Configurar Gunicorn com workers**: `web: gunicorn app:app -w 2 --timeout 120`
4. **Verificar backup do banco** — confirmar plano Railway e política de backup
5. **Adicionar `/health` endpoint** para monitoramento do Railway

### NÍVEL 2 — Alto impacto técnico

6. **Resolver problema de connection pooling** — 3 context processors abrindo conexão
7. **Adicionar índice em `contatos.empresa_id`** — FK sem índice
8. **Adicionar índice composto em `cadencias(tenant_id, canal_whatsapp, whatsapp_status)`**
9. **Política de limpeza para `sdr_log_ao_vivo`** — DELETE de entradas > 30 dias
10. **Resolver dois SDRs** — escolher um e deprecar o outro, ou unificar

### NÍVEL 3 — Qualidade e manutenção

11. **Quebrar `app.py` em blueprints** — pelo menos agrupar por domínio
12. **Remover dead code** — `views/`, `main.py`, `extensions.py`, `migrate_ia.py`
13. **Substituir `except Exception: pass`** pelos 313 blocos — pelo menos logar o erro
14. **Implementar logging estruturado** (Python `logging`, não `print()`)
15. **Adicionar Sentry** para rastreamento de erros em produção

### NÍVEL 4 — Produto e diferenciação

16. **Popular `rf_empresas`** — importar base da Receita Federal; isso desbloqueia o diferencial competitivo real
17. **Implementar webhook Brevo** — abertura de email → atualiza temperatura do lead
18. **Unificar branding Escard** — eliminar todos os defaults "Krylo/Bia/Krylo CRM"
19. **Escrever testes** — começar pelas funções de score e pitch
20. **Usar Claude Sonnet em vez de Haiku** para geração de pitches comerciais

---

*Diagnóstico gerado em 2026-05-20. Dados coletados diretamente do repositório e banco de produção Railway.*
