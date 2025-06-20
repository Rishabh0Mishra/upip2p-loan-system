import logging
import os
import tempfile
from typing import Optional
import requests
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class PDFMerger:
    def __init__(self, output_storage_path: str = None):
        """
        Initialize PDF merger
        
        Args:
            output_storage_path: Path where merged PDFs will be stored
        """
        self.output_storage_path = output_storage_path or "/tmp/merged_pdfs"
        self._ensure_output_directory()
    
    def _ensure_output_directory(self):
        """Ensure output directory exists"""
        try:
            os.makedirs(self.output_storage_path, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create output directory: {e}")
            self.output_storage_path = tempfile.gettempdir()
    
    def merge_signed_documents(self, borrower_signed_url: str, lender_signed_url: str, 
                              loan_id: str) -> Optional[str]:
        """
        Merge borrower and lender signed documents into a single PDF
        
        Args:
            borrower_signed_url: URL of borrower-signed document
            lender_signed_url: URL of lender-signed document
            loan_id: Loan ID for naming the merged file
            
        Returns:
            Path to merged document, or None if merge failed
        """
        try:
            borrower_pdf = self._download_pdf(borrower_signed_url)
            lender_pdf = self._download_pdf(lender_signed_url)
            
            if not borrower_pdf or not lender_pdf:
                logger.error("Failed to download one or both PDFs for merging")
                return None
            
            merged_pdf_path = self._merge_pdfs(borrower_pdf, lender_pdf, loan_id)
            self._cleanup_temp_files([borrower_pdf, lender_pdf])
            return merged_pdf_path
            
        except Exception as e:
            logger.error(f"Error merging PDFs for loan {loan_id}: {str(e)}")
            return None
    
    def _download_pdf(self, pdf_url: str) -> Optional[str]:
        """Download PDF from URL to temporary file"""
        try:
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(response.content)
            temp_file.close()
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Failed to download PDF from {pdf_url}: {str(e)}")
            return None
    
    def _merge_pdfs(self, borrower_pdf_path: str, lender_pdf_path: str, loan_id: str) -> str:
        """Merge two PDFs into one"""
        try:
            borrower_reader = PdfReader(borrower_pdf_path)
            lender_reader = PdfReader(lender_pdf_path)
            writer = PdfWriter()

            for page in borrower_reader.pages:
                writer.add_page(page)
            for page in lender_reader.pages:
                writer.add_page(page)
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_filename = f"merged_loan_{loan_id}_{timestamp}.pdf"
            output_path = os.path.join(self.output_storage_path, output_filename)

            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
            
            logger.info(f"Successfully merged PDFs for loan {loan_id}: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error merging PDF files: {str(e)}")
            raise
    
    def _cleanup_temp_files(self, temp_files: list):
        """Clean up temporary files"""
        for temp_file in temp_files:
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
    
    def add_signature_page(self, pdf_path: str, signature_info: dict) -> Optional[str]:
        """
        Add a signature summary page to the PDF
        
        Args:
            pdf_path: Path to the PDF file
            signature_info: Dictionary containing signature details
            
        Returns:
            Path to PDF with signature page added
        """
        try:
            logger.info(f"Adding signature page to {pdf_path}")
            # Future: Use reportlab to generate a summary page and merge it
            return pdf_path
        except Exception as e:
            logger.error(f"Error adding signature page: {str(e)}")
            return None

class MockPDFMerger(PDFMerger):
    """Mock PDF merger for testing"""
    
    def merge_signed_documents(self, borrower_signed_url: str, lender_signed_url: str, 
                              loan_id: str) -> Optional[str]:
        """Mock implementation that returns a fake merged document URL"""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            mock_url = f"https://mock-storage.com/merged_loan_{loan_id}_{timestamp}.pdf"
            logger.info(f"Mock merged PDF created: {mock_url}")
            return mock_url
        except Exception as e:
            logger.error(f"Mock PDF merge failed: {str(e)}")
            return None
