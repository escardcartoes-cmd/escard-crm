import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import database
from views import dashboard, empresas, contatos, oportunidades, atividades

console = Console()


def main() -> None:
    database.init_db()

    while True:
        console.clear()
        console.print(Panel(
            Text("ESCARD  CRM", justify="center", style="bold green"),
            subtitle="[dim]Cartão de Benefícios B2B[/dim]",
            border_style="green",
            padding=(1, 4),
        ))
        console.print("  [cyan]1[/cyan]  Dashboard")
        console.print("  [cyan]2[/cyan]  Empresas")
        console.print("  [cyan]3[/cyan]  Contatos")
        console.print("  [cyan]4[/cyan]  Oportunidades")
        console.print("  [cyan]5[/cyan]  Atividades")
        console.print("  [cyan]0[/cyan]  Sair\n")

        try:
            opcao = input("  Escolha: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if   opcao == "1": dashboard.menu()
        elif opcao == "2": empresas.menu()
        elif opcao == "3": contatos.menu()
        elif opcao == "4": oportunidades.menu()
        elif opcao == "5": atividades.menu()
        elif opcao == "0": break

    console.print("\n  [dim]Até logo![/dim]\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
