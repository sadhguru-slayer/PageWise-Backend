"""add_blog_posts_table

Revision ID: 7dafe2f6bdcb
Revises: 33f628618ab4
Create Date: 2026-11-17 18:01:01.818449

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = '7dafe2f6bdcb'
down_revision: Union[str, Sequence[str], None] = '33f628618ab4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    # ─── Create blog_posts table if not exists ───────────────────────────────
    if 'blog_posts' not in existing_tables:
        op.create_table(
            'blog_posts',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(length=200), nullable=False),
            sa.Column('title', sa.String(length=300), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('content_html', sa.Text(), nullable=False),
            sa.Column('content_json', sa.Text(), nullable=True),
            sa.Column('cover_image_url', sa.String(length=500), nullable=True),
            sa.Column('author_name', sa.String(length=100), nullable=False, server_default='PageWise Editorial'),
            sa.Column('author_role', sa.String(length=100), nullable=True, server_default='Career & Engineering Lead'),
            sa.Column('tags_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('reading_time_minutes', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_blog_posts_id'), 'blog_posts', ['id'], unique=False)
        op.create_index(op.f('ix_blog_posts_slug'), 'blog_posts', ['slug'], unique=True)
        op.create_index(op.f('ix_blog_posts_is_published'), 'blog_posts', ['is_published'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    existing_tables = set(insp.get_table_names())

    if 'blog_posts' in existing_tables:
        op.drop_index(op.f('ix_blog_posts_is_published'), table_name='blog_posts')
        op.drop_index(op.f('ix_blog_posts_slug'), table_name='blog_posts')
        op.drop_index(op.f('ix_blog_posts_id'), table_name='blog_posts')
        op.drop_table('blog_posts')
