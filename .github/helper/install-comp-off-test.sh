#!/usr/bin/env bash
# Disposable GitHub CI only; no production credentials or business data.
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y redis-server mariadb-client libmariadb-dev libcups2-dev
cd "$HOME"
git clone --depth 1 --branch version-16 https://github.com/frappe/frappe.git frappe
git -C frappe fetch --depth 1 origin 9523516cac25992bc2cd810e1015df8994c257f5
git -C frappe checkout 9523516cac25992bc2cd810e1015df8994c257f5
bench init --skip-assets --frappe-path "$HOME/frappe" --python "$(which python)" frappe-bench
cd frappe-bench
bench set-config -g db_host 127.0.0.1
bench set-config -g db_port 3306
bench set-config -g developer_mode 1
bench setup redis
redis-server config/redis_cache.conf &
redis-server config/redis_queue.conf &
git clone --depth 1 --branch version-16 https://github.com/frappe/erpnext.git "$HOME/erpnext-source"
git -C "$HOME/erpnext-source" fetch --depth 1 origin 8378b6e203841c056925420cc44e6d631c915cf1
git -C "$HOME/erpnext-source" checkout 8378b6e203841c056925420cc44e6d631c915cf1
bench get-app --skip-assets erpnext "$HOME/erpnext-source"
bench get-app --skip-assets hrms "$GITHUB_WORKSPACE"
bench new-site test_site --mariadb-root-password root --admin-password test-only-password --db-host 127.0.0.1 --no-mariadb-socket
bench --site test_site set-config mute_emails 1
bench --site test_site set-config pause_scheduler 1
bench --site test_site set-config allow_tests 1
bench --site test_site install-app erpnext
bench --site test_site install-app hrms
bench build --app frappe
