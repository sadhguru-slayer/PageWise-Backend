import json
import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from ..database import get_db
from ..models import BlogPost, User
from ..auth import get_current_user
from ..schemas import (
    BlogPostCreate,
    BlogPostUpdate,
    BlogPostOut,
    BlogPostSummaryOut,
    BlogListResponse,
)

router = APIRouter(prefix="/api/blogs", tags=["Blog Engine"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to manage blog posts."
        )
    return current_user


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text or "post"


def serialize_tags(tags: Optional[List[str]]) -> str:
    if not tags:
        return "[]"
    clean = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
    return json.dumps(clean)


def parse_tags(tags_json: Optional[str]) -> List[str]:
    if not tags_json:
        return []
    try:
        data = json.loads(tags_json)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def format_blog_summary(post: BlogPost) -> dict:
    return {
        "id": post.id,
        "slug": post.slug,
        "title": post.title,
        "summary": post.summary,
        "cover_image_url": post.cover_image_url,
        "author_name": post.author_name,
        "author_role": post.author_role,
        "tags": parse_tags(post.tags_json),
        "reading_time_minutes": post.reading_time_minutes,
        "views_count": post.views_count,
        "is_published": post.is_published,
        "published_at": post.published_at,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


def format_blog_detail(post: BlogPost) -> dict:
    summary = format_blog_summary(post)
    summary["content_html"] = post.content_html
    summary["content_json"] = post.content_json
    return summary


# ─── Public Endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=BlogListResponse)
def list_published_blogs(
    page: int = Query(1, ge=1),
    limit: int = Query(9, ge=1, le=50),
    tag: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Public listing of published blog posts. Supports search and tag filtering.
    """
    query = db.query(BlogPost).filter(BlogPost.is_published == True)

    if tag:
        # SQLite / PG json substring search
        query = query.filter(BlogPost.tags_json.ilike(f'%"{tag.strip()}"%'))

    if q:
        search_filter = f"%{q.strip()}%"
        query = query.filter(
            (BlogPost.title.ilike(search_filter)) |
            (BlogPost.summary.ilike(search_filter))
        )

    total = query.count()
    offset = (page - 1) * limit
    posts = (
        query.order_by(desc(BlogPost.published_at), desc(BlogPost.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [format_blog_summary(p) for p in posts]
    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


@router.get("/tags/popular")
def get_popular_tags(db: Session = Depends(get_db)):
    """
    Returns unique list of tags across all published blog posts.
    """
    posts = db.query(BlogPost.tags_json).filter(BlogPost.is_published == True).all()
    tag_counts = {}
    for (t_json,) in posts:
        tags = parse_tags(t_json)
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"tag": k, "count": v}
        for k, v in sorted_tags
    ]


@router.get("/{slug}", response_model=BlogPostOut)
def get_blog_by_slug(slug: str, db: Session = Depends(get_db)):
    """
    Public detail view of a published blog post. Increments views count.
    """
    post = db.query(BlogPost).filter(BlogPost.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found.")

    if not post.is_published:
        raise HTTPException(status_code=404, detail="Blog post is not published.")

    # Atomic increment views count
    post.views_count = (post.views_count or 0) + 1
    db.commit()
    db.refresh(post)

    return format_blog_detail(post)


# ─── Admin Endpoints ─────────────────────────────────────────────────────────

@router.get("/admin/all")
def admin_list_blogs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None), # 'published' | 'draft'
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """
    Admin listing of all blogs (drafts, published, archived).
    """
    query = db.query(BlogPost)
    if status_filter == "published":
        query = query.filter(BlogPost.is_published == True)
    elif status_filter == "draft":
        query = query.filter(BlogPost.is_published == False)

    if q:
        search_filter = f"%{q.strip()}%"
        query = query.filter(
            (BlogPost.title.ilike(search_filter)) |
            (BlogPost.slug.ilike(search_filter))
        )

    total = query.count()
    offset = (page - 1) * limit
    posts = (
        query.order_by(desc(BlogPost.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [format_blog_summary(p) for p in posts]
    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


@router.get("/admin/{post_id}", response_model=BlogPostOut)
def admin_get_blog(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    post = db.query(BlogPost).filter(BlogPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found.")
    return format_blog_detail(post)


@router.post("/admin", response_model=BlogPostOut)
def admin_create_blog(
    payload: BlogPostCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    # Determine slug
    clean_slug = slugify(payload.slug or payload.title)
    existing = db.query(BlogPost).filter(BlogPost.slug == clean_slug).first()
    if existing:
        clean_slug = f"{clean_slug}-{int(datetime.utcnow().timestamp())}"

    published_at = datetime.utcnow() if payload.is_published else None

    post = BlogPost(
        slug=clean_slug,
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        content_html=payload.content_html,
        content_json=payload.content_json,
        cover_image_url=payload.cover_image_url,
        author_name=payload.author_name or admin.name or "PageWise Editorial",
        author_role=payload.author_role or "Career & Engineering Lead",
        tags_json=serialize_tags(payload.tags),
        reading_time_minutes=payload.reading_time_minutes or 5,
        is_published=payload.is_published,
        published_at=published_at,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return format_blog_detail(post)


@router.put("/admin/{post_id}", response_model=BlogPostOut)
def admin_update_blog(
    post_id: int,
    payload: BlogPostUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    post = db.query(BlogPost).filter(BlogPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found.")

    if payload.title is not None:
        post.title = payload.title.strip()
    if payload.slug is not None and payload.slug.strip():
        new_slug = slugify(payload.slug)
        existing = db.query(BlogPost).filter(BlogPost.slug == new_slug, BlogPost.id != post_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="A post with this slug already exists.")
        post.slug = new_slug
    if payload.summary is not None:
        post.summary = payload.summary.strip()
    if payload.content_html is not None:
        post.content_html = payload.content_html
    if payload.content_json is not None:
        post.content_json = payload.content_json
    if payload.cover_image_url is not None:
        post.cover_image_url = payload.cover_image_url
    if payload.author_name is not None:
        post.author_name = payload.author_name.strip()
    if payload.author_role is not None:
        post.author_role = payload.author_role.strip()
    if payload.tags is not None:
        post.tags_json = serialize_tags(payload.tags)
    if payload.reading_time_minutes is not None:
        post.reading_time_minutes = payload.reading_time_minutes

    if payload.is_published is not None:
        if payload.is_published and not post.is_published:
            post.published_at = datetime.utcnow()
        post.is_published = payload.is_published

    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return format_blog_detail(post)


@router.post("/admin/{post_id}/toggle-publish")
def admin_toggle_publish(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    post = db.query(BlogPost).filter(BlogPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found.")

    post.is_published = not post.is_published
    if post.is_published and not post.published_at:
        post.published_at = datetime.utcnow()
    post.updated_at = datetime.utcnow()
    db.commit()
    return {
        "id": post.id,
        "is_published": post.is_published,
        "published_at": post.published_at,
    }


@router.delete("/admin/{post_id}")
def admin_delete_blog(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    post = db.query(BlogPost).filter(BlogPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found.")

    db.delete(post)
    db.commit()
    return {"message": "Blog post deleted successfully."}
