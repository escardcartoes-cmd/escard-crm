"""
Baixa e importa o dump oficial da Receita Federal.
Fonte: https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj
Arquivos CSV públicos e gratuitos.

USO: python scripts/importar_receita_federal.py --uf ES --limite 50000
"""

import requests
import zipfile
import io
import csv
import os
import sys
import time
import argparse

# Garante que a raiz do projeto está no path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from database import get_new_db_connection, _USE_PG

URLS_RECEITA = [
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos0.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos1.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos2.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos3.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos4.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos5.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos6.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos7.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos8.zip",
    "https://dadosabertos.rfb.gov.br/CNPJ/Estabelecimentos9.zip",
]

URL_MUNICIPIOS = "https://dadosabertos.rfb.gov.br/CNPJ/Municipios.zip"
URL_CNAES     = "https://dadosabertos.rfb.gov.br/CNPJ/Cnaes.zip"


def baixar_tabela_municipios() -> dict:
    """Baixa tabela de municípios para converter código em nome."""
    print("Baixando tabela de municípios...")
    municipios = {}
    try:
        r = requests.get(URL_MUNICIPIOS, timeout=60, stream=True)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} — tabela de municípios indisponível")
            return municipios
        z = zipfile.ZipFile(io.BytesIO(r.content))
        with z.open(z.namelist()[0]) as f:
            reader = csv.reader(
                io.TextIOWrapper(f, encoding='latin1'),
                delimiter=';'
            )
            for row in reader:
                if len(row) >= 2:
                    municipios[row[0].strip()] = row[1].strip()
        print(f"  {len(municipios)} municípios carregados")
    except Exception as e:
        print(f"  Aviso: não foi possível baixar municípios: {e}")
    return municipios


def baixar_tabela_cnaes() -> dict:
    """Baixa tabela de CNAEs para converter código em descrição."""
    print("Baixando tabela de CNAEs...")
    cnaes = {}
    try:
        r = requests.get(URL_CNAES, timeout=60, stream=True)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} — tabela de CNAEs indisponível")
            return cnaes
        z = zipfile.ZipFile(io.BytesIO(r.content))
        with z.open(z.namelist()[0]) as f:
            reader = csv.reader(
                io.TextIOWrapper(f, encoding='latin1'),
                delimiter=';'
            )
            for row in reader:
                if len(row) >= 2:
                    cnaes[row[0].strip()] = row[1].strip()
        print(f"  {len(cnaes)} CNAEs carregados")
    except Exception as e:
        print(f"  Aviso: não foi possível baixar CNAEs: {e}")
    return cnaes


def importar_estabelecimentos(uf_filtro=None, cnaes_filtro=None,
                               limite=50000, municipios=None, cnaes_desc=None):
    """
    Importa estabelecimentos do dump da Receita Federal.
    Filtra por UF e lista de CNAEs se fornecidos.
    """
    if municipios is None:
        municipios = {}
    if cnaes_desc is None:
        cnaes_desc = {}

    db = get_new_db_connection()
    total_importado = 0
    total_processado = 0

    from models.prospeccao_autonoma import CNAES_BENEFICIOS_CORPORATIVOS
    cnaes_alvo = set(cnaes_filtro or CNAES_BENEFICIOS_CORPORATIVOS)
    cnaes_prefixos = set(c[:4] for c in cnaes_alvo)

    print(f"\n🚀 Iniciando importação")
    print(f"   UF: {uf_filtro or 'Todas'}")
    print(f"   CNAEs alvo: {len(cnaes_alvo)}")
    print(f"   Limite: {limite} empresas")

    for url in URLS_RECEITA:
        if total_importado >= limite:
            break

        print(f"\n📥 Baixando {url.split('/')[-1]}...")

        try:
            r = requests.get(url, timeout=300, stream=True)
            if r.status_code != 200:
                print(f"   Erro HTTP {r.status_code} — pulando")
                continue

            tamanho = int(r.headers.get('content-length', 0))
            if tamanho:
                print(f"   Tamanho: {tamanho / 1024 / 1024:.0f}MB")

            z = zipfile.ZipFile(io.BytesIO(r.content))

            with z.open(z.namelist()[0]) as f:
                reader = csv.reader(
                    io.TextIOWrapper(f, encoding='latin1'),
                    delimiter=';'
                )

                batch = []

                for row in reader:
                    total_processado += 1

                    if len(row) < 30:
                        continue

                    try:
                        cnpj_base  = row[0].strip().zfill(8)
                        cnpj_ordem = row[1].strip().zfill(4)
                        cnpj_dv    = row[2].strip().zfill(2)
                        cnpj = cnpj_base + cnpj_ordem + cnpj_dv

                        # 02 = ATIVA
                        situacao_cod = row[5].strip()
                        if situacao_cod != '02':
                            continue

                        uf = row[25].strip()
                        if uf_filtro and uf != uf_filtro:
                            continue

                        cnae = row[11].strip()
                        if cnaes_prefixos and not any(cnae.startswith(p) for p in cnaes_prefixos):
                            continue

                        tipo = 'MATRIZ' if row[3].strip() == '1' else 'FILIAL'

                        municipio_cod = row[26].strip()
                        municipio = municipios.get(municipio_cod, municipio_cod)

                        ddd = row[27].strip()
                        tel = row[28].strip()
                        telefone = ''.join(filter(str.isdigit, f"{ddd}{tel}")) if ddd and tel else ''

                        email = row[33].strip().lower() if len(row) > 33 else ''

                        nome_fantasia = row[4].strip()
                        cnae_d = cnaes_desc.get(cnae, '')

                        batch.append((
                            cnpj, '', nome_fantasia, cnae, cnae_d,
                            uf, municipio, telefone or None, email or None,
                            'ATIVA', '', None, None, tipo
                        ))

                        if len(batch) >= 500:
                            _inserir_batch(db, batch)
                            total_importado += len(batch)
                            batch = []
                            print(f"   ✅ {total_importado} empresas importadas...")

                            if total_importado >= limite:
                                break

                    except Exception:
                        continue

                if batch:
                    _inserir_batch(db, batch)
                    total_importado += len(batch)

        except Exception as e:
            print(f"   Erro ao processar arquivo: {e}")
            continue

    db.close()
    print(f"\n✅ Importação concluída: {total_importado} empresas")
    print(f"   Total processado: {total_processado} registros")
    return total_importado


def _inserir_batch(db, batch):
    """Insere batch de empresas no banco."""
    if _USE_PG:
        db.executemany("""
            INSERT INTO rf_empresas
            (cnpj, razao_social, nome_fantasia, cnae_principal, cnae_descricao,
             uf, municipio, telefone, email, situacao, porte,
             capital_social, data_abertura, tipo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (cnpj) DO UPDATE SET
                telefone = EXCLUDED.telefone,
                email = EXCLUDED.email,
                importado_em = NOW()
        """, batch)
    else:
        db.executemany("""
            INSERT OR IGNORE INTO rf_empresas
            (cnpj, razao_social, nome_fantasia, cnae_principal, cnae_descricao,
             uf, municipio, telefone, email, situacao, porte,
             capital_social, data_abertura, tipo)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
    db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Importa base da Receita Federal')
    parser.add_argument('--uf',     default='ES', help='UF para filtrar (ex: ES, SP)')
    parser.add_argument('--limite', type=int, default=50000, help='Limite de empresas')
    args = parser.parse_args()

    municipios = baixar_tabela_municipios()
    cnaes_desc = baixar_tabela_cnaes()

    importar_estabelecimentos(
        uf_filtro=args.uf,
        limite=args.limite,
        municipios=municipios,
        cnaes_desc=cnaes_desc,
    )
