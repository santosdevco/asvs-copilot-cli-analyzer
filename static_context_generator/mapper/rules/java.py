"""
rules/java.py — Security rules for Java.
Covers: Spring/Spring Boot, JDBC, Runtime.exec, JNDI, cryptography.
"""
import re
from .base import LanguageRules

RULES = LanguageRules(
    language="Java",
    sinks=[
        ("Runtime.exec",          re.compile(r"\bRuntime\.getRuntime\(\)\.exec\s*\(")),
        ("ProcessBuilder",        re.compile(r"\bnew\s+ProcessBuilder\s*\(")),
        ("ScriptEngine.eval",     re.compile(r"\bScriptEngine\b.*\.eval\s*\(")),
        ("JNDI.lookup",           re.compile(r"InitialContext\s*\(.*\)\.lookup\s*\(")),
        ("ObjectInputStream",     re.compile(r"\bnew\s+ObjectInputStream\s*\(")),
        ("ClassLoader.loadClass", re.compile(r"\bclassLoader\.loadClass\s*\(")),
        ("FileOutputStream",      re.compile(r"\bnew\s+FileOutputStream\s*\(")),
        ("JDBC concat",           re.compile(
            r"""(?:Statement|PreparedStatement)\b.*createStatement\s*\("""
        )),
        ("open redirect",         re.compile(r"\bresponse\.sendRedirect\s*\(\s*request\.")),
        ("path traversal",        re.compile(r"\bnew\s+File\s*\([^)]*request\.")),
    ],
    sources=[
        ("request.getParameter", re.compile(r"\brequest\.getParameter\s*\(")),
        ("request.getHeader",    re.compile(r"\brequest\.getHeader\s*\(")),
        ("@RequestBody",         re.compile(r"@RequestBody\b")),
        ("@RequestParam",        re.compile(r"@RequestParam\b")),
        ("@PathVariable",        re.compile(r"@PathVariable\b")),
        ("@ModelAttribute",      re.compile(r"@ModelAttribute\b")),
    ],
    crypto=[
        ("MD5 (weak)",         re.compile(r"""MessageDigest\.getInstance\s*\(\s*["']MD5["']\s*\)""")),
        ("SHA-1 (weak)",       re.compile(r"""MessageDigest\.getInstance\s*\(\s*["']SHA-1["']\s*\)""")),
        ("SHA-256",            re.compile(r"""MessageDigest\.getInstance\s*\(\s*["']SHA-256["']\s*\)""")),
        ("DES (weak)",         re.compile(r"""Cipher\.getInstance\s*\(\s*["']DES""")),
        ("AES-ECB (weak)",     re.compile(r"""Cipher\.getInstance\s*\(\s*["']AES/ECB""")),
        ("SecretKeySpec",      re.compile(r"\bnew\s+SecretKeySpec\s*\(")),
        ("SecureRandom",       re.compile(r"\bnew\s+SecureRandom\s*\(")),
        ("Math.random (weak)", re.compile(r"\bMath\.random\s*\(")),
        ("Bcrypt",             re.compile(r"\bBCryptPasswordEncoder\b")),
        ("PBKDF2",             re.compile(r"\bPBEKeySpec\b")),
    ],
    error_leaks=[
        ("e.printStackTrace",      re.compile(r"\b(?:e|err|ex|exception)\.printStackTrace\s*\(")),
        ("log.error(e)",           re.compile(
            r"\b(?:log|logger)\.(?:error|warn)\s*\([^)]*[,\s](?:e|ex|err|exception)\s*\)"
        )),
        ("response.getWriter",     re.compile(r"response\.getWriter\(\)\.print\s*\(\s*(?:e|ex)\b")),
    ],
    sqli_patterns=[
        # Statement.execute with string concat
        re.compile(
            r"""(?:statement|stmt|st)\.(?:execute|executeQuery|executeUpdate)\s*\(\s*"""
            r"""(?:['"]\s*\+|""" + r"""sql\s*\+)""",
            re.IGNORECASE,
        ),
        # "SELECT " + variable
        re.compile(
            r"""["']SELECT [^"']*["']\s*\+\s*\w""",
            re.IGNORECASE,
        ),
        re.compile(r"""String\.format\s*\([^)]*SELECT[^)]*\+\s*\w""", re.IGNORECASE),
    ],
    safe_query_patterns=[
        # PreparedStatement with ? placeholders
        re.compile(r"""PreparedStatement\b"""),
        # Spring @Query or JPA
        re.compile(r"""@Query\s*\("""),
        # Criteria API
        re.compile(r"""CriteriaBuilder\b"""),
    ],
    auth_guard_tokens=frozenset({
        "preauthorize", "secured", "rolesallowed",
        "authenticated", "hasrole", "hasauthority",
        "jwtfilter", "securitycontext", "authentication",
    }),
    user_id_patterns=[
        re.compile(r"""request\.getParameter\s*\(\s*["'](?:id|userId|user_id)["']\s*\)"""),
    ],
    validation_guard_re=re.compile(
        r"""\b@Valid\b|\b@Validated\b|\bBindingResult\b|\bConstraintValidator\b"""
    ),
)
