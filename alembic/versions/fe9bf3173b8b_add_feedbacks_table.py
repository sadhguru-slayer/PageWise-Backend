"""add_feedbacks_table

Revision ID: fe9bf3173b8b
Revises: c8d9e0f1a2b3
Create Date: 2026-11-02 20:01:47.126606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'fe9bf3173b8b'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    # ─── Create feedbacks table if not exists ─────────────────────────────────
    if 'feedbacks' not in existing_tables:
        op.create_table(
            'feedbacks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('category', sa.String(length=50), nullable=False, server_default='pilot_feedback'),
            sa.Column('rating', sa.Integer(), nullable=True),
            sa.Column('title', sa.String(length=255), nullable=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('metadata_json', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='new'),
            sa.Column('admin_notes', sa.Text(), nullable=True),
            sa.Column('ip_address', sa.String(length=100), nullable=True),
            sa.Column('user_agent', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_feedbacks_id'), 'feedbacks', ['id'], unique=False)
        op.create_index(op.f('ix_feedbacks_user_id'), 'feedbacks', ['user_id'], unique=False)
        op.create_index(op.f('ix_feedbacks_category'), 'feedbacks', ['category'], unique=False)
        op.create_index(op.f('ix_feedbacks_status'), 'feedbacks', ['status'], unique=False)
        op.create_index(op.f('ix_feedbacks_created_at'), 'feedbacks', ['created_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    if 'feedbacks' in existing_tables:
        op.drop_table('feedbacks')
