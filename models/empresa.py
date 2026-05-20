import logging
import time
import requests as _req
from database import get_connection

logger = logging.getLogger(__name__)

STATUS = ["prospect", "cliente", "inativo"]
PORTES = ["micro", "pequena", "média", "grande"]


def listar(status=None, tenant_id=None) -> list:
    conn = get_connection()
    sql = "SELECT * FROM empresas WHERE 1=1"
    params = []
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY nome"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def buscar_por_id(id_: int, tenant_id=None):
    conn = get_connection()
    sql = "SELECT * FROM empresas WHERE id = ?"
    params = [id_]
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def criar(dados: dict) -> int:
    dados = {**dados, "tenant_id": dados.get("tenant_id", 1)}
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO empresas
               (nome, cnpj, segmento, porte, status, telefone, email, cidade, estado,
                produtos_ativos, num_funcionarios, cliente_ativo, valor_mensal,
                tipo_cartao, nome_private_label, tenant_id)
           VALUES
               (:nome, :cnpj, :segmento, :porte, :status, :telefone, :email, :cidade, :estado,
                :produtos_ativos, :num_funcionarios, :cliente_ativo, :valor_mensal,
                :tipo_cartao, :nome_private_label, :tenant_id)""",
        dados,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def atualizar(id_: int, dados: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE empresas
           SET nome=:nome, cnpj=:cnpj, segmento=:segmento, porte=:porte,
               status=:status, telefone=:telefone, email=:email, cidade=:cidade, estado=:estado,
               produtos_ativos=:produtos_ativos, num_funcionarios=:num_funcionarios,
               cliente_ativo=:cliente_ativo, valor_mensal=:valor_mensal,
               tipo_cartao=:tipo_cartao, nome_private_label=:nome_private_label
           WHERE id=:id""",
        {**dados, "id": id_},
    )
    conn.commit()
    conn.close()


def excluir(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM empresas WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def enriquecer_cnae_batch(tenant_id: int = 1, limite: int = 20) -> dict:
    """
    Busca CNAE na API receitaws.com.br para empresas com CNPJ mas sem cnae_codigo.
    Respeita o rate-limit da API: max 3 req/min (pausa de 21s entre chamadas).
    Retorna {"atualizadas": N, "erros": N, "sem_cnpj": N}.
    """
    conn = get_connection()
    pendentes = [dict(r) for r in conn.execute(
        """SELECT id, cnpj, nome FROM empresas
           WHERE tenant_id=? AND cnpj IS NOT NULL AND cnpj != ''
             AND (cnae_codigo IS NULL OR cnae_codigo = '')
           ORDER BY id LIMIT ?""",
        (tenant_id, limite),
    ).fetchall()]
    conn.close()

    atualizadas = erros = sem_cnpj = 0

    for emp in pendentes:
        cnpj_digits = "".join(c for c in str(emp["cnpj"] or "") if c.isdigit())
        if len(cnpj_digits) != 14:
            sem_cnpj += 1
            continue
        try:
            resp = _req.get(
                f"https://receitaws.com.br/v1/cnpj/{cnpj_digits}",
                headers={"User-Agent": "EscardCRM/1.0"},
                timeout=10,
            )
            if resp.status_code == 429:
                logger.warning("[CNAE] Rate-limit receitaws — aguardando 60s")
                time.sleep(60)
                resp = _req.get(
                    f"https://receitaws.com.br/v1/cnpj/{cnpj_digits}",
                    headers={"User-Agent": "EscardCRM/1.0"},
                    timeout=10,
                )
            if resp.status_code != 200:
                logger.warning("[CNAE] HTTP %s para CNPJ %s (%s)", resp.status_code, cnpj_digits, emp["nome"])
                erros += 1
                time.sleep(21)
                continue
            data = resp.json()
            atividades = data.get("atividade_principal") or []
            if not atividades:
                erros += 1
                time.sleep(21)
                continue
            cnae_code = (atividades[0].get("code") or "").replace(".", "").replace("-", "").replace("/", "")
            cnae_desc = atividades[0].get("text") or ""
            conn2 = get_connection()
            conn2.execute(
                "UPDATE empresas SET cnae_codigo=?, segmento=? WHERE id=?",
                (cnae_code, cnae_desc, emp["id"]),
            )
            conn2.commit()
            conn2.close()
            logger.info("[CNAE] Empresa %s (%s): %s — %s", emp["id"], emp["nome"], cnae_code, cnae_desc[:60])
            atualizadas += 1
        except Exception as e:
            logger.error("[CNAE] Erro ao enriquecer empresa %s: %s", emp["id"], e, exc_info=True)
            erros += 1
        time.sleep(21)  # rate-limit: 3 req/min

    return {"atualizadas": atualizadas, "erros": erros, "sem_cnpj": sem_cnpj, "total": len(pendentes)}


def contar_por_status(tenant_id=None) -> dict:
    conn = get_connection()
    if tenant_id is not None:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM empresas WHERE tenant_id=? GROUP BY status",
            (tenant_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM empresas GROUP BY status"
        ).fetchall()
    conn.close()
    return {r["status"]: r["total"] for r in rows}
