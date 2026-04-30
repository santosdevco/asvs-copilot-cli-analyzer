"""
rules/go.py — Security rules for Go.
Covers: net/http, gorilla/mux, gin, exec.Command, sql/db, crypto packages.
"""
import re
from .base import LanguageRules

RULES = LanguageRules(
    language="Go",
    sinks=[
        ("exec.Command",        re.compile(r"\bexec\.Command\s*\(")),
        ("os.OpenFile (write)", re.compile(r"\bos\.(?:OpenFile|Create|WriteFile)\s*\(")),
        ("http.Redirect",       re.compile(r"\bhttp\.Redirect\s*\(\s*w\s*,\s*r\s*,")),
        ("fmt.Fprintf stderr",  re.compile(r"\bfmt\.Fprintf\s*\(\s*(?:os\.Stderr|w)\s*,")),
        ("template/text",       re.compile(r'"text/template"')),
        ("unsafe pointer",      re.compile(r"\bunsafe\.Pointer\b")),
        ("reflect unsafe",      re.compile(r"\breflect\.NewAt\s*\(")),
        ("plugin.Open",         re.compile(r"\bplugin\.Open\s*\(")),
    ],
    sources=[
        ("r.FormValue",          re.compile(r"\br\.FormValue\s*\(")),
        ("r.URL.Query",          re.compile(r"\br\.URL\.Query\s*\(\s*\)")),
        ("r.PostForm",           re.compile(r"\br\.PostForm\b")),
        ("r.Body",               re.compile(r"\br\.Body\b")),
        ("r.Header.Get",         re.compile(r"\br\.Header\.Get\s*\(")),
        ("gin.Context.Param",    re.compile(r"\bc\.Param\s*\(")),
        ("gin.Context.Query",    re.compile(r"\bc\.Query\s*\(")),
        ("gin.Context.PostForm", re.compile(r"\bc\.PostForm\s*\(")),
        ("json.Decode(r.Body)",  re.compile(r"json\.NewDecoder\s*\(\s*r\.Body\s*\)")),
    ],
    crypto=[
        ("md5 (weak)",         re.compile(r'"crypto/md5"')),
        ("sha1 (weak)",        re.compile(r'"crypto/sha1"')),
        ("sha256",             re.compile(r'"crypto/sha256"')),
        ("sha512",             re.compile(r'"crypto/sha512"')),
        ("des (weak)",         re.compile(r'"crypto/des"')),
        ("aes",                re.compile(r'"crypto/aes"')),
        ("rsa",                re.compile(r'"crypto/rsa"')),
        ("bcrypt",             re.compile(r'"golang.org/x/crypto/bcrypt"')),
        ("rand (weak)",        re.compile(r'"math/rand"')),
        ("crypto/rand",        re.compile(r'"crypto/rand"')),
        ("jwt-go",             re.compile(r'"github.com/golang-jwt/')),
    ],
    error_leaks=[
        ("fmt.Fprintf(w, err)", re.compile(
            r"""fmt\.Fprintf\s*\(\s*w\s*,[^)]*(?:err|error|e)\.Error\s*\(\)""",
        )),
        ("http.Error(w, err.Error())", re.compile(
            r"""http\.Error\s*\(\s*w\s*,[^)]*(?:err|error|e)\.Error\s*\(\)""",
        )),
        ("json.NewEncoder write err", re.compile(
            r"""json\.NewEncoder\s*\(\s*w\s*\)\.Encode\s*\(\s*(?:err|e|error)\b""",
        )),
        ("log.Println(err)",  re.compile(
            r"""\blog\.(?:Println|Printf|Print|Fatal|Fatalf)\s*\([^)]*(?:err|error)\b""",
        )),
    ],
    sqli_patterns=[
        # fmt.Sprintf in db.Query / db.Exec
        re.compile(
            r"""(?:db|tx|stmt)\.(?:Query|QueryRow|Exec)\s*\(\s*fmt\.Sprintf\s*\(""",
            re.IGNORECASE,
        ),
        # string concat directly
        re.compile(
            r"""(?:db|tx)\.(?:Query|QueryRow|Exec)\s*\(\s*["'][^"']*["']\s*\+\s*\w""",
            re.IGNORECASE,
        ),
    ],
    safe_query_patterns=[
        # ? placeholders (database/sql convention)
        re.compile(r"""(?:db|tx)\.(?:Query|QueryRow|Exec)\s*\(\s*["'][^"']*\?"""),
        # GORM
        re.compile(r"""\.Where\s*\(\s*["'][^"']*\?"""),
    ],
    auth_guard_tokens=frozenset({
        "validjwt", "authenticate", "authorize", "jwtmiddleware",
        "claims", "checkclaims", "validatesession", "bearertoken",
        "context.value", "ctxuserid",
    }),
    user_id_patterns=[
        re.compile(r"""r\.(?:FormValue|URL\.Query|PathValue)\s*\(\s*["'](?:id|userId|user_id)["']\s*\)"""),
    ],
    validation_guard_re=re.compile(
        r"""\bvalidate\.Struct\b|\bgo-playground/validator\b|\bgo-validator\b"""
        r"""|\bgovalidator\.\b|\bgin\.ShouldBind\b"""
    ),
)
