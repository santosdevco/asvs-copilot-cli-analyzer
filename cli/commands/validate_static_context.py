"""
validate_static_context.py
──────────────────────────
Emit filtered static_context XML for a component to stdout.

Usage:
  python cli.py validate-static-context <app_name> <component_id> > filtered_context.xml
  python cli.py validate-static-context <app_name> <component_id> --asset-tag auth_service > filtered_context.xml
"""
from __future__ import annotations

import sys

import click

from cli.core import build_filtered_static_context
from cli.core.app_logger import init_app_logger, log_event


def _normalize_asset_tags(raw_values: tuple[str, ...]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in raw.split(","):
            tag = part.strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
    return tags


@click.command("validate-static-context")
@click.argument("app_name")
@click.argument("component_id")
@click.option(
    "--asset-tag",
    "asset_tags",
    multiple=True,
    help="Optional asset tag override. Repeat the option or pass a comma-separated list.",
)
def validate_static_context_cmd(app_name: str, component_id: str, asset_tags: tuple[str, ...]) -> None:
    """Emit filtered static_context XML for one component to stdout."""
    normalized_asset_tags = _normalize_asset_tags(asset_tags)
    init_app_logger(
        app_name=app_name,
        command_name="validate-static-context",
        command_line=" ".join(sys.argv),
        options={"component_id": component_id, "asset_tags": normalized_asset_tags},
    )

    log_event(
        "validate_static_context.started",
        {"component_id": component_id, "asset_tags": normalized_asset_tags},
    )

    try:
        filtered_static = build_filtered_static_context(
            app_name=app_name,
            component_id=component_id,
            asset_tags=normalized_asset_tags or None,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    log_event(
        "validate_static_context.completed",
        {
            "component_id": component_id,
            "asset_tags": normalized_asset_tags,
            "output_chars": len(filtered_static),
        },
    )
    click.echo(filtered_static)
