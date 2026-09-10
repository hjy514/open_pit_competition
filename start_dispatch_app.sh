#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
expected_api_version="dashboard-map-v14"

agent_python="${OPENPIT_PYTHON:-}"
if [[ -z "${agent_python}" && -x "${HOME}/miniconda3/envs/openpit-agent/bin/python" ]]; then
  agent_python="${HOME}/miniconda3/envs/openpit-agent/bin/python"
fi
if [[ -z "${agent_python}" ]]; then
  agent_python="$(command -v python3 || true)"
fi

ui_python="${OPENPIT_DISPATCH_PYTHON:-}"
if [[ -z "${ui_python}" && -x "${HOME}/miniconda3/envs/openpit-ui/bin/python" ]]; then
  ui_python="${HOME}/miniconda3/envs/openpit-ui/bin/python"
fi
if [[ -z "${ui_python}" && -x "${project_dir}/open_pit_dispatch_app/.venv/bin/python" ]]; then
  ui_python="${project_dir}/open_pit_dispatch_app/.venv/bin/python"
fi

if [[ -z "${agent_python}" || ! -x "${agent_python}" ]]; then
  echo "ERROR: 未找到 openpit-agent Python。" >&2
  exit 1
fi
if [[ -z "${ui_python}" || ! -x "${ui_python}" ]]; then
  echo "ERROR: 未找到 PyQt UI Python。" >&2
  exit 1
fi

api_started=0
api_pid=""
api_port=""
api_url=""

cleanup() {
  if [[ "${api_started}" == "1" && -n "${api_pid}" ]]; then
    kill "${api_pid}" 2>/dev/null || true
    wait "${api_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

check_api_version() {
  local url="$1"
  OPENPIT_CHECK_URL="${url}" OPENPIT_EXPECTED_VERSION="${expected_api_version}" \
  "${agent_python}" - <<'PY' >/dev/null 2>&1
import json
import os
import urllib.request

url = os.environ["OPENPIT_CHECK_URL"].rstrip("/") + "/api/health"
expected = os.environ["OPENPIT_EXPECTED_VERSION"]
payload = json.loads(
    urllib.request.urlopen(url, timeout=0.6).read().decode("utf-8")
)
if payload.get("api_version") != expected:
    raise SystemExit(2)
PY
}

port_is_busy() {
  local port="$1"
  OPENPIT_TEST_PORT="${port}" "${agent_python}" - <<'PY' >/dev/null 2>&1
import os
import socket

port = int(os.environ["OPENPIT_TEST_PORT"])
sock = socket.socket()
sock.settimeout(0.25)
try:
    result = sock.connect_ex(("127.0.0.1", port))
finally:
    sock.close()
raise SystemExit(0 if result == 0 else 1)
PY
}

if [[ -n "${OPENPIT_DASHBOARD_API:-}" ]]; then
  api_url="${OPENPIT_DASHBOARD_API%/}"
  if ! check_api_version "${api_url}"; then
    echo "ERROR: OPENPIT_DASHBOARD_API 指向的 API 不是 ${expected_api_version}" >&2
    exit 1
  fi
else
  # Reuse 8765 only if it is already the exact current API.  If an old
  # dashboard process is still occupying 8765, leave it untouched and start
  # the current API on a clean alternate port.
  if check_api_version "http://127.0.0.1:8765"; then
    api_port="8765"
    api_url="http://127.0.0.1:8765"
    echo "[OpenPit Desktop] 复用当前 V1.4 API :8765"
  else
    for candidate in 8765 8766 8767 8768 8769; do
      if ! port_is_busy "${candidate}"; then
        api_port="${candidate}"
        break
      fi
    done

    if [[ -z "${api_port}" ]]; then
      echo "ERROR: 8765-8769 均被占用，无法启动 Dashboard API。" >&2
      exit 1
    fi

    api_url="http://127.0.0.1:${api_port}"
    mkdir -p "${project_dir}/runtime_data/logs"
    api_log="${project_dir}/runtime_data/logs/dashboard_api_v14_${api_port}.log"

    echo "[OpenPit Desktop] 启动 V1.4 Dashboard API :${api_port} ..."
    (
      cd "${project_dir}"
      export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"
      exec "${agent_python}" scripts/start_dashboard.py \
        --host 127.0.0.1 \
        --port "${api_port}"
    ) >"${api_log}" 2>&1 &
    api_pid=$!
    api_started=1

    ready=0
    for _ in $(seq 1 40); do
      if check_api_version "${api_url}"; then
        ready=1
        break
      fi
      sleep 0.2
    done

    if [[ "${ready}" != "1" ]]; then
      echo "ERROR: V1.4 Dashboard API 启动失败。" >&2
      echo "日志: ${api_log}" >&2
      exit 1
    fi
  fi
fi

echo "[OpenPit Desktop] API: ${api_url}"
echo "[OpenPit Desktop] UI Python: ${ui_python}"
cd "${project_dir}/open_pit_dispatch_app"
export OPENPIT_DASHBOARD_API="${api_url}"
exec "${ui_python}" main.py
