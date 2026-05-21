#!/usr/bin/env python3
"""
Backup script for Krylo CRM (Railway PostgreSQL).

Usage:
    python scripts/backup.py

Requires:
    - DATABASE_URL environment variable (PostgreSQL connection string)
    - pg_dump available in PATH (ships with PostgreSQL client tools)

Output:
    backups/krylo_YYYYMMDD_HHMMSS.sql.gz

Schedule (Railway cron job or external cron):
    0 3 * * *  python /app/scripts/backup.py
"""

import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path(__file__).parent.parent / "backups"
KEEP_LAST = int(os.getenv("BACKUP_KEEP", "7"))  # keep 7 days by default


def main() -> int:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[backup] ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    if not shutil.which("pg_dump"):
        print("[backup] ERROR: pg_dump not found in PATH", file=sys.stderr)
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_file = BACKUP_DIR / f"krylo_{timestamp}.sql"
    gz_file = BACKUP_DIR / f"krylo_{timestamp}.sql.gz"

    print(f"[backup] Dumping database → {gz_file.name}")
    try:
        result = subprocess.run(
            ["pg_dump", "--no-password", "--format=plain", db_url],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[backup] pg_dump failed:\n{e.stderr.decode()}", file=sys.stderr)
        return 1

    with gzip.open(gz_file, "wb") as f:
        f.write(result.stdout)

    size_kb = gz_file.stat().st_size // 1024
    print(f"[backup] Done — {size_kb} KB compressed")

    _rotate_old_backups()
    return 0


def _rotate_old_backups() -> None:
    files = sorted(BACKUP_DIR.glob("krylo_*.sql.gz"), key=lambda p: p.stat().st_mtime)
    to_delete = files[:-KEEP_LAST] if len(files) > KEEP_LAST else []
    for f in to_delete:
        f.unlink()
        print(f"[backup] Removed old backup: {f.name}")


if __name__ == "__main__":
    sys.exit(main())
