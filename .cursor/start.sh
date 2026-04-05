#!/usr/bin/env bash
set -euo pipefail

service_is_running() {
    local service_name="$1"

    case "$service_name" in
        mariadb|mysql)
            pgrep -x mariadbd >/dev/null 2>&1 || pgrep -x mysqld >/dev/null 2>&1
            ;;
        redis-server|redis)
            pgrep -x redis-server >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

start_service() {
    local service_name="$1"

    if service_is_running "$service_name"; then
        return 0
    fi

    if command -v service >/dev/null 2>&1; then
        sudo service "$service_name" start >/dev/null 2>&1 && return 0
    fi

    if [ -x "/etc/init.d/${service_name}" ]; then
        sudo "/etc/init.d/${service_name}" start >/dev/null 2>&1 && return 0
    fi

    service_is_running "$service_name"
}

wait_for() {
    local label="$1"
    local command="$2"

    for _ in $(seq 1 30); do
        if eval "$command" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    echo "Timed out waiting for ${label}" >&2
    return 1
}

start_service mariadb || start_service mysql || {
    echo "Could not start MariaDB" >&2
    exit 1
}

start_service redis-server || start_service redis || {
    echo "Could not start Redis" >&2
    exit 1
}

wait_for "MariaDB" "sudo mariadb-admin ping --silent"
wait_for "Redis" "[ \"\$(redis-cli ping 2>/dev/null)\" = \"PONG\" ]"
