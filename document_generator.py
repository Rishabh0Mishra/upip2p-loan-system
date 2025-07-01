import os
import tempfile
from typing import Dict, Any, Optional
from jinja2 import Template
import pdfkit
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DocumentGenerator:
    def __init__(self, template_path: str = None, output_storage_path: str = None):
        """
        Initialize document generator

        Args:
            template_path: Path to HTML template file
            output_storage_path: Path where generated documents will be stored
        """
        self.template_path = template_path or os.path.join("templates", "loan_agreement_template.html")
        default_path = "/Users/rishabhmishra/Desktop/UPIp2p/uploaded_docs/generated_docs"
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

    def generate_loan_agreement(self, loan_data: Dict[str, Any]) -> Optional[str]:
        """
        Generate loan agreement PDF from template

        Args:
            loan_data: Dictionary containing loan information

        Returns:
            Path to generated PDF file, or None if generation failed
        """
        try:
            html_content = self._render_template(loan_data)
            if not html_content:
                return None
            pdf_path = self._generate_pdf(html_content, loan_data.get('loan_id', 'unknown'))
            return pdf_path
        except Exception as e:
            logger.error(f"Error generating loan agreement: {str(e)}")
            return None

    def _render_template(self, loan_data: Dict[str, Any]) -> Optional[str]:
        """Render HTML template with loan data"""
        try:
            with open(self.template_path, 'r', encoding='utf-8') as file:
                template_content = file.read()

            template = Template(template_content)
            template_data = self._prepare_template_data(loan_data)
            rendered_html = template.render(loan=template_data)
            return rendered_html
        except Exception as e:
            logger.error(f"Error rendering template: {str(e)}")
            return None

    def _prepare_template_data(self, loan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare and validate data for template rendering"""
        principal = float(loan_data.get('principal_amount', 0))
        rate = float(loan_data.get('interest_rate', 0)) / 100 / 12
        num_payments = int(loan_data.get('number_of_payments', 12))

        if principal > 0 and rate > 0 and num_payments > 0:
            emi = principal * rate * (1 + rate) ** num_payments / ((1 + rate) ** num_payments - 1)
            total_amount = emi * num_payments
        else:
            emi = 0
            total_amount = principal

        return {
            'loan_id': loan_data.get('loan_id', 'AUTO-GENERATED'),
            'lender_name': loan_data.get('lender_name', ''),
            'lender_email': loan_data.get('lender_email', ''),
            'lender_phone': loan_data.get('lender_phone', ''),
            'borrower_name': loan_data.get('borrower_name', ''),
            'borrower_email': loan_data.get('borrower_email', ''),
            'borrower_phone': loan_data.get('borrower_phone', ''),
            'amount': f"{principal:,.2f}",
            'interest_rate': loan_data.get('interest_rate', 0),
            'num_payments': num_payments,
            'start_date': loan_data.get('start_date', datetime.now().strftime('%Y-%m-%d')),
            'emi_amount': f"{emi:,.2f}",
            'total_amount': f"{total_amount:,.2f}",
            'generated_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'description': loan_data.get('description', 'No description provided')
        }

    def _generate_pdf(self, html_content: str, loan_id: str) -> str:
        """Generate PDF from HTML content"""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"loan_agreement_{loan_id}_{timestamp}.pdf"
            pdf_path = os.path.join(self.output_storage_path, pdf_filename)

            options = {
                'page-size': 'A4',
                'margin-top': '0.75in',
                'margin-right': '0.75in',
                'margin-bottom': '0.75in',
                'margin-left': '0.75in',
                'encoding': 'UTF-8',
                'no-outline': None,
                'enable-local-file-access': None
            }

            pdfkit.from_string(html_content, pdf_path, options=options)

            logger.info(f"Generated PDF: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error generating PDF: {str(e)}")
            raise


class MockDocumentGenerator(DocumentGenerator):
    """Mock document generator for testing"""

    def generate_loan_agreement(self, loan_data: Dict[str, Any]) -> Optional[str]:
        """Mock implementation that returns a fake document URL"""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            loan_id = loan_data.get('loan_id', 'unknown')
            mock_url = f"https://mock-storage.com/loan_agreement_{loan_id}_{timestamp}.pdf"
            logger.info(f"Mock loan agreement generated: {mock_url}")
            return mock_url
        except Exception as e:
            logger.error(f"Mock document generation failed: {str(e)}")
            return None
