from database import get_connection

KEYWORDS_EDITAL = [
    "vale refeição", "vale alimentação", "cartão benefício",
    "auxílio alimentação", "benefícios corporativos",
]

DOU_URLS = [
    "https://www.in.gov.br/servicos/pesquisa-diario-oficial-em-rss"
    "?tipoPesquisa=0&termoPesquisa=vale+alimentacao",
    "https://www.in.gov.br/servicos/pesquisa-diario-oficial-em-rss"
    "?tipoPesquisa=0&termoPesquisa=cartao+beneficio",
    "https://www.in.gov.br/servicos/pesquisa-diario-oficial-em-rss"
    "?tipoPesquisa=0&termoPesquisa=beneficios+corporativos",
]

GNEWS_URL = (
    "https://news.google.com/rss/search?"
    "q=Alelo+OR+Ticket+OR+Sodexo+OR+Flash+Beneficios+"
    "problema+OR+falha+OR+instabilidade+OR+reclamacao"
    "&hl=pt-BR&gl=BR&ceid=BR:pt"
)


def _salvar_item(conn, tipo, titulo, resumo, link, fonte) -> bool:
    titulo = (titulo or "")[:400]
    if not titulo:
        return False
    existing = conn.execute(
        "SELECT id FROM radar_mercado WHERE titulo = ?", (titulo,)
    ).fetchone()
    if existing:
        return False
    conn.execute(
        "INSERT INTO radar_mercado (tipo, titulo, resumo, link, fonte) VALUES (?, ?, ?, ?, ?)",
        (tipo, titulo, (resumo or "")[:300], link or "", fonte),
    )
    return True


def buscar_feeds() -> dict:
    import feedparser

    editais_count = 0
    concorrentes_count = 0
    conn = get_connection()

    # Busca 1: Editais DOU
    for url in DOU_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = getattr(entry, "title", "") or ""
                resumo = getattr(entry, "summary", "") or ""
                link   = getattr(entry, "link", "") or ""
                combined = (titulo + " " + resumo).lower()
                if any(kw in combined for kw in KEYWORDS_EDITAL):
                    if _salvar_item(conn, "edital", titulo, resumo, link, "Diário Oficial"):
                        editais_count += 1
        except Exception:
            pass

    # Busca 2: Concorrentes com problemas
    try:
        feed = feedparser.parse(GNEWS_URL)
        for entry in feed.entries[:30]:
            titulo = getattr(entry, "title", "") or ""
            link   = getattr(entry, "link", "") or ""
            if _salvar_item(conn, "concorrente", titulo, "", link, "Google News"):
                concorrentes_count += 1
    except Exception:
        pass

    conn.commit()
    conn.close()
    return {
        "editais": editais_count,
        "concorrentes": concorrentes_count,
        "total": editais_count + concorrentes_count,
    }


def listar() -> dict:
    conn = get_connection()
    editais = conn.execute(
        "SELECT * FROM radar_mercado WHERE tipo='edital' ORDER BY criado_em DESC"
    ).fetchall()
    concorrentes = conn.execute(
        "SELECT * FROM radar_mercado WHERE tipo='concorrente' ORDER BY criado_em DESC"
    ).fetchall()
    conn.close()
    return {
        "editais": [dict(r) for r in editais],
        "concorrentes": [dict(r) for r in concorrentes],
    }


def marcar_lido(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE radar_mercado SET lido=1 WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM radar_mercado WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def contar_nao_lidos() -> dict:
    try:
        conn = get_connection()
        e = conn.execute(
            "SELECT COUNT(*) AS n FROM radar_mercado WHERE tipo='edital' AND lido=0"
        ).fetchone()["n"]
        c = conn.execute(
            "SELECT COUNT(*) AS n FROM radar_mercado WHERE tipo='concorrente' AND lido=0"
        ).fetchone()["n"]
        conn.close()
        return {"editais": e, "concorrentes": c, "total": e + c}
    except Exception:
        return {"editais": 0, "concorrentes": 0, "total": 0}
