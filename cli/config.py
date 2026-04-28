from pathlib import Path

# ── Root paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent          # repo root
FORMATS_DIR = BASE_DIR / "formats"
OUTPUTS_DIR = BASE_DIR / "outputs"

# ── Taxonomy ─────────────────────────────────────────────────────────────────
TAXONOMY_DIR = FORMATS_DIR / "taxonomy"
ASVS_ASSET_RELATION_FILE = TAXONOMY_DIR / "asvs_asset_relation.json"
CONTEXT_CHOOSE_FILE       = TAXONOMY_DIR / "cotext_choose.json"   # typo kept from original
ASSET_CATEGORY_FILE       = TAXONOMY_DIR / "asset_category.json"

# ── ASVS chapter rules ───────────────────────────────────────────────────────
ASVS_JSON_DIR = FORMATS_DIR / "asvs_json"

# ── Format templates (examples shown to the LLM) ────────────────────────────
FORMAT_OUTPUTS_DIR         = FORMATS_DIR / "outputs"
AUDIT_OUTPUT_FORMAT_FILE   = FORMAT_OUTPUTS_DIR / "audit_output.json"
COMPONENT_INDEX_FORMAT_FILE= FORMAT_OUTPUTS_DIR / "component-output.json"
COMPONENT_CTX_FORMAT_FILE  = FORMAT_OUTPUTS_DIR / "component_context.md"

# ── Prompt templates ─────────────────────────────────────────────────────────
PROMPTS_DIR       = FORMATS_DIR / "prompts"
TRIAGE_PROMPT_FILE = PROMPTS_DIR / "components_creation.md"
AUDIT_PROMPT_FILE  = PROMPTS_DIR / "asvs_analysis.md"

# ── Static context mapper script (called as subprocess) ──────────────────────
MAPPER_SCRIPT = BASE_DIR / "static_context_generator" / "run_mapper.py"

# ── Static context report names (match file suffix *_{name}.txt) ─────────────
# These come from context_choose.json; listed here for discoverability only.
CORE_REPORT_NAMES = ["identity", "structure", "imports", "database"]
