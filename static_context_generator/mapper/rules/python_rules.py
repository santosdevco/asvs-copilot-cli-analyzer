"""
rules/python_rules.py — Security rules for Python.
Covers: Flask, FastAPI, Django, SQLAlchemy, subprocess, hashlib, PyJWT.
"""
import re
from .base import LanguageRules

RULES = LanguageRules(
    language="Python",
    sinks=[
        ("eval/exec",         re.compile(r"\b(?:eval|exec)\s*\(")),
        ("os.system",         re.compile(r"\bos\.system\s*\(")),
        ("subprocess",        re.compile(
            r"\bsubprocess\.(?:run|call|Popen|check_output|check_call|getoutput)\s*\(",
        )),
        ("pickle.loads",      re.compile(r"\bpickle\.(?:loads|load|Unpickler)\s*\(")),
        ("marshal.loads",     re.compile(r"\bmarshal\.loads?\s*\(")),
        ("yaml.load (unsafe)", re.compile(r"\byaml\.load\s*\([^)]*\)")),
        ("open (write)",      re.compile(r'\bopen\s*\([^)]+,\s*["\']w')),
        ("jinja2 autoescape off", re.compile(r"autoescape\s*=\s*False")),
        ("template injection", re.compile(r"render_template_string\s*\(")),
        ("open redirect",     re.compile(r"\bredirect\s*\(\s*request\.")),
    ],
    sources=[
        ("request.json",    re.compile(r"\brequest\.(?:json|get_json)\s*\(")),
        ("request.form",    re.compile(r"\brequest\.form\b")),
        ("request.args",    re.compile(r"\brequest\.args\b")),
        ("request.values",  re.compile(r"\brequest\.values\b")),
        ("request.data",    re.compile(r"\brequest\.data\b")),
        ("request.headers", re.compile(r"\brequest\.headers\b")),
        ("request.files",   re.compile(r"\brequest\.files\b")),
        # FastAPI
        ("Body()",          re.compile(r"\bBody\s*\(")),
        ("Depends()",       re.compile(r"\bDepends\s*\(")),
        ("Query()",         re.compile(r"\bQuery\s*\(")),
        ("Path()",          re.compile(r"\bPath\s*\(")),
        ("Form()",          re.compile(r"\bForm\s*\(")),
        ("File()",          re.compile(r"\bFile\s*\(")),
        ("UploadFile",      re.compile(r"\bUploadFile\b")),
        # Django
        ("request.POST",    re.compile(r"\brequest\.POST\b")),
        ("request.GET",     re.compile(r"\brequest\.GET\b")),
        ("request.META",    re.compile(r"\brequest\.META\b")),
        ("request.COOKIES", re.compile(r"\brequest\.COOKIES\b")),
        ("request.session", re.compile(r"\brequest\.session\b")),
        # Additional framework patterns
        ("sys.argv",        re.compile(r"\bsys\.argv\b")),
        ("input()",         re.compile(r"\binput\s*\(")),
        ("raw_input()",     re.compile(r"\braw_input\s*\(")),
        ("environ",         re.compile(r"\bos\.environ\b")),
    ],
    crypto=[
        ("hashlib.md5 (weak)",    re.compile(r"\bhashlib\.md5\s*\(")),
        ("hashlib.sha1 (weak)",   re.compile(r"\bhashlib\.sha1\s*\(")),
        ("hashlib.sha256",        re.compile(r"\bhashlib\.sha256\s*\(")),
        ("hashlib.sha512",        re.compile(r"\bhashlib\.sha512\s*\(")),
        ("jwt.encode",            re.compile(r"\bjwt\.encode\s*\(")),
        ("jwt.decode",            re.compile(r"\bjwt\.decode\s*\(")),
        ("passlib",               re.compile(r"\bpasslib\.")),
        ("cryptography",          re.compile(r"\bfrom\s+cryptography\b")),
        ("bcrypt",                re.compile(r"\bbcrypt\.(?:hashpw|checkpw)\s*\(")),
        ("secrets.token",         re.compile(r"\bsecrets\.token_(?:hex|bytes|urlsafe)\s*\(")),
        ("random (weak)",         re.compile(r"\brandom\.(?:random|randint|choice)\s*\(")),
        ("Fernet",                re.compile(r"\bFernet\s*\(")),
    ],
    error_leaks=[
        ("return str(e)",         re.compile(r"return\s+str\s*\(\s*(?:e|err|error|ex|exception)\s*\)")),
        ("logging.error(e)",      re.compile(r"\blogging\.(?:error|exception)\s*\(\s*(?:e|err|error)\b")),
        ("print(traceback)",      re.compile(r"\bprint\s*\(\s*traceback\b")),
        ("jsonify(error)",        re.compile(r"\bjsonify\s*\(\s*(?:error|str\(e|e\.)")),
        ("raise from e",          re.compile(r"\braise\b.*\bfrom\s+(?:e|err|exception)\b")),
    ],
    sqli_patterns=[
        # f-string / % format in cursor.execute
        re.compile(
            r"""cursor\.execute\s*\(\s*(?:f['"]|['"][^'"]*['"]\s*%\s*|['"][^'"]*['"]\s*\.format\s*\()""",
            re.IGNORECASE,
        ),
        # raw string concatenation
        re.compile(
            r"""(?:cursor|conn|connection|db)\.execute\s*\(\s*['"][^'"]*['"]\s*\+\s*\w""",
            re.IGNORECASE,
        ),
        # SQLAlchemy text() with format/f-string
        re.compile(r"""text\s*\(\s*f['"]|text\s*\(\s*['"][^'"]*['"]\s*\.format"""),
    ],
    safe_query_patterns=[
        # Parameterized: cursor.execute(sql, (param,))
        re.compile(r"""cursor\.execute\s*\([^,]+,\s*(?:\(|\[)"""),
        # SQLAlchemy ORM  .filter(Model.col == val)
        re.compile(r"""\.filter\s*\([^)]*==\s*\w"""),
        # SQLAlchemy bindparams
        re.compile(r"""\bbindparams\s*\("""),
    ],
    auth_guard_tokens=frozenset({
        "login_required", "jwt_required", "permission_required",
        "require_http_methods", "user_passes_test", "get_current_user",
        "current_user", "security", "authenticate", "authorize",
        "checkpermission", "requiresauth", "token_required",
    }),
    user_id_patterns=[
        re.compile(r"\brequest\.(?:args|form|json|POST|GET)\s*\.get\s*\(['\"](?:id|user_id|userId)\b"),
        re.compile(r"\b(?:user_id|userId)\b\s*=\s*request\."),
    ],
    destructure_patterns=[],
    simple_field_re=re.compile(
        r"""request\.(?:args|form|json)\s*(?:\.get\s*\(['""]|\.get\s*\(['""])(\w+)"""
    ),
    validation_guard_re=re.compile(
        r"""\bSerializer\s*\(|\bSchema\s*\(|\bvalidator\b|\bpydantic\b"""
        r"""|\bForm\s*\(|\bWTForms\b|\bvalidate\b|\bForm\.validate_on_submit\b"""
    ),
)
