"""account command — show authenticated provider info."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.command("account")
def account_cmd() -> None:
    """Show current LLM provider and authentication status."""
    from cli.adapters.llm.factory import get_llm_provider

    provider = get_llm_provider()

    with console.status("[cyan]Querying provider...[/cyan]"):
        info = provider.get_account_info()

    table = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
    table.add_column("key", style="bold cyan", min_width=22)
    table.add_column("value", style="white")

    _SKIP = {"available_models"}
    for key, value in info.items():
        if key in _SKIP:
            continue
        label = key.replace("_", " ").title()
        if key == "auth":
            styled = f"[bold green]{value}[/bold green]" if value == "ok" else f"[bold red]{value}[/bold red]"
            table.add_row(label, styled)
        else:
            table.add_row(label, str(value))

    models = info.get("available_models")
    if models:
        table.add_row("", "")
        table.add_row("[bold cyan]Available Models[/bold cyan]", "")
        for m in models:
            table.add_row("", f"[dim]•[/dim] {m}")

    console.print(Panel(table, title="[bold]Account / Status[/bold]", border_style="cyan", padding=(1, 2)))
