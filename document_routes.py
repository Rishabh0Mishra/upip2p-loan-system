import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from dependencies import get_db, get_current_user
import models, schemas
from document_service import DocumentService
from fastapi.responses import FileResponse

router = APIRouter(prefix="/documents", tags=["documents"])
doc_service = DocumentService()

ALLOWED_DOCUMENT_TYPES = {"income_proof", "identity", "agreement"}

@router.get("/download/{document_id}")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    doc = db.query(models.LoanDocument).filter(models.LoanDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Authorization check: only uploader, lender or borrower of the loan can access
    if current_user.id not in [doc.uploaded_by, doc.loan.lender_id, doc.loan.borrower_id]:
        raise HTTPException(status_code=403, detail="Not authorized to access this document")
    
    file_path = doc.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(path=file_path, filename=doc.filename, media_type="application/octet-stream")


@router.post("/upload/{loan_id}")
async def upload_document(
    loan_id: int,
    document_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Validate loan exists
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    # Validate document_type
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid document_type. Allowed types: {ALLOWED_DOCUMENT_TYPES}")

    # Read file content
    content = await file.read()

    # Save file locally (assuming doc_service.save_document saves locally and returns path)
    saved_path = doc_service.save_document(content, file.filename, loan_id, document_type)

    # Create LoanDocument record
    loan_doc = models.LoanDocument(
        loan_id=loan_id,
        document_type=document_type,
        filename=file.filename,
        file_path=saved_path,
        uploaded_by=current_user.id
    )
    try:
        db.add(loan_doc)
        db.commit()
        db.refresh(loan_doc)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}")

    return {"message": "Document uploaded", "document_id": loan_doc.id}
