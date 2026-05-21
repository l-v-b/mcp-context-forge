"""add_numeric_id_to_email_users

Revision ID: 51d4f5e82d88
Revises: 351b43e1d273
Create Date: 2026-05-21 15:22:46.307164

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = '51d4f5e82d88'
down_revision: Union[str, Sequence[str], None] = '351b43e1d273'  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add numeric id column to email_users table.

    This migration adds a new auto-incrementing integer id column to email_users
    and makes it the primary key, while keeping email as a unique indexed column.
    This allows removing email from JWT tokens for PII compliance.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "email_users" not in inspector.get_table_names():
        return

    # Check if id column already exists
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "id" in columns:
        return

    # Get database backend
    backend = bind.engine.url.get_backend_name()

    if backend == "postgresql":
        # PostgreSQL: Add id column with sequence, backfill, then make it PK
        op.execute(text("ALTER TABLE email_users ADD COLUMN id SERIAL"))
        op.execute(text("ALTER TABLE email_users DROP CONSTRAINT email_users_pkey"))
        op.execute(text("ALTER TABLE email_users ADD PRIMARY KEY (id)"))
        op.create_index(op.f("ix_email_users_id"), "email_users", ["id"], unique=False)

    elif backend == "sqlite":
        # SQLite: Requires table recreation due to PK change
        # 1. Create new table with id as PK
        op.execute(text("""
            CREATE TABLE email_users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(255),
                is_admin BOOLEAN NOT NULL DEFAULT 0,
                admin_origin VARCHAR(20),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                email_verified_at DATETIME,
                auth_provider VARCHAR(50) NOT NULL DEFAULT 'local',
                password_hash_type VARCHAR(20) NOT NULL DEFAULT 'argon2id',
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until DATETIME,
                password_change_required BOOLEAN NOT NULL DEFAULT 0,
                password_changed_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_login DATETIME
            )
        """))

        # 2. Copy data from old table
        op.execute(text("""
            INSERT INTO email_users_new (
                email, password_hash, full_name, is_admin, admin_origin,
                is_active, email_verified_at, auth_provider, password_hash_type,
                failed_login_attempts, locked_until, password_change_required,
                password_changed_at, created_at, updated_at, last_login
            )
            SELECT
                email, password_hash, full_name, is_admin, admin_origin,
                is_active, email_verified_at, auth_provider, password_hash_type,
                failed_login_attempts, locked_until, password_change_required,
                password_changed_at, created_at, updated_at, last_login
            FROM email_users
        """))

        # 3. Drop old table and rename new one
        op.execute(text("DROP TABLE email_users"))
        op.execute(text("ALTER TABLE email_users_new RENAME TO email_users"))

        # 4. Recreate indexes
        op.create_index(op.f("ix_email_users_email"), "email_users", ["email"], unique=True)
        op.create_index(op.f("ix_email_users_full_name"), "email_users", ["full_name"], unique=False)


def downgrade() -> None:
    """Remove numeric id column and restore email as primary key.

    WARNING: This is a destructive operation that changes the primary key.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist
    if "email_users" not in inspector.get_table_names():
        return

    # Check if id column exists
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "id" not in columns:
        return

    # Get database backend
    backend = bind.engine.url.get_backend_name()

    if backend == "postgresql":
        # PostgreSQL: Drop id column and restore email as PK
        op.drop_index(op.f("ix_email_users_id"), table_name="email_users")
        op.execute(text("ALTER TABLE email_users DROP CONSTRAINT email_users_pkey"))
        op.execute(text("ALTER TABLE email_users ADD PRIMARY KEY (email)"))
        op.execute(text("ALTER TABLE email_users DROP COLUMN id"))

    elif backend == "sqlite":
        # SQLite: Requires table recreation
        # 1. Create old table structure with email as PK
        op.execute(text("""
            CREATE TABLE email_users_old (
                email VARCHAR(255) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(255),
                is_admin BOOLEAN NOT NULL DEFAULT 0,
                admin_origin VARCHAR(20),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                email_verified_at DATETIME,
                auth_provider VARCHAR(50) NOT NULL DEFAULT 'local',
                password_hash_type VARCHAR(20) NOT NULL DEFAULT 'argon2id',
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until DATETIME,
                password_change_required BOOLEAN NOT NULL DEFAULT 0,
                password_changed_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_login DATETIME
            )
        """))

        # 2. Copy data (excluding id column)
        op.execute(text("""
            INSERT INTO email_users_old (
                email, password_hash, full_name, is_admin, admin_origin,
                is_active, email_verified_at, auth_provider, password_hash_type,
                failed_login_attempts, locked_until, password_change_required,
                password_changed_at, created_at, updated_at, last_login
            )
            SELECT
                email, password_hash, full_name, is_admin, admin_origin,
                is_active, email_verified_at, auth_provider, password_hash_type,
                failed_login_attempts, locked_until, password_change_required,
                password_changed_at, created_at, updated_at, last_login
            FROM email_users
        """))

        # 3. Drop new table and rename old one
        op.execute(text("DROP TABLE email_users"))
        op.execute(text("ALTER TABLE email_users_old RENAME TO email_users"))

        # 4. Recreate indexes
        op.create_index(op.f("ix_email_users_email"), "email_users", ["email"], unique=True)
        op.create_index(op.f("ix_email_users_full_name"), "email_users", ["full_name"], unique=False)
