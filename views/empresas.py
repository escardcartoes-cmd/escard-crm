from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import models.empresa as emp_model

console = Console()

_STATUS_COLORS = {"prospect": "yellow", "cliente": "green", "inativo": "dim"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _tabela(empresas: list) -> Table:
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID",       justify="right", width=4)
    t.add_column("Nome")
    t.add_column("CNPJ",     width=18)
    t.add_column("Segmento")
    t.add_column("Porte")
    t.add_column("Status",   width=10)
    t.add_column("Cidade/UF")
    for e in empresas:
        color = _STATUS_COLORS.get(e["status"], "white")
        cidade_uf = "/".join(filter(None, [e["cidade"], e["estado"]])) or "-"
        t.add_row(
            str(e["id"]),
            e["nome"],
            e["cnpj"] or "-",
            e["segmento"] or "-",
            e["porte"] or "-",
            f"[{color}]{e['status']}[/{color}]",
            cidade_uf,
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


def _formulario(existente: dict | None = None) -> dict:
    e = existente or {}
    dados: dict = {}
    dados["nome"]     = _ask("Nome",       e.get("nome", ""),     obrigatorio=True)
    dados["cnpj"]     = _ask("CNPJ",       e.get("cnpj", ""))
    dados["segmento"] = _ask("Segmento",   e.get("segmento", ""))
    console.print(f"  Porte {emp_model.PORTES} (atual: {e.get('porte', '')}): ", end="")
    porte = input().strip()
    dados["porte"] = porte if porte else (e.get("porte") or None)
    console.print(f"  Status {emp_model.STATUS} (atual: {e.get('status', 'prospect')}): ", end="")
    status = input().strip()
    dados["status"] = status if status in emp_model.STATUS else (e.get("status") or "prospect")
    dados["telefone"] = _ask("Telefone",   e.get("telefone", ""))
    dados["email"]    = _ask("E-mail",     e.get("email", ""))
    dados["cidade"]   = _ask("Cidade",     e.get("cidade", ""))
    dados["estado"]   = _ask("Estado/UF",  e.get("estado", ""))
    return dados


def _selecionar() -> dict | None:
    empresas = emp_model.listar()
    if not empresas:
        console.print("[yellow]Nenhuma empresa cadastrada.[/yellow]")
        return None
    console.print(_tabela(empresas))
    console.print("\n  ID (ou Enter para cancelar): ", end="")
    val = input().strip()
    if not val:
        return None
    try:
        emp = emp_model.buscar_por_id(int(val))
        if not emp:
            console.print("[red]ID não encontrado.[/red]")
        return emp
    except ValueError:
        console.print("[red]ID inválido.[/red]")
        return None


# ── ações ─────────────────────────────────────────────────────────────────────

def listar() -> None:
    console.clear()
    empresas = emp_model.listar()
    if empresas:
        console.print(_tabela(empresas))
    else:
        console.print("[yellow]Nenhuma empresa cadastrada.[/yellow]")
    input("\n  [Enter] para voltar...")


def criar() -> None:
    console.clear()
    console.print(Panel("[bold]Nova Empresa[/bold]", border_style="green"))
    dados = _formulario()
    new_id = emp_model.criar(dados)
    console.print(f"\n  [green]Empresa criada com ID {new_id}.[/green]")
    input("  [Enter] para continuar...")


def editar() -> None:
    console.clear()
    console.print(Panel("[bold]Editar Empresa[/bold]", border_style="yellow"))
    emp = _selecionar()
    if not emp:
        input("  [Enter] para voltar...")
        return
    console.print(f"\n  Editando: [bold]{emp['nome']}[/bold]  (Enter = manter valor atual)\n")
    dados = _formulario(dict(emp))
    emp_model.atualizar(emp["id"], dados)
    console.print("  [green]Empresa atualizada.[/green]")
    input("  [Enter] para continuar...")


def excluir() -> None:
    console.clear()
    console.print(Panel("[bold red]Excluir Empresa[/bold red]", border_style="red"))
    emp = _selecionar()
    if not emp:
        input("  [Enter] para voltar...")
        return
    console.print(
        f"\n  [red]Isso excluirá '{emp['nome']}' e todos os contatos/oportunidades vinculados.[/red]"
    )
    console.print("  Digite [bold]SIM[/bold] para confirmar: ", end="")
    if input().strip().upper() == "SIM":
        emp_model.excluir(emp["id"])
        console.print("  [green]Empresa excluída.[/green]")
    else:
        console.print("  [yellow]Cancelado.[/yellow]")
    input("  [Enter] para continuar...")


def detalhar() -> None:
    console.clear()
    emp = _selecionar()
    if not emp:
        input("  [Enter] para voltar...")
        return

    import models.contato as cont_model
    import models.oportunidade as op_model

    console.clear()
    info = Table(show_header=False, box=None, padding=(0, 1))
    info.add_column("Campo", style="dim", width=16)
    info.add_column("Valor")
    for col in ["nome", "cnpj", "segmento", "porte", "status", "telefone", "email", "cidade", "estado", "criado_em"]:
        info.add_row(col, str(emp[col] or "-"))
    console.print(Panel(info, title=f"[bold]{emp['nome']}[/bold]", border_style="blue"))

    contatos = cont_model.listar(empresa_id=emp["id"])
    if contatos:
        tc = Table(title="Contatos", header_style="bold", show_header=True)
        tc.add_column("Nome"); tc.add_column("Cargo"); tc.add_column("E-mail"); tc.add_column("Telefone")
        for c in contatos:
            tc.add_row(c["nome"], c["cargo"] or "-", c["email"] or "-", c["telefone"] or "-")
        console.print(tc)

    ops = op_model.listar(empresa_id=emp["id"])
    if ops:
        to = Table(title="Oportunidades", header_style="bold", show_header=True)
        to.add_column("Título"); to.add_column("Estágio"); to.add_column("Valor Est.", justify="right"); to.add_column("Responsável")
        for o in ops:
            valor = f"R$ {o['valor_estimado']:,.2f}" if o["valor_estimado"] else "-"
            to.add_row(o["titulo"], o["estagio"], valor, o["responsavel"] or "-")
        console.print(to)

    input("\n  [Enter] para voltar...")


# ── menu ──────────────────────────────────────────────────────────────────────

def menu() -> None:
    while True:
        console.clear()
        console.print(Panel("[bold]Empresas[/bold]", border_style="blue"))
        console.print("  [cyan]1[/cyan]  Listar todas")
        console.print("  [cyan]2[/cyan]  Nova empresa")
        console.print("  [cyan]3[/cyan]  Editar empresa")
        console.print("  [cyan]4[/cyan]  Excluir empresa")
        console.print("  [cyan]5[/cyan]  Ver detalhes")
        console.print("  [cyan]0[/cyan]  Voltar\n")
        opcao = input("  Escolha: ").strip()
        if   opcao == "1": listar()
        elif opcao == "2": criar()
        elif opcao == "3": editar()
        elif opcao == "4": excluir()
        elif opcao == "5": detalhar()
        elif opcao == "0": break
