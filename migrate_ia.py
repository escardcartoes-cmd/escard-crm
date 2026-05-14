"""
Script de migração para garantir tabela ia_config no banco.
- Em produção (PostgreSQL/Railway): cria com DDL nativo PostgreSQL.
- Em desenvolvimento (SQLite): usa init_db() normal.

Execute via: python migrate_ia.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # ── PostgreSQL (Railway) ─────────────────────────────────────────────────
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    import psycopg2
    conn = psycopg2.connect(url)
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ia_config (
          id                 SERIAL PRIMARY KEY,
          nome_assistente    VARCHAR(100) DEFAULT 'Bia',
          personalidade      TEXT DEFAULT 'Profissional, direta e empática. Fala de forma natural e consultiva, nunca como vendedora agressiva.',
          tom                VARCHAR(50)  DEFAULT 'consultivo',
          estrategia         TEXT DEFAULT 'Foco em entender a dor do cliente antes de apresentar solução. Perguntar antes de propor.',
          estilo_escrita     TEXT DEFAULT 'Mensagens curtas no WhatsApp (máximo 2 frases). E-mails formais mas acessíveis. Sem jargões técnicos.',
          contexto_empresa   TEXT DEFAULT 'Krylo é uma empresa de cartão de benefícios B2B oferecendo VR, VA, combustível, premiação, Welhub e Vidalink.',
          objetivo_principal TEXT DEFAULT 'Qualificar leads e agendar reuniões com decisores de RH.',
          restricoes         TEXT DEFAULT 'Nunca mencionar concorrentes. Nunca prometer preços sem consultar o time. Nunca ser insistente após 3 tentativas.',
          saudacao_whatsapp  TEXT DEFAULT 'Olá {nome}! Tudo bem? Sou a Bia da Krylo.',
          saudacao_email     TEXT DEFAULT 'Prezado(a) {nome},',
          assinatura_email   TEXT DEFAULT 'Atenciosamente,\nBia | Consultora Krylo\ncontato@krylo.com.br',
          modo_chat          BOOLEAN   DEFAULT TRUE,
          ativo              BOOLEAN   DEFAULT TRUE,
          atualizado_em      TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("INSERT INTO ia_config (id) VALUES (1) ON CONFLICT DO NOTHING")
    conn.commit()
    cur.close()
    conn.close()
    print("OK — PostgreSQL: tabela ia_config criada/verificada, seed id=1 garantido.")

else:
    # ── SQLite (desenvolvimento local) ───────────────────────────────────────
    from database import init_db, get_connection
    init_db()
    conn = get_connection()
    r = conn.execute("SELECT COUNT(*) AS cnt FROM ia_config").fetchone()
    print(f"OK — SQLite local: ia_config existe com {r['cnt']} linha(s).")
    conn.close()
