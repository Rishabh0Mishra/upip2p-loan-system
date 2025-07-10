import logging
import os
import tempfile
from typing import Optional
import requests
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime

logger = logging.getLogger(__name__)

class PDFMerger:
    def __init__(self, output_storage_path: str = None):
        """
        Initialize PDF merger
        """
        default_path = "/Users/rishabhmishra/Desktop/UPIp2p/uploaded_docs/merged_pdfs"
        self.output_storage_path = output_storage_path or default_path
        self._ensure_output_directory()

    def _ensure_output_directory(self):
        """Ensure the output directory exists"""
        try:
            os.makedirs(self.output_storage_path, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create output directory: {e}")
            self.output_storage_path = tempfile.gettempdir()

    def merge_signed_documents(self, borrower_signed_url: str, lender_signed_url: str, loan_id: str) -> Optional[str]:
        """
        Merge borrower and lender signed documents into a single PDF
        """
        try:
            borrower_pdf = self._get_pdf_path(borrower_signed_url)
            lender_pdf = self._get_pdf_path(lender_signed_url)

            if not borrower_pdf or not lender_pdf:
                logger.error("Failed to get one or both PDFs for merging")
                return None

            merged_pdf_path = self._merge_pdfs(borrower_pdf, lender_pdf, loan_id)

            self._cleanup_temp_files([
                borrower_pdf if self._is_url(borrower_signed_url) else None,
                lender_pdf if self._is_url(lender_signed_url) else None
            ])

            return merged_pdf_path

        except Exception as e:
            logger.error(f"Error merging PDFs for loan {loan_id}: {str(e)}")
            return None

    def _is_url(self, path: str) -> bool:
        return path.startswith("http://") or path.startswith("https://")

    def _get_pdf_path(self, source: str) -> Optional[str]:
        return self._download_pdf(source) if self._is_url(source) else self._get_local_pdf(source)

    def _get_local_pdf(self, path: str) -> Optional[str]:
        try:
            if os.path.exists(path) and path.lower().endswith('.pdf'):
                logger.info(f"Using local PDF file: {path}")
                return path
            logger.error(f"Local PDF not found or invalid: {path}")
            return None
        except Exception as e:
            logger.error(f"Error accessing local PDF {path}: {e}")
            return None

    def _download_pdf(self, url: str) -> Optional[str]:
        try:
            logger.info(f"Downloading PDF from URL: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.write(response.content)
            temp_file.close()
            logger.info(f"Downloaded PDF to: {temp_file.name}")
            return temp_file.name
        except Exception as e:
            logger.error(f"Failed to download PDF from {url}: {e}")
            return None

    def _merge_pdfs(self, path1: str, path2: str, loan_id: str) -> str:
        try:
            writer = PdfWriter()
            for path in [path1, path2]:
                reader = PdfReader(path)
                for page in reader.pages:
                    writer.add_page(page)

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"merged_loan_{loan_id}_{timestamp}.pdf"
            output_path = os.path.join(self.output_storage_path, filename)

            with open(output_path, 'wb') as out_file:
                writer.write(out_file)

            logger.info(f"Merged PDF saved: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error merging PDFs: {e}")
            raise

    def _cleanup_temp_files(self, paths: list):
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    logger.debug(f"Cleaned up temp file: {path}")
            except Exception as e:
                logger.warning(f"Failed to clean temp file {path}: {e}")

    def add_signature_page(self, pdf_path: str, signature_info: dict) -> Optional[str]:
        """
        Stub: Add a signature page to the PDF (optional future)
        """
        try:
            logger.info(f"Adding signature page to {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"Error adding signature page: {e}")
            return None

class MockPDFMerger(PDFMerger):
    def merge_signed_documents(self, borrower_signed_url: str, lender_signed_url: str, loan_id: str) -> Optional[str]:
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            mock_url = f"https://mock-storage.com/merged_loan_{loan_id}_{timestamp}.pdf"
            logger.info(f"[MOCK] Merged PDF: {mock_url}")
            return mock_url
        except Exception as e:
            logger.error(f"[MOCK] Merge failed: {e}")
            return None
