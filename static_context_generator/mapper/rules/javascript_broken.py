"""
rules/javascript.py — Security rules for JavaScript and TypeScript.
Covers: Express/Node.js, browser APIs, JWT, pg, bcrypt, crypto.
"""
import re
from .base import LanguageRules

RULES = LanguageRules(
    language="JavaScript",
    sinks=[
        ("eval",               re.compile(r"\beval\s*\(")),
        ("exec/spawn",         re.compile(r"\b(?:exec|execSync|spawn|spawnSync|execFile)\s*\(")),
        ("fs.write",           re.compile(r"\bfs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)\s*\(")),
        ("fs.unlink/rm",       re.compile(r"\bfs\.(?:unlink|rmdir|rm|rmdirSync|unlinkSync)\s*\(")),
        ("fs.readFile",        re.compile(r"\bfs\.(?:readFile|readFileSync)\s*\(")),
        ("child_process",      re.compile(r"\brequire\(['\"]child_process['\"]\)")),
        ("vm.runInContext",    re.compile(r"\bvm\.(?:runInNewContext|runInContext|runInThisContext)\s*\(")),
        ("innerHTML",          re.compile(r"\binnerHTML\s*=")),
        ("document.write",     re.compile(r"\bdocument\.write\s*\(")),
        ("open redirect",      re.compile(r"\bres\.redirect\s*\(\s*req\.")),
        ("path traversal",     re.compile(r"(?:path\.join|path\.resolve)\s*\([^)]*req\.")),        # React-specific dangerous patterns
        ("dangerouslySetInnerHTML", re.compile(r"\bdangerouslySetInnerHTML\s*:")),
        ("ReactDOM.render",    re.compile(r"\bReactDOM\.render\s*\(")),
        ("createRef unsafe",   re.compile(r"\bcreateRef\s*\(\)\s*\.current\s*=")),
        ("Function constructor", re.compile(r"\bnew\s+Function\s*\(")),
        ("setTimeout string",  re.compile(r"\bsetTimeout\s*\(\s*['"]")),
        ("setInterval string", re.compile(r"\bsetInterval\s*\(\s*['"]")),    ],
    sources=[
        ("req.body",    re.compile(r"\breq\.body\b")),
        ("req.query",   re.compile(r"\breq\.query\b")),
        ("req.params",  re.compile(r"\breq\.params\b")),
        ("req.headers", re.compile(r"\breq\.headers\b")),
        ("req.files",   re.compile(r"\breq\.files?\b")),
        # React/Frontend sources
        ("props",       re.compile(r"\b(?:this\.)?props\.\.")),
        ("useState",    re.compile(r"\buseState\s*\(")),
        ("useContext",  re.compile(r"\buseContext\s*\(")),
        ("event.target", re.compile(r"\bevent\.target\.value\b")),
        ("onChange",    re.compile(r"\bonChange\s*=")),
        ("window.location", re.compile(r"\bwindow\.location\b")),
        ("document.URL", re.compile(r"\bdocument\.(?:URL|referrer)\b")),
        ("localStorage", re.compile(r"\blocalStorage\.getItem\s*\(")),
        ("sessionStorage", re.compile(r"\bsessionStorage\.getItem\s*\(")),
        ("URLSearchParams", re.compile(r"\bnew\s+URLSearchParams\s*\(")),
        ("FormData",    re.compile(r"\bnew\s+FormData\s*\(")),
        ("fetch response", re.compile(r"\bfetch\s*\([^)]*\)\.then")),
        ("WebSocket",   re.compile(r"\bnew\s+WebSocket\s*\(")),
        ("process.argv", re.compile(r"\bprocess\.argv\b")),
    ],
    crypto=[
        ("bcrypt.hash",         re.compile(r"\bbcrypt(?:js)?\.hash\s*\(")),
        ("bcrypt.compare",      re.compile(r"\bbcrypt(?:js)?\.compare\s*\(")),
        ("jwt.sign",            re.compile(r"\bjwt\.sign\s*\(")),
        ("jwt.verify",          re.compile(r"\bjwt\.verify\s*\(")),
        ("jwt.decode (unsafe)", re.compile(r"\bjwt\.decode\s*\(")),
        ("crypto.createHash",   re.compile(r"\bcrypto\.createHash\s*\(")),
        ("crypto.createCipher", re.compile(r"\bcrypto\.createCipher(?:iv)?\s*\(")),
        ("Math.random (weak)",  re.compile(r"\bMath\.random\s*\(")),
        ("crypto-js",           re.compile(r"\bCryptoJS\.")),
        ("otplib",              re.compile(r"\bauthenticator\.")),
    ],
    error_leaks=[
        ("res.json(err)", re.compile(
            r"res\.(?:json|send|status\(\d+\)\.json)\s*\(\s*(?:err|error|e|ex|exception)\b",
            re.IGNORECASE,
        )),
        ("console.log(err)", re.compile(
            r"console\.(?:log|error)\s*\(\s*(?:err|error|e|ex|exception)\b",
            re.IGNORECASE,
        )),
    ],
    sqli_patterns=[
        # Template literal with user input
        re.compile(
            r"""(?:db|pool|client|pg|connection|conn|query)\.query\s*\(\s*"""
            r"""`[^`]*\$\{.*?req\.""",
            re.IGNORECASE | re.DOTALL,
        ),
        # String concatenation with user input
        re.compile(
            r"""(?:db|pool|client|pg|connection|conn|query)\.query\s*\(\s*"""
            r"""['"][^'"]*['"]\s*\+\s*(?:req\.|[a-z_]\w*)""",
            re.IGNORECASE,
        ),
        # format() with direct user input concatenation
        re.compile(
            r"""(?:pg\.format|format)\s*\([^)]*\+\s*(?:req\.|params\.|body\.)""",
            re.IGNORECASE,
        ),
    ],
    safe_query_patterns=[
        # pg parameterized: { text: '...', values: [...] }
        re.compile(
            r"""\.query\s*\(\s*\{[^{}]{0,400}\btext\s*:[^{}]*\bvalues\s*:""",
            re.IGNORECASE | re.DOTALL,
        ),
        # $1 $2 placeholders
        re.compile(r"""\.query\s*\(\s*['"`][^'"`]*\$\d"""),
    ],
    auth_guard_tokens=frozenset({
        "validjwt", "validpermission", "validagent", "checkrole",
        "isadmin", "authorize", "authenticate", "requireauth",
        "ensureauth", "jwtauth", "bearerauth", 
        # React auth patterns
        "useauth", "withauth", "protectedroute", "authguard",
        "usepermission", "canaccess", "hasrole", "isauthorized",
        "authprovider", "authcontext", "useuser", "requirerole",
        "ensureloggedin", "checkuser", "verifysession",
    }),
    user_id_patterns=[
        re.compile(r"\breq\.(?:params|body|query)\s*\.\s*(?:id|userId|user_id|agentId|agent_id)\b"),
    ],
    jwt_sign_re=re.compile(r"""jwt\.sign\s*\(.*?\)""", re.DOTALL),
    jwt_verify_re=re.compile(r"""jwt\.verify\s*\(.*?\)""", re.DOTALL),
    destructure_patterns=[
        re.compile(r"""const\s*\{([^}]+)\}\s*=\s*req\.(?:body|params|query)\b""", re.DOTALL),
    ],
    simple_field_re=re.compile(r"""req\.(?:body|params|query)\.(\w+)"""),
    validation_guard_re=re.compile(
        r"""\bcheck\s*\(|\bvalidRequest\b|\bvalidate\s*\(|\bJoi\.\b|\bbody\(|\bquery\("""
    ),
)
