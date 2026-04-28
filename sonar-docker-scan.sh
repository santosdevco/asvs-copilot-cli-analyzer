#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
WORKSPACE_ENV_FILE="${SONAR_ENV_FILE:-${SCRIPT_DIR}/.env}"
DEFAULT_URL="http://host.docker.internal:9000"
DEFAULT_SOURCES="."
DEFAULT_SCANNER_IMAGE="sonarsource/sonar-scanner-cli"
DEFAULT_ADD_HOST="host.docker.internal:host-gateway"
PROJECT_DIR=""
PROJECT_KEY="${SONAR_PROJECT_KEY:-}"
PROJECT_NAME="${SONAR_PROJECT_NAME:-}"
PROJECT_NAME_PREFIX="${SONAR_PROJECT_NAME_PREFIX:-}"
SONAR_TOKEN_VALUE="${SONAR_TOKEN:-}"
SONAR_HOST_URL_VALUE="${SONAR_HOST_URL:-}"
SONAR_SOURCES_VALUE="${SONAR_SOURCES:-}"
SONAR_PROJECT_VERSION_VALUE="${SONAR_PROJECT_VERSION:-}"
SONAR_EXCLUSIONS_VALUE="${SONAR_EXCLUSIONS:-}"
SONAR_INCLUSIONS_VALUE="${SONAR_INCLUSIONS:-}"
SONAR_EXTRA_ARGS_VALUE="${SONAR_EXTRA_ARGS:-}"
SCANNER_IMAGE="${SONAR_SCANNER_IMAGE:-}"
DOCKER_ADD_HOST="${SONAR_DOCKER_ADD_HOST:-}"
PRINT_GLOBAL_COMMAND="false"
EXTRA_ARGS=()

read_env_var() {
  local key="$1"
  local file="$2"
  local line=""
  local value=""

  if [[ ! -f "${file}" ]]; then
    return 0
  fi

  line="$(grep -E "^[[:space:]]*${key}=" "${file}" | tail -n1 || true)"
  if [[ -z "${line}" ]]; then
    return 0
  fi

  value="${line#*=}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "${value}"
}

print_help() {
  cat <<EOF
Uso:
  ${SCRIPT_NAME} [ruta_proyecto] [opciones] [-- argumentos_extra_scanner]

Opciones:
  -t, --token <token>         Token de SonarQube (opcional: usa SONAR_TOKEN o .env)
  -u, --url <url>             URL de SonarQube (default: ${DEFAULT_URL})
  -k, --key <project_key>     sonar.projectKey (obligatorio si no hay sonar-project.properties)
  -n, --name <project_name>   sonar.projectName (default: project_key)
  -s, --sources <ruta>        sonar.sources (default: ${DEFAULT_SOURCES})
      --print-global-command  Muestra comando para instalar uso global
  -h, --help                  Muestra esta ayuda

Ejemplos:
  ${SCRIPT_NAME} ~/codigo/mi-api -t <TOKEN> -k mi-api
  ${SCRIPT_NAME} ~/codigo/mi-api -k mi-api
  ${SCRIPT_NAME} . -t <TOKEN> -- -Dsonar.exclusions=**/*.test.ts

Notas:
  - Prioridad de configuración: CLI > variables de entorno > ${WORKSPACE_ENV_FILE} > default.
  - Puedes dejar casi todo en ${WORKSPACE_ENV_FILE} y usar por proyecto solo: -k <PROJECT_KEY>.
  - Variables soportadas en .env: SONAR_TOKEN, SONAR_HOST_URL, SONAR_SOURCES,
    SONAR_SCANNER_IMAGE, SONAR_DOCKER_ADD_HOST, SONAR_PROJECT_NAME_PREFIX,
    SONAR_PROJECT_VERSION, SONAR_EXCLUSIONS, SONAR_INCLUSIONS, SONAR_EXTRA_ARGS,
    SONAR_ENV_FILE.
  - Si existe sonar-project.properties, el script lo usa automáticamente.
  - Si no existe, debes enviar -k/--key para que el scanner tenga configuración mínima.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--token)
      SONAR_TOKEN_VALUE="$2"
      shift 2
      ;;
    -u|--url)
      SONAR_HOST_URL_VALUE="$2"
      shift 2
      ;;
    -k|--key)
      PROJECT_KEY="$2"
      shift 2
      ;;
    -n|--name)
      PROJECT_NAME="$2"
      shift 2
      ;;
    -s|--sources)
      SONAR_SOURCES_VALUE="$2"
      shift 2
      ;;
    --print-global-command)
      PRINT_GLOBAL_COMMAND="true"
      shift
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      if [[ -z "${PROJECT_DIR}" ]]; then
        PROJECT_DIR="$1"
      else
        EXTRA_ARGS+=("$1")
      fi
      shift
      ;;
  esac
done

if [[ "${PRINT_GLOBAL_COMMAND}" == "true" ]]; then
  SCRIPT_PATH="$(realpath "$0")"
  echo "Comando de instalación global:"
  echo "sudo ln -sf \"${SCRIPT_PATH}\" /usr/local/bin/sonar-docker-scan"
  echo
  echo "Luego puedes usarlo así desde cualquier proyecto:"
  echo "sonar-docker-scan . -k <PROJECT_KEY>"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker no está instalado o no está en PATH." >&2
  exit 1
fi

if [[ -z "${SONAR_TOKEN_VALUE}" ]]; then
  SONAR_TOKEN_VALUE="$(read_env_var "SONAR_TOKEN" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_HOST_URL_VALUE}" ]]; then
  SONAR_HOST_URL_VALUE="$(read_env_var "SONAR_HOST_URL" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_SOURCES_VALUE}" ]]; then
  SONAR_SOURCES_VALUE="$(read_env_var "SONAR_SOURCES" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${PROJECT_NAME_PREFIX}" ]]; then
  PROJECT_NAME_PREFIX="$(read_env_var "SONAR_PROJECT_NAME_PREFIX" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_PROJECT_VERSION_VALUE}" ]]; then
  SONAR_PROJECT_VERSION_VALUE="$(read_env_var "SONAR_PROJECT_VERSION" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_EXCLUSIONS_VALUE}" ]]; then
  SONAR_EXCLUSIONS_VALUE="$(read_env_var "SONAR_EXCLUSIONS" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_INCLUSIONS_VALUE}" ]]; then
  SONAR_INCLUSIONS_VALUE="$(read_env_var "SONAR_INCLUSIONS" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_EXTRA_ARGS_VALUE}" ]]; then
  SONAR_EXTRA_ARGS_VALUE="$(read_env_var "SONAR_EXTRA_ARGS" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SCANNER_IMAGE}" ]]; then
  SCANNER_IMAGE="$(read_env_var "SONAR_SCANNER_IMAGE" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${DOCKER_ADD_HOST}" ]]; then
  DOCKER_ADD_HOST="$(read_env_var "SONAR_DOCKER_ADD_HOST" "${WORKSPACE_ENV_FILE}")"
fi

if [[ -z "${SONAR_HOST_URL_VALUE}" ]]; then
  SONAR_HOST_URL_VALUE="${DEFAULT_URL}"
fi

if [[ -z "${SONAR_SOURCES_VALUE}" ]]; then
  SONAR_SOURCES_VALUE="${DEFAULT_SOURCES}"
fi

if [[ -z "${SCANNER_IMAGE}" ]]; then
  SCANNER_IMAGE="${DEFAULT_SCANNER_IMAGE}"
fi

if [[ -z "${DOCKER_ADD_HOST}" ]]; then
  DOCKER_ADD_HOST="${DEFAULT_ADD_HOST}"
fi

if [[ -z "${SONAR_TOKEN_VALUE}" ]]; then
  echo "Error: falta token. Usa -t/--token, variable SONAR_TOKEN o define SONAR_TOKEN en ${WORKSPACE_ENV_FILE}." >&2
  exit 1
fi

if [[ -z "${PROJECT_DIR}" ]]; then
  PROJECT_DIR="$(pwd)"
fi

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Error: la ruta del proyecto no existe: ${PROJECT_DIR}" >&2
  exit 1
fi

PROJECT_DIR="$(cd "${PROJECT_DIR}" && pwd)"
SCANNER_ARGS=()

if [[ -f "${PROJECT_DIR}/sonar-project.properties" ]]; then
  if [[ -n "${PROJECT_KEY}" ]]; then
    SCANNER_ARGS+=("-Dsonar.projectKey=${PROJECT_KEY}")
  fi
  if [[ -n "${PROJECT_NAME}" ]]; then
    SCANNER_ARGS+=("-Dsonar.projectName=${PROJECT_NAME}")
  fi
else
  if [[ -z "${PROJECT_KEY}" ]]; then
    echo "Error: no existe sonar-project.properties y falta -k/--key." >&2
    exit 1
  fi

  if [[ -z "${PROJECT_NAME}" ]]; then
    if [[ -n "${PROJECT_NAME_PREFIX}" ]]; then
      PROJECT_NAME="${PROJECT_NAME_PREFIX}${PROJECT_KEY}"
    else
      PROJECT_NAME="${PROJECT_KEY}"
    fi
  fi

  SCANNER_ARGS+=("-Dsonar.projectKey=${PROJECT_KEY}")
  SCANNER_ARGS+=("-Dsonar.projectName=${PROJECT_NAME}")
  SCANNER_ARGS+=("-Dsonar.sources=${SONAR_SOURCES_VALUE}")
fi

if [[ -n "${SONAR_PROJECT_VERSION_VALUE}" ]]; then
  SCANNER_ARGS+=("-Dsonar.projectVersion=${SONAR_PROJECT_VERSION_VALUE}")
fi

if [[ -n "${SONAR_EXCLUSIONS_VALUE}" ]]; then
  SCANNER_ARGS+=("-Dsonar.exclusions=${SONAR_EXCLUSIONS_VALUE}")
fi

if [[ -n "${SONAR_INCLUSIONS_VALUE}" ]]; then
  SCANNER_ARGS+=("-Dsonar.inclusions=${SONAR_INCLUSIONS_VALUE}")
fi

if [[ -n "${SONAR_EXTRA_ARGS_VALUE}" ]]; then
  read -r -a ENV_EXTRA_ARGS <<< "${SONAR_EXTRA_ARGS_VALUE}"
  SCANNER_ARGS+=("${ENV_EXTRA_ARGS[@]}")
fi

echo "Ejecutando análisis en: ${PROJECT_DIR}"
docker run \
  --rm \
  "--add-host=${DOCKER_ADD_HOST}" \
  -e SONAR_HOST_URL="${SONAR_HOST_URL_VALUE}" \
  -e SONAR_TOKEN="${SONAR_TOKEN_VALUE}" \
  -v "${PROJECT_DIR}:/usr/src" \
  "${SCANNER_IMAGE}" \
  "${SCANNER_ARGS[@]}" \
  "${EXTRA_ARGS[@]}"
