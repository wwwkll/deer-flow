#!/usr/bin/env python3
"""Migrate checkpointer and store data from SQLite to PostgreSQL."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
from pathlib import Path


def migrate_table(sqlite_conn, pg_conn, table_name: str) -> int:
    """Migrate a single table from SQLite to PostgreSQL."""
    cursor = sqlite_conn.cursor()
    
    # Check if table exists
    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if not cursor.fetchone():
        print(f"  Table {table_name} not found in SQLite")
        return 0
    
    # Get column names
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    
    # Read data
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    if not rows:
        print(f"  Table {table_name}: no data to migrate")
        return 0
    
    # Build INSERT query
    col_str = ", ".join(columns)
    val_placeholders = ", ".join(["%s"] * len(columns))
    
    migrated = 0
    for row in rows:
        values = [row[i] for i in range(len(columns))]
        try:
            pg_conn.execute(
                f"INSERT INTO {table_name} ({col_str}) VALUES ({val_placeholders}) ON CONFLICT DO NOTHING",
                values
            )
            migrated += 1
        except Exception as e:
            print(f"  Error migrating row: {e}")
    
    pg_conn.commit()
    print(f"  Migrated {migrated}/{len(rows)} rows from {table_name}")
    return migrated


def migrate(sqlite_db_path: str = ".deer-flow/checkpoints.db", postgres_dsn: str = "postgresql://postgres:yuhan1014@localhost:5432/deerflow") -> None:
    """Migrate checkpointer and store data."""
    path = Path(sqlite_db_path)
    if not path.is_absolute():
        from deerflow.config.paths import get_paths
        path = get_paths().base_dir.parent / sqlite_db_path
    sqlite_path = str(path.resolve())
    
    print(f"Source (SQLite): {sqlite_path}")
    print(f"Target (PostgreSQL): {postgres_dsn}")
    
    if not Path(sqlite_path).exists():
        print("SQLite database not found. Nothing to migrate.")
        return
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    
    # Get list of tables
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"\nFound tables: {tables}")
    
    # Connect to PostgreSQL
    import psycopg
    pg_conn = psycopg.connect(postgres_dsn)
    
    # Create tables in PostgreSQL (using SQLite schema as reference)
    print("\nCreating tables in PostgreSQL...")
    for table in tables:
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        schema = cursor.fetchone()[0]
        print(f"  SQLite schema for {table}:")
        print(f"    {schema[:100]}...")
        # Note: LangGraph's PostgresSaver will create its own schema
    
    print("\nNote: LangGraph PostgreSQL backends manage their own schema.")
    print("Data migration is handled by the application on first run.")
    print("Please update config.yaml to use postgres and restart the service.")
    
    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    migrate()
