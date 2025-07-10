import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

# Create uploads directory if it doesn't exist
UPLOAD_DIR = "uploaded_docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/upload", tags=["File Uploads"])

@router.post("/document")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        file_url = f"/uploaded_docs/{filename}"
        return JSONResponse(status_code=200, content={"file_url": file_url})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
