import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Resume, User
from ..schemas import ResumeCreate, ResumeUpdate, ResumeSummary, ResumeDetail
from ..auth import get_current_user

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])


def serialize_json_field(val) -> str:
    """Helper to ensure a field is stored as a valid JSON string."""
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, str):
        return val
    return "{}"


def parse_json_field(val, default):
    """Helper to safely parse JSON text into Python object."""
    if not val:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


@router.get("", response_model=List[ResumeSummary])
def list_resumes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all resumes belonging strictly to the currently authenticated user."""
    resumes = (
        db.query(Resume)
        .filter(Resume.user_id == current_user.id)
        .order_by(Resume.updated_at.desc())
        .all()
    )

    result = []
    for r in resumes:
        sec_list = parse_json_field(r.sections_json, [])
        sec_count = len(sec_list) if isinstance(sec_list, list) else 0
        result.append(
            ResumeSummary(
                id=r.id,
                user_id=r.user_id,
                name=r.name,
                created_at=r.created_at,
                updated_at=r.updated_at,
                section_count=sec_count,
            )
        )
    return result


@router.post("", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def create_resume(
    payload: ResumeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a new resume for the currently authenticated user."""
    new_resume = Resume(
        user_id=current_user.id,
        name=payload.name or "Untitled Resume",
        header_json=serialize_json_field(payload.header_json),
        settings_json=serialize_json_field(payload.settings_json),
        sections_json=serialize_json_field(payload.sections_json),
    )
    db.add(new_resume)
    db.commit()
    db.refresh(new_resume)

    return ResumeDetail(
        id=new_resume.id,
        user_id=new_resume.user_id,
        name=new_resume.name,
        header_json=parse_json_field(new_resume.header_json, {}),
        settings_json=parse_json_field(new_resume.settings_json, {}),
        sections_json=parse_json_field(new_resume.sections_json, []),
        created_at=new_resume.created_at,
        updated_at=new_resume.updated_at,
    )


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieves a single resume by ID, ensuring user ownership."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    return ResumeDetail(
        id=resume.id,
        user_id=resume.user_id,
        name=resume.name,
        header_json=parse_json_field(resume.header_json, {}),
        settings_json=parse_json_field(resume.settings_json, {}),
        sections_json=parse_json_field(resume.sections_json, []),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


@router.put("/{resume_id}", response_model=ResumeDetail)
def update_resume(
    resume_id: int,
    payload: ResumeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates an existing resume, ensuring user ownership."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    if payload.name:
        resume.name = payload.name
    if payload.header_json is not None:
        resume.header_json = serialize_json_field(payload.header_json)
    if payload.settings_json is not None:
        resume.settings_json = serialize_json_field(payload.settings_json)
    if payload.sections_json is not None:
        resume.sections_json = serialize_json_field(payload.sections_json)

    db.commit()
    db.refresh(resume)

    return ResumeDetail(
        id=resume.id,
        user_id=resume.user_id,
        name=resume.name,
        header_json=parse_json_field(resume.header_json, {}),
        settings_json=parse_json_field(resume.settings_json, {}),
        sections_json=parse_json_field(resume.sections_json, []),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


@router.delete("/{resume_id}", status_code=status.HTTP_200_OK)
def delete_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes a resume by ID, ensuring user ownership."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    db.delete(resume)
    db.commit()
    return {"message": "Resume deleted successfully", "id": resume_id}


@router.post("/parse-pdf")
async def parse_pdf_resume(
    file: UploadFile = File(...),
    create_resume: bool = Form(False),
    resume_name: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Extracts text from an uploaded resume PDF using PyMuPDF and uses
    Google GenAI (Gemini) to parse it into structured sections and header.
    """
    from ..ai_extractor import extract_text_from_pdf, parse_resume_with_gemini
    import traceback

    print(f"[parse-pdf] Received uploaded file: '{file.filename}', user: {current_user.email}")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for import.")

    try:
        content = await file.read()
        print(f"[parse-pdf] Read {len(content)} bytes from PDF. Extracting text...")
        extracted_text = extract_text_from_pdf(content)
        print(f"[parse-pdf] Extracted {len(extracted_text)} characters of text from PDF.")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Failed to extract text from PDF: {str(e)}")

    try:
        print("[parse-pdf] Sending extracted text to Gemini AI...")
        parsed_data = parse_resume_with_gemini(extracted_text)
        print("[parse-pdf] Gemini AI parsing completed successfully.")
    except ValueError as ve:
        print(f"[parse-pdf] Configuration/Validation Error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ge:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Gemini AI extraction failed: {str(ge)}")

    if create_resume:
        name = resume_name or parsed_data.get("header", {}).get("name") or "Imported Resume"
        default_settings = {
            "marginTop": 15,
            "marginBottom": 15,
            "marginLeft": 15,
            "marginRight": 15,
            "bodyFont": "Georgia, serif",
            "bodyFontSize": 8.5,
            "headingColor": "#111827",
            "sectionSpacing": 1,
            "accentColor": "#1a56db",
            "lineHeight": 1.2,
        }
        new_resume = Resume(
            user_id=current_user.id,
            name=f"{name} (Imported)",
            header_json=serialize_json_field(parsed_data.get("header", {})),
            settings_json=serialize_json_field(default_settings),
            sections_json=serialize_json_field(parsed_data.get("sections", [])),
        )
        db.add(new_resume)
        db.commit()
        db.refresh(new_resume)

        return {
            "success": True,
            "created_resume_id": new_resume.id,
            "header": parsed_data.get("header", {}),
            "sections": parsed_data.get("sections", []),
            "resume": ResumeDetail(
                id=new_resume.id,
                user_id=new_resume.user_id,
                name=new_resume.name,
                header_json=parse_json_field(new_resume.header_json, {}),
                settings_json=parse_json_field(new_resume.settings_json, {}),
                sections_json=parse_json_field(new_resume.sections_json, []),
                created_at=new_resume.created_at,
                updated_at=new_resume.updated_at,
            )
        }

    return {
        "success": True,
        "header": parsed_data.get("header", {}),
        "sections": parsed_data.get("sections", []),
    }


# ─── Legacy Backward Compatibility Router (/api/resume/*) ──────────────────────
legacy_router = APIRouter(prefix="/api/resume", tags=["Legacy"])

@legacy_router.get("/list")
def legacy_list_resumes(db: Session = Depends(get_db)):
    """Provides backward-compatibility for cached client tabs calling /api/resume/list."""
    resumes = db.query(Resume).order_by(Resume.updated_at.desc()).limit(20).all()
    out = []
    for r in resumes:
        out.append({
            "id": r.id,
            "name": r.name,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "headerJson": parse_json_field(r.header_json, {}),
            "settingsJson": parse_json_field(r.settings_json, {}),
            "sectionsJson": parse_json_field(r.sections_json, []),
        })
    return {"resumes": out}

