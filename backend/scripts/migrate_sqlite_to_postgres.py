#!/usr/bin/env python3
"""Migrate global variables from SQLite to PostgreSQL."""

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
from pathlib import Path

from deerflow.config.paths import get_paths


def migrate(sqlite_path: str | None = None, postgres_dsn: str = "postgresql://postgres:yuhan1014@localhost:5432/deerflow") -> None:
    """Migrate data from SQLite to PostgreSQL.
    
    Steps:
        1. Read all data from SQLite
        2. Insert into PostgreSQL with UPSERT
        3. Verify data consistency
    """
    # Determine SQLite path
    if sqlite_path is None:
        sqlite_path = str(get_paths().base_dir / "global_variables.db")
    
    print(f"Source (SQLite): {sqlite_path}")
    print(f"Target (PostgreSQL): {postgres_dsn}")
    
    # Check if SQLite file exists
    if not Path(sqlite_path).exists():
        print("SQLite database not found. Nothing to migrate.")
        return
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    
    try:
        import psycopg
    except ImportError:
        print("Error: psycopg is not installed. Run: uv add psycopg[binary]")
        sys.exit(1)
    
    # Connect to PostgreSQL
    pg_conn = psycopg.connect(postgres_dsn)
    
    try:
        # Migrate global_variables
        print("\nMigrating global_variables...")
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("""
            SELECT thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by
            FROM global_variables
        """)
        
        rows = sqlite_cursor.fetchall()
        migrated_count = 0
        
        for row in rows:
            pg_conn.execute(
                """
                INSERT INTO global_variables 
                (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s::boolean, %s::boolean, %s, %s)
                ON CONFLICT (thread_id, key) 
                DO UPDATE SET 
                    value = EXCLUDED.value,
                    description = EXCLUDED.description,
                    is_system = EXCLUDED.is_system,
                    llm_editable = EXCLUDED.llm_editable,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
            """,
                (row["thread_id"], row["key"], row["value"], row["description"], 
                 bool(row["is_system"]), bool(row["llm_editable"]), row["updated_at"], row["updated_by"]),
            )
            migrated_count += 1
        
        pg_conn.commit()
        print(f"  Migrated {migrated_count} global_variables")
        
        # Migrate agent_favorites
        print("\nMigrating agent_favorites...")
        sqlite_cursor.execute("SELECT agent_name, created_at FROM agent_favorites")
        
        rows = sqlite_cursor.fetchall()
        migrated_count = 0
        
        for row in rows:
            pg_conn.execute(
                """
                INSERT INTO agent_favorites (agent_name, created_at)
                VALUES (%s, %s)
                ON CONFLICT (agent_name) DO UPDATE SET created_at = EXCLUDED.created_at
            """,
                (row["agent_name"], row["created_at"]),
            )
            migrated_count += 1
        
        pg_conn.commit()
        print(f"  Migrated {migrated_count} agent_favorites")
        
        # Verify data consistency
        print("\nVerifying data consistency...")
        
        sqlite_cursor.execute("SELECT COUNT(*) FROM global_variables")
        sqlite_count = sqlite_cursor.fetchone()[0]
        
        pg_cursor = pg_conn.cursor()
        pg_cursor.execute("SELECT COUNT(*) FROM global_variables")
        pg_count = pg_cursor.fetchone()[0]
        
        print(f"  global_variables: SQLite={sqlite_count}, PostgreSQL={pg_count}")
        
        sqlite_cursor.execute("SELECT COUNT(*) FROM agent_favorites")
        sqlite_count = sqlite_cursor.fetchone()[0]
        
        pg_cursor.execute("SELECT COUNT(*) FROM agent_favorites")
        pg_count = pg_cursor.fetchone()[0]
        
        print(f"  agent_favorites: SQLite={sqlite_count}, PostgreSQL={pg_count}")
        
        if sqlite_count == pg_count:
            print("\nMigration completed successfully!")
        else:
            print("\nWarning: Record counts don't match. Please check manually.")
        
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    migrate()
