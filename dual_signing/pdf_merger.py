import logging
import os
import tempfile
from typing import Optional
import requests
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

import os

class PDFMerger:
    def __init__(self, output_storage_path: str = None):
        """
        Initialize PDF merger

        Args:
            output_storage_path: Path where merged PDFs will be stored
        """
        default_path = "/Users/rishabhmishra/Desktop/UPIp2p/uploaded_docs/merged_pdfs"
        self.output_storage_path = output_storage_path or default_path
        self._ensure_output_directory()

    def _ensure_output_directory(self):
        """Ensure the output directory exists"""
        os.makedirs(self.output_storage_path, exist_ok=True)

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
            borrower_signed_url: URL or local path of borrower-signed document
            lender_signed_url: URL or local path of lender-signed document
            loan_id: Loan ID for naming the merged file
            
        Returns:
            Path to merged document, or None if merge failed
        """
        try:
            borrower_pdf = self._get_pdf_path(borrower_signed_url)
            lender_pdf = self._get_pdf_path(lender_signed_url)
            
            if not borrower_pdf or not lender_pdf:
                logger.error("Failed to get one or both PDFs for merging")
                return None
            
            merged_pdf_path = self._merge_pdfs(borrower_pdf, lender_pdf, loan_id)
            
            # Only cleanup temp files if they were downloaded (not local files)
            temp_files_to_cleanup = []
            if self._is_url(borrower_signed_url):
                temp_files_to_cleanup.append(borrower_pdf)
            if self._is_url(lender_signed_url):
                temp_files_to_cleanup.append(lender_pdf)
            
            self._cleanup_temp_files(temp_files_to_cleanup)
            return merged_pdf_path
            
        except Exception as e:
            logger.error(f"Error merging PDFs for loan {loan_id}: {str(e)}")
            return None
    
    def _is_url(self, path: str) -> bool:
        """Check if the path is a URL"""
        return path.startswith("http://") or path.startswith("https://")
    
    def _get_pdf_path(self, pdf_source: str) -> Optional[str]:
        """
        Get PDF path - either download from URL or validate local path
        
        Args:
            pdf_source: URL or local file path
            
        Returns:
            Path to PDF file, or None if failed
        """
        if self._is_url(pdf_source):
            return self._download_pdf(pdf_source)
        else:
            return self._get_local_pdf(pdf_source)
    
    def _get_local_pdf(self, pdf_path: str) -> Optional[str]:
        """Validate and return local PDF path"""
        try:
            if os.path.exists(pdf_path) and pdf_path.lower().endswith('.pdf'):
                logger.info(f"Using local PDF file: {pdf_path}")
                return pdf_path
            else:
                logger.error(f"Local PDF file not found or invalid: {pdf_path}")
                return None
        except Exception as e:
            logger.error(f"Error accessing local PDF {pdf_path}: {str(e)}")
            return None
    
    def _download_pdf(self, pdf_url: str) -> Optional[str]:
        """Download PDF from URL to temporary file"""
        try:
            logger.info(f"Downloading PDF from URL: {pdf_url}")
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(response.content)
            temp_file.close()
            logger.info(f"Downloaded PDF to temp file: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Failed to download PDF from {pdf_url}: {str(e)}")
            return None
    
    def _merge_pdfs(self, borrower_pdf_path: str, lender_pdf_path: str, loan_id: str) -> str:
        """Merge two PDFs into one"""
        try:
            logger.info(f"Merging PDFs: {borrower_pdf_path} + {lender_pdf_path}")
            
            borrower_reader = PdfReader(borrower_pdf_path)
            lender_reader = PdfReader(lender_pdf_path)
            writer = PdfWriter()

            # Add all pages from borrower document
            for page in borrower_reader.pages:
                writer.add_page(page)
            
            # Add all pages from lender document
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
                    logger.debug(f"Cleaned up temp file: {temp_file}")
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