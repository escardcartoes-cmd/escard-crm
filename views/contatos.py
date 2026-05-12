from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import models.contato as cont_model
import models.empresa as emp_model

console = Console()


# ── helpers ───────────────────────────────────────────────────────────────────

def _tabela(contatos: list) -> Table:
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID",       justify="right", width=4)
    t.add_column("Nome")
    t.add_column("Empresa")
    t.add_column("Cargo")
    t.add_column("E-mail")
    t.add_column("Telefone")
    for c in contatos:
        t.add_row(
            str(c["id"]),
            c["nome"],
            c["empresa_nome"],
            c["cargo"] or "-",
            c["email"] or "-",
            c["telefone"] or "-",
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


def _selecionar_contato() -> dict | None:
    contatos = cont_model.listar()
    if not contatos:
        console.print("[yellow]Nenhum contato cadastrado.[/yellow]")
        return None
    console.print(_tabela(contatos))
    console.print("\n  ID (ou Enter para cancelar): ", end="")
    val = input().strip()
    if not val:
        return None
    try:
        c = cont_model.buscar_por_id(int(val))
        if not c:
            console.print("[red]ID não encontrado.[/red]")
        return c
    except ValueError:
        console.print("[red]ID inválido.[/red]")
        return None


def _formulario(existente: dict | None = None) -> dict:
    e = existente or {}
    return {
        "nome":     _ask("Nome",     e.get("nome", ""),     obrigatorio=True),
        "cargo":    _ask("Cargo",    e.get("cargo", "")),
        "email":    _ask("E-mail",   e.get("email", "")),
        "telefone": _ask("Telefone", e.get("telefone", "")),
    }


# ── ações ─────────────────────────────────────────────────────────────────────

def listar() -> None:
    console.clear()
    contatos = cont_model.listar()
    if contatos:
        console.print(_tabela(contatos))
    else:
        console.print("[yellow]Nenhum contato cadastrado.[/yellow]")
    input("\n  [Enter] para voltar...")


def listar_por_empresa() -> None:
    console.clear()
    emp = _selecionar_empresa()
    if not emp:
        input("  [Enter] para voltar...")
        return
    contatos = cont_model.listar(empresa_id=emp["id"])
    console.clear()
    console.print(Panel(f"[bold]Contatos — {emp['nome']}[/bold]", border_style="blue"))
    if contatos:
        console.print(_tabela(contatos))
    else:
        console.print("[yellow]Nenhum contato nesta empresa.[/yellow]")
    input("\n  [Enter] para voltar...")


def criar() -> None:
    console.clear()
    console.print(Panel("[bold]Novo Contato[/bold]", border_style="green"))
    emp = _selecionar_empresa()
    if not emp:
        console.print("[red]Empresa não encontrada.[/red]")
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  Empresa: [bold]{emp['nome']}[/bold]\n")
    dados = _formulario()
    dados["empresa_id"] = emp["id"]
    new_id = cont_model.criar(dados)
    console.print(f"\n  [green]Contato criado com ID {new_id}.[/green]")
    input("  [Enter] para continuar...")


def editar() -> None:
    console.clear()
    console.print(Panel("[bold]Editar Contato[/bold]", border_style="yellow"))
    c = _selecionar_contato()
    if not c:
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  Editando: [bold]{c['nome']}[/bold]  (Enter = manter valor atual)\n")
    dados = _formulario(dict(c))
    dados["empresa_id"] = c["empresa_id"]
    cont_model.atualizar(c["id"], dados)
    console.print("  [green]Contato atualizado.[/green]")
    input("  [Enter] para continuar...")


def excluir() -> None:
    console.clear()
    console.print(Panel("[bold red]Excluir Contato[/bold red]", border_style="red"))
    c = _selecionar_contato()
    if not c:
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  [red]Excluir '{c['nome']}'?[/red]  Digite [bold]SIM[/bold] para confirmar: ", end="")
    if input().strip().upper() == "SIM":
        cont_model.excluir(c["id"])
        console.print("  [green]Contato excluído.[/green]")
    else:
        console.print("  [yellow]Cancelado.[/yellow]")
    input("  [Enter] para continuar...")


# ── menu ──────────────────────────────────────────────────────────────────────

def menu() -> None:
    while True:
        console.clear()
        console.print(Panel("[bold]Contatos[/bold]", border_style="blue"))
        console.print("  [cyan]1[/cyan]  Listar todos")
        console.print("  [cyan]2[/cyan]  Filtrar por empresa")
        console.print("  [cyan]3[/cyan]  Novo contato")
        console.print("  [cyan]4[/cyan]  Editar contato")
        console.print("  [cyan]5[/cyan]  Excluir contato")
        console.print("  [cyan]0[/cyan]  Voltar\n")
        opcao = input("  Escolha: ").strip()
        if   opcao == "1": listar()
        elif opcao == "2": listar_por_empresa()
        elif opcao == "3": criar()
        elif opcao == "4": editar()
        elif opcao == "5": excluir()
        elif opcao == "0": break
