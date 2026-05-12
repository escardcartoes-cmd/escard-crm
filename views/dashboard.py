from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import models.empresa as emp_model
import models.oportunidade as op_model
import models.atividade as atv_model

console = Console()

_ESTAGIO_COLORS = {
    "lead": "yellow",
    "qualificado": "cyan",
    "proposta": "blue",
    "negociacao": "magenta",
    "fechado_ganho": "green",
    "fechado_perdido": "red",
}


def menu() -> None:
    console.clear()
    console.print(Panel(
        Text("DASHBOARD  —  ESCARD CRM", justify="center", style="bold green"),
        subtitle="Cartão de Benefícios B2B",
    ))

    # ── Empresas ──────────────────────────────────────────────────────────────
    status_counts = emp_model.contar_por_status()
    total_emp = sum(status_counts.values())

    t_emp = Table(show_header=False, box=None, padding=(0, 2))
    t_emp.add_column("", style="dim")
    t_emp.add_column("", justify="right")
    t_emp.add_row("Total", f"[bold]{total_emp}[/bold]")
    t_emp.add_row("Clientes",  f"[green]{status_counts.get('cliente',  0)}[/green]")
    t_emp.add_row("Prospects", f"[yellow]{status_counts.get('prospect', 0)}[/yellow]")
    t_emp.add_row("Inativos",  f"[dim]{status_counts.get('inativo',  0)}[/dim]")

    # ── Pipeline ──────────────────────────────────────────────────────────────
    estagio_counts = op_model.contar_por_estagio()
    pipeline_val   = op_model.valor_total_pipeline()
    fechados       = ("fechado_ganho", "fechado_perdido")
    em_aberto      = sum(v for k, v in estagio_counts.items() if k not in fechados)

    t_pipe = Table(show_header=False, box=None, padding=(0, 2))
    t_pipe.add_column("", style="dim")
    t_pipe.add_column("", justify="right")
    t_pipe.add_row("Em aberto",  f"[cyan]{em_aberto}[/cyan]")
    t_pipe.add_row("Ganhas",     f"[green]{estagio_counts.get('fechado_ganho',   0)}[/green]")
    t_pipe.add_row("Perdidas",   f"[red]{estagio_counts.get('fechado_perdido', 0)}[/red]")
    t_pipe.add_row("Pipeline",   f"[bold yellow]R$ {pipeline_val:,.2f}[/bold yellow]")

    console.print(Columns([
        Panel(t_emp,  title="[bold]Empresas[/bold]",  border_style="blue",    width=30),
        Panel(t_pipe, title="[bold]Pipeline[/bold]",  border_style="magenta", width=36),
    ]))

    # ── Distribuição por estágio ───────────────────────────────────────────────
    if estagio_counts:
        t_est = Table(title="Distribuição do Pipeline", header_style="bold", show_header=True)
        t_est.add_column("Estágio", style="cyan")
        t_est.add_column("Qtd", justify="right")
        for est in op_model.ESTAGIOS:
            qtd = estagio_counts.get(est, 0)
            if qtd:
                color = _ESTAGIO_COLORS.get(est, "white")
                label = op_model.ESTAGIO_LABELS.get(est, est)
                t_est.add_row(f"[{color}]{label}[/{color}]", str(qtd))
        console.print(t_est)

    # ── Atividades recentes ───────────────────────────────────────────────────
    ativs = atv_model.listar(limit=5)
    if ativs:
        t_atv = Table(title="Últimas 5 Atividades", header_style="bold", show_header=True)
        t_atv.add_column("Data",       width=12, style="dim")
        t_atv.add_column("Tipo",       style="cyan")
        t_atv.add_column("Empresa")
        t_atv.add_column("Descrição")
        for a in ativs:
            t_atv.add_row(
                a["data"],
                a["tipo"],
                a["empresa_nome"] or "-",
                (a["descricao"] or "")[:55],
            )
        console.print(t_atv)

    input("\n  [Enter] para voltar ao menu principal...")
