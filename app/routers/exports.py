import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ExportedResume, Resume, User
from ..schemas import ExportPDFRequest, ExportImageRequest, ExportHTMLRequest, ExportDocxRequest, ExportedResumeOut
from ..auth import get_current_user, get_user_from_token, security
from ..export_service import generate_pdf_from_html, generate_image_from_html, generate_html_file, generate_docx_from_resume_data

router = APIRouter(prefix="/api/exports", tags=["Exports"])


@router.post("/pdf", response_model=ExportedResumeOut, status_code=status.HTTP_201_CREATED)
async def export_pdf(
    payload: ExportPDFRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Renders high-fidelity PDF from HTML, tracks it in the database for the user,
    and returns metadata for downloading.
    """
    if not payload.html or not payload.html.strip():
        raise HTTPException(status_code=400, detail="HTML content is required for PDF generation")

    try:
        file_path, file_name, file_size = await generate_pdf_from_html(
            html_content=payload.html,
            base_filename=payload.name or "resume"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    target_job = None
    target_comp = None
    tmpl_name = None
    if payload.resume_id:
        r = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
        if r:
            target_job = r.target_job_title
            target_comp = r.target_company
            # Read font/style name from settings
            try:
                import json
                s = json.loads(r.settings_json) if isinstance(r.settings_json, str) else r.settings_json
                tmpl_name = s.get("bodyFont", "Standard").split(",")[0]
            except Exception:
                tmpl_name = "Custom"

    export_record = ExportedResume(
        user_id=current_user.id,
        resume_id=payload.resume_id,
        resume_name=payload.name or "Resume",
        file_type="pdf",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        target_job_title=target_job,
        target_company=target_comp,
        template_name=tmpl_name,
    )
    db.add(export_record)
    db.commit()
    db.refresh(export_record)

    return export_record


@router.post("/image", response_model=ExportedResumeOut, status_code=status.HTTP_201_CREATED)
async def export_image(
    payload: ExportImageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Renders high-resolution PNG image (Retina quality) from HTML and tracks it in the database.
    """
    if not payload.html or not payload.html.strip():
        raise HTTPException(status_code=400, detail="HTML content is required for image generation")

    try:
        file_path, file_name, file_size = await generate_image_from_html(
            html_content=payload.html,
            base_filename=payload.name or "resume"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

    target_job = None
    target_comp = None
    tmpl_name = None
    if payload.resume_id:
        r = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
        if r:
            target_job = r.target_job_title
            target_comp = r.target_company
            try:
                import json
                s = json.loads(r.settings_json) if isinstance(r.settings_json, str) else r.settings_json
                tmpl_name = s.get("bodyFont", "Standard").split(",")[0]
            except Exception:
                tmpl_name = "Custom"

    export_record = ExportedResume(
        user_id=current_user.id,
        resume_id=payload.resume_id,
        resume_name=payload.name or "Resume",
        file_type="png",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        target_job_title=target_job,
        target_company=target_comp,
        template_name=tmpl_name,
    )
    db.add(export_record)
    db.commit()
    db.refresh(export_record)

    return export_record


@router.post("/html", response_model=ExportedResumeOut, status_code=status.HTTP_201_CREATED)
async def export_html(
    payload: ExportHTMLRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Saves standalone HTML document and tracks it in the database.
    """
    if not payload.html or not payload.html.strip():
        raise HTTPException(status_code=400, detail="HTML content is required")

    try:
        file_path, file_name, file_size = await generate_html_file(
            html_content=payload.html,
            base_filename=payload.name or "resume"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HTML export failed: {str(e)}")

    target_job = None
    target_comp = None
    tmpl_name = None
    if payload.resume_id:
        r = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
        if r:
            target_job = r.target_job_title
            target_comp = r.target_company
            try:
                import json
                s = json.loads(r.settings_json) if isinstance(r.settings_json, str) else r.settings_json
                tmpl_name = s.get("bodyFont", "Standard").split(",")[0]
            except Exception:
                tmpl_name = "Custom"

    export_record = ExportedResume(
        user_id=current_user.id,
        resume_id=payload.resume_id,
        resume_name=payload.name or "Resume",
        file_type="html",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        target_job_title=target_job,
        target_company=target_comp,
        template_name=tmpl_name,
    )
    db.add(export_record)
    db.commit()
    db.refresh(export_record)

    return export_record


@router.post("/docx", response_model=ExportedResumeOut, status_code=status.HTTP_201_CREATED)
def export_docx(
    payload: ExportDocxRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generates a formatted Word (.docx) document from resume data, tracks it in the database,
    and returns metadata for downloading.
    """
    try:
        file_path, file_name, file_size = generate_docx_from_resume_data(
            name=payload.name or "Resume",
            header=payload.header_json or {},
            settings=payload.settings_json or {},
            sections=payload.sections_json or []
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Word document generation failed: {str(e)}")

    export_record = ExportedResume(
        user_id=current_user.id,
        resume_id=payload.resume_id,
        resume_name=payload.name or "Resume",
        file_type="docx",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
    )
    db.add(export_record)
    db.commit()
    db.refresh(export_record)

    return export_record


@router.get("", response_model=List[ExportedResumeOut])
def list_exports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all exported files created by the logged-in user."""
    exports = (
        db.query(ExportedResume)
        .filter(ExportedResume.user_id == current_user.id)
        .order_by(ExportedResume.created_at.desc())
        .all()
    )
    return exports


@router.get("/download/{export_id}")
def download_export(
    export_id: int,
    token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
):
    """Downloads an exported file, ensuring the file belongs to the authenticated user."""
    user = None
    if credentials and credentials.credentials:
        user = get_user_from_token(credentials.credentials, db)
    elif token:
        user = get_user_from_token(token, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    export = (
        db.query(ExportedResume)
        .filter(ExportedResume.id == export_id, ExportedResume.user_id == user.id)
        .first()
    )
    if not export or not os.path.exists(export.file_path):
        raise HTTPException(status_code=404, detail="Exported file not found")

    if export.file_type == "pdf":
        media_type = "application/pdf"
    elif export.file_type == "png":
        media_type = "image/png"
    elif export.file_type == "html":
        media_type = "text/html; charset=utf-8"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return FileResponse(
        path=export.file_path,
        filename=export.file_name,
        media_type=media_type,
    )


@router.delete("/{export_id}", status_code=status.HTTP_200_OK)
def delete_export(
    export_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes an exported file entry and cleans up the file on disk."""
    export = (
        db.query(ExportedResume)
        .filter(ExportedResume.id == export_id, ExportedResume.user_id == current_user.id)
        .first()
    )
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if os.path.exists(export.file_path):
        try:
            os.remove(export.file_path)
        except Exception:
            pass

    db.delete(export)
    db.commit()
    return {"message": "Export deleted successfully", "id": export_id}
