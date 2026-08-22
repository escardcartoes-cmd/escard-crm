import os
import re
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
_USE_PG = bool(DATABASE_URL)

if not _USE_PG:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "escard.db")

_SQLITE_DDL = """
    CREATE TABLE IF NOT EXISTS empresas (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        nome                TEXT    NOT NULL,
        cnpj                TEXT    UNIQUE,
        segmento            TEXT,
        porte               TEXT,
        status              TEXT    NOT NULL DEFAULT 'prospect',
        telefone            TEXT,
        email               TEXT,
        cidade              TEXT,
        estado              TEXT,
        produtos_ativos     TEXT,
        num_funcionarios    INTEGER,
        cliente_ativo       INTEGER DEFAULT 0,
        valor_mensal        REAL,
        tipo_cartao         TEXT,
        nome_private_label  TEXT,
        criado_em           TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS contatos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id  INTEGER NOT NULL,
        nome        TEXT    NOT NULL,
        cargo       TEXT,
        email       TEXT,
        telefone    TEXT,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS oportunidades (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id          INTEGER NOT NULL,
        titulo              TEXT    NOT NULL,
        etapa               VARCHAR(30) DEFAULT 'prospect',
        valor_estimado      REAL,
        num_cartoes         INTEGER,
        responsavel         TEXT,
        previsao_fechamento TEXT,
        notas               TEXT,
        criado_em           TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS atividades (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id       INTEGER,
        oportunidade_id  INTEGER,
        tipo             TEXT    NOT NULL,
        descricao        TEXT,
        data             TEXT    DEFAULT (date('now', 'localtime')),
        criado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id)      REFERENCES empresas(id)      ON DELETE SET NULL,
        FOREIGN KEY (oportunidade_id) REFERENCES oportunidades(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS prospeccao (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        contato_id           INTEGER NOT NULL UNIQUE,
        empresa_id           INTEGER NOT NULL,
        score                INTEGER,
        score_justificativa  TEXT,
        score_pontos_fortes  TEXT,
        score_pontos_fracos  TEXT,
        status               TEXT    NOT NULL DEFAULT 'pendente',
        msg_whatsapp         TEXT,
        msg_email_assunto    TEXT,
        msg_email_corpo      TEXT,
        criado_em            TEXT    DEFAULT (datetime('now', 'localtime')),
        atualizado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE,
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cadencias (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id        INTEGER,
        empresa_nome      TEXT    NOT NULL,
        contato_whatsapp  TEXT,
        contato_email     TEXT,
        oportunidade_id   INTEGER,
        etapa             INTEGER NOT NULL DEFAULT 1,
        data_acao         TEXT    NOT NULL,
        mensagem_whatsapp TEXT,
        assunto_email     TEXT,
        corpo_email       TEXT,
        status            TEXT    NOT NULL DEFAULT 'pendente',
        email_status      TEXT    NOT NULL DEFAULT 'sem_email',
        email_brevo_id    TEXT,
        criado_em         TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS clientes_cobranca (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nome            TEXT    NOT NULL,
        cnpj            TEXT,
        contato_nome    TEXT,
        contato_fone    TEXT,
        contato_email   TEXT,
        comissao_pct    REAL    NOT NULL DEFAULT 10,
        status          TEXT    NOT NULL DEFAULT 'ativo',
        criado_em       TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS relatorios_cobranca (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id       INTEGER NOT NULL,
        mes_referencia   TEXT    NOT NULL,
        total_cobrado    REAL    NOT NULL DEFAULT 0,
        total_recuperado REAL    NOT NULL DEFAULT 0,
        comissao_krylo   REAL    NOT NULL DEFAULT 0,
        observacoes      TEXT,
        retorno_cliente  TEXT,
        status           TEXT    NOT NULL DEFAULT 'rascunho',
        data_envio       TEXT,
        criado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cliente_id) REFERENCES clientes_cobranca(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS recebiveis_krylo (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id      INTEGER NOT NULL,
        mes_referencia  TEXT    NOT NULL,
        valor           REAL    NOT NULL,
        vencimento      TEXT,
        status          TEXT    NOT NULL DEFAULT 'pendente',
        data_pagamento  TEXT,
        observacoes     TEXT,
        criado_em       TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS documentos_ia (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id       INTEGER   NOT NULL DEFAULT 1,
        nome            TEXT    NOT NULL,
        tipo            TEXT    NOT NULL,
        conteudo_texto  TEXT,
        data_upload     TEXT    DEFAULT (datetime('now', 'localtime')),
        tamanho         INTEGER
    );

    CREATE TABLE IF NOT EXISTS portal_acessos (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id    INTEGER,
        empresa_nome  TEXT,
        token_acesso  TEXT UNIQUE,
        ativo         INTEGER DEFAULT 1,
        ultimo_acesso TEXT,
        criado_em     TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (empresa_id) REFERENCES empresas(id)
    );

    CREATE TABLE IF NOT EXISTS radar_mercado (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo      TEXT,
        titulo    TEXT,
        resumo    TEXT,
        link      TEXT,
        fonte     TEXT,
        lido      INTEGER DEFAULT 0,
        criado_em TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS prospeccao_automatica (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        cnpj              TEXT    UNIQUE,
        razao_social      TEXT,
        municipio         TEXT,
        uf                TEXT,
        cnae_descricao    TEXT,
        telefone          TEXT,
        email             TEXT,
        capital_social    REAL    DEFAULT 0,
        score_fit         INTEGER DEFAULT 0,
        status            TEXT    DEFAULT 'novo',
        tentativas        INTEGER DEFAULT 0,
        ultima_tentativa  TEXT,
        motivo_descarte   TEXT,
        fonte             TEXT    DEFAULT 'brasilapi',
        idade_empresa     INTEGER DEFAULT 0,
        natureza_juridica TEXT    DEFAULT '',
        porte             TEXT    DEFAULT '',
        produto_alvo      TEXT    DEFAULT '',
        importado_em      TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS ia_config (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id          INTEGER   DEFAULT 1,
        nome_assistente    TEXT      DEFAULT 'Bia',
        personalidade      TEXT      DEFAULT 'Profissional, direta e empática. Fala de forma natural e consultiva, nunca como vendedora agressiva.',
        tom                TEXT      DEFAULT 'consultivo',
        estrategia         TEXT      DEFAULT 'Foco em entender a dor do cliente antes de apresentar solução. Perguntar antes de propor.',
        estilo_escrita     TEXT      DEFAULT 'Mensagens curtas no WhatsApp (máximo 2 frases). E-mails formais mas acessíveis. Sem jargões técnicos.',
        contexto_empresa   TEXT      DEFAULT 'Krylo é uma empresa de cartão de benefícios B2B oferecendo VR, VA, combustível, premiação, Welhub e Vidalink.',
        objetivo_principal TEXT      DEFAULT 'Qualificar leads e agendar reuniões com decisores de RH.',
        restricoes         TEXT      DEFAULT 'Nunca mencionar concorrentes. Nunca prometer preços sem consultar o time. Nunca ser insistente após 3 tentativas.',
        saudacao_whatsapp  TEXT      DEFAULT 'Olá {nome}! Tudo bem? Sou a Bia da Krylo.',
        saudacao_email     TEXT      DEFAULT 'Prezado(a) {nome},',
        assinatura_email   TEXT      DEFAULT 'Atenciosamente,\nBia | Consultora Krylo\ncontato@krylo.com.br',
        modo_chat          INTEGER   DEFAULT 1,
        ativo              INTEGER   DEFAULT 1,
        atualizado_em      TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS ramos_atividade (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id   INTEGER NOT NULL DEFAULT 1,
        nome        TEXT    NOT NULL,
        descricao   TEXT,
        cnaes       TEXT,
        pitch       TEXT,
        score_min   INTEGER DEFAULT 6,
        estados     TEXT    DEFAULT 'ES,SP',
        capital_min INTEGER DEFAULT 100000,
        ativo       INTEGER DEFAULT 1,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS usuarios (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nome        TEXT    NOT NULL,
        email       TEXT    UNIQUE,
        usuario     TEXT    NOT NULL UNIQUE,
        senha_hash  TEXT    NOT NULL,
        perfil      TEXT    NOT NULL DEFAULT 'admin',
        ativo       INTEGER NOT NULL DEFAULT 1,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS empresa_config (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id         INTEGER   DEFAULT 1,
        nome              TEXT      DEFAULT 'Krylo',
        nome_fantasia     TEXT      DEFAULT 'Krylo',
        cnpj              TEXT      DEFAULT '',
        telefone          TEXT      DEFAULT '',
        whatsapp          TEXT      DEFAULT '',
        email             TEXT      DEFAULT '',
        site              TEXT      DEFAULT '',
        instagram         TEXT      DEFAULT '',
        linkedin          TEXT      DEFAULT '',
        tiktok            TEXT      DEFAULT '',
        ramo_atividade    TEXT      DEFAULT 'Benefícios Corporativos B2B',
        descricao         TEXT      DEFAULT '',
        missao            TEXT      DEFAULT '',
        diferenciais      TEXT      DEFAULT '',
        publico_alvo      TEXT      DEFAULT '',
        produtos_servicos TEXT      DEFAULT '',
        regiao_atuacao    TEXT      DEFAULT '',
        historico         TEXT      DEFAULT '',
        tom_da_marca      TEXT      DEFAULT 'profissional e consultivo',
        palavras_chave    TEXT      DEFAULT '',
        concorrentes      TEXT      DEFAULT '',
        atualizado_em     TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS radar_analises (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        analise              TEXT,
        num_itens_analisados INTEGER,
        criado_em            TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS sdr_config (
        id                         INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_campanha              TEXT    DEFAULT 'Campanha Principal',
        ativo                      INTEGER DEFAULT 1,
        rodar_continuo             INTEGER DEFAULT 1,
        intervalo_horas            INTEGER DEFAULT 6,
        estados                    TEXT    DEFAULT 'ES,SP',
        cidades                    TEXT    DEFAULT '',
        cnaes                      TEXT    DEFAULT '',
        funcionarios_min           INTEGER DEFAULT 10,
        funcionarios_max           INTEGER DEFAULT 5000,
        capital_social_min         REAL    DEFAULT 50000,
        tipo_empresa               TEXT    DEFAULT 'MATRIZ',
        idade_empresa_min          INTEGER DEFAULT 0,
        idade_empresa_max          INTEGER DEFAULT 50,
        tem_email                  INTEGER DEFAULT 0,
        tem_telefone               INTEGER DEFAULT 1,
        situacao_cadastral         TEXT    DEFAULT 'ATIVA',
        score_minimo               INTEGER DEFAULT 6,
        max_tentativas_por_empresa INTEGER DEFAULT 3,
        dias_recontato             INTEGER DEFAULT 30,
        excluir_ja_prospectados    INTEGER DEFAULT 1,
        canal_primario             TEXT    DEFAULT 'whatsapp',
        canal_secundario           TEXT    DEFAULT 'email',
        horario_inicio             INTEGER DEFAULT 8,
        horario_fim                INTEGER DEFAULT 18,
        dias_semana                TEXT    DEFAULT 'seg,ter,qua,qui,sex',
        max_leads_por_execucao     INTEGER DEFAULT 20,
        max_cadencias_por_dia      INTEGER DEFAULT 50,
        sem_restricao_horario      INTEGER DEFAULT 0,
        atualizado_em              TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS sdr_execucoes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id    INTEGER   NOT NULL DEFAULT 1,
        encontrados  INTEGER DEFAULT 0,
        salvos       INTEGER DEFAULT 0,
        cadencias    INTEGER DEFAULT 0,
        descartados  INTEGER DEFAULT 0,
        log          TEXT,
        executado_em TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS produtos_krylo (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id               INTEGER DEFAULT 1,
        nome                    TEXT    NOT NULL,
        descricao               TEXT    DEFAULT '',
        pitch_whatsapp          TEXT    DEFAULT '',
        pitch_email             TEXT    DEFAULT '',
        cnaes_alvo              TEXT    DEFAULT '',
        estados_alvo            TEXT    DEFAULT 'ES,SP',
        capital_min             REAL    DEFAULT 50000,
        score_min               INTEGER DEFAULT 6,
        valor_por_funcionario   REAL    DEFAULT 0,
        palavras_chave          TEXT    DEFAULT '',
        publico_alvo            TEXT    DEFAULT '',
        beneficios              TEXT    DEFAULT '',
        objecoes_comuns         TEXT    DEFAULT '',
        como_responder_objecoes TEXT    DEFAULT '',
        ativo                   INTEGER DEFAULT 1,
        criado_em               TEXT    DEFAULT (datetime('now', 'localtime')),
        atualizado_em           TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS sdr_sessoes (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id      INTEGER   NOT NULL DEFAULT 1,
        sessao_id      TEXT    UNIQUE,
        status         TEXT    DEFAULT 'rodando',
        encontrados    INTEGER DEFAULT 0,
        aprovados      INTEGER DEFAULT 0,
        importados     INTEGER DEFAULT 0,
        cadencias      INTEGER DEFAULT 0,
        descartados    INTEGER DEFAULT 0,
        filtrados      INTEGER DEFAULT 0,
        produto_atual  TEXT    DEFAULT '',
        estado_atual   TEXT    DEFAULT '',
        empresa_atual  TEXT    DEFAULT '',
        ultima_acao    TEXT    DEFAULT '',
        iniciado_em    TEXT    DEFAULT (datetime('now', 'localtime')),
        finalizado_em  TEXT,
        config_snapshot TEXT   DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS sdr_log_ao_vivo (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id  INTEGER NOT NULL DEFAULT 1,
        sessao_id  TEXT,
        tipo       TEXT,
        mensagem   TEXT,
        empresa    TEXT    DEFAULT '',
        uf         TEXT    DEFAULT '',
        score      INTEGER DEFAULT 0,
        produto    TEXT    DEFAULT '',
        status     TEXT    DEFAULT '',
        capital    REAL    DEFAULT 0,
        criado_em  TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS cnae_cache (
        id            INTEGER PRIMARY KEY,
        dados         TEXT,
        atualizado_em TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS cqa_resultados (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        check_nome     TEXT    NOT NULL,
        status         TEXT    NOT NULL,
        mensagem       TEXT,
        auto_corrigido INTEGER DEFAULT 0,
        executado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS cqa_alertas (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id  INTEGER NOT NULL DEFAULT 1,
        tipo       TEXT    NOT NULL,
        check_nome TEXT    NOT NULL,
        mensagem   TEXT,
        resolvido  INTEGER DEFAULT 0,
        criado_em  TEXT    DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS tenants (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        slug                 TEXT    UNIQUE NOT NULL,
        nome_empresa         TEXT    NOT NULL,
        nome_plataforma      TEXT    DEFAULT 'Krylo',
        logo_url             TEXT,
        cor_primaria         TEXT    DEFAULT '#C5A089',
        cor_secundaria       TEXT    DEFAULT '#8B6914',
        cor_fundo            TEXT    DEFAULT '#FAF8F5',
        dominio_personalizado TEXT,
        plano                TEXT    DEFAULT 'starter',
        ativo                INTEGER DEFAULT 1,
        trial_ate            TEXT,
        criado_em            TEXT    DEFAULT (datetime('now', 'localtime')),
        configurado          INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS tenant_config (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id       INTEGER UNIQUE,
        ramo_principal  TEXT,
        produtos_texto  TEXT,
        diferenciais    TEXT,
        historico       TEXT,
        concorrentes    TEXT,
        tom_ia          TEXT    DEFAULT 'profissional',
        personalidade_ia TEXT,
        whatsapp        TEXT,
        email_contato   TEXT,
        site            TEXT,
        configurado_em  TEXT
    );

    CREATE TABLE IF NOT EXISTS kia_historico (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id  INTEGER DEFAULT 1,
        pergunta   TEXT,
        resposta   TEXT,
        criado_em  TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS metas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id   INTEGER REFERENCES tenants(id),
        nome        TEXT    DEFAULT 'Meta Principal',
        valor_meta  REAL    DEFAULT 100000,
        data_inicio TEXT    DEFAULT (date('now', 'localtime')),
        data_fim    TEXT,
        tipo        TEXT    DEFAULT 'receita',
        ativo       INTEGER DEFAULT 1,
        criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
    );
"""


def _to_pg(sql: str) -> str:
    """Convert SQLite SQL syntax to PostgreSQL."""
    # Named placeholders :name → %(name)s  (must run before ? → %s)
    # Negative lookbehind avoids mangling PostgreSQL cast syntax ::type
    sql = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", sql)
    # Positional placeholders
    sql = sql.replace("?", "%s")
    # Date/time functions: TEXT DEFAULT (datetime(...)) needs ::TEXT cast
    # because PostgreSQL has no implicit cast from timestamptz to TEXT in DDL
    sql = re.sub(r"(?i)(TEXT\b[^,;\n]*DEFAULT\s+\()datetime\s*\([^)]*\)\)",
                 r"\g<1>NOW()::TEXT)", sql)
    sql = re.sub(r"datetime\s*\([^)]*\)", "NOW()", sql)
    sql = re.sub(r"date\s*\([^)]*\)", "CURRENT_DATE", sql)
    # DDL: AUTOINCREMENT → SERIAL
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    # INSERT OR IGNORE → INSERT … ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE INTO" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class _PgCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cur = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgConn:
    def __init__(self, raw):
        import psycopg2.extras
        self._raw = raw
        self._extras = psycopg2.extras

    def execute(self, sql: str, params=()) -> _PgCursor:
        sql = _to_pg(sql)
        is_insert = sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = self._raw.cursor(cursor_factory=self._extras.RealDictCursor)
        cur.execute(sql, params or None)
        rid = None
        if is_insert:
            row = cur.fetchone()
            if row:
                rid = row.get("id")
        return _PgCursor(cur, rid)

    def executemany(self, sql: str, params_list) -> None:
        sql = _to_pg(sql)
        cur = self._raw.cursor()
        cur.executemany(sql, list(params_list))
        cur.close()

    def executescript(self, sql: str) -> None:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                cur = self._raw.cursor()
                cur.execute(_to_pg(stmt))
                self._raw.commit()
                cur.close()
            except Exception as e:
                print(f"executescript aviso (stmt ignorado): {e}")
                try: self._raw.rollback()
                except Exception: pass

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


class _SqliteConn:
    """Thin wrapper around sqlite3.Connection that accepts %s placeholders (psycopg2 style)."""
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params=()):
        sql = sql.replace('%s', '?')
        return self._raw.execute(sql, params or ())

    def executemany(self, sql: str, params_list):
        sql = sql.replace('%s', '?')
        return self._raw.executemany(sql, params_list)

    def executescript(self, sql: str):
        return self._raw.executescript(sql)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def get_connection():
    if _USE_PG:
        import psycopg2
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        raw = psycopg2.connect(url, options="-c client_encoding=UTF8")
        return _PgConn(raw)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return _SqliteConn(conn)


def get_new_db_connection():
    """Cria uma conexão dedicada para uso em threads background (sem cache)."""
    if _USE_PG:
        import psycopg2
        import psycopg2.extras
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        raw = psycopg2.connect(url, options="-c client_encoding=UTF8")
        raw.autocommit = False
        return _PgConn(raw)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return _SqliteConn(conn)


def run_migrations(conn) -> None:
    """Apply schema migrations safely — each statement is independent with rollback on failure."""
    # PostgreSQL supports IF NOT EXISTS; SQLite does not — use plain ADD COLUMN there
    _ifne = " IF NOT EXISTS" if _USE_PG else ""

    _ALTER = [
        # usuarios
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} perfil TEXT NOT NULL DEFAULT 'admin'",
        # empresas — CNAE e enriquecimento
        f"ALTER TABLE empresas ADD COLUMN{_ifne} cnae_codigo TEXT",
        # empresas — Motor de Expansão
        f"ALTER TABLE empresas ADD COLUMN{_ifne} produtos_ativos TEXT",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} num_funcionarios INTEGER",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} cliente_ativo INTEGER DEFAULT 0",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} valor_mensal REAL",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} tipo_cartao TEXT",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} nome_private_label TEXT",
        # oportunidades — Deal Radar
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} score_fechamento INTEGER DEFAULT 0",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} data_ultimo_contato TEXT",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} num_interacoes INTEGER DEFAULT 0",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} dias_sem_contato INTEGER DEFAULT 0",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} proxima_acao_sugerida TEXT",
        # cadencias — Brevo e-mail tracking
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_status TEXT NOT NULL DEFAULT 'sem_email'",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_brevo_id TEXT",
        # prospeccao_automatica — SDR avançado
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} tentativas INTEGER DEFAULT 0",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} ultima_tentativa TEXT",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} motivo_descarte TEXT",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} fonte TEXT DEFAULT 'brasilapi'",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} idade_empresa INTEGER DEFAULT 0",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} natureza_juridica TEXT DEFAULT ''",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} porte TEXT DEFAULT ''",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} produto_alvo TEXT DEFAULT ''",
        # sdr_config — modo de busca e seleções de localização
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} modo_busca VARCHAR(20) DEFAULT 'cnae'",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} estados_selecionados TEXT DEFAULT ''",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} cidades_selecionadas TEXT DEFAULT ''",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} sem_restricao_horario INTEGER DEFAULT 0",
        # Multi-tenant columns
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE atividades ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE cqa_resultados ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        # cadencias — email multi-canal por etapa
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_empresa TEXT",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} canal_email INTEGER DEFAULT 1",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} canal_whatsapp INTEGER DEFAULT 1",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d0_enviado INTEGER DEFAULT 0",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d3_enviado INTEGER DEFAULT 0",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d7_enviado INTEGER DEFAULT 0",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d14_enviado INTEGER DEFAULT 0",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d0_at TEXT",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d3_at TEXT",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d7_at TEXT",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} email_d14_at TEXT",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} ramos_selecionados TEXT DEFAULT ''",
        f"ALTER TABLE sdr_config ADD COLUMN{_ifne} fonte_leads VARCHAR(20) DEFAULT 'busca'",
        f"ALTER TABLE contatos ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        # cadencias — WhatsApp approval queue
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} whatsapp_status TEXT DEFAULT 'pendente'",
        f"ALTER TABLE cadencias ADD COLUMN{_ifne} whatsapp_aprovado_em TEXT",
        # empresas — temperatura de engajamento
        f"ALTER TABLE empresas ADD COLUMN{_ifne} temperatura TEXT DEFAULT 'frio'",
        f"ALTER TABLE empresas ADD COLUMN{_ifne} score INTEGER DEFAULT 0",
        # prospeccao_automatica — temperatura
        f"ALTER TABLE prospeccao_automatica ADD COLUMN{_ifne} temperatura TEXT DEFAULT 'frio'",
        # oportunidades — Pipeline Inteligente
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} etapa VARCHAR(30) DEFAULT 'prospect'",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} valor_mensal REAL DEFAULT 0",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} dias_etapa INTEGER DEFAULT 0",
        f"ALTER TABLE oportunidades ADD COLUMN{_ifne} ultima_acao_em TEXT",
        # Remove coluna legada estagio (substituída por etapa)
        "ALTER TABLE oportunidades DROP COLUMN IF EXISTS estagio" if _USE_PG else "",
        # Multi-tenant: cobranca, recebiveis, portal
        f"ALTER TABLE clientes_cobranca ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE recebiveis_krylo ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE relatorios_cobranca ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE portal_acessos ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE prospeccao ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        # 2FA & security
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} telefone VARCHAR(20)",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} dois_fatores_ativo BOOLEAN DEFAULT FALSE",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} dois_fatores_canal VARCHAR(20) DEFAULT 'email'",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} codigo_2fa VARCHAR(10)",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} codigo_2fa_expira TIMESTAMP",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} codigo_recuperacao VARCHAR(10)",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} recuperacao_expira TIMESTAMP",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} tentativas_login INTEGER DEFAULT 0",
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} bloqueado_ate TIMESTAMP",
        # Multi-tenant: ia_config, empresa_config, produtos_krylo
        f"ALTER TABLE ia_config ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE empresa_config ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE produtos_krylo ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ia_config_tenant ON ia_config (tenant_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_empresa_config_tenant ON empresa_config (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_produtos_krylo_tenant ON produtos_krylo (tenant_id)",
        # Bloco 1 — sdr e documentos_ia
        f"ALTER TABLE sdr_sessoes ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE sdr_execucoes ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE documentos_ia ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        "CREATE INDEX IF NOT EXISTS idx_sdr_sessoes_tenant ON sdr_sessoes (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_sdr_execucoes_tenant ON sdr_execucoes (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_documentos_ia_tenant ON documentos_ia (tenant_id)",
        # Bloco 2 — ramos_atividade e sdr_log_ao_vivo
        f"ALTER TABLE ramos_atividade ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE sdr_log_ao_vivo ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        "CREATE INDEX IF NOT EXISTS idx_ramos_atividade_tenant ON ramos_atividade (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_sdr_log_ao_vivo_tenant ON sdr_log_ao_vivo (tenant_id)",
        # Bloco 3 — cqa_alertas e cqa_config
        f"ALTER TABLE cqa_alertas ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        f"ALTER TABLE cqa_config ADD COLUMN{_ifne} tenant_id INTEGER DEFAULT 1",
        "CREATE INDEX IF NOT EXISTS idx_cqa_alertas_tenant ON cqa_alertas (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_cqa_config_tenant ON cqa_config (tenant_id)",
        # Bloco 3 — onboarding wizard
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} email_remetente TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} nome_vendedor TEXT",
        # Bloco 4 — integrações por tenant (Brevo + WhatsApp)
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} brevo_api_key TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} brevo_sender_email TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} brevo_sender_nome TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} whatsapp_provider TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} whatsapp_api_key TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} whatsapp_instance_id TEXT",
        f"ALTER TABLE tenant_config ADD COLUMN{_ifne} whatsapp_sender_numero TEXT",
    ]

    _CREATE = [
        # Audit log — quem fez o quê, quando, de onde
        """CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER,
            user_id     INTEGER,
            user_email  TEXT,
            action      TEXT NOT NULL,
            resource    TEXT,
            resource_id INTEGER,
            metadata    TEXT,
            ip          TEXT,
            user_agent  TEXT,
            created_at  TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_user   ON audit_log(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
        """CREATE TABLE IF NOT EXISTS clientes_cobranca (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nome            TEXT    NOT NULL,
            cnpj            TEXT,
            contato_nome    TEXT,
            contato_fone    TEXT,
            contato_email   TEXT,
            comissao_pct    REAL    NOT NULL DEFAULT 10,
            status          TEXT    NOT NULL DEFAULT 'ativo',
            criado_em       TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS relatorios_cobranca (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id       INTEGER NOT NULL,
            mes_referencia   TEXT    NOT NULL,
            total_cobrado    REAL    NOT NULL DEFAULT 0,
            total_recuperado REAL    NOT NULL DEFAULT 0,
            comissao_krylo   REAL    NOT NULL DEFAULT 0,
            observacoes      TEXT,
            retorno_cliente  TEXT,
            status           TEXT    NOT NULL DEFAULT 'rascunho',
            data_envio       TEXT,
            criado_em        TEXT    DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (cliente_id) REFERENCES clientes_cobranca(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS recebiveis_krylo (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id      INTEGER NOT NULL,
            mes_referencia  TEXT    NOT NULL,
            valor           REAL    NOT NULL,
            vencimento      TEXT,
            status          TEXT    NOT NULL DEFAULT 'pendente',
            data_pagamento  TEXT,
            observacoes     TEXT,
            criado_em       TEXT    DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS documentos_ia (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER   NOT NULL DEFAULT 1,
            nome            TEXT    NOT NULL,
            tipo            TEXT    NOT NULL,
            conteudo_texto  TEXT,
            data_upload     TEXT    DEFAULT (datetime('now', 'localtime')),
            tamanho         INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS portal_acessos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id    INTEGER,
            empresa_nome  TEXT,
            token_acesso  TEXT UNIQUE,
            ativo         INTEGER DEFAULT 1,
            ultimo_acesso TEXT,
            criado_em     TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )""",
        """CREATE TABLE IF NOT EXISTS radar_mercado (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo      TEXT,
            titulo    TEXT,
            resumo    TEXT,
            link      TEXT,
            fonte     TEXT,
            lido      INTEGER DEFAULT 0,
            criado_em TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS prospeccao_automatica (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj              TEXT    UNIQUE,
            razao_social      TEXT,
            municipio         TEXT,
            uf                TEXT,
            cnae_descricao    TEXT,
            telefone          TEXT,
            email             TEXT,
            capital_social    REAL    DEFAULT 0,
            score_fit         INTEGER DEFAULT 0,
            status            TEXT    DEFAULT 'novo',
            tentativas        INTEGER DEFAULT 0,
            ultima_tentativa  TEXT,
            motivo_descarte   TEXT,
            fonte             TEXT    DEFAULT 'brasilapi',
            idade_empresa     INTEGER DEFAULT 0,
            natureza_juridica TEXT    DEFAULT '',
            porte             TEXT    DEFAULT '',
            produto_alvo      TEXT    DEFAULT '',
            importado_em      TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS ia_config (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id          INTEGER   DEFAULT 1,
            nome_assistente    TEXT      DEFAULT 'Bia',
            personalidade      TEXT      DEFAULT 'Profissional, direta e empática. Fala de forma natural e consultiva, nunca como vendedora agressiva.',
            tom                TEXT      DEFAULT 'consultivo',
            estrategia         TEXT      DEFAULT 'Foco em entender a dor do cliente antes de apresentar solução. Perguntar antes de propor.',
            estilo_escrita     TEXT      DEFAULT 'Mensagens curtas no WhatsApp (máximo 2 frases). E-mails formais mas acessíveis. Sem jargões técnicos.',
            contexto_empresa   TEXT      DEFAULT 'Krylo é uma empresa de cartão de benefícios B2B oferecendo VR, VA, combustível, premiação, Welhub e Vidalink.',
            objetivo_principal TEXT      DEFAULT 'Qualificar leads e agendar reuniões com decisores de RH.',
            restricoes         TEXT      DEFAULT 'Nunca mencionar concorrentes. Nunca prometer preços sem consultar o time. Nunca ser insistente após 3 tentativas.',
            saudacao_whatsapp  TEXT      DEFAULT 'Olá {nome}! Tudo bem? Sou a Bia da Krylo.',
            saudacao_email     TEXT      DEFAULT 'Prezado(a) {nome},',
            assinatura_email   TEXT      DEFAULT 'Atenciosamente,\nBia | Consultora Krylo\ncontato@krylo.com.br',
            modo_chat          INTEGER   DEFAULT 1,
            ativo              INTEGER   DEFAULT 1,
            atualizado_em      TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS ramos_atividade (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER NOT NULL DEFAULT 1,
            nome        TEXT    NOT NULL,
            descricao   TEXT,
            cnaes       TEXT,
            pitch       TEXT,
            score_min   INTEGER DEFAULT 6,
            estados     TEXT    DEFAULT 'ES,SP',
            capital_min INTEGER DEFAULT 100000,
            ativo       INTEGER DEFAULT 1,
            criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS empresa_config (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id         INTEGER   DEFAULT 1,
            nome              TEXT      DEFAULT 'Krylo',
            nome_fantasia     TEXT      DEFAULT 'Krylo',
            cnpj              TEXT      DEFAULT '',
            telefone          TEXT      DEFAULT '',
            whatsapp          TEXT      DEFAULT '',
            email             TEXT      DEFAULT '',
            site              TEXT      DEFAULT '',
            instagram         TEXT      DEFAULT '',
            linkedin          TEXT      DEFAULT '',
            tiktok            TEXT      DEFAULT '',
            ramo_atividade    TEXT      DEFAULT 'Benefícios Corporativos B2B',
            descricao         TEXT      DEFAULT '',
            missao            TEXT      DEFAULT '',
            diferenciais      TEXT      DEFAULT '',
            publico_alvo      TEXT      DEFAULT '',
            produtos_servicos TEXT      DEFAULT '',
            regiao_atuacao    TEXT      DEFAULT '',
            historico         TEXT      DEFAULT '',
            tom_da_marca      TEXT      DEFAULT 'profissional e consultivo',
            palavras_chave    TEXT      DEFAULT '',
            concorrentes      TEXT      DEFAULT '',
            atualizado_em     TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS radar_analises (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            analise              TEXT,
            num_itens_analisados INTEGER,
            criado_em            TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS email_fila (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id         INTEGER DEFAULT 1,
            destinatario      TEXT,
            nome_destinatario TEXT,
            assunto           TEXT,
            html              TEXT,
            texto             TEXT,
            status            TEXT DEFAULT 'pendente',
            tentativas        INTEGER DEFAULT 0,
            criado_em         TEXT DEFAULT (datetime('now','localtime')),
            enviado_em        TEXT,
            erro              TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_config (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_campanha              TEXT    DEFAULT 'Campanha Principal',
            ativo                      INTEGER DEFAULT 1,
            rodar_continuo             INTEGER DEFAULT 1,
            intervalo_horas            INTEGER DEFAULT 6,
            estados                    TEXT    DEFAULT 'ES,SP',
            cidades                    TEXT    DEFAULT '',
            cnaes                      TEXT    DEFAULT '',
            funcionarios_min           INTEGER DEFAULT 10,
            funcionarios_max           INTEGER DEFAULT 5000,
            capital_social_min         REAL    DEFAULT 50000,
            tipo_empresa               TEXT    DEFAULT 'MATRIZ',
            idade_empresa_min          INTEGER DEFAULT 0,
            idade_empresa_max          INTEGER DEFAULT 50,
            tem_email                  INTEGER DEFAULT 0,
            tem_telefone               INTEGER DEFAULT 1,
            situacao_cadastral         TEXT    DEFAULT 'ATIVA',
            score_minimo               INTEGER DEFAULT 6,
            max_tentativas_por_empresa INTEGER DEFAULT 3,
            dias_recontato             INTEGER DEFAULT 30,
            excluir_ja_prospectados    INTEGER DEFAULT 1,
            canal_primario             TEXT    DEFAULT 'whatsapp',
            canal_secundario           TEXT    DEFAULT 'email',
            horario_inicio             INTEGER DEFAULT 8,
            horario_fim                INTEGER DEFAULT 18,
            dias_semana                TEXT    DEFAULT 'seg,ter,qua,qui,sex',
            max_leads_por_execucao     INTEGER DEFAULT 20,
            max_cadencias_por_dia      INTEGER DEFAULT 50,
                sem_restricao_horario      INTEGER DEFAULT 0,
            atualizado_em              TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_execucoes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id    INTEGER   NOT NULL DEFAULT 1,
            encontrados  INTEGER DEFAULT 0,
            salvos       INTEGER DEFAULT 0,
            cadencias    INTEGER DEFAULT 0,
            descartados  INTEGER DEFAULT 0,
            log          TEXT,
            executado_em TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS produtos_krylo (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id               INTEGER DEFAULT 1,
            nome                    TEXT    NOT NULL,
            descricao               TEXT    DEFAULT '',
            pitch_whatsapp          TEXT    DEFAULT '',
            pitch_email             TEXT    DEFAULT '',
            cnaes_alvo              TEXT    DEFAULT '',
            estados_alvo            TEXT    DEFAULT 'ES,SP',
            capital_min             REAL    DEFAULT 50000,
            score_min               INTEGER DEFAULT 6,
            valor_por_funcionario   REAL    DEFAULT 0,
            palavras_chave          TEXT    DEFAULT '',
            publico_alvo            TEXT    DEFAULT '',
            beneficios              TEXT    DEFAULT '',
            objecoes_comuns         TEXT    DEFAULT '',
            como_responder_objecoes TEXT    DEFAULT '',
            ativo                   INTEGER DEFAULT 1,
            criado_em               TEXT    DEFAULT (datetime('now', 'localtime')),
            atualizado_em           TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_sessoes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id      INTEGER   NOT NULL DEFAULT 1,
            sessao_id      TEXT    UNIQUE,
            status         TEXT    DEFAULT 'rodando',
            encontrados    INTEGER DEFAULT 0,
            aprovados      INTEGER DEFAULT 0,
            importados     INTEGER DEFAULT 0,
            cadencias      INTEGER DEFAULT 0,
            descartados    INTEGER DEFAULT 0,
            filtrados      INTEGER DEFAULT 0,
            produto_atual  TEXT    DEFAULT '',
            estado_atual   TEXT    DEFAULT '',
            empresa_atual  TEXT    DEFAULT '',
            ultima_acao    TEXT    DEFAULT '',
            iniciado_em    TEXT    DEFAULT (datetime('now', 'localtime')),
            finalizado_em  TEXT,
            config_snapshot TEXT   DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_log_ao_vivo (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id  INTEGER NOT NULL DEFAULT 1,
            sessao_id  TEXT,
            tipo       TEXT,
            mensagem   TEXT,
            empresa    TEXT    DEFAULT '',
            uf         TEXT    DEFAULT '',
            score      INTEGER DEFAULT 0,
            produto    TEXT    DEFAULT '',
            status     TEXT    DEFAULT '',
            capital    REAL    DEFAULT 0,
            criado_em  TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS cnae_cache (
            id            INTEGER PRIMARY KEY,
            dados         TEXT,
            atualizado_em TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS cqa_resultados (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            check_nome     TEXT    NOT NULL,
            status         TEXT    NOT NULL,
            mensagem       TEXT,
            auto_corrigido INTEGER DEFAULT 0,
            executado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS cqa_alertas (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id  INTEGER NOT NULL DEFAULT 1,
            tipo       TEXT    NOT NULL,
            check_nome TEXT    NOT NULL,
            mensagem   TEXT,
            resolvido  INTEGER DEFAULT 0,
            criado_em  TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS tenants (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            slug                  TEXT    UNIQUE NOT NULL,
            nome_empresa          TEXT    NOT NULL,
            nome_plataforma       TEXT    DEFAULT 'Krylo',
            logo_url              TEXT,
            cor_primaria          TEXT    DEFAULT '#C5A089',
            cor_secundaria        TEXT    DEFAULT '#8B6914',
            cor_fundo             TEXT    DEFAULT '#FAF8F5',
            dominio_personalizado TEXT,
            plano                 TEXT    DEFAULT 'starter',
            ativo                 INTEGER DEFAULT 1,
            trial_ate             TEXT,
            criado_em             TEXT    DEFAULT (datetime('now', 'localtime')),
            configurado           INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS tenant_config (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id        INTEGER UNIQUE,
            ramo_principal   TEXT,
            produtos_texto   TEXT,
            diferenciais     TEXT,
            historico        TEXT,
            concorrentes     TEXT,
            tom_ia           TEXT    DEFAULT 'profissional',
            personalidade_ia TEXT,
            whatsapp         TEXT,
            email_contato    TEXT,
            site             TEXT,
            configurado_em   TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS kia_historico (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id  INTEGER DEFAULT 1,
            pergunta   TEXT,
            resposta   TEXT,
            criado_em  TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS metas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER REFERENCES tenants(id),
            nome        TEXT    DEFAULT 'Meta Principal',
            valor_meta  REAL    DEFAULT 100000,
            data_inicio TEXT    DEFAULT (date('now', 'localtime')),
            data_fim    TEXT,
            tipo        TEXT    DEFAULT 'receita',
            ativo       INTEGER DEFAULT 1,
            criado_em   TEXT    DEFAULT (datetime('now', 'localtime'))
        )""",
        # Indexes for multi-tenant performance
        "CREATE INDEX IF NOT EXISTS idx_empresas_tenant ON empresas(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_empresas_tenant_status ON empresas(tenant_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_cadencias_tenant ON cadencias(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_cadencias_tenant_status ON cadencias(tenant_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_oportunidades_tenant ON oportunidades(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_contatos_empresa ON contatos(empresa_id)",
        "CREATE INDEX IF NOT EXISTS idx_usuarios_tenant ON usuarios(tenant_id)",
        # Base local Receita Federal
        """CREATE TABLE IF NOT EXISTS rf_empresas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj          VARCHAR(14) UNIQUE NOT NULL,
            razao_social  VARCHAR(200),
            nome_fantasia VARCHAR(200),
            cnae_principal VARCHAR(7),
            cnae_descricao VARCHAR(200),
            uf            VARCHAR(2),
            municipio     VARCHAR(100),
            telefone      VARCHAR(20),
            email         VARCHAR(200),
            situacao      VARCHAR(20) DEFAULT 'ATIVA',
            porte         VARCHAR(20),
            capital_social NUMERIC(15,2),
            data_abertura DATE,
            tipo          VARCHAR(10) DEFAULT 'MATRIZ',
            importado_em  TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_rf_cnae ON rf_empresas(cnae_principal)",
        "CREATE INDEX IF NOT EXISTS idx_rf_uf ON rf_empresas(uf)",
        "CREATE INDEX IF NOT EXISTS idx_rf_cnae_uf ON rf_empresas(cnae_principal, uf)",
        "CREATE INDEX IF NOT EXISTS idx_rf_situacao ON rf_empresas(situacao)",
        """CREATE TABLE IF NOT EXISTS cqa_config (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            chave         VARCHAR(50) NOT NULL,
            valor         TEXT,
            atualizado_em TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            UNIQUE (tenant_id, chave)
        )""",
        """CREATE TABLE IF NOT EXISTS radar_alertas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER REFERENCES tenants(id),
            tipo            TEXT,
            titulo          TEXT,
            descricao       TEXT,
            fonte           TEXT,
            url_original    TEXT,
            valor_estimado  REAL,
            estado          TEXT,
            orgao           TEXT,
            palavras_chave  TEXT,
            relevancia      INTEGER DEFAULT 50,
            lido            INTEGER DEFAULT 0,
            arquivado       INTEGER DEFAULT 0,
            conteudo_gerado TEXT,
            tipo_conteudo   TEXT,
            criado_em       TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS radar_config (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id           INTEGER UNIQUE REFERENCES tenants(id),
            palavras_chave      TEXT,
            estados             TEXT DEFAULT 'ES',
            monitorar_editais   INTEGER DEFAULT 1,
            monitorar_noticias  INTEGER DEFAULT 1,
            gerar_conteudo      INTEGER DEFAULT 1,
            gerar_insights      INTEGER DEFAULT 1,
            ativo               INTEGER DEFAULT 1,
            ultima_busca        TEXT,
            atualizado_em       TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS radar_insights (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER REFERENCES tenants(id),
            tipo        TEXT,
            titulo      TEXT,
            conteudo    TEXT,
            fonte_dados TEXT,
            aplicado    INTEGER DEFAULT 0,
            criado_em   TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_evolutivo_config (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id             INTEGER   DEFAULT 1,
            score_prontidao_minimo INTEGER DEFAULT 8,
            max_leads_por_execucao INTEGER DEFAULT 20,
            usar_radar_intent     INTEGER DEFAULT 1,
            usar_ecosistema       INTEGER DEFAULT 1,
            pitch_adaptativo      INTEGER DEFAULT 1,
            atualizado_em         TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS radar_intent (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER   DEFAULT 1,
            fonte           TEXT,
            titulo          TEXT,
            link            TEXT,
            data_evento     TEXT,
            resumo          TEXT,
            score_intent    INTEGER DEFAULT 8,
            criado_em       TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_radar_tenant_lido ON radar_alertas(tenant_id, lido, criado_em)",
        "CREATE INDEX IF NOT EXISTS idx_sdr_evolutivo_config_tenant ON sdr_evolutivo_config(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_radar_intent_tenant ON radar_intent(tenant_id)",
    ]

    _seen = set()
    for sql in _ALTER + _CREATE:
        if not sql or not str(sql).strip():
            continue
        try:
            conn.execute(sql)
            conn.commit()
        except Exception as e:
            msg = str(e).lower()
            benign = (
                "duplicate column" in msg
                or "already exists" in msg
                or "duplicate table" in msg
                or "duplicate index" in msg
                or "no such column" in msg
                or "cannot drop" in msg
            )
            if not benign:
                k = f"{msg}|{sql[:80]}"
                if k not in _seen:
                    _seen.add(k)
                    print(f"Migration aviso: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    # Seeds
    _seeds = [
        "INSERT OR IGNORE INTO ia_config (id, tenant_id) VALUES (1, 1)",
        "INSERT OR IGNORE INTO empresa_config (id, tenant_id) VALUES (1, 1)",
        "INSERT OR IGNORE INTO sdr_config (id) VALUES (1)",
        "INSERT OR IGNORE INTO sdr_evolutivo_config (id, tenant_id) VALUES (1, 1)",
        # Tenant padrão Krylo (id=1 garantido na primeira execução)
        "INSERT OR IGNORE INTO tenants (slug, nome_empresa, nome_plataforma, cor_primaria, cor_secundaria, ativo, configurado) VALUES ('krylo', 'Krylo', 'Krylo CRM', '#4A90D9', '#2C5F8A', 1, 1)",
        "INSERT OR IGNORE INTO tenant_config (tenant_id) SELECT 1 WHERE EXISTS (SELECT 1 FROM tenants WHERE slug='krylo')",
    ]
    for sql in _seeds:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception as e:
            print(f"Seed aviso: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    # Ensure tenant_id=1 for all existing rows (idempotent)
    for _tab_tenant in ["empresas", "cadencias", "oportunidades", "atividades",
                         "prospeccao_automatica", "usuarios",
                         "ia_config", "empresa_config", "produtos_krylo",
                         "sdr_sessoes", "sdr_execucoes", "documentos_ia",
                         "ramos_atividade", "sdr_log_ao_vivo",
                         "cqa_alertas", "cqa_config"]:
        try:
            conn.execute(f"UPDATE {_tab_tenant} SET tenant_id=1 WHERE tenant_id IS NULL")
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass

    # Repair double-encoded city names (postgres only, idempotent)
    if _USE_PG:
        for _repair_sql in [
            """UPDATE prospeccao_automatica
               SET municipio = convert_from(convert_to(municipio, 'LATIN1'), 'UTF8')
               WHERE municipio IS NOT NULL AND municipio ~ '[ÃÂ]'""",
            """UPDATE empresas
               SET cidade = convert_from(convert_to(cidade, 'LATIN1'), 'UTF8')
               WHERE cidade IS NOT NULL AND cidade ~ '[ÃÂ]'""",
            """UPDATE empresas
               SET nome = convert_from(convert_to(nome, 'LATIN1'), 'UTF8')
               WHERE nome IS NOT NULL AND nome ~ '[ÃÂ]'""",
            # Trailing dash/em-dash fix
            """UPDATE empresas
               SET cidade = TRIM(REGEXP_REPLACE(cidade, '[-–—]+\\s*$', ''))
               WHERE cidade IS NOT NULL AND cidade ~ '[-–—]\\s*$'""",
            """UPDATE empresas
               SET nome = TRIM(REGEXP_REPLACE(nome, '[-–—]+\\s*$', ''))
               WHERE nome IS NOT NULL AND nome ~ '[-–—]\\s*$'""",
        ]:
            try:
                conn.execute(_repair_sql)
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
    else:
        # SQLite: trailing dash fix via Python (re module available at module level)
        try:
            _rows_dash = conn.execute(
                "SELECT id, cidade, nome FROM empresas "
                "WHERE (cidade IS NOT NULL AND (cidade LIKE '%—' OR cidade LIKE '%–' OR cidade LIKE '%-')) "
                "   OR (nome IS NOT NULL AND (nome LIKE '%—' OR nome LIKE '%–'))"
            ).fetchall()
            for _dr in _rows_dash:
                _dr = dict(_dr)
                _cidade_f = re.sub(r'[-–—]+\s*$', '', (_dr.get('cidade') or '')).strip() or None
                _nome_f   = re.sub(r'[-–—]+\s*$', '', (_dr.get('nome') or '')).strip() or None
                conn.execute("UPDATE empresas SET cidade=?, nome=? WHERE id=?",
                             (_cidade_f, _nome_f, _dr['id']))
            conn.commit()
        except Exception as _e:
            print(f"Trailing dash fix aviso: {_e}")
            try: conn.rollback()
            except Exception: pass

    # Seed ramos_atividade only if empty
    try:
        _cnt = conn.execute("SELECT COUNT(*) AS cnt FROM ramos_atividade WHERE tenant_id=1").fetchone()
        if (_cnt["cnt"] if _cnt else 0) == 0:
            for _r in [
                ("Benefícios Corporativos",
                 "Empresas que consomem VR/VA/combustível",
                 "4711302,6202300,4120400,8610101",
                 "A Krylo oferece Vale Refeição, VA e Combustível sem taxa de adesão",
                 6, "ES,SP"),
                ("Cobrança Terceirizada",
                 "Empresas com carteira de inadimplentes",
                 "6491300,6492100,7020400",
                 "Recuperamos seus inadimplentes com taxa só sobre o recuperado",
                 7, "ES,SP,MG,RJ"),
            ]:
                conn.execute(
                    "INSERT INTO ramos_atividade (tenant_id, nome, descricao, cnaes, pitch, score_min, estados) VALUES (1, ?, ?, ?, ?, ?, ?)",
                    _r,
                )
            conn.commit()
    except Exception as e:
        print(f"Seed ramos aviso: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


    # Seed produtos_krylo only if empty
    try:
        _cnt2 = conn.execute("SELECT COUNT(*) AS cnt FROM produtos_krylo WHERE tenant_id=1").fetchone()
        if (_cnt2["cnt"] if _cnt2 else 0) == 0:
            _produtos_seed = [
                (1, "Vale Refeição",    "Cartão para uso em restaurantes e lanchonetes credenciadas",
                 "Olá {empresa}! A Krylo oferece Vale Refeição sem taxa de adesão. Posso apresentar?",
                 "4711302,5611201,5611203,4712100", "ES,SP,MG,RJ", 50000, 6, 550,
                 "VR,refeição,restaurante,alimentação"),
                (1, "Vale Alimentação", "Cartão para compras em supermercados credenciados",
                 "Olá {empresa}! Nosso Vale Alimentação é aceito em +800 estabelecimentos. Quer conhecer?",
                 "4711302,8610101,4712100", "ES,SP,MG,RJ", 50000, 6, 400,
                 "VA,alimentação,supermercado,mercado"),
                (1, "Combustível",      "Cartão para abastecimento em postos credenciados com controle por motorista",
                 "Olá {empresa}! Reduza até 15% do custo com combustível usando o cartão Krylo.",
                 "4120400,4930201,4930202,5320201", "ES,SP,MG,RJ,BA", 50000, 6, 300,
                 "combustível,frota,posto,abastecimento"),
                (1, "Premiação",        "Cartão de premiação para reconhecimento de metas e datas comemorativas",
                 "Olá {empresa}! Reconheça sua equipe com o Cartão Premiação Krylo. Simples e rápido!",
                 "6202300,7490104,7020400", "ES,SP,MG,RJ", 50000, 6, 200,
                 "premiação,incentivo,reconhecimento,bonificação"),
                (1, "Welhub",           "Plataforma de saúde e bem-estar para colaboradores",
                 "Olá {empresa}! O Welhub reduz absenteísmo em até 30%. Posso mostrar como funciona?",
                 "8599604,7020400,6202300", "ES,SP,MG,RJ", 50000, 6, 150,
                 "saúde,bem-estar,academia,terapia,welhub"),
                (1, "Vidalink",         "Desconto de até 70% em medicamentos em +15.000 farmácias",
                 "Olá {empresa}! Com o Vidalink seus funcionários têm desconto em farmácias. Implantação gratuita!",
                 "8610101,8630503,8650099", "ES,SP,MG,RJ", 50000, 6, 120,
                 "farmácia,medicamento,saúde,vidalink"),
                (1, "Private Label",    "Cartão de benefícios com a marca da empresa cliente",
                 "Olá {empresa}! Imagine um cartão de benefícios com a marca da sua empresa.",
                 "4711302,8610101,6202300,4120400", "ES,SP,MG,RJ", 100000, 7, 500,
                 "private label,marca própria,cartão personalizado"),
                (1, "Cobrança",         "Serviço de recuperação de inadimplentes terceirizado",
                 "Olá {empresa}! Recuperamos seus inadimplentes com taxa só sobre o recuperado.",
                 "6491300,6492100,7020400", "ES,SP,MG,RJ", 50000, 6, 0,
                 "cobrança,inadimplência,recuperação,crédito"),
            ]
            for _p in _produtos_seed:
                conn.execute(
                    """INSERT OR IGNORE INTO produtos_krylo
                       (tenant_id, nome, descricao, pitch_whatsapp, cnaes_alvo, estados_alvo,
                        capital_min, score_min, valor_por_funcionario, palavras_chave)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    _p,
                )
            conn.commit()
    except Exception as e:
        print(f"Seed produtos aviso: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def init_db() -> None:
    conn = get_connection()
    conn.executescript(_SQLITE_DDL)
    conn.commit()
    run_migrations(conn)
    conn.close()
