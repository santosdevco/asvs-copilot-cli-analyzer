import os
import json
import click
from pathlib import Path
from cli.config import OUTPUTS_DIR

@click.command('build-report')
@click.option('--app', 'app_name', required=True, help='App name to aggregate reports for')
def build_report_cmd(app_name):
    """Aggregate all audit results for all components and chapters into a single JSON file, merging context and audits."""
    output_dir = Path('builds')
    output_dir.mkdir(exist_ok=True)
    # Load components/index.json
    index_path = OUTPUTS_DIR / app_name / 'components' / 'index.json'
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    components = index_data['project_triage']
    # Build a dict for fast lookup by component_id
    comp_map = {c['component_id']: c for c in components}
    # For each component, add context and audit fields
    for comp in components:
        # Add context from initial_semantic_context if present
        comp['context'] = build_context(app_name, comp['component_id']) or comp.get('initial_semantic_context', {})
        # Aggregate all audits for this component
        audits = []
        analysis_dir = OUTPUTS_DIR / app_name / 'components' / comp['component_id'] / 'analysis'
        if analysis_dir.exists():
            for f in analysis_dir.glob('V*.json'):
                try:
                    with open(f, 'r', encoding='utf-8') as af:
                        audits.append(json.load(af))
                except Exception as e:
                    audits.append({'error': f'Failed to load {f.name}: {e}'})
        comp['audit'] = audits
    out_path = output_dir / f'{app_name}_full_report.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(components, f, ensure_ascii=False, indent=2)
    click.echo(f'Full report written to {out_path}')


def build_context(
    app_name: str,
    component_id: str):
    context_path = OUTPUTS_DIR / app_name / 'components' / component_id / 'context.xml'
    context_data = None
    print(f'context_path= {context_path} = {context_path.exists()}  ')
    if context_path.exists():
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(context_path)
            root = tree.getroot()
            context_data = {child.tag: child.text for child in root}
        except Exception as e:
            context_data = {'error': f'Failed to parse context.xml: {e}'}
    return context_data