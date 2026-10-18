#!/usr/bin/env bash
# 把现有数据库整体复制到新库名（AIOA → AIOS 改名专用）
#
# 背景：产品由 AIOA 更名为 AIOS 后，后端默认库名变为 `aios`。
# MySQL 不支持 `RENAME DATABASE`，因此用「建新库 + 整库导入 + 校验」的方式迁移。
# 旧库**不删除**，保留用于回滚（确认稳定后再手工 DROP）。
#
# 用法（生产须先停机，避免迁移过程中的写入丢失）：
#   MYSQL_HOST=10.0.0.5 MYSQL_PORT=13049 MYSQL_USER=root MYSQL_PASSWORD=*** \
#     bash deploy/db/02-migrate-db-to-aios.sh
#
# 可选环境变量：
#   SRC_DB  源库名（默认 aioa）
#   DST_DB  目标库名（默认 aios）
#   FORCE=1 目标库已存在且有表时强制覆盖（会先 DROP）
set -euo pipefail

HOST="${MYSQL_HOST:-127.0.0.1}"
PORT="${MYSQL_PORT:-3306}"
USER="${MYSQL_USER:-root}"
PASS="${MYSQL_PASSWORD:-}"
SRC_DB="${SRC_DB:-aioa}"
DST_DB="${DST_DB:-aios}"

MYSQL_BIN="${MYSQL_BIN:-mysql}"
MYSQLDUMP_BIN="${MYSQLDUMP_BIN:-mysqldump}"
TMP_SQL="${TMP_SQL:-/tmp/${SRC_DB}_to_${DST_DB}.sql}"

args=(-h"$HOST" -P"$PORT" -u"$USER")
[ -n "$PASS" ] && args+=(-p"$PASS")

echo "[1/6] 检查源库 $SRC_DB 是否存在且有表"
tables=$("$MYSQL_BIN" "${args[@]}" -N -B -e \
  "select count(*) from information_schema.tables where table_schema='$SRC_DB';")
if [ "$tables" -eq 0 ]; then
  echo "  ✗ 源库 $SRC_DB 不存在或为空，终止" >&2
  exit 1
fi
echo "  ✓ 源库表数：$tables"

echo "[2/6] 检查目标库 $DST_DB 现状"
dst_tables=$("$MYSQL_BIN" "${args[@]}" -N -B -e \
  "select count(*) from information_schema.tables where table_schema='$DST_DB';" 2>/dev/null || echo 0)
if [ "$dst_tables" -gt 0 ]; then
  if [ "${FORCE:-0}" != "1" ]; then
    echo "  ✗ 目标库 $DST_DB 已有 $dst_tables 张表；如确认覆盖请设 FORCE=1" >&2
    exit 1
  fi
  echo "  ! FORCE=1，将先 DROP 目标库"
  "$MYSQL_BIN" "${args[@]}" -e "DROP DATABASE \`$DST_DB\`;"
fi

echo "[3/6] 导出源库到 $TMP_SQL"
"$MYSQLDUMP_BIN" "${args[@]}" \
  --single-transaction --routines --triggers --events \
  --set-gtid-purged=OFF --default-character-set=utf8mb4 \
  "$SRC_DB" > "$TMP_SQL"
echo "  ✓ 导出完成：$(du -h "$TMP_SQL" | cut -f1)"

echo "[4/6] 建库并导入"
"$MYSQL_BIN" "${args[@]}" -e \
  "CREATE DATABASE \`$DST_DB\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
"$MYSQL_BIN" "${args[@]}" "$DST_DB" < "$TMP_SQL"
echo "  ✓ 导入完成"

echo "[5/6] 校验表数与关键表行数"
"$MYSQL_BIN" "${args[@]}" -e "
select '$SRC_DB' as db, count(*) as tables from information_schema.tables where table_schema='$SRC_DB'
union all
select '$DST_DB', count(*) from information_schema.tables where table_schema='$DST_DB';
select 'sys_user' as t, (select count(*) from \`$SRC_DB\`.sys_user) as src, (select count(*) from \`$DST_DB\`.sys_user) as dst
union all select 'chat_conversation', (select count(*) from \`$SRC_DB\`.chat_conversation), (select count(*) from \`$DST_DB\`.chat_conversation)
union all select 'chat_message', (select count(*) from \`$SRC_DB\`.chat_message), (select count(*) from \`$DST_DB\`.chat_message)
union all select 'pm_project', (select count(*) from \`$SRC_DB\`.pm_project), (select count(*) from \`$DST_DB\`.pm_project);
select max(cast(version as unsigned)) as flyway_src from \`$SRC_DB\`.flyway_schema_history;
select max(cast(version as unsigned)) as flyway_dst from \`$DST_DB\`.flyway_schema_history;"

echo "[6/6] 完成。下一步："
echo "  - 更新部署机的 deploy/.env（未入库）：SPRING_DATASOURCE_URL 中库名改为 $DST_DB，并确认 AIOS_* 变量名"
echo "  - 重启后端；Flyway 会校验历史迁移 checksum（本次改名未改动历史迁移文件，应全部匹配）"
echo "  - 旧库 $SRC_DB 保留，确认稳定后再手工 DROP"
