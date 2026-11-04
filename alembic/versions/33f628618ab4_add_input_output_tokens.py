"""add_input_output_tokens

Revision ID: 33f628618ab4
Revises: a03e8367b0d7
Create Date: 2026-11-04 20:37:29.932527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = '33f628618ab4'
down_revision: Union[str, Sequence[str], None] = 'a03e8367b0d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    if 'ai_usage_logs' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('ai_usage_logs')}
        if 'input_tokens' not in existing_cols:
            op.add_column(
                'ai_usage_logs',
                sa.Column('input_tokens', sa.Integer(), nullable=False, server_default=sa.text('0'))
            )
        if 'output_tokens' not in existing_cols:
            op.add_column(
                'ai_usage_logs',
                sa.Column('output_tokens', sa.Integer(), nullable=False, server_default=sa.text('0'))
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    if 'ai_usage_logs' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('ai_usage_logs')}
        # SQLite batch mode if needed, or drop_column for databases supporting it
        if bind.dialect.name == 'sqlite':
            with op.batch_alter_table('ai_usage_logs') as batch_op:
                if 'output_tokens' in existing_cols:
                    batch_op.drop_column('output_tokens')
                if 'input_tokens' in existing_cols:
                    batch_op.drop_column('input_tokens')
        else:
            if 'output_tokens' in existing_cols:
                op.drop_column('ai_usage_logs', 'output_tokens')
            if 'input_tokens' in existing_cols:
                op.drop_column('ai_usage_logs', 'input_tokens')
