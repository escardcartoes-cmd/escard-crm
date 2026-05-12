from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import models.oportunidade as op_model
import models.empresa as emp_model

console = Console()

_ESTAGIO_COLORS = {
    "lead":            "yellow",
    "qualificado":     "cyan",
    "proposta":        "blue",
    "negociacao":      "magenta",
    "fechado_ganho":   "green",
    "fechado_perdido": "red",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _tabela(ops: list) -> Table:
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID",           justify="right", width=4)
    t.add_column("Título")
    t.add_column("Empresa")
    t.add_column("Estágio",      width=18)
    t.add_column("Valor Est.",   justify="right")
    t.add_column("Cartões",      justify="right", width=8)
    t.add_column("Responsável")
    t.add_column("Prev. Fech.",  width=12)
    for o in ops:
        color = _ESTAGIO_COLORS.get(o["estagio"], "white")
        label = op_model.ESTAGIO_LABELS.get(o["estagio"], o["estagio"])
        valor = f"R$ {o['valor_estimado']:,.2f}" if o["valor_estimado"] else "-"
        t.add_row(
            str(o["id"]),
            o["titulo"],
            o["empresa_nome"],
            f"[{color}]{label}[/{color}]",
            valor,
            str(o["num_cartoes"]) if o["num_cartoes"] else "-",
            o["responsavel"] or "-",
            o["previsao_fechamento"] or "-",
        )
    return t


def _ask(label: str, atual: str = "", obrigatorio: bool = False) -> str | None:
    sufixo = f" (atual: {atual})" if atual else ""
    while True:
        console.print(f"  {label}{sufixo}: ", end="")
        val = input().strip()
        if val:
            return val
        if atual:
            return atual
        if not obrigatorio:
            return None
        console.print("  [red]Campo obrigatório.[/red]")


def _selecionar_empresa() -> dict | None:
    from views.empresas import _tabela as emp_tabela
    empresas = emp_model.listar()
    if not empresas:
        console.print("[yellow]Nenhuma empresa cadastrada.[/yellow]")
        return None
    console.print(emp_tabela(empresas))
    console.print("  ID da empresa: ", end="")
    try:
        return emp_model.buscar_por_id(int(input().strip()))
    except (ValueError, TypeError):
        return None


def _selecionar_oportunidade() -> dict | None:
    ops = op_model.listar()
    if not ops:
        console.print("[yellow]Nenhuma oportunidade cadastrada.[/yellow]")
        return None
    console.print(_tabela(ops))
    console.print("\n  ID (ou Enter para cancelar): ", end="")
    val = input().strip()
    if not val:
        return None
    try:
        o = op_model.buscar_por_id(int(val))
        if not o:
            console.print("[red]ID não encontrado.[/red]")
        return o
    except ValueError:
        console.print("[red]ID inválido.[/red]")
        return None


def _formulario(existente: dict | None = None) -> dict:
    e = existente or {}
    dados: dict = {}

    dados["titulo"] = _ask("Título", e.get("titulo", ""), obrigatorio=True)

    console.print(f"  Estágio {op_model.ESTAGIOS}")
    console.print(f"  (atual: {e.get('estagio', 'lead')}): ", end="")
    est = input().strip()
    dados["estagio"] = est if est in op_model.ESTAGIOS else (e.get("estagio") or "lead")

    atual_val = str(e.get("valor_estimado", "") or "")
    console.print(f"  Valor estimado mensal R$ (atual: {atual_val}): ", end="")
    raw = input().strip()
    try:
        dados["valor_estimado"] = float(raw.replace(",", ".")) if raw else (e.get("valor_estimado") or None)
    except ValueError:
        dados["valor_estimado"] = e.get("valor_estimado") or None

    atual_nc = str(e.get("num_cartoes", "") or "")
    console.print(f"  Nº de cartões (atual: {atual_nc}): ", end="")
    raw = input().strip()
    try:
        dados["num_cartoes"] = int(raw) if raw else (e.get("num_cartoes") or None)
    except ValueError:
        dados["num_cartoes"] = e.get("num_cartoes") or None

    dados["responsavel"]          = _ask("Responsável",                   e.get("responsavel", ""))
    dados["previsao_fechamento"]   = _ask("Previsão fechamento AAAA-MM-DD", e.get("previsao_fechamento", ""))
    dados["notas"]                = _ask("Notas",                          e.get("notas", ""))

    return dados


# ── ações ─────────────────────────────────────────────────────────────────────

def listar() -> None:
    console.clear()
    ops = op_model.listar()
    if ops:
        console.print(_tabela(ops))
    else:
        console.print("[yellow]Nenhuma oportunidade cadastrada.[/yellow]")
    input("\n  [Enter] para voltar...")


def criar() -> None:
    console.clear()
    console.print(Panel("[bold]Nova Oportunidade[/bold]", border_style="green"))
    emp = _selecionar_empresa()
    if not emp:
        console.print("[red]Empresa não encontrada.[/red]")
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  Empresa: [bold]{emp['nome']}[/bold]\n")
    dados = _formulario()
    dados["empresa_id"] = emp["id"]
    new_id = op_model.criar(dados)
    console.print(f"\n  [green]Oportunidade criada com ID {new_id}.[/green]")
    input("  [Enter] para continuar...")


def editar() -> None:
    console.clear()
    console.print(Panel("[bold]Editar Oportunidade[/bold]", border_style="yellow"))
    o = _selecionar_oportunidade()
    if not o:
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  Editando: [bold]{o['titulo']}[/bold]  (Enter = manter valor atual)\n")
    dados = _formulario(dict(o))
    dados["empresa_id"] = o["empresa_id"]
    op_model.atualizar(o["id"], dados)
    console.print("  [green]Oportunidade atualizada.[/green]")
    input("  [Enter] para continuar...")


def avancar_estagio() -> None:
    console.clear()
    console.print(Panel("[bold]Avançar Estágio[/bold]", border_style="cyan"))
    o = _selecionar_oportunidade()
    if not o:
        input("  [Enter] para voltar...")
        return

    console.print(f"\n  Oportunidade: [bold]{o['titulo']}[/bold]")
    console.print(f"  Empresa:      {o['empresa_nome']}\n")

    for i, est in enumerate(op_model.ESTAGIOS, 1):
        marker = "▶" if est == o["estagio"] else " "
        color  = _ESTAGIO_COLORS.get(est, "white")
        label  = op_model.ESTAGIO_LABELS.get(est, est)
        console.print(f"  {marker} [cyan]{i}[/cyan]  [{color}]{label}[/{color}]")

    console.print("\n  Novo estágio (número ou nome, Enter para cancelar): ", end="")
    val = input().strip()
    if not val:
        return

    novo = None
    try:
        idx = int(val) - 1
        if 0 <= idx < len(op_model.ESTAGIOS):
            novo = op_model.ESTAGIOS[idx]
    except ValueError:
        if val in op_model.ESTAGIOS:
            novo = val

    if novo:
        dados = dict(o)
        dados["estagio"] = novo
        op_model.atualizar(o["id"], dados)
        label = op_model.ESTAGIO_LABELS.get(novo, novo)
        console.print(f"  [green]Estágio atualizado para '{label}'.[/green]")
    else:
        console.print("  [red]Estágio inválido.[/red]")
    input("  [Enter] para continuar...")


def excluir() -> None:
    console.clear()
    console.print(Panel("[bold red]Excluir Oportunidade[/bold red]", border_style="red"))
    o = _selecionar_oportunidade()
    if not o:
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  [red]Excluir '{o['titulo']}'?[/red]  Digite [bold]SIM[/bold] para confirmar: ", end="")
    if input().strip().upper() == "SIM":
        op_model.excluir(o["id"])
        console.print("  [green]Oportunidade excluída.[/green]")
    else:
        console.print("  [yellow]Cancelado.[/yellow]")
    input("  [Enter] para continuar...")


def detalhar() -> None:
    console.clear()
    o = _selecionar_oportunidade()
    if not o:
        input("  [Enter] para voltar...")
        return

    import models.atividade as atv_model

    console.clear()
    info = Table(show_header=False, box=None, padding=(0, 1))
    info.add_column("Campo", style="dim", width=22)
    info.add_column("Valor")
    campos = [
        ("Empresa",              o["empresa_nome"]),
        ("Estágio",              op_model.ESTAGIO_LABELS.get(o["estagio"], o["estagio"])),
        ("Valor estimado",       f"R$ {o['valor_estimado']:,.2f}" if o["valor_estimado"] else "-"),
        ("Nº de cartões",        str(o["num_cartoes"] or "-")),
        ("Responsável",          o["responsavel"] or "-"),
        ("Prev. fechamento",     o["previsao_fechamento"] or "-"),
        ("Notas",                o["notas"] or "-"),
        ("Criado em",            o["criado_em"]),
    ]
    for label, valor in campos:
        info.add_row(label, valor)
    console.print(Panel(info, title=f"[bold]{o['titulo']}[/bold]", border_style="magenta"))

    ativs = atv_model.listar(oportunidade_id=o["id"])
    if ativs:
        ta = Table(title="Atividades", header_style="bold", show_header=True)
        ta.add_column("Data", width=12, style="dim")
        ta.add_column("Tipo", style="cyan")
        ta.add_column("Descrição")
        for a in ativs:
            ta.add_row(a["data"], a["tipo"], a["descricao"] or "-")
        console.print(ta)

    input("\n  [Enter] para voltar...")


# ── menu ──────────────────────────────────────────────────────────────────────

def menu() -> None:
    while True:
        console.clear()
        console.print(Panel("[bold]Oportunidades[/bold]", border_style="magenta"))
        console.print("  [cyan]1[/cyan]  Listar todas")
        console.print("  [cyan]2[/cyan]  Nova oportunidade")
        console.print("  [cyan]3[/cyan]  Editar oportunidade")
        console.print("  [cyan]4[/cyan]  Avançar estágio")
        console.print("  [cyan]5[/cyan]  Excluir oportunidade")
        console.print("  [cyan]6[/cyan]  Ver detalhes")
        console.print("  [cyan]0[/cyan]  Voltar\n")
        opcao = input("  Escolha: ").strip()
        if   opcao == "1": listar()
        elif opcao == "2": criar()
        elif opcao == "3": editar()
        elif opcao == "4": avancar_estagio()
        elif opcao == "5": excluir()
        elif opcao == "6": detalhar()
        elif opcao == "0": break
