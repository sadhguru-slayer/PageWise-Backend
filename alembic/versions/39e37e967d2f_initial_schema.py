"""initial_schema

Revision ID: 39e37e967d2f
Revises: 
Create Date: 2026-11-01 19:12:14.565758

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39e37e967d2f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('preferences_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'resumes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, server_default='Untitled Resume'),
        sa.Column('header_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('settings_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('sections_json', sa.Text(), nullable=True, server_default='[]'),
        sa.Column('target_job_title', sa.String(length=255), nullable=True),
        sa.Column('target_company', sa.String(length=255), nullable=True),
        sa.Column('target_job_description', sa.Text(), nullable=True),
        sa.Column('target_ats_score', sa.Float(), nullable=True),
        sa.Column('jd_analysis_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resumes_id'), 'resumes', ['id'], unique=False)
    op.create_index(op.f('ix_resumes_user_id'), 'resumes', ['user_id'], unique=False)

    op.create_table(
        'resume_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('settings_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('header_style_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('section_defaults_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resume_templates_id'), 'resume_templates', ['id'], unique=False)
    op.create_index(op.f('ix_resume_templates_user_id'), 'resume_templates', ['user_id'], unique=False)

    op.create_table(
        'exported_resumes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('resume_id', sa.Integer(), nullable=True),
        sa.Column('resume_name', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.String(length=10), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('target_job_title', sa.String(length=255), nullable=True),
        sa.Column('target_company', sa.String(length=255), nullable=True),
        sa.Column('template_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_exported_resumes_id'), 'exported_resumes', ['id'], unique=False)
    op.create_index(op.f('ix_exported_resumes_user_id'), 'exported_resumes', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('exported_resumes')
    op.drop_table('resume_templates')
    op.drop_table('resumes')
    op.drop_table('users')
