from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extraction import UnsupportedDocumentError, extract_text
from app.ai.solicitation_analyzer import ANALYSIS_FIELDS, AiNotConfiguredError, SolicitationAnalyzer
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.document import AiSolicitationAnalysis, OpportunityDocument
from app.models.enums import ActivityType, DocumentCategory
from app.models.opportunity import Opportunity
from app.models.user import User
from app.schemas.document import AiSolicitationAnalysisRead, NotConfiguredResponse, OpportunityDocumentRead
from app.services.activities import log_activity
from app.services.storage import get_storage_backend, guess_content_type

router = APIRouter(tags=["documents"])
analyzer = SolicitationAnalyzer()


@router.get("/api/opportunities/{opportunity_id}/documents", response_model=list[OpportunityDocumentRead])
def list_documents(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(
        select(OpportunityDocument)
        .where(OpportunityDocument.opportunity_id == opportunity_id)
        .order_by(OpportunityDocument.created_at.desc())
    ).scalars().all()


@router.post(
    "/api/opportunities/{opportunity_id}/documents",
    response_model=OpportunityDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    opportunity_id: UUID,
    file: UploadFile = File(...),
    category: DocumentCategory = Form(DocumentCategory.OTHER),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")

    storage = get_storage_backend()
    try:
        storage_path, size = storage.save(file, subdir=str(opportunity_id))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    document = OpportunityDocument(
        opportunity_id=opportunity_id,
        category=category,
        original_filename=file.filename or "upload",
        storage_path=storage_path,
        content_type=file.content_type or guess_content_type(file.filename or ""),
        size_bytes=size,
        uploaded_by_id=current_user.id,
        notes=notes,
    )
    db.add(document)
    db.flush()
    log_activity(
        db, opportunity_id, ActivityType.DOCUMENT_UPLOADED,
        f"{current_user.full_name} uploaded {document.original_filename}", actor_id=current_user.id,
    )
    db.commit()
    db.refresh(document)
    return document


@router.get("/api/documents/{document_id}/download")
def download_document(document_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    document = db.get(OpportunityDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    storage = get_storage_backend()
    path = storage.read_path(document.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file is missing")
    return FileResponse(path, filename=document.original_filename, media_type=document.content_type)


@router.post(
    "/api/documents/{document_id}/analyze",
    response_model=AiSolicitationAnalysisRead,
    responses={503: {"model": NotConfiguredResponse}},
)
def analyze_document(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.get(OpportunityDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    if not analyzer.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI solicitation analysis is not configured. Add ANTHROPIC_API_KEY to the backend "
            "environment to enable this feature (see backend/.env.example).",
        )

    storage = get_storage_backend()
    path = storage.read_path(document.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file is missing")

    try:
        text = extract_text(path, document.content_type)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    try:
        result = analyzer.analyze(text)
    except AiNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    analysis = AiSolicitationAnalysis(
        document_id=document.id,
        opportunity_id=document.opportunity_id,
        model_used=result.pop("_model", "unknown"),
        raw_model_response=result,
        **{k: v for k, v in result.items() if k in ANALYSIS_FIELDS},
    )
    db.add(analysis)
    log_activity(
        db, document.opportunity_id, ActivityType.AI_ANALYSIS_COMPLETED,
        f"AI analysis completed for {document.original_filename}", actor_id=current_user.id,
    )
    db.commit()
    db.refresh(analysis)
    return analysis


@router.get("/api/documents/{document_id}/analysis", response_model=AiSolicitationAnalysisRead)
def get_analysis(document_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    analysis = db.execute(
        select(AiSolicitationAnalysis)
        .where(AiSolicitationAnalysis.document_id == document_id)
        .order_by(AiSolicitationAnalysis.analyzed_at.desc())
    ).scalars().first()
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No AI analysis has been run for this document yet")
    return analysis
