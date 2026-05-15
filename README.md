# ASVS Audit Pipeline — CLI

Pipeline semi-automatizado para auditar aplicaciones contra **OWASP ASVS v5.0**.  
Cada comando corresponde a un paso del flujo descrito en el README principal.

---

## Estructura del proyecto

```
sonarqube-reports/
├── cli.py                          ← entry point
├── cli/
│   ├── config.py                   ← rutas globales (OUTPUTS_DIR, FORMATS_DIR, …)
│   ├── requirements.txt
│   ├── models/
│   │   ├── component.py            ← ComponentIndex, ComponentItem
│   │   └── audit_result.py         ← AuditOutput, AuditResultItem
│   ├── core/
│   │   ├── prompt_renderer.py      ← reemplaza {{keys}} en los .md
│   │   ├── context_builder.py      ← arma el contexto para cada prompt
│   │   ├── llm_client.py           ← abstracción OpenAI / Anthropic
│   │   └── output_writer.py        ← escribe/actualiza artefactos en outputs/
│   └── commands/
│       ├── extract.py              ← Step 1
│       ├── triage.py               ← Step 2
│       ├── audit.py                ← Step 4
│       └── validate_static_context.py  ← Validación de filtrado de contexto estático
├── formats/
│   ├── asvs_json/                  ← reglas OWASP por capítulo
│   ├── prompts/                    ← plantillas con {{keys}}
│   ├── taxonomy/                   ← asset_category, asvs_asset_relation, context_choose
│   └── outputs/                    ← ejemplos de formato (mostrados al LLM)
└── outputs/
    └── {app_name}/
        ├── static_context.xml      ← contexto estático consolidado (XML)
        ├── static_context/         ← opcional para compat/debug (txt/json)
        └── components/
            ├── index.json
            └── {component_id}/
                ├── context.md
                └── analysis/
                    └── V6.json
```

---

## Guía rápida de comandos

| Comando | Paso | Descripción |
|---|---|---|
| `extract` | 1 | Extrae contexto estático desde el código fuente |
| `triage` | 2 | Agrupa archivos en componentes (agent arquitecto) |
| `audit` | 4 | Audita componentes contra OWASP ASVS |
| `list-components` | Utilidad | Lista los componentes de un proyecto |
| `save-analysis` | Utilidad | Guarda resultados de análisis (no-interactivo, ideal para integración) |
| `list` | Menu de issues | Lista de issues y su estado |
| `report` | Reporte | Genera reporte final en Markdown |
---

## Instalación

```bash
# Desde la raíz del repositorio
pip install -r cli/requirements.txt
```

### Variables de entorno

Crea un `.env` en la raíz (o expórtalas manualmente):

```dotenv
# ── GitHub Copilot / GitHub Models (proveedor por defecto) ───────────────────
# Genera el token en: https://github.com/settings/tokens  (sin scopes especiales)
GITHUB_TOKEN=ghp_...

LLM_PROVIDER=github          # github (default) | openai | anthropic
LLM_MODEL=gpt-4o             # gpt-4o | o4-mini | meta-llama-3.1-405b-instruct | …
LLM_MAX_TOKENS=8192

# Proveedores alternativos (solo si cambias LLM_PROVIDER)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

> El proveedor `github` usa el SDK oficial `azure-ai-inference` contra  
> `https://models.inference.ai.azure.com`, el mismo endpoint que alimenta  
> el catálogo de modelos de GitHub Copilot.

---

## Comandos

### `extract` — Paso 1: Extracción estática

Llama a `run_mapper.py` y genera el contexto estático consolidado en XML.

```bash
python3 cli.py extract <app_name> [--source-dir PATH] [--format xml]
```

| Argumento/Opción | Descripción |
|---|---|
| `app_name` | Nombre lógico de la app (se usa como carpeta en `outputs/`) |
| `--source-dir` | Ruta al código fuente. Por defecto se pasa `app_name` al mapper. |
| `--format` | `xml` (default) genera solo `outputs/{app_name}/static_context.xml`. `txt/json` se mantienen para compatibilidad/debug. |

**Salida recomendada para pipeline:** `outputs/{app_name}/static_context.xml`

```bash
# Ejemplo (XML recomendado)
python3 cli.py extract watshelp-bancodebogota-api \
  --source-dir analysis-repos/watshelp-bancodebogota-api \
  --format xml
```

---

### `triage` — Paso 2: Agente Arquitecto

El LLM analiza el contexto estático completo, agrupa los archivos en componentes
y genera `index.json` + `context.md` por componente.

```bash
python3 cli.py triage <app_name> [--dry-run]
```

| Opción | Descripción |
|---|---|
| `--dry-run` | Muestra el prompt renderizado sin llamar al LLM |

**Salida:**
- `outputs/{app_name}/components/index.json`
- `outputs/{app_name}/components/{component_id}/context.md`

```bash
python3 cli.py triage watshelp-bancodebogota-api
python3 cli.py triage watshelp-bancodebogota-api --dry-run   # inspección
```

> **Formato esperado de respuesta del LLM**  
> El LLM debe devolver un JSON con dos claves:
> ```json
> {
>   "index":    { ...ComponentIndex... },
>   "contexts": { "<component_id>": "<contenido context.md>" }
> }
> ```

---

### `audit` — Paso 4: Bucle de Auditoría

Itera sobre cada componente × capítulo ASVS aplicable y genera un `.json` de hallazgos.

```bash
python3 cli.py audit <app_name> [OPTIONS]
```

| Opción | Descripción |
|---|---|
| `--component ID` | Auditar solo un componente específico |
| `--chapter V6` | Restringir a un solo capítulo ASVS (acepta prefijo, ej. `V6`). Use `n` para el siguiente capítulo pendiente |
| `--dry-run` | Renderiza prompts sin llamar al LLM |
| `--show-prompt` | Muestra el contenido completo del prompt |
| `--copy-clipboard` | Copia automáticamente el prompt al portapapeles (útil con `--show-prompt`) |
| `--it false` | Modo no-interactivo: omite prompts de "¿Pegar análisis?" y "¿Ejecutar otra auditoría?". Default: `true` (interactivo) |
| `--prompt-sections SECTIONS` | Secciones a incluir en el prompt (comma-separated). Opciones: `component_context`, `filtered_static_context`, `file_contents`, `files_to_audit`. Default: todas incluidas. Valida valores automáticamente. |

**Salida por cada (componente, capítulo):**
- `outputs/{app_name}/components/{component_id}/analysis/{chapter}.json`
- Append en `outputs/{app_name}/components/{component_id}/context.md`

```bash
# Auditar todo el proyecto
python3 cli.py audit watshelp-bancodebogota-api

# Solo un componente
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module

# Un componente, un capítulo
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V6

# Ver prompts sin gastar tokens
python3 cli.py audit watshelp-bancodebogota-api --dry-run

# Ver prompt y copiarlo al portapapeles automáticamente
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V6 \
  --show-prompt --copy-clipboard

# Copiar el prompt al portapapeles sin mostrarlo (modo interactivo o dry-run)
python3 cli.py audit watshelp-bancodebogota-api --copy-clipboard

# Copiar y mostrar en modo dry-run
python3 cli.py audit watshelp-bancodebogota-api --dry-run --copy-clipboard

# Incluir solo cierto contenido en el prompt (reducir tokens)
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V6 \
  --prompt-sections "component_context,files_to_audit"

# Incluir archivos con números de línea pero sin contexto estático
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V6 \
  --prompt-sections "component_context,file_contents,files_to_audit"

# Solo ver lista de archivos sin contenido
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V6 \
  --prompt-sections "files_to_audit" \
  --dry-run --show-prompt --copy-clipboard

# Auditar el siguiente capítulo pendiente (no interactivo)
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter n \
  --dry-run --it false

# Modo no-interactivo: sin prompts de pegar análisis ni "¿ejecutar otra?"
python3 cli.py audit watshelp-bancodebogota-api \
  --component auth_and_session_module \
  --chapter V1 \
  --dry-run --it false
```

---

### `list-components` — Listar componentes del proyecto

Comando rápido para listar todos los componentes de un proyecto en varios formatos.

```bash
python3 cli.py list-components <app_name> [--format FORMAT]
```

| Opción | Descripción |
|---|---|
| `app_name` | Nombre lógico de la app |
| `--format` | Formato de salida: `table` (default), `json`, `ids`, o `names` |

**Formatos disponibles:**
- `table` — Tabla formateada con información de riesgo y progreso
- `json` — Salida JSON con metadatos completos del componente
- `ids` — Solo IDs de componentes, uno por línea
- `names` — Solo nombres de componentes, uno por línea (raw)

```bash
# Tabla formateada (por defecto)
python3 cli.py list-components watshelp-bancodebogota-api

# JSON para procesamiento automatizado
python3 cli.py list-components watshelp-bancodebogota-api --format json

# Solo IDs para piping
python3 cli.py list-components watshelp-bancodebogota-api --format ids

# Solo nombres (raw)
python3 cli.py list-components watshelp-bancodebogota-api --format names
```

---

### `save-analysis` — Guardar resultados de análisis (no-interactivo)

Comando no-interactivo para guardar resultados de análisis JSON desde otra aplicación.
Seguro para JSON grandes: lee desde archivo o stdin (evita límites de argumentos shell).

```bash
python3 cli.py save-analysis <app_name> --component <id> --chapter <V#> [--file FILE]
```

| Argumento/Opción | Descripción |
|---|---|
| `app_name` | Nombre lógico de la app |
| `--component` | ID del componente (requerido) |
| `--chapter` | Capítulo ASVS (ej. V1, V2, ..., V14) (requerido) |
| `--file` | Ruta al archivo JSON. Si se omite, lee desde stdin |

**Salida:**
- Archivo JSON guardado en `outputs/{app_name}/components/{component_id}/analysis/{chapter}.json`
- Una línea JSON en stdout con confirmación (para parseo automático)
- Errores en stderr

**Ejemplos:**

```bash
# Vía archivo
python3 cli.py save-analysis watshelp-bancodebogota-api \
  --component room_message_management \
  --chapter V1 \
  --file analysis_result.json

# Vía stdin (recomendado para JSON grande)
cat analysis_result.json | python3 cli.py save-analysis watshelp-bancodebogota-api \
  --component room_message_management \
  --chapter V1

# Echo directo (para testing)
echo '{"results":[{"req":"V1.1","status":"PASS"}]}' | python3 cli.py save-analysis watshelp-bancodebogota-api \
  --component room_message_management \
  --chapter V1

# En un pipeline desde otra aplicación
some_analysis_tool output.json | python3 cli.py save-analysis watshelp-bancodebogota-api \
  --component auth_mfa_session_module \
  --chapter V6
```

**Ejemplo de integración (no-interactivo):**

```bash
# Script que integra análisis externo
#!/bin/bash

APP_NAME="watshelp-bancodebogota-api"
COMPONENT="auth_mfa_session_module"
CHAPTER="V6"

# Obtener análisis desde API/herramienta externa
curl -s "https://analysis-service/generate?component=$COMPONENT" | \
  python3 cli.py save-analysis "$APP_NAME" \
    --component "$COMPONENT" \
    --chapter "$CHAPTER"

# Resultado en JSON (parseable)
# {"success": true, "saved": "outputs/..../V6.json", "component": "...", "chapter": "V6"}
```

---

### `validate-static-context` — Validación de compresión/filtrado del contexto estático

Emite a `stdout` el `static_context.xml` ya filtrado con la misma lógica usada por el flujo de auditoría.
Sirve para validar compresión de contexto por componente sin ejecutar el loop completo de audit.

El comando:

- recibe `app_name` y `component_id`
- usa los `files_to_audit` del componente y los `core_paths` desde `outputs/{app_name}/components/index.json`
- usa los `asset_tags` del componente por defecto
- permite sobrescribir los `asset_tags` con `--asset-tag`
- imprime el XML filtrado a `stdout`, para que puedas redirigirlo con `>`

```bash
python3 cli.py validate-static-context <app_name> <component_id> [--asset-tag TAG]
```

| Opción | Descripción |
|---|---|
| `app_name` | Nombre lógico de la app |
| `component_id` | ID exacto del componente en `outputs/{app_name}/components/index.json` |
| `--asset-tag` | Override opcional de asset tags. Puede repetirse o pasarse como lista separada por comas. Si no se envía, usa los tags del componente. |

```bash
# Usa los asset_tags definidos en index.json para el componente
python3 cli.py validate-static-context \
  watshelp-bancodebogota-admin-new \
  auth_and_mfa \
  > filtered_context.xml

# Override de asset tags para probar otro routing táctico
python3 cli.py validate-static-context \
  watshelp-bancodebogota-admin-new \
  auth_and_mfa \
  --asset-tag auth_service \
  --asset-tag frontend_http_client \
  > filtered_context.xml
```

---

### `run` — Pipeline completo

Encadena `extract → triage → audit` en un solo comando.

```bash
python3 cli.py run <app_name> [--source-dir PATH] [--component ID] [--chapter V6]
```

```bash
python3 cli.py run watshelp-bancodebogota-api \
  --source-dir analysis-repos/watshelp-bancodebogota-api
```

### Controlar contenido del prompt con `--prompt-sections`

Para reducir consumo de tokens, puedes incluir solo las secciones que necesitas:

**Secciones disponibles:**
- `component_context` — Contexto y arquitectura del componente (análisis previos)
- `filtered_static_context` — Reportes estáticos filtrados (señales de código, importes, etc.)
- `file_contents` — Contenido real de los archivos con números de línea
- `files_to_audit` — Lista de archivos a auditar (sin contenido)

**Validación:**
El comando valida automáticamente los valores. Si usas un valor inválido, obtendrás un error claro:

```bash
$ python3 cli.py audit app --prompt-sections "invalid_section"
Error: Invalid prompt section(s): invalid_section. Valid options are: 
  component_context, file_contents, files_to_audit, filtered_static_context
```

**Ejemplos de combinaciones:**

```bash
# Solo componente y archivos (más tokens)
python3 cli.py audit app --prompt-sections "component_context,file_contents"

# Solo lista de archivos y contenido (sin contexto estático)
python3 cli.py audit app --prompt-sections "file_contents,files_to_audit"

# Mínimo: solo lista de archivos (eficiente en tokens)
python3 cli.py audit app --prompt-sections "files_to_audit"
```

Para reducir consumo de tokens durante audit, también puedes excluir el diario incremental del contexto:

```bash
python3 cli.py audit <app_name> --no-include-auditor-diary
```

Esto elimina del prompt la sección `=== AUDITOR DIARY ... ===` dentro de `context.md`.

---

### `report` — Reporte final en Markdown

Genera un reporte MD por aplicación, consolidando:

- logs de ejecución por app (`log_app.log`)
- reportes de consumo (`usage/*_usage.json`)
- resumen de análisis por componente/capítulo

Incluye menú interactivo para elegir qué secciones incluir en el reporte final.

```bash
python3 cli.py report <app_name>
python3 cli.py report <app_name> --no-interactive-menu
python3 cli.py report <app_name> --no-interactive-menu \
  --no-include-sessions --no-include-events --no-include-prompts --no-include-outputs \
  --include-audit-summary --include-usage-files
```

En modo `--no-interactive-menu` puedes controlar secciones con flags:

- `--include-sessions/--no-include-sessions`
- `--include-events/--no-include-events`
- `--include-prompts/--no-include-prompts`
- `--include-outputs/--no-include-outputs`
- `--include-audit-summary/--no-include-audit-summary`
- `--include-usage-files/--no-include-usage-files`
- `--max-events <N>`
- `--max-block-chars <N>`

**Salidas:**

- `outputs/{app_name}/reports/{timestamp}_app_report.md`
- `outputs/{app_name}/reports/latest_app_report.md`

El reporte incluye al final el **consumo total de tokens** (sumatoria de usage reports).

---

## Token usage tracking (real values)

When using `LLM_PROVIDER=copilot`, the CLI captures real token usage from Copilot SDK
`assistant.usage` events (not estimates based on characters).

After each execution:

- `triage` writes:
  - `outputs/{app_name}/usage/{timestamp}_triage_usage.json`
  - `outputs/{app_name}/usage/latest_triage_usage.json`
- `audit` writes:
  - `outputs/{app_name}/usage/{timestamp}_audit_usage.json`
  - `outputs/{app_name}/usage/latest_audit_usage.json`

Each usage report includes:

- Total input/output tokens
- Cache read/write tokens
- Reasoning tokens
- Provider/model metadata
- Per-call usage breakdown

---

## App execution log (`log_app.log`)

Each command execution now writes a per-app log file:

- `outputs/{app_name}/log_app.log`

The log includes:

- Command executed (full CLI command line)
- Parsed options selected
- Input prompts sent to the LLM (full prompt text)
- AI/chat output returned by the model (full response text)
- Interactive choices (menu selections and answers in interactive mode)

Example path:

- `outputs/watshelp-bancodebogota-admin/log_app.log`

---

## Flujo completo resumido

```
extract         →   outputs/{app}/static_context.xml
    ↓
triage          →   outputs/{app}/components/index.json
                    outputs/{app}/components/{id}/context.md
    ↓
audit (loop)    →   outputs/{app}/components/{id}/analysis/V6.json
                    outputs/{app}/components/{id}/analysis/V8.json
                    …
                    outputs/{app}/components/{id}/context.md  ← APPEND
```

---

## Taxonomía y archivos de configuración clave

| Archivo | Propósito |
|---|---|
| `formats/taxonomy/asvs_asset_relation.json` | Qué capítulos ASVS aplican a cada `asset_tag` |
| `formats/taxonomy/cotext_choose.json` | Qué secciones `<report type="...">` cargar de `static_context.xml` para cada capítulo |
| `formats/taxonomy/asset_category.json` | Catálogo de `asset_tag` válidos |
| `formats/asvs_json/0x{nn}-{Vn}-*.json` | Reglas OWASP por capítulo |
| `formats/prompts/components_creation.md` | Prompt del Agente Arquitecto (usa `{{keys}}`) |
| `formats/prompts/asvs_analysis.md` | Prompt del Agente Auditor (usa `{{keys}}`) |

### Placeholders `{{key}}` en los prompts

El motor `prompt_renderer.py` sustituye `{{key}}` con los valores del contexto construido.
Los **keys disponibles** para cada prompt son:

**`components_creation.md`**
- `{{app_name}}` — nombre de la app
- `{{asset_tags}}` — catálogo de asset_tags disponibles
- `{{component_json_format}}` — ejemplo de `index.json`
- `{{component_context_format}}` — ejemplo de `context.md`
- `{{full_static_context}}` — contenido completo de `outputs/{app_name}/static_context.xml`

**`asvs_analysis.md`**
- `{{app_name}}` / `{{component_key}}` — identificadores
- `{{asvs_i_rules_txt}}` — reglas del capítulo en texto plano
- `{{context_md}}` — diario del auditor actual
- `{{filtered_static_context}}` — subsecciones XML relevantes según `context_choose.json`
- `{{audit_output.json}}` — ejemplo del formato de salida

---

## Asset Tags — Catálogo y routing ASVS

Los `asset_tags` son las etiquetas que el triage asigna a cada componente. Determinan qué capítulos ASVS se auditan — si el tag es incorrecto, el routing es incorrecto.

### Catálogo completo (25 tags)

#### Frontend / Browser

| Tag | Nombre | Qué cubre |
|---|---|---|
| `client_ui` | Frontend / Client User Interface | Componentes React/Vue/Angular que renderizan HTML/CSS/JS, manejan eventos DOM y enrutamiento client-side |
| `client_storage` | Client-side Storage | localStorage, sessionStorage, IndexedDB, Cache API, cookies del browser |
| `frontend_http_client` | Frontend HTTP Client / API Client Layer | Capa axios/fetch browser-side: interceptores, inyección de tokens en headers, manejo de 401/403 |
| `frontend_router` | Frontend Router / Navigation Guard | Route guards, PrivateRoute, AuthGuard — controles de acceso client-side (bypasseables, no son autorización real) |
| `frontend_realtime_client` | Frontend Realtime Client | Socket.io-client, WebSocket, SSE — conexiones persistentes desde el browser con token en handshake |

#### Backend / Servidor

| Tag | Nombre | Qué cubre |
|---|---|---|
| `backend_controller` | Backend Application Controllers | REST controllers, Express routes, GraphQL resolvers, Lambda HTTP-triggered, gRPC handlers |
| `backend_service` | Backend Microservices / Internal Services | Servicios de dominio, workers async, Lambda event-triggered (SQS/S3), daemons internos |
| `auth_service` | Authentication Service / Identity Provider | Servidores de login, MFA, gestión de credenciales, LDAP/AD, Keycloak/Auth0 operado por el equipo |
| `authz_service` | Authorization Service / Policy Engine | Middleware RBAC/ABAC, OPA, Casbin, guards de autorización centralizados |
| `token_service` | Token Issuer / Authorization Server | OAuth 2.0 AS, OIDC OP, JWT/SAML issuers, gestión de refresh tokens y PKCE |
| `api_gateway` | API Gateway / Reverse Proxy / Edge Layer | Kong, AWS API Gateway, NGINX reverse proxy, BFF, WAF — entrada HTTP/S del tráfico |

#### Procesos no interactivos

| Tag | Nombre | Qué cubre |
|---|---|---|
| `scheduled_job` | Scheduled Job / Event-driven Worker / ETL | Cron, CloudWatch Events, Lambda scheduled, batch processors, ETL — sin contexto HTTP ni sesión de usuario |
| `batch_and_admin` | Admin Script / CLI Tool / Maintenance Utility | Scripts de admin, migraciones, CLI tools internos — corren con credenciales elevadas, ejecutados manualmente por operadores |

#### Infraestructura declarativa

| Tag | Nombre | Qué cubre |
|---|---|---|
| `iac_config` | Infrastructure as Code / Configuration as Code | Terraform, Helm, K8s manifests, Ansible, CloudFormation — define IAM roles, network policies y RBAC del entorno |
| `ci_cd_pipeline` | CI/CD Pipeline / Build Infrastructure | GitHub Actions, GitLab CI, Jenkins — build, test, SCA, empaquetado y despliegue |
| `container_infra` | Container & Orchestration Infrastructure | Dockerfiles, K8s deployments/pods, Helm values — runtime del contenedor |
| `network_infra` | Network Infrastructure / TLS Termination | TLS terminators, firewalls, load balancers con cert management, service mesh (Istio/Linkerd) |

#### Almacenamiento y datos

| Tag | Nombre | Qué cubre |
|---|---|---|
| `database` | Database / Persistence Layer | PostgreSQL, MySQL, MongoDB, DynamoDB, Elasticsearch — también ORM models y repository classes en source code |
| `cache_layer` | Cache / In-Memory Store | Redis/Memcached como cache de aplicación (distinto de `session_store`) |
| `session_store` | Session Store / State Management Backend | Redis/Memcached como backend de sesiones server-side (tokens de referencia) |
| `file_storage` | File Storage Service / Object Storage | S3, GCS, Azure Blob, filesystem local — recibe, almacena y sirve archivos |
| `secret_manager` | Secret Management Service / Key Vault | HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, HSMs |

#### Comunicación y servicios externos

| Tag | Nombre | Qué cubre |
|---|---|---|
| `message_broker` | Message Broker / Event Bus | Kafka, RabbitMQ, SQS/SNS, Azure Service Bus — transporte async entre servicios |
| `external_service` | External / Third-party Service Integration | APIs externas: Stripe, SendGrid, Google OAuth, SMS, mapas — cualquier tercero consumido por la app |
| `webrtc_server` | WebRTC Infrastructure | TURN/STUN servers, SFU/MCU, media gateways — infraestructura de comunicación en tiempo real |

---

### Routing ASVS por tipo de componente

La tabla muestra qué capítulos ASVS se auditan para cada categoría de tag. El propósito es evidenciar por qué los tags no son intercambiables — un `scheduled_job` etiquetado como `backend_service` hereda capítulos que no aplican (V3, V4, V6, V7) y subaudita los que sí importan (V13, V16).

| Capítulo | `backend_controller` | `backend_service` | `scheduled_job` | `batch_and_admin` | `iac_config` | `client_ui` | `frontend_http_client` | `frontend_router` | `frontend_realtime_client` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| V1 Encoding & Sanitization | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | |
| V2 Validation & Business Logic | ✓ | ✓ | ✓ | ✓ | | ✓ | | | |
| V3 Web Frontend Security | | | | | | ✓ | ✓ | ✓ | ✓ |
| V4 API & Web Service | ✓ | ✓ | | | | ✓ | ✓ | | ✓ |
| V5 File Handling | ✓ | ✓ | | | | ✓ | | | |
| V6 Authentication | ✓ | | | | | ✓ | | | |
| V7 Session Management | ✓ | ✓ | | | | | ✓ | ✓ | ✓ |
| V8 Authorization | ✓ | ✓ | | ✓ | ✓ | | | ✓ | |
| V9 Self-contained Tokens | ✓ | ✓ | | | | | ✓ | | |
| V10 OAuth & OIDC | ✓ | ✓ | | | | ✓ | ✓ | ✓ | |
| V11 Cryptography | ✓ | ✓ | | | | | | | |
| V12 Secure Communication | ✓ | ✓ | | | | | | | ✓ |
| V13 Configuration | ✓ | ✓ | ✓ | ✓ | ✓ | | | | |
| V14 Data Protection | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ |
| V15 Secure Coding & Architecture | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | |
| V16 Logging & Error Handling | ✓ | ✓ | ✓ | ✓ | ✓ | | | | |
| V17 WebRTC | ✓ | ✓ | | | | | | | |

