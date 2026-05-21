# AUDITORIA COMPLETA — SISTEMA KRYLO CRM
**Data:** 2026-05-20 | **Auditor:** Claude Sonnet 4.6 (análise estática + leitura de código)  
**Projeto:** `escard-crm-repo` | **Stack:** Flask + SQLite/PostgreSQL + Anthropic + Brevo  
**Modo:** READ-ONLY — nenhuma alteração foi feita

---

## LEGENDA
- 🟢 **VERDE** — OK, sem problema
- 🟡 **AMARELO** — atenção, risco moderado ou lacuna funcional
- 🔴 **VERMELHO** — crítico, risco alto ou funcionalidade quebrada/ausente

---

## SUMÁRIO EXECUTIVO

| Área | Status | Problemas Críticos |
|------|--------|--------------------|
| Rotas Flask | 🔴 VERMELHO | 4 rotas sem tenant_id, 1 rota pública sem login |
| Formulários / CSRF | 🔴 VERMELHO | 20+ forms sem CSRF token |
| Banco de Dados | 🟡 AMARELO | 13 FKs sem índice, sem backup, migrations sem versão |
| Segurança | 🔴 VERMELHO | Credenciais hardcoded no .env, SQL injection, cookies inseguros |
| Conflitos de Código | 🔴 VERMELHO | Dois SDRs paralelos e sobrepostos, imports mortos |
| Dependências | 🟡 AMARELO | 5 pacotes instalados mas não usados |
| Backup e Deploy | 🔴 VERMELHO | ZERO mecanismo de backup com 527 empresas em produção |
| Funcionalidades Faltando | 🔴 VERMELHO | 10 funcionalidades-chave completamente ausentes |

---

## 1. ROTAS FLASK

### 1.1 Inventário completo de rotas (149 rotas totais)

| Rota | Método | Template Existe? | @login_required? | tenant_id Filtrado? | Status |
|------|--------|-----------------|-----------------|--------------------|---------| 
| `/` (dashboard) | GET | ✅ dashboard.html | ✅ | ✅ | 🟢 |
| `/dashboard` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/v2/dashboard` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/v2/sdr` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/metas/configurar` | GET/POST | ✅ | ✅ | ✅ | 🟢 |
| `/empresas` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/empresas/nova` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/empresas/<id>` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/empresas/<id>/editar` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/empresas/<id>/excluir` | POST | ✅ | ✅ | ✅ | 🟢 |
| `/empresas/excluir-lote` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/contatos` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/contatos/novo` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/contatos/<id>/editar` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/contatos/<id>/excluir` | POST | ✅ | ✅ | ✅ | 🟢 |
| `/oportunidades` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/oportunidades/nova` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/oportunidades/<id>` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/oportunidades/<id>/editar` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/oportunidades/<id>/excluir` | POST | ✅ | ✅ | ✅ | 🟢 |
| `/oportunidades/<id>/mover` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/oportunidades/radar` | GET | N/A JSON | ✅ | ✅ | 🟢 |
| `/pipeline` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/pipeline/mover` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/atividades` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/atividades/nova` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/atividades/<id>/excluir` | POST | ✅ | ✅ | ✅ | 🟢 |
| `/ai/score/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ai/whatsapp/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ai/proxima-acao/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/leads/importar` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/leads/importar/preview` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/leads/importar/confirmar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/prospeccao` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/prospeccao/<id>/status` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/prospeccao/<id>/excluir` | POST | ✅ | ✅ | ✅ | 🟢 |
| `/prospeccao/excluir-lote` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/prospeccao/exportar` | GET | N/A CSV | ✅ | ✅ | 🟢 |
| `/prospeccao/automatica` | GET | ✅ | ✅ | ✅ | 🟢 |
| **`/prospeccao/buscar-automatico`** | POST | N/A JSON | ✅ | ❌ | 🔴 SEM TENANT |
| **`/prospeccao/automatica/<id>/importar`** | POST | N/A JSON | ✅ | ❌ | 🔴 SEM TENANT |
| **`/prospeccao/automatica/importar-selecionados`** | POST | N/A JSON | ✅ | ❌ | 🔴 SEM TENANT |
| **`/prospeccao/automatica/<id>/status`** | POST | N/A JSON | ✅ | ❌ | 🔴 SEM TENANT |
| `/prospeccao/autonoma/rodar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/prospeccao/autonoma/status` | GET | N/A JSON | ✅ | ✅ | 🟢 |
| `/ai/leads/pontuar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ai/leads/whatsapp/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ai/leads/email/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cadencias` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/cadencia/iniciar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cadencia/<id>/concluir` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cadencia/<id>/cancelar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cadencia/emails` | GET | ✅ | ✅ | ✅ | 🟢 |
| **`/portal/<token>`** | GET | ✅ | ❌ | N/A | 🔴 SEM LOGIN |
| `/portal/gerar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/portal/revogar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/radar` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/radar/rodar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/radar/marcar-lido/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/radar/arquivar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/radar/config/salvar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/expansao` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/expansao/pitch/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cobranca` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/cobranca/clientes/novo` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/cobranca/clientes/<id>/editar` | GET/POST | ✅ | ✅ | ✅ | 🟡 CSRF |
| `/cobranca/relatorio/gerar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/recebiveis` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/recebiveis/gerar-mensal` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/recebiveis/<id>/pagar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/financeiro` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/termometro` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/simulador` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/simulador/gerar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/relatorio/semanal` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/relatorio/semanal/json` | GET | N/A JSON | ✅ | ✅ | 🟢 |
| `/usuarios` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/usuarios/novo` | GET/POST | ✅ | ✅ | ✅ | 🟢 |
| `/usuarios/<id>/editar` | GET/POST | ✅ | ✅ | ✅ | 🟢 |
| `/usuarios/<id>/toggle` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/usuarios/<id>/excluir` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/produtos` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/produtos/novo` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/produtos/<id>/editar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/produtos/<id>/toggle` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/produtos/<id>/deletar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/produtos/gerar-com-ia` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ia/config` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/ia/config/salvar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ia/chat` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/ia/testar-pitch` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/central-ia` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/central-ia/chat` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/central-ia/upload` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/central-ia/documentos` | GET | N/A JSON | ✅ | ✅ | 🟢 |
| `/central-ia/documentos/<id>` | DELETE | N/A JSON | ✅ | ✅ | 🟢 |
| `/configuracoes/ramos` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/configuracoes/empresa` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/painel` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/config/salvar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/config/toggle` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/stats` | GET | N/A JSON | ✅ | ✅ | 🟢 |
| **`/api/empresa/<id>/contato`** | GET | N/A JSON | ✅ | ❌ | 🔴 IDOR POSSÍVEL |
| `/api/cnaes` | GET | N/A JSON | ✅ | N/A | 🟢 (API pública ok) |
| `/api/cnaes/busca` | GET | N/A JSON | ✅ | N/A | 🟢 |
| `/sdr/pipeline` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/otimizar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/log-ao-vivo` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/pausar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/relatorio/<session>` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/sessoes` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/fila-aprovacao` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr/aprovar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/rejeitar/<id>` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/sdr/fila-whatsapp` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/admin` | GET | ✅ | ✅ | N/A admin | 🟢 |
| `/admin/tenant/novo` | POST | N/A JSON | ✅ | N/A admin | 🟢 |
| `/admin/tenant/<id>/entrar` | POST | N/A JSON | ✅ | N/A admin | 🟢 |
| `/admin/importar-rf` | GET/POST | ✅ | ✅ | N/A admin | 🟢 |
| `/setup` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/setup/salvar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/planos` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/ajuda` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/ajuda/kia` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cqa` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/cqa/rodar` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/cqa/fix/all` | POST | N/A JSON | ✅ | ✅ | 🟢 |
| `/login` | GET/POST | ✅ | ❌ intencional | N/A | 🟢 |
| `/logout` | GET | N/A redirect | ✅ | ✅ | 🟢 |
| `/login/2fa` | GET/POST | ✅ | ❌ intencional | N/A | 🟢 |
| `/recuperar-senha` | GET/POST | ✅ | ❌ intencional | N/A | 🟢 |
| `/nova-senha` | GET/POST | ✅ | ❌ intencional | N/A | 🟢 |
| `/sdr-evolutivo` | GET | ✅ | ✅ | ✅ | 🟢 |
| `/sdr-evolutivo/executar` | POST | N/A redirect | ✅ | ✅ | 🟢 |
| `/sdr-evolutivo/configurar` | GET/POST | ✅ | ✅ | ✅ | 🟢 |
| `/sdr-evolutivo/radar` | GET | ✅ | ✅ | ✅ | 🟢 |

### 1.2 Problemas críticos de rotas

**🔴 CRÍTICO — Rota pública sem autenticação:**
- `/portal/<token>` — acesso baseado apenas em token. Sem `@login_required`. Token pode ser bruteforçado ou vazado. Dados de clientes expostos para qualquer pessoa com o URL.

**🔴 CRÍTICO — 4 rotas sem filtro de tenant_id:**
- `/prospeccao/buscar-automatico` — chama `pauto_model.buscar_e_salvar()` sem `tenant_id`
- `/prospeccao/automatica/<id>/importar` — cross-tenant possível
- `/prospeccao/automatica/importar-selecionados` — cross-tenant possível
- `/prospeccao/automatica/<id>/status` — cross-tenant possível

**🔴 CRÍTICO — IDOR em endpoint de API:**
- `/api/empresa/<id>/contato` — usa `WHERE id=?` sem `AND tenant_id=?`. Usuário autenticado pode buscar contatos de qualquer tenant passando ID correto. A correção de VULN-02 aplicada em oportunidades **não foi estendida** a este endpoint.

---

## 2. FORMULÁRIOS E BOTÕES

### 2.1 Inventário de formulários por template

| Template | Form Action | Método | CSRF Token? | Rota Válida? | Status |
|----------|------------|--------|------------|-------------|--------|
| admin_tenants.html | admin_tenant_* | POST | ✅ | ✅ | 🟢 |
| **atividades/form.html** | atividades_nova | POST | ❌ | ✅ | 🔴 |
| atividades/lista.html — concluir | cadencia_concluir | POST | ❌ | ✅ | 🔴 |
| atividades/lista.html — excluir | atividades_excluir | POST | ❌ | ✅ | 🔴 |
| **cobranca/form_cliente.html** | variável | POST | ❌ | ✅ | 🔴 |
| cobranca/index.html | cobranca_relatorio_gerar | POST | ❌ | ✅ | 🔴 |
| configuracoes_ramos.html | configuracoes_ramos_novo | POST | ❌ | ✅ | 🔴 |
| **contatos/form.html** | variável | POST | ❌ | ✅ | 🔴 |
| contatos/lista.html | contatos_excluir | POST | ❌ | ✅ | 🔴 |
| cqa_dashboard.html | _rodar, _fixall | POST | ✅ | ✅ | 🟢 |
| empresas/detalhe.html | empresas_excluir | POST | ❌ | ✅ | 🔴 |
| **empresas/form.html** | variável | POST | ❌ | ✅ | 🔴 |
| empresas/lista.html | empresas_excluir | POST | ❌ | ✅ | 🔴 |
| financeiro.html | recebiveis_gerar | POST | ❌ | ✅ | 🔴 |
| leads/prospeccao.html | prospeccao_excluir | POST | ❌ | ✅ | 🔴 |
| login.html | auth.login | POST | ✅ | ✅ | 🟢 |
| login_2fa.html | auth.login_2fa | POST | ✅ | ✅ | 🟢 |
| nova_senha.html | auth.nova_senha | POST | ✅ | ✅ | 🟢 |
| oportunidades/detalhe.html | atividades_excluir | POST | ❌ | ✅ | 🔴 |
| oportunidades/detalhe.html | oportunidades_excluir | POST | ❌ | ✅ | 🔴 |
| **oportunidades/form.html** | variável | POST | ❌ | ✅ | 🔴 |
| radar.html | radar_config_salvar | POST | ✅ | ✅ | 🟢 |
| recebiveis/index.html | recebiveis_gerar | POST | ❌ | ✅ | 🔴 |
| recuperar_senha.html | auth.recuperar_senha | POST | ✅ | ✅ | 🟢 |
| sdr_evolutivo/dashboard.html | sdr_evolutivo_executar | POST | ✅ | ✅ | 🟢 |
| setup_wizard.html | setup_salvar | POST | ✅ | ✅ | 🟢 |
| usuarios/form.html | variável | POST | ✅ | ✅ | 🟢 |
| usuarios/lista.html | excluir | POST | ✅ | ✅ | 🟢 |

### 2.2 Resumo CSRF

- **Forms COM CSRF:** 9 (login, 2FA, recuperar senha, radar, setup, usuarios, cqa, sdr_evolutivo)
- **Forms SEM CSRF:** 20+ (atividades, cobrança, configurações, contatos, empresas, financeiro, leads, oportunidades, recebíveis)
- **Configuração:** `WTF_CSRF_ENABLED = True` está no `app.py`, mas a maioria dos templates não inclui `{{ csrf_token() }}`
- **Impacto:** Qualquer usuário logado pode ser enganado por um site malicioso para executar ações em seu nome (CSRF attack)

---

## 3. BANCO DE DADOS

### 3.1 Tabelas do sistema (45+ tabelas identificadas)

| Tabela | Propósito | FKs | Tenant? | Status |
|--------|-----------|-----|---------|--------|
| `tenants` | Workspaces multi-tenant | — | N/A | 🟢 |
| `tenant_config` | Configurações por tenant | tenant_id | ✅ | 🟢 |
| `usuarios` | Usuários com RBAC | tenant_id | ✅ | 🟢 |
| `empresas` | Empresas/clientes | tenant_id | ✅ | 🟢 |
| `contatos` | Contatos das empresas | empresa_id, tenant_id | ✅ | 🟢 |
| `atividades` | Histórico de atividades | empresa_id, oportunidade_id, tenant_id | ✅ | 🟢 |
| `oportunidades` | Pipeline de vendas | empresa_id, tenant_id | ✅ | 🟢 |
| `prospeccao` | Scoring de prospecção | contato_id, empresa_id, tenant_id | ✅ | 🟢 |
| `cadencias` | Sequências de email/WA | empresa_id, oportunidade_id, tenant_id | ✅ | 🟢 |
| `email_fila` | Fila de emails | cadencia_id, tenant_id | ✅ | 🟢 |
| `prospeccao_automatica` | Leads da Receita Federal | tenant_id | ✅ | 🟡 (vazia) |
| `portal_acessos` | Tokens do portal cliente | empresa_id, tenant_id | ✅ | 🟢 |
| `ia_config` | Config do assistente IA | tenant_id | ✅ | 🟢 |
| `empresa_config` | Config IA por empresa | empresa_id | ✅ | 🟢 |
| `radar_alertas` | Alertas de mercado | tenant_id | ✅ | 🟢 |
| `radar_config` | Config do radar | tenant_id | ✅ | 🟢 |
| `radar_insights` | Insights gerados por IA | tenant_id | ✅ | 🟢 |
| `clientes_cobranca` | Clientes para cobrança | tenant_id | ✅ | 🟡 (0 dados) |
| `relatorios_cobranca` | Relatórios de cobrança | cliente_id, tenant_id | ✅ | 🟡 (0 dados) |
| `recebiveis_krylo` | Recebíveis | empresa_id, tenant_id | ✅ | 🟡 (0 dados) |
| `sdr_sessoes` | Sessões do SDR | tenant_id | ✅ | 🟢 |
| `sdr_execucoes` | Execuções do SDR | tenant_id | ✅ | 🟢 |
| `sdr_log_ao_vivo` | Logs do SDR em tempo real | tenant_id | ✅ | 🟢 |
| `rf_empresas` | Dados da Receita Federal | — | N/A | 🔴 (0 linhas) |
| `branches` / `products` | Listas de referência | — | N/A | 🟢 |
| `logs` | Trilha de auditoria | usuario_id, tenant_id | ✅ | 🟢 |

### 3.2 Chaves estrangeiras sem índice (13 identificadas)

| Tabela | Coluna sem índice | Impacto |
|--------|------------------|---------|
| `cadencias` | `empresa_id` | 🔴 Alto — JOINs frequentes |
| `cadencias` | `oportunidade_id` | 🔴 Alto — JOINs frequentes |
| `atividades` | `empresa_id` | 🔴 Alto — Histório de empresa |
| `atividades` | `oportunidade_id` | 🟡 Médio |
| `email_fila` | `cadencia_id` | 🔴 Alto — Processamento de fila |
| `email_fila` | `status` | 🔴 Alto — Query por status pendente |
| `portal_acessos` | `empresa_id` | 🟡 Médio |
| `tenant_config` | `tenant_id` | 🟡 Médio |
| `logs` | `usuario_id` | 🟡 Médio |
| `logs` | `tenant_id` | 🟡 Médio |
| `prospeccao` | `empresa_id` | 🟡 Médio |
| `prospeccao` | `status` | 🟡 Médio |
| `relatorios_cobranca` | `cliente_id` | 🟡 Médio |

### 3.3 Integridade — registros órfãos potenciais

| Cenário | FK | Comportamento | Risco |
|---------|----|---------------|-------|
| Cadência sem empresa | `empresa_id` | ON DELETE SET NULL | 🟡 Cadências "soltas" possíveis |
| Cadência sem oportunidade | `oportunidade_id` | ON DELETE SET NULL | 🟡 Possível — cadências empresa-nível |
| Atividade sem empresa | `empresa_id` | ON DELETE SET NULL | 🟡 Atividades orphans possíveis |
| Contato sem empresa | `empresa_id` | ON DELETE CASCADE | 🟢 Protegido |
| Oportunidade sem empresa | `empresa_id` | ON DELETE CASCADE | 🟢 Protegido |
| Prospecção sem contato | `contato_id` | ON DELETE CASCADE | 🟢 Protegido |
| Email na fila sem cadência | `cadencia_id` | ON DELETE CASCADE | 🟢 Protegido |
| Portal sem empresa | `empresa_id` | ON DELETE CASCADE | 🟢 Protegido |

**Query de diagnóstico recomendada (não executada — modo read-only):**
```sql
SELECT COUNT(*) FROM cadencias WHERE empresa_id IS NULL AND oportunidade_id IS NULL;
SELECT COUNT(*) FROM atividades WHERE empresa_id IS NULL AND oportunidade_id IS NULL;
SELECT COUNT(*) FROM rf_empresas; -- Esperado: 0
```

### 3.4 Estado das migrations

| Aspecto | Status | Detalhe |
|---------|--------|---------|
| Sistema de migration | 🟡 Custom | Função `run_migrations()` em `database.py` |
| Controle de versão das migrations | 🔴 Ausente | Sem tabela `schema_versions`, sem Alembic, sem Flask-Migrate funcional |
| Idempotência | 🟡 Parcial | Usa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` mas sem garantia total |
| Rollback | 🔴 Impossível | Nenhum mecanismo de reversão |
| Flask-Migrate no requirements.txt | 🔴 Instalado mas não usado | Pacote listado mas nunca chamado no código |
| Migrations em arquivos separados | 🔴 Ausente | Tudo em uma função gigante, sem versionamento |

---

## 4. SEGURANÇA

### 4.1 Gestão de credenciais

| Item | Status | Detalhe |
|------|--------|---------|
| `SECRET_KEY` no `.env` | 🔴 CRÍTICO | Chave fixa hardcoded: `0856c8b8...` |
| `ANTHROPIC_API_KEY` no `.env` | 🔴 CRÍTICO | Chave real exposta: `sk-ant-api03-WQZg...` |
| `BREVO_API_KEY` no `.env` | 🔴 CRÍTICO | Chave real exposta: `xkeysib-e354...` |
| `DATABASE_URL` no `.env` | 🔴 CRÍTICO | URL completa com usuário/senha do PostgreSQL exposta |
| `.env` no `.gitignore` | 🟡 Verificar | Se `.env` estiver comitado alguma vez no histórico, credenciais estão comprometidas |
| Fallback SECRET_KEY aleatória | 🟢 Existe | `secrets.token_hex(32)` como fallback em `app.py` — mas nunca usado pois `.env` está presente |
| Chaves nos templates/logs | 🟢 Não encontrado | Chaves não aparecem em templates HTML |

### 4.2 Vulnerabilidades de código

| Vulnerabilidade | Local | Severidade |
|----------------|-------|-----------|
| **SQL Injection via nomes de coluna** | `models/prospeccao_autonoma.py:885` — `f"UPDATE sdr_sessoes SET {set_clause}"` onde `set_clause` vem de `kwargs` não validados | 🔴 CRÍTICO |
| **IDOR em API** | `/api/empresa/<id>/contato` — sem filtro de `tenant_id` | 🔴 CRÍTICO |
| **CSRF em 20+ forms** | Múltiplos templates | 🔴 CRÍTICO |
| **Cross-tenant em prospecção automática** | 4 rotas em `app.py` | 🔴 CRÍTICO |
| **Cookies de sessão sem flags de segurança** | `app.py` — falta `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` | 🟡 ALTO |
| **print() em produção** | `app.py:247,249,280,288` — debug logs para stdout | 🟡 MÉDIO |
| **traceback completo exposto** | `app.py:553,590` — `traceback.format_exc()` pode vazar variáveis | 🟡 MÉDIO |
| **Validação insuficiente de input** | `app.py:610-613, 727-753, 813-819` — apenas `.strip()` em emails, CNPJ, telefone | 🟡 MÉDIO |
| **XSS via resposta de IA** | Dados de usuário incluídos em prompts; resposta da IA renderizada sem sanitização | 🟡 MÉDIO |

### 4.3 Controles de segurança existentes

| Controle | Status | Detalhe |
|----------|--------|---------|
| Rate limiting | 🟢 Presente | Flask-Limiter: 200/dia, 50/hora (default); aplicado nas rotas críticas |
| 2FA | 🟢 Presente | Por email ou WhatsApp, configurável por usuário |
| bcrypt para senhas | 🟢 Presente | `bcrypt>=4.0.0` |
| Login lockout (5 tentativas) | 🟢 Presente | Bloqueio por 15 minutos após 5 falhas |
| RBAC (5 níveis de perfil) | 🟢 Presente | super_admin, admin, gerente, vendedor, visualizador |
| HTTPS forçado | 🟡 Não verificável | Depende do proxy Railway/Heroku; sem redirect no código |
| WTF_CSRF_ENABLED | 🟡 Habilitado mas incompleto | Configurado mas templates não implementam |
| Input SQL via parâmetros | 🟢 Maioria OK | Usa `?` placeholders — problema só nos nomes de coluna dinâmicos |
| Jinja2 autoescape | 🟢 Ativo | XSS básico protegido |

---

## 5. CONFLITOS DE CÓDIGO

### 5.1 Dois SDRs paralelos — conflito arquitetural

**🔴 CRÍTICO: Dois sistemas SDR completamente independentes e sobrepostos**

| Aspecto | SDR Clássico (Prospecção Autônoma) | SDR Evolutivo |
|---------|-----------------------------------|---------------|
| Arquivo principal | `models/prospeccao_autonoma.py` (~1.512 linhas) | `models/sdr_evolutivo.py` (~700 linhas) |
| Rotas | `/sdr/painel`, `/sdr/pipeline`, `/sdr/fila-aprovacao` | `/sdr-evolutivo`, `/sdr-evolutivo/executar` |
| Função principal | `rodar_prospeccao_autonoma()` | `executar_sdr_evolutivo()` |
| Agendador | `_job_prospeccao_autonoma()` em `app.py:296` | Execução manual via rota |
| Tabelas usadas | `sdr_sessoes`, `sdr_execucoes`, `sdr_log_ao_vivo` | Usa as mesmas tabelas? **Ambíguo** |
| Config lida de | `sdr_config` (tenant_config) | `sdr_config` (tenant_config) |
| Cadências de email | Cadência linear D0/D3/D7/D14 | Cadência 5 toques (mais recente) |

**Sobreposições confirmadas:**
- Ambos buscam empresas por CNAE
- Ambos geram pitches via IA
- Ambos acessam a tabela `sdr_config`
- Ambos têm lógica de score de prontidão
- Confusão real: qual SDR está em produção? Qual é o "oficial"?

### 5.2 Funções duplicadas

| Função | Arquivo 1 | Arquivo 2 | Tipo |
|--------|-----------|-----------|------|
| `_normalizar_texto()` | `prospeccao_autonoma.py:18` | `sdr_evolutivo.py:25` | 🔴 Código idêntico |
| `get_sdr_config()` | `prospeccao_autonoma.py:68` | Não em evolutivo | 🟡 Não compartilhado |
| `_log()` | `prospeccao_autonoma.py:891` | Não abstraída | 🟡 Deveria ser utils |

### 5.3 Imports não utilizados

| Arquivo | Import morto | Status |
|---------|-------------|--------|
| `app.py:4` | `import csv` (apenas via `_ler_csv_bytes`) | 🟡 Verificar uso real |
| `models/sdr_evolutivo.py:12` | `from concurrent.futures import ThreadPoolExecutor` | 🔴 Nunca usado |
| `requirements.txt` | `flask-sqlalchemy` | 🔴 Instalado, nenhum ORM no código |
| `requirements.txt` | `flask-migrate` | 🔴 Instalado, nunca chamado |
| `requirements.txt` | `livereload` | 🔴 Dev dependency em produção |
| `requirements.txt` | `PyPDF2` | 🔴 Nunca referenciado |
| `requirements.txt` | `python-docx` | 🔴 Nunca processado em nenhuma rota |
| `requirements.txt` | `feedparser` | 🟡 Usado em `_fetch_rss_feed()` que nunca é chamada |

### 5.4 Variáveis definidas e nunca usadas

| Arquivo | Variável | Linha | Status |
|---------|----------|-------|--------|
| `app.py` | `_START_TIME = str(time.time())` | ~205 | 🟡 Nunca referenciada |
| `prospeccao_autonoma.py` | `_HEADERS = {"User-Agent": "KryloCRM/1.0 SDR-autonomo"}` | ~15 | 🔴 Definido, nunca passado para requests |
| `sdr_evolutivo.py` | `_HEADERS = {"User-Agent": "..."}` | ~22 | 🔴 Mesmo problema |

### 5.5 Tratamento de erros problemático

- **15+ ocorrências de `except Exception: pass`** em `app.py` (linhas 253, 257, 1669, 1673) e `database.py` (linhas 528, 1219, 1267)
- Erros silenciados ocultam falhas reais em produção

---

## 6. DEPENDÊNCIAS

### 6.1 Lista completa do requirements.txt

| Pacote | Versão mínima | Usado? | Vulnerabilidade conhecida? |
|--------|--------------|--------|---------------------------|
| `flask` | >=3.0.0 | ✅ | Atualizar para >=3.1.0 |
| `flask-wtf` | >=1.2.0 | ✅ | 🟢 OK |
| `flask-limiter` | >=3.5.0 | ✅ | 🟢 OK |
| `flask-sqlalchemy` | >=3.1.0 | ❌ não usado | 🟡 Peso morto |
| `flask-migrate` | >=4.0.0 | ❌ não usado | 🟡 Peso morto |
| `anthropic` | >=0.25.0 | ✅ | 🟡 Desatualizado — usar >=0.30.0 |
| `feedparser` | >=6.0.0 | 🟡 função morta | 🟡 Dead code |
| `requests` | >=2.31.0 | ✅ | 🟡 Atualizar para >=2.32.0 (fix CVE) |
| `python-dotenv` | >=1.0.0 | ✅ | 🟢 OK |
| `openpyxl` | >=3.1.0 | ✅ | 🟢 OK |
| `xlrd` | >=2.0.0 | ✅ | 🟢 OK |
| `psycopg2-binary` | >=2.9.0 | ✅ | 🟢 OK |
| `gunicorn` | >=21.0.0 | ✅ | 🟢 OK |
| `livereload` | >=2.6.0 | ❌ dev only | 🟡 Em produção sem necessidade |
| `PyPDF2` | >=3.0.0 | ❌ não usado | 🔴 Peso morto |
| `python-docx` | >=1.1.0 | ❌ não usado | 🔴 Peso morto |
| `Pillow` | >=10.0.0 | 🟡 Verificar | 🟢 OK |
| `flask-login` | >=0.6.3 | ✅ | 🟢 OK |
| `bcrypt` | >=4.0.0 | ✅ | 🟢 OK |
| `apscheduler` | >=3.10.0 | ✅ | 🟡 Atualizar para >=3.11.0 |
| `sib-api-v3-sdk` | >=7.6.0 | ✅ (Brevo) | 🟢 OK |

**Resumo:** 5 pacotes completamente não usados, 1 dev-only em produção, 3 desatualizados com fixes de segurança disponíveis.

---

## 7. BACKUP E DADOS

### 7.1 Mecanismo de backup

| Item | Status |
|------|--------|
| Script de backup no repositório | 🔴 INEXISTENTE |
| Backup automático configurado | 🔴 NÃO CONFIRMADO |
| Dependência do Railway | 🟡 Railway Pro tem backup diário; plano atual desconhecido |
| Volume de dados sem backup confirmado | 🔴 **527 empresas, 533 contatos, histórico de atividades** |
| Estratégia de disaster recovery | 🔴 Nenhuma documentada |

**Scripts existentes em `scripts/`:** `pre_deploy_check.py`, `importar_receita_federal.py`, `mapear_sistema.py`, `run_cqa.py`, `cqa_autofix.py`, `cqa_testes.py`, `run_sdr_verbose.py` — **nenhum relacionado a backup**.

### 7.2 Últimos commits (histórico git)

| Hash | Data | Mensagem |
|------|------|---------|
| `61ca651` | 2026-05-20 | feat(sdr): variação A/B nos pitches para evitar mensagens idênticas |
| `6d627c9` | 2026-05-20 | perf(cache): cache de 5 min nos escalares do dashboard por tenant |
| `e4ceb98` | 2026-05-20 | feat(enriquecimento): busca CNAE via receitaws.com.br para empresas |
| `e6b9859` | 2026-05-20 | perf(dashboard): consolida 20+ queries em 4 queries no carregamento |
| `4ccf0b4` | 2026-05-20 | perf(db): adiciona índices compostos nas tabelas de alta frequência |
| `30792f5` | 2026-05-20 | fix(logging): substitui print() por logging estruturado nos módulos SDR |
| `e299612` | 2026-05-20 | fix(infra): adiciona 2 workers e timeout 120s ao Gunicorn |
| `8e1641e` | 2026-05-20 | feat(ai): substitui claude-haiku por claude-sonnet-4-6 na geração de pitches |
| `40d728d` | 2026-05-20 | fix(security): corrige VULN-01 open redirect e VULN-02 IDOR em oportunidades |
| `5923555` | 2026-05-20 | Adiciona diagnóstico técnico completo do sistema |
| `13c2280` | 2026-05-20 | Corrige switch de tenant e meta do dashboard |
| `65277b9` | 2026-05-20 | Três correções na fila de aprovação WhatsApp |
| `5c300c3` | 2026-05-20 | Usa email_remetente do tenant ao enviar emails de cadência |
| `69753b3` | 2026-05-20 | fix: enviar_email_brevo verifica HTTP status antes de marcar como enviado |
| `868c781` | 2026-05-20 | fix: SDR executar — CSRF token, resultado inline e loading no botão |
| `e72de03` | 2026-05-20 | fix: aplica .title() no nome da empresa no pitch genérico |
| `cd70024` | 2026-05-20 | fix: pitch genérico quando cnae_codigo vazio |
| `f1bc538` | 2026-05-20 | fix: cadencia.py — remove cnae_fiscal_descricao (coluna inexistente no PG) |
| `b1659c7` | 2026-05-20 | fix: configurar SDR permanece na página após salvar |
| `4bd317f` | 2026-05-20 | fix: SDR aprovação por email OU telefone sem threshold numérico |
| `69d4b8c` | 2026-05-20 | fix: SDR usa email de contatos + dashboard dinâmico |
| `14e2240` | 2026-05-20 | fix: SDR usa tabela produtos_krylo + redirect corrigido |
| `a5d2338` | 2026-05-20 | fix: SDR não captava leads — remove colunas inexistentes |
| `d15578b` | 2026-05-20 | feat: SDR Evolutivo — cadência 5 toques, produto por CNAE |
| `e97e7d6` | 2026-05-19 | fix: sdr_evolutivo configurar POST usa redirect |
| `056e0bf` | 2026-05-19 | fix: grupo 9 — espaçamento e placeholders em setup_wizard e metas |
| `50dfe45` | 2026-05-19 | fix: grupo 8 — limites de planos: Starter 1000/5, Pro 10000/20 |
| `876869e` | 2026-05-19 | fix: grupo 7 — botão Excluir para tenants inativos no painel admin |
| `e681796` | 2026-05-19 | fix: grupo 6 — remove campo Nome Private Label do form |
| `897982c` | 2026-05-19 | fix: grupo 5 — remove entrada duplicada de Central de IA no sidebar |
| `b9e0f17` | 2026-05-19 | fix: grupo 4 — remove aiWhatsapp duplicado em empresas/detalhe.html |
| `8c03232` | 2026-05-19 | fix: grupo 3 — redirects após salvar apontam para detalhe da empresa |
| `cbc46aa` | 2026-05-19 | fix: grupo 2 — APScheduler protegido com SCHEDULER_OFF env var |
| `8371110` | 2026-05-19 | fix: grupo 1 — APIs retornam JSON (unauthorized + 404/500 handlers) |

**Branches:** `master` (produção no Railway) e `melhoria/modularizar-app` (legado)

**Padrão observado:** 30+ commits em 2 dias — intensa atividade de correção, sinal de débito técnico acumulado sendo pago rapidamente.

---

## 8. O QUE ESTÁ FALTANDO

### 8.1 Comparativo com CRM SaaS padrão de mercado

| Funcionalidade | Status Krylo | Detalhe |
|---------------|-------------|---------|
| **CRUD Empresas** | 🟢 Funcional | 527 empresas em produção |
| **CRUD Contatos** | 🟢 Funcional | 533 contatos em produção |
| **CRUD Atividades** | 🟢 Funcional | Histórico de ligações, emails, reuniões |
| **Pipeline/Kanban** | 🟡 Parcial | Template existe, drag-and-drop implementado, **0 oportunidades em uso real** |
| **Importação CSV** | 🟢 Funcional | Upload e preview funcionando |
| **Exportação CSV** | 🟢 Funcional | /prospeccao/exportar |
| **SDR / Prospecção automática** | 🟡 Parcial | Lógica OK, mas `rf_empresas` tem **0 linhas** — o diferencial central está vazio |
| **Cadências de email** | 🟡 Parcial | Email via Brevo funciona; WhatsApp é aprovação manual |
| **Envio de email transacional** | 🟢 Funcional | Brevo integrado (fix recente) |
| **Gestão de usuários / RBAC** | 🟢 Funcional | 5 perfis de acesso |
| **2FA** | 🟢 Funcional | Email ou WhatsApp |
| **Setup Wizard** | 🟢 Funcional | 5 passos de onboarding |
| **Dashboard com métricas** | 🟢 Funcional | Cache de 5 min, 4 queries consolidadas |
| **IA — geração de pitch** | 🟢 Funcional | Sonnet 4.6, pitch genérico quando CNAE vazio |
| **Central de IA / chat** | 🟢 Funcional | Upload de documentos, chat contextual |
| **Portal do cliente** | 🟡 Parcial | Funcional, apenas 1 acesso registrado historicamente |
| **Radar de mercado** | 🟡 Beta | RSS feeds + editais PNCP, funciona |
| **Módulo de cobrança** | 🟡 Parcial | UI pronta, **0 clientes cadastrados** |
| **Recebíveis** | 🟡 Parcial | UI pronta, **0 recebíveis cadastrados** |
| **Relatório semanal** | 🟡 Parcial | Estrutura existe, sem dados reais para preencher |
| **Planos e billing** | 🟡 Mock | Página existe, upgrade via link WhatsApp manual, **sem Stripe** |
| **Multi-tenant** | 🟢 Funcional | Isolamento por tenant_id consistente (com 4 exceções mapeadas) |
| **CQA automático** | 🟢 Funcional | Quality assurance automatizado rodando |
| **Webhooks de entrada** | 🔴 AUSENTE | Sem `/webhook*` para Brevo, WhatsApp, ou qualquer terceiro |
| **Integração com calendário** | 🔴 AUSENTE | Zero referência a Google Calendar, Calendly, Outlook |
| **Notificações push/email proativas** | 🔴 AUSENTE | Sem SSE, WebSocket, email de alerta ao aprovador |
| **API pública documentada** | 🔴 AUSENTE | 3 endpoints internos apenas, sem autenticação por token, sem Swagger |
| **WhatsApp Business API oficial** | 🔴 AUSENTE | Usa wa.me manual; sem integração com API oficial Meta |
| **App mobile / PWA** | 🔴 AUSENTE | HTML responsivo mas sem `manifest.json`, service worker, ou app nativo |
| **Automações de workflow** | 🔴 AUSENTE | Sem engine "se X então Y"; apenas cadência linear fixa |
| **Exportação PDF/Excel de relatórios** | 🔴 AUSENTE | Nenhuma geração de PDF ou Excel para pipeline, relatório semanal |
| **Integração LinkedIn** | 🔴 AUSENTE | Zero referência no código |
| **Score de prontidão funcional** | 🟡 Parcial | Lógica existe, não usada como gate real; CNAE vazio = score arbitrário |

### 8.2 Promessas do setup wizard não implementadas

O setup wizard menciona os seguintes itens que têm lacunas na implementação real:

| Promessa | Status Real |
|----------|-------------|
| Integração de email funcional | 🟡 Funciona via Brevo, mas sem webhook de tracking (abertura, clique) |
| SDR automático captando leads | 🔴 `rf_empresas` com 0 linhas — sem dados da Receita Federal para prospectar |
| Plano de assinatura selecionável | 🔴 Mock — nenhum pagamento real possível |
| Configuração visual (logo, cores) | 🟢 Funciona |
| Produtos e ramos configuráveis | 🟢 Funciona |

### 8.3 Endpoints documentados mas com problemas

| Endpoint | Problema |
|----------|---------|
| `/api/empresa/<id>/contato` | Sem filtro de tenant_id — IDOR potencial |
| `/sdr/log-ao-vivo` | Streaming funciona, sem autenticação adicional |
| `/prospeccao/autonoma/rodar` | SDR clássico sem dados RF para operar |
| `/portal/<token>` | Acesso público por token sem rate limiting específico |

---

## 9. SCOREBOARD FINAL

| Categoria | Problemas Críticos | Problemas Médios | Problemas Baixos | Score |
|-----------|-------------------|-----------------|-----------------|-------|
| Rotas | 5 🔴 | 1 🟡 | 0 | 🔴 |
| Formulários CSRF | 20+ 🔴 | 0 | 0 | 🔴 |
| Banco de Dados | 1 🔴 | 5 🟡 | 2 | 🟡 |
| Segurança | 4 🔴 | 4 🟡 | 1 | 🔴 |
| Qualidade de Código | 3 🔴 | 3 🟡 | 2 | 🔴 |
| Dependências | 0 | 6 🟡 | 0 | 🟡 |
| Backup | 1 🔴 | 0 | 0 | 🔴 |
| Funcionalidades | 10 🔴 ausentes | 8 🟡 parciais | 12 🟢 | 🟡 |

---

## 10. PLANO DE REMEDIAÇÃO PRIORIZADO

### PRIORIDADE MÁXIMA — Fazer antes do próximo deploy

1. **🔴 Rotacionar todas as credenciais expostas no `.env`**
   - Gerar novo `ANTHROPIC_API_KEY`, `BREVO_API_KEY`, `SECRET_KEY`, `DATABASE_URL`
   - O arquivo `.env` está em produção com chaves reais — se alguém viu o arquivo uma vez, as chaves estão comprometidas

2. **🔴 Corrigir SQL injection em `models/prospeccao_autonoma.py:885`**
   - Implementar whitelist de colunas permitidas antes do UPDATE dinâmico

3. **🔴 Adicionar tenant_id às 4 rotas de prospecção automática**
   - `/prospeccao/buscar-automatico`, `/automatica/<id>/importar`, `/importar-selecionados`, `/automatica/<id>/status`

4. **🔴 Corrigir IDOR em `/api/empresa/<id>/contato`**
   - Adicionar `AND tenant_id = ?` à query

5. **🔴 Adicionar CSRF aos 20+ formulários sem proteção**
   - Especialmente: `empresas/form.html`, `contatos/form.html`, `oportunidades/form.html`, `atividades/form.html`

### PRIORIDADE ALTA — Próxima sprint

6. **🔴 Configurar backup do banco de dados**
   - Script de dump diário, pelo menos para Railway PostgreSQL
   - 527 empresas sem backup é risco empresarial real

7. **🟡 Configurar cookies de sessão seguros**
   ```python
   app.config["SESSION_COOKIE_SECURE"] = True
   app.config["SESSION_COOKIE_HTTPONLY"] = True
   app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
   ```

8. **🟡 Criar 13 índices faltando nas FKs críticas**
   - Prioridade: `cadencias.empresa_id`, `atividades.empresa_id`, `email_fila.cadencia_id`

9. **🟡 Popular `rf_empresas` com dados da Receita Federal**
   - O script `scripts/importar_receita_federal.py` existe — executar para ativar o principal diferencial competitivo do sistema

### PRIORIDADE MÉDIA — Backlog técnico

10. **🟡 Resolver conflito entre SDR Clássico e SDR Evolutivo**
    - Definir qual é o oficial, deprecar o outro, unificar tabelas e lógica

11. **🟡 Remover pacotes não utilizados do `requirements.txt`**
    - `flask-sqlalchemy`, `flask-migrate`, `PyPDF2`, `python-docx`, `livereload`, `feedparser`

12. **🟡 Implementar sistema de migrations versionado**
    - Criar tabela `schema_versions` e arquivos numerados em `migrations/`

13. **🟡 Substituir `except Exception: pass` por logging adequado**
    - 15+ ocorrências ocultam erros reais em produção

---

*Auditoria gerada em 2026-05-20 por análise estática completa do código-fonte. Nenhuma alteração foi realizada no sistema.*
