from datetime import date, timedelta
from database import get_connection

ETAPA_LABELS = {
    1: "Apresentação",
    2: "Follow-up (D+3)",
    3: "Proposta de Valor (D+7)",
    4: "Último Contato (D+14)",
}
DIAS_POR_ETAPA = {1: 0, 2: 3, 3: 7, 4: 14}


def criar_etapa(dados: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO cadencias
               (empresa_id, empresa_nome, contato_whatsapp, contato_email,
                oportunidade_id, etapa, data_acao, mensagem_whatsapp,
                assunto_email, corpo_email, status)
           VALUES
               (:empresa_id, :empresa_nome, :contato_whatsapp, :contato_email,
                :oportunidade_id, :etapa, :data_acao, :mensagem_whatsapp,
                :assunto_email, :corpo_email, :status)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def cancelar_por_empresa(empresa_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE cadencias SET status='cancelada' WHERE empresa_id=? AND status='pendente'",
        (empresa_id,),
    )
    conn.commit()
    conn.close()


def listar_hoje() -> list:
    today = str(date.today())
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM cadencias
           WHERE data_acao = ? AND status='pendente'
           ORDER BY empresa_nome ASC, etapa ASC""",
        (today,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def listar_proximos_dias(n: int = 7) -> list:
    tomorrow = str(date.today() + timedelta(days=1))
    cutoff   = str(date.today() + timedelta(days=n))
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM cadencias
           WHERE data_acao >= ? AND data_acao <= ? AND status='pendente'
           ORDER BY data_acao ASC, empresa_nome ASC""",
        (tomorrow, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def contar_hoje() -> int:
    today = str(date.today())
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cadencias WHERE data_acao = ? AND status='pendente'",
        (today,),
    ).fetchone()
    conn.close()
    return int(row["n"]) if row else 0


def concluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE cadencias SET status='concluida' WHERE id=?", (id_,))
    conn.commit()
    conn.close()


def cancelar(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE cadencias SET status='cancelada' WHERE id=?", (id_,))
    conn.commit()
    conn.close()
