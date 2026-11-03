"""add_custom_section_schemas_table

Revision ID: a03e8367b0d7
Revises: fe9bf3173b8b
Create Date: 2026-11-03 18:01:04.204745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'a03e8367b0d7'
down_revision: Union[str, Sequence[str], None] = 'fe9bf3173b8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    # ─── Create custom_section_schemas table if not exists ────────────────────
    if 'custom_section_schemas' not in existing_tables:
        op.create_table(
            'custom_section_schemas',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('section_key', sa.String(length=100), nullable=False),
            sa.Column('label', sa.String(length=150), nullable=False),
            sa.Column('icon', sa.String(length=50), nullable=False, server_default='FileText'),
            sa.Column('description', sa.String(length=255), nullable=True),
            sa.Column('is_repeatable', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('fields_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_custom_section_schemas_id'), 'custom_section_schemas', ['id'], unique=False)
        op.create_index(op.f('ix_custom_section_schemas_section_key'), 'custom_section_schemas', ['section_key'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    if 'custom_section_schemas' in existing_tables:
        op.drop_index(op.f('ix_custom_section_schemas_section_key'), table_name='custom_section_schemas')
        op.drop_index(op.f('ix_custom_section_schemas_id'), table_name='custom_section_schemas')
        op.drop_table('custom_section_schemas')
