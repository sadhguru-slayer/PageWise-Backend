"""add_soft_delete_and_ai_usage_logs

Revision ID: a1b2c3d4e5f6
Revises: 39e37e967d2f
Create Date: 2026-11-02 02:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '39e37e967d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Soft-delete columns
    for table_name in ['resumes', 'resume_templates', 'exported_resumes']:
        op.add_column(table_name, sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'))
        op.add_column(table_name, sa.Column('deleted_at', sa.DateTime(), nullable=True))
        op.create_index(f'ix_{table_name}_is_deleted', table_name, ['is_deleted'], unique=False)

    # 2. AI Usage Logs Table
    op.create_table(
        'ai_usage_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('resume_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('ai_model', sa.String(length=100), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('meta_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_usage_logs_id'), 'ai_usage_logs', ['id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_user_id'), 'ai_usage_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_resume_id'), 'ai_usage_logs', ['resume_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_action_type'), 'ai_usage_logs', ['action_type'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_created_at'), 'ai_usage_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('ai_usage_logs')
    for table_name in ['resumes', 'resume_templates', 'exported_resumes']:
        op.drop_index(f'ix_{table_name}_is_deleted', table_name=table_name)
        op.drop_column(table_name, 'deleted_at')
        op.drop_column(table_name, 'is_deleted')
