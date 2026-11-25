#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

log_file="sessions/11_test_database_setup_output.txt"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

required_files=(
  "sql/01_schema.sql"
  "sql/02_triggers.sql"
  "sql/03_procedures.sql"
  "sql/04_views.sql"
  "output/seed_data.sql"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: required file not found: $file" | tee "$log_file"
    exit 1
  fi
done

if ! command -v mysql >/dev/null 2>&1; then
  echo "ERROR: mysql client was not found. Install/use the MySQL command-line client." | tee "$log_file"
  exit 1
fi

existing_db="$(sudo mysql -NBe "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = 'pharma_counterfeit_test';")"
if [[ "$existing_db" == "pharma_counterfeit_test" ]]; then
  echo "ERROR: pharma_counterfeit_test already exists. Nothing was changed." | tee "$log_file"
  echo "Inspect or remove that test database deliberately before rerunning this setup." | tee -a "$log_file"
  exit 1
fi

{
  echo "Pharma Counterfeit DBMS - test database setup"
  echo "Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Target database: pharma_counterfeit_test"
  echo
} > "$log_file"

for source_file in \
  "sql/01_schema.sql" \
  "sql/02_triggers.sql" \
  "sql/03_procedures.sql" \
  "sql/04_views.sql" \
  "output/seed_data.sql"
do
  target_file="$tmp_dir/$(basename "$source_file")"
  sed 's/pharma_counterfeit_db/pharma_counterfeit_test/g' "$source_file" > "$target_file"

  {
    echo
    echo "===== Loading $source_file ====="
  } >> "$log_file"

  sudo mysql --show-warnings --table < "$target_file" >> "$log_file" 2>&1
done

cat > "$tmp_dir/verify.sql" <<'SQL'
USE pharma_counterfeit_test;

SELECT 'participant' AS table_name, COUNT(*) AS row_count FROM participant
UNION ALL SELECT 'license_history', COUNT(*) FROM license_history
UNION ALL SELECT 'drug', COUNT(*) FROM drug
UNION ALL SELECT 'material_lot', COUNT(*) FROM material_lot
UNION ALL SELECT 'batch', COUNT(*) FROM batch
UNION ALL SELECT 'batch_material', COUNT(*) FROM batch_material
UNION ALL SELECT 'pack', COUNT(*) FROM pack
UNION ALL SELECT 'link', COUNT(*) FROM link
UNION ALL SELECT 'shipment', COUNT(*) FROM shipment
UNION ALL SELECT 'shipment_item', COUNT(*) FROM shipment_item
UNION ALL SELECT 'trace_event', COUNT(*) FROM trace_event
UNION ALL SELECT 'anomaly_flag', COUNT(*) FROM anomaly_flag
UNION ALL SELECT 'injected_counterfeit', COUNT(*) FROM injected_counterfeit
UNION ALL SELECT 'link_risk_score', COUNT(*) FROM link_risk_score
UNION ALL SELECT 'risk_factor', COUNT(*) FROM risk_factor
ORDER BY table_name;

SELECT 'views' AS object_type, COUNT(*) AS object_count
FROM information_schema.views
WHERE table_schema = 'pharma_counterfeit_test';

SELECT 'triggers' AS object_type, COUNT(*) AS object_count
FROM information_schema.triggers
WHERE trigger_schema = 'pharma_counterfeit_test';

SELECT 'routines' AS object_type, COUNT(*) AS object_count
FROM information_schema.routines
WHERE routine_schema = 'pharma_counterfeit_test';
SQL

{
  echo
  echo "===== Test database verification ====="
} >> "$log_file"

sudo mysql --show-warnings --table < "$tmp_dir/verify.sql" >> "$log_file" 2>&1

{
  echo
  echo "Completed: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Result: SUCCESS"
} >> "$log_file"

echo "Test database created successfully."
echo "Output saved to: $log_file"
