"""
interactive_llm.py
─────────────────
Enhanced LLM client with interactive capabilities, streaming responses, and file access monitoring.
Shows AI reasoning, file access, and allows real-time interaction.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from .llm_client import complete, extract_json, parse_json
from .app_logger import log_event, log_output, log_prompt

console = Console()


class StreamingLLMClient:
    """LLM client with real-time streaming and file access monitoring."""
    
    def __init__(self, verbose: bool = False, interactive: bool = False, streaming: bool = False):
        self.verbose = verbose
        self.interactive = interactive
        self.streaming = streaming
        self.conversation_history: list[dict[str, str]] = []
        self.files_accessed: list[str] = []
        self.tools_used: list[str] = []
    
    def _show_ai_activity_header(self) -> None:
        """Show header for AI activity monitoring."""
        if self.streaming:
            console.print(Panel(
                "[bold cyan]🤖 AI Analysis in Progress[/bold cyan]\n"
                "Watch below to see:\n"
                "• 🔧 Tools and files the AI accesses\n" 
                "• 💭 Real-time response generation\n"
                "• 📁 File reading activity",
                title="[cyan]Live AI Activity Monitor[/cyan]",
                border_style="cyan"
            ))
    
    def _show_reasoning(self, prompt: str) -> None:
        """Display the prompt and reasoning for transparency."""
        if not self.verbose:
            return
            
        console.print(Panel(
            prompt[:2000] + "..." if len(prompt) > 2000 else prompt,
            title="[cyan]AI Prompt (Internal Analysis)[/cyan]",
            border_style="cyan"
        ))
        
        # Show key aspects being analyzed
        console.print("\n[bold cyan]🧠 AI Analysis Focus:[/bold cyan]")
        
        if "triage" in prompt.lower() or "component" in prompt.lower():
            console.print("• Identifying security components and architecture")
            console.print("• Mapping asset tags and risk levels")
            console.print("• Analyzing data flows and trust boundaries")
        
        if "asvs" in prompt.lower() or "audit" in prompt.lower():
            console.print("• Evaluating OWASP ASVS v5.0 compliance")
            console.print("• Searching for security vulnerabilities")
            console.print("• Analyzing code against security requirements")
    
    def _ask_clarifying_questions(self, prompt: str) -> str:
        """Allow user to provide additional context if interactive mode is enabled."""
        if not self.interactive:
            return prompt
        
        console.print("\n[bold yellow]🤔 Interactive Mode: AI wants to ask questions[/bold yellow]")
        
        # Generate contextual questions based on the prompt
        questions = []
        if "triage" in prompt.lower():
            questions = [
                "Are there any specific security concerns you want me to focus on?",
                "Should I consider any non-standard architectural patterns?",
                "Are there external dependencies I should be aware of?",
                "Which files or components are most critical for security?"
            ]
        elif "audit" in prompt.lower():
            questions = [
                "Are there known security issues in this component?",
                "Should I prioritize certain types of vulnerabilities?",
                "Are there compliance requirements beyond ASVS?",
                "Which code patterns should I pay special attention to?"
            ]
        
        additional_context = []
        
        console.print("The AI has some clarifying questions. You can:")
        console.print("• Answer any that are relevant")
        console.print("• Press Enter to skip")
        console.print("• Type 'done' to finish\n")
        
        for i, question in enumerate(questions, 1):
            answer = Prompt.ask(f"[cyan]Q{i}:[/cyan] {question}", default="")
            log_event("interactive.question", {"index": i, "question": question, "answer": answer})
            if answer.lower() == 'done':
                break
            if answer.strip():
                additional_context.append(f"Q: {question}\nA: {answer}")
        
        if additional_context:
            additional_info = "\n\n=== ADDITIONAL USER CONTEXT ===\n" + "\n\n".join(additional_context)
            prompt = prompt + additional_info
            
            if self.verbose:
                console.print(Panel(
                    additional_info,
                    title="[green]Added User Context[/green]",
                    border_style="green"
                ))
        
        return prompt
    
    def _process_streaming_response(self, response: str) -> tuple[Any, str]:
        """Process streaming response after completion."""
        
        # Show summary of AI activity
        if self.streaming:
            console.print(f"\n[bold green]✅ AI Analysis Complete[/bold green]")
            console.print(f"[dim]Response length: {len(response)} characters[/dim]")
            
            if self.tools_used:
                console.print(f"[cyan]🔧 Tools used:[/cyan] {', '.join(self.tools_used)}")
            
            if self.files_accessed:
                console.print(f"[cyan]📁 Files accessed:[/cyan] {len(self.files_accessed)} files")
                for file_path in self.files_accessed[:5]:  # Show first 5
                    console.print(f"  • {file_path}")
                if len(self.files_accessed) > 5:
                    console.print(f"  ... and {len(self.files_accessed) - 5} more")
        
        # Show raw response in verbose mode
        if self.verbose and not self.streaming:
            console.print(Panel(
                response[:1500] + "..." if len(response) > 1500 else response,
                title="[cyan]AI Raw Response[/cyan]",
                border_style="blue"
            ))
        
        # Look for reasoning patterns in the response
        reasoning_patterns = [
            r"(?i)(?:analysis|reasoning|thinking|rationale):\s*(.+?)(?:\n\n|\n$|$)",
            r"(?i)(?:because|since|due to|given that)[\s\S]{0,200}",
            r"(?i)(?:i (?:found|identified|noticed|observed))[\s\S]{0,150}"
        ]
        
        extracted_reasoning = []
        for pattern in reasoning_patterns:
            matches = re.findall(pattern, response, re.MULTILINE | re.DOTALL)
            extracted_reasoning.extend(matches[:2])  # Limit to avoid spam
        
        if self.verbose and extracted_reasoning and not self.streaming:
            console.print("\n[bold cyan]🧠 AI Reasoning Detected:[/bold cyan]")
            for reason in extracted_reasoning:
                console.print(f"• {reason.strip()[:200]}...")
        
        # Parse the main JSON response
        try:
            if not response or response.strip() == "":
                if self.streaming:
                    console.print("[yellow]⚠️ Empty assistant text output (tool-only run). Continuing.[/yellow]")
                    return {"tool_only": True}, ""
                raise ValueError("Empty response from AI")
            
            # Additional check for streaming - sometimes response might only contain tool output
            if self.streaming and (not response.strip() or not response.strip().startswith('{')):
                console.print("[yellow]⚠️ Response may not contain JSON. This might be expected for tool-only operations.[/yellow]")
                console.print(f"[dim]Response content: {repr(response[:200])}...[/dim]")
                # In streaming mode, allow non-JSON answers and let caller decide.
                return {"non_json_streaming_output": True}, response
            
            parsed_response = parse_json(response)
            return parsed_response, response
        except Exception as e:
            if self.verbose:
                console.print(f"[red]JSON Parse Error: {e}[/red]")
                console.print(f"[dim]Response preview: {repr(response[:200])}...[/dim]")
                console.print(f"[dim]Response length: {len(response)} characters[/dim]")
            raise
    
    def complete_with_analysis(self, prompt: str, context: str = "") -> tuple[Any, str]:
        """Complete a prompt with optional reasoning display and interaction."""
        
        # Show internal analysis
        self._show_reasoning(prompt)
        
        # Ask clarifying questions if interactive
        enhanced_prompt = self._ask_clarifying_questions(prompt)
        log_prompt(enhanced_prompt, label="interactive_prompt")
        
        # Show activity header for streaming
        if self.streaming:
            self._show_ai_activity_header()
        
        # Make the LLM call
        if self.verbose:
            console.print("\n[bold cyan]🚀 Calling AI...[/bold cyan]")
        elif self.streaming:
            console.print("\n[bold cyan]💭 AI Response:[/bold cyan]")
        
        response = complete(enhanced_prompt, streaming=self.streaming)
        
        # Process and show reasoning
        parsed_response, raw_response = self._process_streaming_response(response)
        log_output(raw_response, label="interactive_output")
        log_event(
            "interactive.completed",
            {
                "context": context,
                "streaming": self.streaming,
                "response_chars": len(raw_response),
            },
        )
        
        # Store in conversation history for potential follow-up
        self.conversation_history.append({
            "prompt": enhanced_prompt,
            "response": response,
            "context": context
        })
        
        return parsed_response, raw_response
    
    def ask_follow_up_question(self, question: str) -> str:
        """Ask a follow-up question in the context of the current conversation."""
        if not self.conversation_history:
            return complete(question)
        
        # Build context from conversation history
        context_prompt = "Previous conversation:\n"
        for i, conv in enumerate(self.conversation_history[-3:], 1):  # Last 3 exchanges
            context_prompt += f"\nExchange {i}:\nUser: {conv['prompt'][:200]}...\nAI: {conv['response'][:200]}...\n"
        
        context_prompt += f"\nNew question: {question}"
        
        if self.verbose:
            console.print(Panel(
                context_prompt,
                title="[cyan]Follow-up Question with Context[/cyan]",
                border_style="cyan"
            ))
        
        response = complete(context_prompt, streaming=self.streaming)
        log_prompt(context_prompt, label="chat_followup_prompt")
        log_output(response, label="chat_followup_output")
        log_event("chat.followup", {"question_chars": len(question), "response_chars": len(response)})
        
        if self.verbose:
            console.print(Panel(
                response,
                title="[cyan]AI Follow-up Response[/cyan]",
                border_style="blue"
            ))
        
        return response


# Legacy compatibility - map old class name
InteractiveLLMClient = StreamingLLMClient


def complete_interactive(
    prompt: str, 
    verbose: bool = False, 
    interactive: bool = False, 
    streaming: bool = False,
    context: str = ""
) -> tuple[Any, str]:
    """Enhanced complete function with interactive and streaming capabilities."""
    client = StreamingLLMClient(verbose=verbose, interactive=interactive, streaming=streaming)
    return client.complete_with_analysis(prompt, context)