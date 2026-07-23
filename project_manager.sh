#!/usr/bin/env bash

set -euo pipefail

########################################
# CONFIGURATION
########################################

# Core Project Directories
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
OUTPUT_DIR="${PROJECT_ROOT}/output"
DELIVERABLES_DIR="${PROJECT_ROOT}/deliverables"

# Requirements Specification
REQUIREMENTS_DEV_FILE="${PROJECT_ROOT}/requirements-dev.txt"

# TA Directories & Configuration
TA_NAME="moviri_ti_manager_addon"
TA_VERSION="0.0.1"
TA_ROOT="${PROJECT_ROOT}/${TA_NAME}"
TA_PACKAGE_DIR="${TA_ROOT}/package"
TA_PACKAGE_BIN_DIR="${TA_PACKAGE_DIR}/bin"

# TA Version Injection Mapping
TA_CONFIGS_FILE="${TA_PACKAGE_BIN_DIR}/configs.py"
TA_VERSION_VAR_NAME="ADDON_VERSION"

# Python Runtime Configuration
PYTHON_VERSION="3.9.20"
PYTHON_BIN=""

########################################
# LOGGING
########################################

print_info() {
    echo "[INFO] $1"
}

print_warn() {
    echo "[WARN] $1"
}

print_error() {
    echo "[ERROR] $1" >&2
}

########################################
# HELPERS
########################################

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command '$1' is not installed or not in PATH."
        exit 1
    fi
}

ensure_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        print_error "Virtual environment not found. Run 'venv-create' first."
        exit 1
    fi
}

########################################
# VENV
########################################

ensure_python_version() {
    require_command pyenv

    if ! pyenv versions --bare | grep -xF "${PYTHON_VERSION}" >/dev/null 2>&1; then
        print_info "Python ${PYTHON_VERSION} not found in pyenv."
        print_warn "Orchestrator will now download and compile Python ${PYTHON_VERSION}."
        print_warn "This might take a few minutes depending on your CPU..."
        
        pyenv install "${PYTHON_VERSION}"
        
        print_info "Python ${PYTHON_VERSION} compiled successfully."
    else
        print_info "Verified: Python ${PYTHON_VERSION} is already available via pyenv."
    fi

    PYTHON_BIN="$(pyenv root)/versions/${PYTHON_VERSION}/bin/python"
}

venv_create() {
    if [[ -d "${VENV_DIR}" ]]; then
        print_warn "Virtual environment already exists."
        return
    fi

    ensure_python_version

    print_info "Creating virtual environment..."

    ${PYTHON_BIN} -m venv "${VENV_DIR}"

    print_info "Virtual environment created."
}

venv_install_dev() {
    ensure_venv

    print_info "Installing development dependencies..."

    source "${VENV_DIR}/bin/activate"

    pip install --upgrade pip
    pip install -r "${REQUIREMENTS_DEV_FILE}"

    deactivate

    print_info "Dependencies installed."
}

venv_all() {
    clean_venv
    venv_create
    venv_install_dev

    print_info "Virtual environment recreated and ready for development."
}

########################################
# BUILD
########################################

ta_build() {
    print_info "Building TA..."

    ensure_venv
    source "${VENV_DIR}/bin/activate"

    mkdir -p "${OUTPUT_DIR}"
    rm -rf "${OUTPUT_DIR}/${TA_NAME}"

    find "${TA_PACKAGE_BIN_DIR}" -type d -name '__pycache__' -exec rm -rf -- {} + 2>/dev/null || true

    if [[ -f "${TA_CONFIGS_FILE}" ]]; then
        print_info "Injecting version ${TA_VERSION} into ${TA_CONFIGS_FILE}..."
        sed -i -E "s/^(${TA_VERSION_VAR_NAME}\s*=\s*\").*/\1${TA_VERSION}\"/" "${TA_CONFIGS_FILE}"
    else
        print_warn "configs.py not found at ${TA_CONFIGS_FILE}, skipping version injection."
    fi

    ucc-gen build \
        --source "${TA_PACKAGE_DIR}" \
        --ta-version "${TA_VERSION}"

    deactivate

    print_info "TA build completed."
}

########################################
# PACKAGE
########################################

ta_package() {
    print_info "Packaging TA..."

    ensure_venv
    source "${VENV_DIR}/bin/activate"

    mkdir -p "${DELIVERABLES_DIR}"

    ucc-gen package \
        --path "${OUTPUT_DIR}/${TA_NAME}" \
        --output "${DELIVERABLES_DIR}"

    deactivate

    print_info "TA package completed."
}

########################################
# FULL PIPELINE
########################################

ta_all() {
    ta_build
    ta_package
}

########################################
# CLEAN
########################################

clean_venv() {
    print_info "Removing virtual environment..."
    rm -rf "${VENV_DIR}"
}

clean_output() {
    print_info "Cleaning output directory..."

    if [[ -d "${OUTPUT_DIR}" ]]; then
        find "${OUTPUT_DIR}" -mindepth 1 -exec rm -rf -- {} +
    fi

    print_info "Output cleaned."
}

clean_deliverables() {
    print_info "Cleaning deliverables directory..."

    if [[ -d "${DELIVERABLES_DIR}" ]]; then
        find "${DELIVERABLES_DIR}" -mindepth 1 -exec rm -rf -- {} +
    fi

    print_info "Deliverables cleaned."
}

########################################
# HELP
########################################

show_help() {
    cat <<EOF

Usage:

  ./project_manager.sh COMMAND

Commands:

  help                      Show this help

  venv-create               Create virtual environment
  venv-install-dev          Install development dependencies into venv
  venv-all                  Setup dev virtual environment (clean + create + install-dev)

  ta-build                  Build TA addon
  ta-package                Package TA addon
  ta-all                    Run quality tests + build + package TA addon

  clean-venv                Remove virtual environment
  clean-output              Remove output content
  clean-deliverables        Remove deliverables content

Current configuration:

  TA Name      : ${TA_NAME}
  TA Version   : ${TA_VERSION}

EOF
}

########################################
# MAIN
########################################

main() {
    local command="${1:-help}"

    case "${command}" in
        help)
            show_help
            ;;

        venv-create)
            venv_create
            ;;

        venv-install-dev)
            venv_install_dev
            ;;

        venv-all)
            venv_all
            ;;

        ta-build)
            ta_build
            ;;

        ta-package)
            ta_package
            ;;

        ta-all)
            ta_all
            ;;

        clean-venv)
            clean_venv
            ;;

        clean-output)
            clean_output
            ;;

        clean-deliverables)
            clean_deliverables
            ;;

        *)
            print_error "Unknown command: ${command}"
            echo
            show_help
            exit 1
            ;;
    esac
}

main "$@"