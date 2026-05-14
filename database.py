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
        estagio             TEXT    NOT NULL DEFAULT 'lead',
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
        produto_foco               TEXT    DEFAULT 'todos',
        atualizado_em              TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS sdr_execucoes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        encontrados  INTEGER DEFAULT 0,
        salvos       INTEGER DEFAULT 0,
        cadencias    INTEGER DEFAULT 0,
        descartados  INTEGER DEFAULT 0,
        log          TEXT,
        executado_em TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS produtos_krylo (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        nome                    TEXT    NOT NULL UNIQUE,
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
"""


def _to_pg(sql: str) -> str:
    """Convert SQLite SQL syntax to PostgreSQL."""
    # Named placeholders :name → %(name)s  (must run before ? → %s)
    sql = re.sub(r":([A-Za-z_]\w*)", r"%(\1)s", sql)
    # Positional placeholders
    sql = sql.replace("?", "%s")
    # Date/time functions
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

    def executescript(self, sql: str) -> None:
        cur = self._raw.cursor()
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            cur.execute(_to_pg(stmt))
        self._raw.commit()
        cur.close()

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
        return _PgConn(psycopg2.connect(url))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_new_db_connection():
    """Cria uma conexão dedicada para uso em threads background (sem cache)."""
    if _USE_PG:
        import psycopg2
        import psycopg2.extras
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        raw = psycopg2.connect(url)
        raw.autocommit = False
        return _PgConn(raw)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def run_migrations(conn) -> None:
    """Apply schema migrations safely — each statement is independent with rollback on failure."""
    # PostgreSQL supports IF NOT EXISTS; SQLite does not — use plain ADD COLUMN there
    _ifne = " IF NOT EXISTS" if _USE_PG else ""

    _ALTER = [
        # usuarios
        f"ALTER TABLE usuarios ADD COLUMN{_ifne} perfil TEXT NOT NULL DEFAULT 'admin'",
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
    ]

    _CREATE = [
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
            produto_foco               TEXT    DEFAULT 'todos',
            atualizado_em              TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS sdr_execucoes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            encontrados  INTEGER DEFAULT 0,
            salvos       INTEGER DEFAULT 0,
            cadencias    INTEGER DEFAULT 0,
            descartados  INTEGER DEFAULT 0,
            log          TEXT,
            executado_em TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS produtos_krylo (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            nome                    TEXT    NOT NULL UNIQUE,
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
    ]

    for sql in _ALTER + _CREATE:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception as e:
            print(f"Migration aviso (normal se coluna já existe): {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    # Seeds
    _seeds = [
        "INSERT OR IGNORE INTO ia_config (id) VALUES (1)",
        "INSERT OR IGNORE INTO empresa_config (id) VALUES (1)",
        "INSERT OR IGNORE INTO sdr_config (id) VALUES (1)",
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

    # Seed ramos_atividade only if empty
    try:
        _cnt = conn.execute("SELECT COUNT(*) AS cnt FROM ramos_atividade").fetchone()
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
                    "INSERT INTO ramos_atividade (nome, descricao, cnaes, pitch, score_min, estados) VALUES (?, ?, ?, ?, ?, ?)",
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
        _cnt2 = conn.execute("SELECT COUNT(*) AS cnt FROM produtos_krylo").fetchone()
        if (_cnt2["cnt"] if _cnt2 else 0) == 0:
            _produtos_seed = [
                ("Vale Refeição",    "Cartão para uso em restaurantes e lanchonetes credenciadas",
                 "Olá {empresa}! A Krylo oferece Vale Refeição sem taxa de adesão. Posso apresentar?",
                 "4711302,5611201,5611203,4712100", "ES,SP,MG,RJ", 50000, 6, 550,
                 "VR,refeição,restaurante,alimentação"),
                ("Vale Alimentação", "Cartão para compras em supermercados credenciados",
                 "Olá {empresa}! Nosso Vale Alimentação é aceito em +800 estabelecimentos. Quer conhecer?",
                 "4711302,8610101,4712100", "ES,SP,MG,RJ", 50000, 6, 400,
                 "VA,alimentação,supermercado,mercado"),
                ("Combustível",      "Cartão para abastecimento em postos credenciados com controle por motorista",
                 "Olá {empresa}! Reduza até 15% do custo com combustível usando o cartão Krylo.",
                 "4120400,4930201,4930202,5320201", "ES,SP,MG,RJ,BA", 50000, 6, 300,
                 "combustível,frota,posto,abastecimento"),
                ("Premiação",        "Cartão de premiação para reconhecimento de metas e datas comemorativas",
                 "Olá {empresa}! Reconheça sua equipe com o Cartão Premiação Krylo. Simples e rápido!",
                 "6202300,7490104,7020400", "ES,SP,MG,RJ", 50000, 6, 200,
                 "premiação,incentivo,reconhecimento,bonificação"),
                ("Welhub",           "Plataforma de saúde e bem-estar para colaboradores",
                 "Olá {empresa}! O Welhub reduz absenteísmo em até 30%. Posso mostrar como funciona?",
                 "8599604,7020400,6202300", "ES,SP,MG,RJ", 50000, 6, 150,
                 "saúde,bem-estar,academia,terapia,welhub"),
                ("Vidalink",         "Desconto de até 70% em medicamentos em +15.000 farmácias",
                 "Olá {empresa}! Com o Vidalink seus funcionários têm desconto em farmácias. Implantação gratuita!",
                 "8610101,8630503,8650099", "ES,SP,MG,RJ", 50000, 6, 120,
                 "farmácia,medicamento,saúde,vidalink"),
                ("Private Label",    "Cartão de benefícios com a marca da empresa cliente",
                 "Olá {empresa}! Imagine um cartão de benefícios com a marca da sua empresa.",
                 "4711302,8610101,6202300,4120400", "ES,SP,MG,RJ", 100000, 7, 500,
                 "private label,marca própria,cartão personalizado"),
                ("Cobrança",         "Serviço de recuperação de inadimplentes terceirizado",
                 "Olá {empresa}! Recuperamos seus inadimplentes com taxa só sobre o recuperado.",
                 "6491300,6492100,7020400", "ES,SP,MG,RJ", 50000, 6, 0,
                 "cobrança,inadimplência,recuperação,crédito"),
            ]
            for _p in _produtos_seed:
                conn.execute(
                    """INSERT OR IGNORE INTO produtos_krylo
                       (nome, descricao, pitch_whatsapp, cnaes_alvo, estados_alvo,
                        capital_min, score_min, valor_por_funcionario, palavras_chave)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
