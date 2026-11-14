"""Apply every SQL file under infra/mysql/init in filename order.

Used by CI instead of shelling out to the `mysql` client: the GitHub runner image
moved to Ubuntu 26 where the `mysql-client` package no longer installs, and we
already ship pymysql for the app itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "infra" / "mysql" / "init"


def main() -> None:
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    database = os.getenv("MYSQL_DATABASE", "docaudit")
    user = os.getenv("MYSQL_ROOT_USER", "root")
    password = os.getenv("MYSQL_ROOT_PASSWORD", "root_pwd")

    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        raise SystemExit(f"no migrations found in {MIGRATIONS}")

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        # 每个 .sql 文件里有多条语句，交给服务端按分号切分。
        client_flag=CLIENT.MULTI_STATEMENTS,
    )

    try:
        with connection.cursor() as cursor:
            for path in files:
                print(f"applying {path.relative_to(ROOT)}", flush=True)
                cursor.execute(path.read_text(encoding="utf-8"))
                while cursor.nextset():
                    pass
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
    finally:
        connection.close()

    print(f"done: {len(files)} migrations, {len(tables)} tables -> {', '.join(tables)}")


if __name__ == "__main__":
    sys.exit(main())
