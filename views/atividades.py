from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import models.atividade as atv_model
import models.empresa as emp_model
import models.oportunidade as op_model

console = Console()


# ── helpers ───────────────────────────────────────────────────────────────────

def _tabela(atividades: list) -> Table:
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID",           justify="right", width=4)
    t.add_column("Data",         width=12, style="dim")
    t.add_column("Tipo",         style="cyan")
    t.add_column("Empresa")
    t.add_column("Oportunidade")
    t.add_column("Descrição")
    for a in atividades:
        t.add_row(
            str(a["id"]),
            a["data"],
            a["tipo"],
            a["empresa_nome"] or "-",
            a["oportunidade_titulo"] or "-",
            (a["descricao"] or "")[:60],
        )
    return t


# ── ações ─────────────────────────────────────────────────────────────────────

def listar() -> None:
    console.clear()
    console.print("  Quantas atividades exibir? (Enter = 20): ", end="")
    try:
        limit = int(input().strip() or "20")
    except ValueError:
        limit = 20
    atividades = atv_model.listar(limit=limit)
    if atividades:
        console.print(_tabela(atividades))
    else:
        console.print("[yellow]Nenhuma atividade registrada.[/yellow]")
    input("\n  [Enter] para voltar...")


def criar() -> None:
    console.clear()
    console.print(Panel("[bold]Nova Atividade[/bold]", border_style="green"))

    # Empresa (obrigatória)
    from views.empresas import _tabela as emp_tabela
    empresas = emp_model.listar()
    if not empresas:
        console.print("[red]Cadastre uma empresa antes de registrar uma atividade.[/red]")
        input("  [Enter] para voltar...")
        return
    console.print(emp_tabela(empresas))
    console.print("  ID da empresa: ", end="")
    emp_id = None
    try:
        val = input().strip()
        emp = emp_model.buscar_por_id(int(val)) if val else None
        emp_id = emp["id"] if emp else None
    except (ValueError, TypeError):
        pass

    if emp_id is None:
        console.print("[red]Empresa não encontrada.[/red]")
        input("  [Enter] para voltar...")
        return

    # Oportunidade (opcional)
    op_id = None
    ops = op_model.listar(empresa_id=emp_id)
    if ops:
        from views.oportunidades import _tabela as op_tabela
        console.print(op_tabela(ops))
        console.print("  ID da oportunidade (Enter para pular): ", end="")
        try:
            val = input().strip()
            if val:
                op = op_model.buscar_por_id(int(val))
                op_id = op["id"] if op else None
        except (ValueError, TypeError):
            pass

    # Tipo
    console.print(f"\n  Tipos disponíveis: {atv_model.TIPOS}")
    console.print("  Tipo: ", end="")
    tipo = input().strip()
    if tipo not in atv_model.TIPOS:
        tipo = "outro"

    console.print("  Descrição: ", end="")
    descricao = input().strip() or None

    console.print("  Data AAAA-MM-DD (Enter = hoje): ", end="")
    data_str = input().strip() or None

    new_id = atv_model.criar({
        "empresa_id":      emp_id,
        "oportunidade_id": op_id,
        "tipo":            tipo,
        "descricao":       descricao,
        "data":            data_str,
    })
    console.print(f"\n  [green]Atividade registrada com ID {new_id}.[/green]")
    input("  [Enter] para continuar...")


def excluir() -> None:
    console.clear()
    console.print(Panel("[bold red]Excluir Atividade[/bold red]", border_style="red"))
    atividades = atv_model.listar(limit=30)
    if not atividades:
        console.print("[yellow]Nenhuma atividade registrada.[/yellow]")
        input("  [Enter] para voltar...")
        return
    console.print(_tabela(atividades))
    console.print("\n  ID (ou Enter para cancelar): ", end="")
    val = input().strip()
    if not val:
        input("  [Enter] para voltar...")
        return
    try:
        atv_model.excluir(int(val))
        console.print("  [green]Atividade excluída.[/green]")
    except ValueError:
        console.print("  [red]ID inválido.[/red]")
    input("  [Enter] para continuar...")


# ── menu ──────────────────────────────────────────────────────────────────────

def menu() -> None:
    while True:
        console.clear()
        console.print(Panel("[bold]Atividades[/bold]", border_style="blue"))
        console.print("  [cyan]1[/cyan]  Listar recentes")
        console.print("  [cyan]2[/cyan]  Registrar atividade")
        console.print("  [cyan]3[/cyan]  Excluir atividade")
        console.print("  [cyan]0[/cyan]  Voltar\n")
        opcao = input("  Escolha: ").strip()
        if   opcao == "1": listar()
        elif opcao == "2": criar()
        elif opcao == "3": excluir()
        elif opcao == "0": break
