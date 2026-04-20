#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_NAME="${REPO_NAME:-ask_alyf}"
BENCH_APP_PATH="apps/${REPO_NAME}"
BENCH_ROOT="${BENCH_ROOT:-$HOME/frappe-bench}"
SITE_NAME="${SITE_NAME:-${REPO_NAME//_/-}.localhost}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-16}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_ADMIN_USER="${DB_ADMIN_USER:-frappe}"
DB_ADMIN_PASSWORD="${DB_ADMIN_PASSWORD:-frappe}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"

sanitize_path() {
	PATH="$(
		python3 - <<'PY'
import os

preferred = ["/usr/local/bin", os.path.expanduser("~/.local/bin")]
parts = []
seen = set()

for part in os.environ.get("PATH", "").split(":"):
	if not part or "nvm" in part or part in preferred or part in seen:
		continue
	seen.add(part)
	parts.append(part)

print(":".join([*preferred, *parts]), end="")
PY
	)"
	export PATH
}

sanitize_path

python3 - <<'PY'
import sys

if sys.version_info < (3, 14):
	raise SystemExit(
		"Python 3.14+ is required. Rebuild the Cursor environment so it uses the custom Dockerfile."
	)
PY

bash "${REPO_ROOT}/.cursor/start.sh"

sudo mariadb <<SQL
CREATE USER IF NOT EXISTS '${DB_ADMIN_USER}'@'localhost' IDENTIFIED BY '${DB_ADMIN_PASSWORD}';
ALTER USER '${DB_ADMIN_USER}'@'localhost' IDENTIFIED BY '${DB_ADMIN_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO '${DB_ADMIN_USER}'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL

if [ ! -d "${BENCH_ROOT}" ]; then
    bench init \
        --frappe-branch "${FRAPPE_BRANCH}" \
        --python "$(command -v python3)" \
        --skip-assets \
        --skip-redis-config-generation \
        "${BENCH_ROOT}"
fi

cd "${BENCH_ROOT}"

bench set-config -g db_host "${DB_HOST}"
bench set-config -gp db_port "${DB_PORT}"
bench set-config -g redis_cache "redis://127.0.0.1:6379/0"
bench set-config -g redis_queue "redis://127.0.0.1:6379/1"
bench set-config -g redis_socketio "redis://127.0.0.1:6379/2"
bench set-config -gp socketio_port 9000
bench set-config -gp webserver_port 8000
bench set-config -g serve_default_site true

# Keep the bench pointed at the live repo checkout so agent edits are visible immediately.
if [ -e "${BENCH_APP_PATH}" ]; then
    current_app_path="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BENCH_APP_PATH}")"
    if [ "${current_app_path}" != "${REPO_ROOT}" ]; then
        rm -rf "${BENCH_APP_PATH}"
    fi
fi

if [ ! -e "${BENCH_APP_PATH}" ]; then
    bench get-app "${REPO_ROOT}" --soft-link
fi

bench setup requirements --dev

if [ ! -d "sites/${SITE_NAME}" ]; then
    bench new-site \
        --db-root-username "${DB_ADMIN_USER}" \
        --db-root-password "${DB_ADMIN_PASSWORD}" \
        --admin-password "${ADMIN_PASSWORD}" \
        --mariadb-user-host-login-scope "%" \
        "${SITE_NAME}"
fi

bench use "${SITE_NAME}"

if ! bench --site "${SITE_NAME}" list-apps | python3 -c "import sys; sys.exit(0 if any(line.strip() == '${REPO_NAME}' for line in sys.stdin) else 1)"; then
    bench --site "${SITE_NAME}" install-app "${REPO_NAME}"
fi

bench --site "${SITE_NAME}" set-config developer_mode 1
bench --site "${SITE_NAME}" set-config allow_tests true
bench build
bench --site "${SITE_NAME}" migrate
