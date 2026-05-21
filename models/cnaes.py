import json
import requests
import database

CNAES_POR_CATEGORIA = {
    "Indústria e Manufatura": [
        "1011201", "1012101", "1031700", "1091100",
        "1311100", "1411802",
        "2011800", "2031200", "2061400", "2110600",
        "2211100", "2221800",
        "2411300", "2421100", "2511000", "2531401",
        "2541100", "2610800", "2710401",
        "2811900", "2821601", "2910701", "2941700",
    ],
    "Construção Civil": [
        "4110700", "4120400",
        "4211101", "4211102",
        "4221901", "4222701",
        "4291000",
        "4311801", "4311802", "4312600", "4313400",
        "4321500", "4322301", "4330401", "4330499",
        "4391600", "4399103",
    ],
    "Comércio Varejista": [
        "4711301", "4711302", "4712100",
        "4721102", "4721103",
        "4731800",
        "4741500",
        "4751201", "4751202",
        "4771701", "4772500",
        "4781400", "4789001",
    ],
    "Comércio Atacadista": [
        "4611700", "4612100",
        "4621400",
        "4631100",
        "4641901", "4641902",
        "4661300",
        "4671100",
        "4681801", "4681802",
        "4691500",
    ],
    "Alimentação e Bebidas": [
        "5611201", "5611202", "5611203",
        "5612100",
        "5620101", "5620102",
        "1011201", "1031700", "1091100",
        "1111901", "1111902",
        "5629800",
    ],
    "Transporte e Logística": [
        "4921301", "4921302", "4922101", "4922102", "4923001",
        "4930200",
        "5011401", "5011402",
        "5111100",
        "5231101", "5231102",
        "5250801",
        "5310501", "5310502",
        "5320201",
    ],
    "Saúde e Medicina": [
        "8610101", "8610102",
        "8621601", "8621602",
        "8630501", "8630502",
        "8640201", "8640202", "8640203",
        "8650001", "8650002", "8650003",
        "8660700",
        "4771701",
        "3250705", "3250706",
    ],
    "Educação": [
        "8511200", "8512100", "8513900",
        "8520100",
        "8531700", "8532500",
        "8541400",
        "8542200",
        "8550301", "8550302",
        "8591100",
        "8599601", "8599602",
    ],
    "Tecnologia e TI": [
        "6201501", "6201502",
        "6202300",
        "6203100",
        "6204000",
        "6311900",
        "6319400",
        "6391700",
        "7110701",
    ],
    "Serviços Financeiros": [
        "6422100",
        "6423900",
        "6424701",
        "6431000",
        "6461100",
        "6470101",
        "6491300",
        "6499301",
        "6611801",
        "6612601",
    ],
    "Seguros e Previdência": [
        "6511101", "6511102",
        "6512000",
        "6521300",
        "6531500",
        "6550200",
        "6621501", "6621502",
        "6629100",
    ],
    "Imobiliário": [
        "6810201", "6810202",
        "6821801", "6821802",
        "6822600",
        "4110700",
        "7490105",
    ],
    "Agronegócio": [
        "0111301", "0111302", "0111303",
        "0112101", "0112102",
        "0119999",
        "0121101", "0121102",
        "0122901",
        "0130600",
        "0141501",
        "0151201",
        "0159801",
        "0162801",
        "0210101",
    ],
    "Mineração e Energia": [
        "0500301", "0500302",
        "0600001", "0600002",
        "0710301", "0710302",
        "0723402",
        "0810001",
        "3511501", "3511502",
        "3512300",
        "3513100",
        "3520401", "3520402",
        "3531600",
        "3600601", "3600602",
    ],
    "Governo e Administração Pública": [
        "8411600",
        "8412400",
        "8413200",
        "8421300",
        "8422100",
        "8423000",
        "8424800",
        "8425600",
        "8430200",
    ],
    "Serviços Empresariais": [
        "7020400", "7111100", "7112000", "7119701", "7119702",
        "7120100", "7210000", "7220700", "7311400", "7312200",
        "7319001", "7319004", "7490101", "7490102", "7490103",
        "7490104", "7490105", "8211300", "8219901", "8219999",
        "8220200", "8299701",
    ],
    "Recursos Humanos e RH": [
        "7810800", "7820500", "7830200",
    ],
    "Hotelaria e Turismo": [
        "5510801", "5510802", "5590601", "5590602", "5590699",
        "7911200", "7912100", "7990200", "5611201",
    ],
    "Entretenimento e Cultura": [
        "9001901", "9001902", "9001903", "9001999", "9002701",
        "9003500", "9101500", "9200301", "9200302", "9200303",
        "9311500", "9312300", "9313100", "9319101", "9319199",
        "5911101", "5912001", "5913800", "5920100", "6010100",
    ],
    "Telecomunicações": [
        "6110801", "6110802", "6120501", "6120502", "6130200",
        "6141800", "6142600", "6143400", "6190601", "6190602",
        "6190699",
    ],
    "Varejo de Combustível": [
        "4731800", "4732600",
    ],
    "Cooperativas": [
        "6494300", "4622200", "4623109", "0161099", "4613300",
    ],
}

_IBGE_URL = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
_CACHE_TTL_SECONDS = 86400 * 7  # 7 days


def _get_from_db():
    try:
        conn = database.get_connection()
        row = conn.execute(
            "SELECT dados, atualizado_em FROM cnae_cache WHERE id=1"
        ).fetchone()
        conn.close()
        if not row:
            return None, None
        return row["dados"], row["atualizado_em"]
    except Exception:
        return None, None


def _salvar_no_db(dados_json: str):
    import datetime as _dt
    try:
        conn = database.get_connection()
        now = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "INSERT INTO cnae_cache (id, dados, atualizado_em) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados, atualizado_em = EXCLUDED.atualizado_em",
            (dados_json, now),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"cnae_cache salvar erro: {e}")


def _cache_fresco(ts: str) -> bool:
    import datetime as _dt
    if not ts:
        return False
    try:
        salvo = _dt.datetime.fromisoformat(str(ts))
        return (_dt.datetime.now() - salvo).total_seconds() < _CACHE_TTL_SECONDS
    except Exception:
        return False


def carregar_todos_cnaes() -> dict:
    """Returns dict keyed by divisão code (first 2 digits), fetched from IBGE API with DB cache."""
    dados_str, ts = _get_from_db()
    if dados_str and _cache_fresco(ts):
        try:
            return json.loads(dados_str)
        except Exception:
            pass

    try:
        r = requests.get(
            _IBGE_URL, timeout=15, headers={"User-Agent": "KryloCRM/1.0"}
        )
        r.raise_for_status()
        subclasses = r.json()
    except Exception as e:
        print(f"IBGE CNAE fetch erro: {e}")
        if dados_str:
            try:
                return json.loads(dados_str)
            except Exception:
                pass
        return {}

    por_divisao: dict = {}
    for sub in subclasses:
        cod = str(sub.get("id", "")).strip()
        if not cod or len(cod) < 2:
            continue
        div_cod = cod[:2]
        try:
            div_nome = sub["classe"]["grupo"]["divisao"]["descricao"]
        except (KeyError, TypeError):
            div_nome = f"Divisão {div_cod}"

        if div_cod not in por_divisao:
            por_divisao[div_cod] = {"nome": div_nome, "itens": []}
        por_divisao[div_cod]["itens"].append(
            {"id": cod, "descricao": sub.get("descricao", "")}
        )

    resultado = dict(sorted(por_divisao.items()))
    _salvar_no_db(json.dumps(resultado, ensure_ascii=False))
    return resultado


def buscar_cnaes(q: str) -> list:
    """Search CNAEs by description or code, returns up to 50 matches."""
    todos = carregar_todos_cnaes()
    q = q.lower().strip()
    resultado = []
    for div_cod, div in todos.items():
        for item in div["itens"]:
            if q in item["descricao"].lower() or q in item["id"]:
                resultado.append(
                    {
                        "id": item["id"],
                        "descricao": item["descricao"],
                        "divisao": div["nome"],
                    }
                )
    return resultado[:50]
