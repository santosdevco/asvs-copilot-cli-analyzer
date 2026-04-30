"""
chat.py — Interactive chat command
───────────────────────────────────
Conversational interface for discussing security analysis with AI.
"""
from __future__ import annotations

import click
import sys
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from cli.core import load_component_index
from cli.core.interactive_llm import InteractiveLLMClient, StreamingLLMClient
from cli.core.app_logger import init_app_logger, log_event

console = Console()


@click.command("chat")
@click.argument("app_name")
@click.option("--component", help="Focus chat on a specific component.")
@click.option("--chapter", help="Focus chat on a specific ASVS chapter.")
@click.option("--streaming", "-s", is_flag=True, help="Enable streaming responses and file access monitoring.")
def chat_cmd(app_name: str, component: str | None, chapter: str | None, streaming: bool) -> None:
    """Interactive chat mode for discussing security analysis with AI."""
    init_app_logger(
        app_name=app_name,
        command_name="chat",
        command_line=" ".join(sys.argv),
        options={"component": component, "chapter": chapter, "streaming": streaming},
    )
    log_event("chat.started", {"component": component, "chapter": chapter, "streaming": streaming})
    
    console.print(f"[bold cyan]💬 Security Analysis Chat[/bold cyan] - {app_name}")
    console.print("[dim]Type 'help' for commands, 'quit' to exit[/dim]\n")
    
    # Load context if available
    context_info = []
    try:
        index = load_component_index(app_name)
        context_info.append(f"Loaded {len(index.project_triage)} components from triage analysis")
        
        if component:
            matching_components = [c for c in index.project_triage if component.lower() in c.component_id.lower()]
            if matching_components:
                comp = matching_components[0]
                context_info.append(f"Focusing on component: {comp.component_name} (Risk: {comp.risk_level})")
            else:
                console.print(f"[yellow]Warning: Component '{component}' not found[/yellow]")
                
    except FileNotFoundError:
        context_info.append("No triage analysis found. Consider running 'triage' command first.")
    
    if context_info:
        console.print(Panel(
            "\n".join(context_info),
            title="[cyan]Available Context[/cyan]",
            border_style="cyan"
        ))
    
    # Initialize interactive client
    client = StreamingLLMClient(verbose=True, interactive=False, streaming=streaming)
    
    # Build initial context prompt
    context_prompt = f"""
You are a security expert assistant helping with OWASP ASVS v5.0 analysis of application '{app_name}'.

Available context:
{chr(10).join(context_info)}

You can help with:
- Explaining security analysis results
- Suggesting remediation strategies  
- Clarifying ASVS requirements
- Discussing architectural security patterns
- Answering questions about specific components or vulnerabilities

Focus area: {f"Component '{component}'" if component else "General analysis"}
{f"ASVS Chapter: {chapter}" if chapter else ""}
"""
    
    # Chat loop
    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
            log_event("chat.user_input", {"text": user_input})
            
            if user_input.lower() in ['quit', 'exit', 'bye']:
                console.print("[cyan]Goodbye! 👋[/cyan]")
                break
            
            if user_input.lower() == 'help':
                show_help()
                continue
                
            if user_input.lower() == 'context':
                show_context_info(app_name, component, chapter)
                continue
                
            if user_input.lower() == 'clear':
                console.clear()
                continue
            
            # Generate AI response
            console.print("\n[bold blue]🤖 Security Expert[/bold blue]")
            
            # Combine context with user question
            full_prompt = f"{context_prompt}\n\nUser Question: {user_input}"
            
            try:
                response = client.ask_follow_up_question(full_prompt)
                log_event("chat.response", {"response_chars": len(response)})
                console.print(response)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                
        except KeyboardInterrupt:
            console.print("\n[cyan]Goodbye! 👋[/cyan]")
            break
        except EOFError:
            console.print("\n[cyan]Goodbye! 👋[/cyan]")
            break


def show_help():
    """Display available chat commands."""
    console.print(Panel(
        """Available commands:
        
• [cyan]help[/cyan]    - Show this help message
• [cyan]context[/cyan] - Show available analysis context  
• [cyan]clear[/cyan]   - Clear the screen
• [cyan]quit[/cyan]    - Exit chat mode

You can ask questions like:
• "What are the main security risks in this application?"
• "How can I fix the authentication vulnerabilities?"
• "Explain the ASVS V6 requirements"
• "What's the risk level of the payment component?"
• "Suggest remediation for SQL injection issues"
""",
        title="[cyan]Chat Help[/cyan]",
        border_style="cyan"
    ))


def show_context_info(app_name: str, component: str | None, chapter: str | None):
    """Display current context information."""
    info_lines = [f"Application: {app_name}"]
    
    if component:
        info_lines.append(f"Component Focus: {component}")
    if chapter:
        info_lines.append(f"ASVS Chapter Focus: {chapter}")
    
    try:
        index = load_component_index(app_name)
        info_lines.append(f"Components Available: {len(index.project_triage)}")
        for comp in index.project_triage[:5]:  # Show first 5
            info_lines.append(f"  • {comp.component_id} ({comp.risk_level})")
        if len(index.project_triage) > 5:
            info_lines.append(f"  ... and {len(index.project_triage) - 5} more")
    except FileNotFoundError:
        info_lines.append("No component analysis available")
    
    console.print(Panel(
        "\n".join(info_lines),
        title="[cyan]Current Context[/cyan]",
        border_style="cyan"
    ))