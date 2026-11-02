"""add_subscriptions_tiers_and_admin

Revision ID: c8d9e0f1a2b3
Revises: a1b2c3d4e5f6
Create Date: 2026-11-02 06:00:00.000000

"""
from typing import Sequence, Union
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    # ─── 1. Columns for users table ──────────────────────────────────────────
    if 'users' in existing_tables:
        user_cols = {col['name'] for col in insp.get_columns('users')}
        if 'is_admin' not in user_cols:
            op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='0'))

    # ─── 2. Columns for resumes table ────────────────────────────────────────
    if 'resumes' in existing_tables:
        resume_cols = {col['name'] for col in insp.get_columns('resumes')}
        if 'parent_resume_id' not in resume_cols:
            op.add_column('resumes', sa.Column('parent_resume_id', sa.Integer(), nullable=True))
        if 'is_primary' not in resume_cols:
            op.add_column('resumes', sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='0'))

    # ─── 3. Columns for resume_templates table ───────────────────────────────
    if 'resume_templates' in existing_tables:
        tmpl_cols = {col['name'] for col in insp.get_columns('resume_templates')}
        if 'template_key' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('template_key', sa.String(length=100), nullable=True))
        if 'is_global' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('is_global', sa.Boolean(), nullable=False, server_default='0'))
        if 'min_plan_tier' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('min_plan_tier', sa.String(length=50), nullable=False, server_default='free'))
        if 'badge' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('badge', sa.String(length=100), nullable=True))
        if 'category' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('category', sa.String(length=255), nullable=True))
        if 'preview_thumbnail' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('preview_thumbnail', sa.String(length=255), nullable=True))
        if 'display_order' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'))
        if 'is_active' not in tmpl_cols:
            op.add_column('resume_templates', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))

        # Add indexes if not present
        existing_indices = {idx['name'] for idx in insp.get_indexes('resume_templates')}
        if 'ix_resume_templates_template_key' not in existing_indices:
            op.create_index(op.f('ix_resume_templates_template_key'), 'resume_templates', ['template_key'], unique=False)
        if 'ix_resume_templates_is_global' not in existing_indices:
            op.create_index(op.f('ix_resume_templates_is_global'), 'resume_templates', ['is_global'], unique=False)

    # ─── 4. Subscriptions Table ──────────────────────────────────────────────
    if 'subscriptions' not in existing_tables:
        op.create_table(
            'subscriptions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('plan_type', sa.String(length=50), nullable=False, server_default='free'),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('resumes_created_in_period', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('exports_used_in_period', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('wiser_job_help_used', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('wiser_ats_used', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('period_reset_at', sa.DateTime(), nullable=True),
            sa.Column('razorpay_payment_id', sa.String(length=100), nullable=True),
            sa.Column('razorpay_order_id', sa.String(length=100), nullable=True),
            sa.Column('razorpay_subscription_id', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id')
        )
        op.create_index(op.f('ix_subscriptions_id'), 'subscriptions', ['id'], unique=False)
        op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=True)

    # ─── 5. Payment Orders Table ─────────────────────────────────────────────
    if 'payment_orders' not in existing_tables:
        op.create_table(
            'payment_orders',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('plan_type', sa.String(length=50), nullable=False),
            sa.Column('amount_inr', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='created'),
            sa.Column('razorpay_order_id', sa.String(length=100), nullable=True),
            sa.Column('razorpay_payment_id', sa.String(length=100), nullable=True),
            sa.Column('razorpay_signature', sa.String(length=255), nullable=True),
            sa.Column('receipt', sa.String(length=100), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_payment_orders_id'), 'payment_orders', ['id'], unique=False)
        op.create_index(op.f('ix_payment_orders_user_id'), 'payment_orders', ['user_id'], unique=False)
        op.create_index(op.f('ix_payment_orders_razorpay_order_id'), 'payment_orders', ['razorpay_order_id'], unique=True)
        op.create_index(op.f('ix_payment_orders_razorpay_payment_id'), 'payment_orders', ['razorpay_payment_id'], unique=False)

    # ─── 6. Plan Tier Configs Table ──────────────────────────────────────────
    if 'plan_tier_configs' not in existing_tables:
        op.create_table(
            'plan_tier_configs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('tier_key', sa.String(length=50), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('tagline', sa.String(length=255), nullable=True),
            sa.Column('badge', sa.String(length=100), nullable=True),
            sa.Column('base_price_inr', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('discount_price_inr', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('discount_percent', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('billing_period_text', sa.String(length=50), nullable=True, server_default='forever'),
            sa.Column('duration_days', sa.Integer(), nullable=True),
            sa.Column('resume_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('export_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('wiser_ai_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('wiser_job_help_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('wiser_ats_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('custom_template_limit', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('premium_templates_allowed', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('features_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_plan_tier_configs_id'), 'plan_tier_configs', ['id'], unique=False)
        op.create_index(op.f('ix_plan_tier_configs_tier_key'), 'plan_tier_configs', ['tier_key'], unique=True)
    else:
        # Table already existed, ensure is_archived column exists
        plan_cols = {col['name'] for col in insp.get_columns('plan_tier_configs')}
        if 'is_archived' not in plan_cols:
            op.add_column('plan_tier_configs', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='0'))

    # ─── 7. Clean up deprecated unused legacy tables if present ───────────────
    for old_table in ['feedback', 'system_settings', 'system_templates', 'activity_logs']:
        if old_table in existing_tables:
            try:
                op.drop_table(old_table)
            except Exception:
                pass


def downgrade() -> None:
    # Safe down-migration
    for tbl in ['plan_tier_configs', 'payment_orders', 'subscriptions']:
        try:
            op.drop_table(tbl)
        except Exception:
            pass

    for col_info in [
        ('users', 'is_admin'),
        ('resumes', 'parent_resume_id'),
        ('resumes', 'is_primary'),
        ('resume_templates', 'template_key'),
        ('resume_templates', 'is_global'),
        ('resume_templates', 'min_plan_tier'),
        ('resume_templates', 'badge'),
        ('resume_templates', 'category'),
        ('resume_templates', 'preview_thumbnail'),
        ('resume_templates', 'display_order'),
        ('resume_templates', 'is_active'),
    ]:
        try:
            op.drop_column(col_info[0], col_info[1])
        except Exception:
            pass
