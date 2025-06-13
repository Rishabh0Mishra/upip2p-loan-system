import os
import uuid
from typing import Optional

UPLOAD_DIR = "uploaded_docs"

class DocumentService:
    def __init__(self):
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)

    def save_document(
        self,
        file_content: bytes,
        filename: str,
        loan_id: int,
        document_type: str
    ) -> str:
        ext = filename.split('.')[-1]
        unique_filename = f"{loan_id}_{document_type}_{uuid.uuid4()}.{ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)

        with open(file_path, "wb") as f:
            f.write(file_content)

        return file_path

    def get_document_path(self, file_path: str) -> Optional[str]:
        if os.path.exists(file_path):
            return file_path
        return None
