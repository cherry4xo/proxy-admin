#!/usr/bin/env python3
"""Migration: Add dynamic SNI columns to nodes table.

This migration adds:
- sni_pool_encrypted: TEXT (encrypted JSON list of SNI domains)
- current_sni_index: INTEGER (current pool index)
- last_sni_rotation_at: DATETIME (last rotation timestamp)
- sni_rotation_interval_h: INTEGER (rotation interval in hours)

Run: python scripts/migrations/003_add_sni_rotation.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "proxy.db"


def migrate():
    """Add SNI rotation columns to nodes table."""
    print(f"Migration: Add SNI rotation columns to {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if columns already exist
    cursor.execute("PRAGMA table_info(nodes)")
    columns = {row[1] for row in cursor.fetchall()}

    new_columns = []

    if "sni_pool_encrypted" not in columns:
        new_columns.append("sni_pool_encrypted")
        cursor.execute(
            "ALTER TABLE nodes ADD COLUMN sni_pool_encrypted TEXT"
        )
        print("  + Added sni_pool_encrypted")

    if "current_sni_index" not in columns:
        new_columns.append("current_sni_index")
        cursor.execute(
            "ALTER TABLE nodes ADD COLUMN current_sni_index INTEGER DEFAULT 0"
        )
        print("  + Added current_sni_index")

    if "last_sni_rotation_at" not in columns:
        new_columns.append("last_sni_rotation_at")
        cursor.execute(
            "ALTER TABLE nodes ADD COLUMN last_sni_rotation_at DATETIME"
        )
        print("  + Added last_sni_rotation_at")

    if "sni_rotation_interval_h" not in columns:
        new_columns.append("sni_rotation_interval_h")
        cursor.execute(
            "ALTER TABLE nodes ADD COLUMN sni_rotation_interval_h INTEGER DEFAULT 24"
        )
        print("  + Added sni_rotation_interval_h")

    if not new_columns:
        print("  ✓ All columns already exist, nothing to do")
    else:
        print(f"  ✓ Migration complete: {len(new_columns)} columns added")

    conn.commit()
    conn.close()

    print("\nNext steps:")
    print("1. Restart the bot to load new model fields")
    print("2. Use bot commands to configure SNI pools:")
    print("   /sni_pool <node_id> <domain1,domain2,...>")
    print("   /sni_rotate <node_id> [force]")
    print("   /sni_status [node_id]")


if __name__ == "__main__":
    migrate()
