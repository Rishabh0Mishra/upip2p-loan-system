import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List
from models import Loan
from .dual_signing_models import (
    DualSigningRequest, SigningRequest, DualSigningStatus, 
    SigningRequestStatus, SignerRole, SigningCallbackData
)
from .dual_signing_store import dual_signing_store
from .nsdl_client import NSDLClient
from .pdf_merger import PDFMerger
from document_generator import DocumentGenerator


logger = logging.getLogger(__name__)


class DualSigningService:
    def __init__(self, nsdl_client: NSDLClient, pdf_merger: PDFMerger = None, 
        document_generator: DocumentGenerator = None):
        self.nsdl_client = nsdl_client
        self.pdf_merger = pdf_merger or PDFMerger()
        self.document_generator = document_generator or DocumentGenerator()
        self.store = dual_signing_store

    def create_and_initiate_dual_signing(self, loan_data: Dict[str, Any], 
                                        callback_base_url: str = "http://localhost:8000") -> Tuple[bool, str, Optional[str]]:
        """
        Create loan agreement document and initiate dual signing process
        
        Args:
            loan_data: Complete loan information
            callback_base_url: Base URL for callbacks
            
        Returns:
            Tuple of (success, message, borrower_signing_url)
        """
        try:
            # Step 1: Generate loan agreement PDF
            logger.info(f"Generating loan agreement for loan {loan_data.get('loan_id')}")
            document_url = self.document_generator.generate_loan_agreement(loan_data)
            
            if not document_url:
                return False, "Failed to generate loan agreement document", None
            
            # Step 2: Initiate dual signing with generated document
            return self.initiate_dual_signing(
                loan_id=loan_data['loan_id'],
                borrower_name=loan_data['borrower_name'],
                borrower_email=loan_data['borrower_email'],
                borrower_phone=loan_data['borrower_phone'],
                lender_name=loan_data['lender_name'],
                lender_email=loan_data['lender_email'],
                lender_phone=loan_data['lender_phone'],
                document_url=document_url,
                callback_base_url=callback_base_url
            )
            
        except Exception as e:
            logger.error(f"Error in create_and_initiate_dual_signing: {str(e)}")
            return False, f"Failed to create and initiate signing: {str(e)}", None

    def initiate_dual_signing(self, loan_id: str, borrower_name: str, borrower_email: str,
                             borrower_phone: str, lender_name: str, lender_email: str,
                             lender_phone: str, document_url: str,
                             callback_base_url: str = "http://localhost:8000") -> Tuple[bool, str, Optional[str]]:
        """
        Initiate dual signing process for a loan agreement
        
        Returns:
            Tuple of (success, message, borrower_signing_url)
        """
        try:
            # Check if dual signing already exists for this loan
            existing_request = self.store.get_dual_request(loan_id)
            if existing_request:
                if existing_request.status == DualSigningStatus.FULLY_SIGNED:
                    return False, "Loan agreement already fully signed", None
                elif existing_request.status in [DualSigningStatus.PENDING_BORROWER, DualSigningStatus.BORROWER_SIGNED]:
                    return False, "Dual signing already in progress", None

            # Create dual signing request
            dual_request = DualSigningRequest(
                loan_id=loan_id,
                borrower_name=borrower_name,
                borrower_email=borrower_email,
                borrower_phone=borrower_phone,
                lender_name=lender_name,
                lender_email=lender_email,
                lender_phone=lender_phone,
                document_url=document_url,
                status=DualSigningStatus.PENDING_BORROWER
            )
            
            self.store.create_dual_request(dual_request)

            # Initiate borrower signing first
            success, message, signing_url = self._initiate_borrower_signing(
                dual_request, callback_base_url
            )
            
            if success:
                return True, "Dual signing initiated successfully", signing_url
            else:
                self.store.update_dual_request(
                    loan_id, 
                    status=DualSigningStatus.FAILED, 
                    error_message=message
                )
                return False, message, None

        except Exception as e:
            logger.error(f"Error initiating dual signing for loan {loan_id}: {str(e)}")
            return False, f"Failed to initiate dual signing: {str(e)}", None

    def _initiate_borrower_signing(self, dual_request: DualSigningRequest, 
                                  callback_base_url: str) -> Tuple[bool, str, Optional[str]]:
        """Initiate borrower signing process"""
        try:
            borrower_request_id = str(uuid.uuid4())
            callback_url = f"{callback_base_url}/dual-signing/callback/borrower"
            
            # Create borrower signing request
            borrower_signing_request = SigningRequest(
                request_id=borrower_request_id,
                signer_name=dual_request.borrower_name,
                signer_email=dual_request.borrower_email,
                signer_phone=dual_request.borrower_phone,
                document_url=dual_request.document_url,
                callback_url=callback_url,
                signer_role=SignerRole.BORROWER,
                loan_id=dual_request.loan_id
            )
            
            self.store.create_signing_request(borrower_signing_request)

            # Call NSDL to initiate signing
            success, nsdl_response = self.nsdl_client.initiate_signing(
                request_id=borrower_request_id,
                signer_name=dual_request.borrower_name,
                signer_email=dual_request.borrower_email,
                signer_phone=dual_request.borrower_phone,
                document_url=dual_request.document_url,
                callback_url=callback_url
            )

            if success:
                # Update signing request with NSDL details
                self.store.update_signing_request(
                    borrower_request_id,
                    status=SigningRequestStatus.NSDL_INITIATED,
                    nsdl_request_id=nsdl_response.request_id
                )
                
                # Update dual request
                self.store.update_dual_request(
                    dual_request.loan_id,
                    borrower_signing_request_id=borrower_request_id
                )
                
                return True, "Borrower signing initiated", nsdl_response.signing_url
            else:
                self.store.update_signing_request(
                    borrower_request_id,
                    status=SigningRequestStatus.FAILED,
                    error_message=nsdl_response.error_message
                )
                return False, f"Failed to initiate borrower signing: {nsdl_response.error_message}", None

        except Exception as e:
            logger.error(f"Error initiating borrower signing: {str(e)}")
            return False, f"Failed to initiate borrower signing: {str(e)}", None

    def handle_borrower_signing_callback(self, callback_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Handle callback from borrower signing completion"""
        try:
            callback = SigningCallbackData(**callback_data)
            
            # Find signing request
            signing_request = self.store.get_signing_request(callback.request_id)
            if not signing_request:
                return False, "Signing request not found"

            if callback.is_successful():
                # Update signing request
                self.store.update_signing_request(
                    callback.request_id,
                    status=SigningRequestStatus.SIGNED,
                    signed_document_url=callback.signed_document_url
                )
                
                # Update dual request
                dual_request = self.store.get_dual_request(signing_request.loan_id)
                if dual_request:
                    self.store.update_dual_request(
                        signing_request.loan_id,
                        status=DualSigningStatus.BORROWER_SIGNED,
                        borrower_signed_at=datetime.utcnow(),
                        borrower_signed_doc_url=callback.signed_document_url
                    )
                    
                    # Initiate lender signing
                    lender_success, lender_message = self._initiate_lender_signing(dual_request)
                    if not lender_success:
                        logger.error(f"Failed to initiate lender signing: {lender_message}")
                
                return True, "Borrower signing completed successfully"
            else:
                # Handle failed signing
                self.store.update_signing_request(
                    callback.request_id,
                    status=SigningRequestStatus.FAILED,
                    error_message=callback.error_message
                )
                
                self.store.update_dual_request(
                    signing_request.loan_id,
                    status=DualSigningStatus.FAILED,
                    error_message=f"Borrower signing failed: {callback.error_message}"
                )
                
                return False, f"Borrower signing failed: {callback.error_message}"

        except Exception as e:
            logger.error(f"Error handling borrower callback: {str(e)}")
            return False, f"Error processing borrower signing callback: {str(e)}"

    def _initiate_lender_signing(self, dual_request: DualSigningRequest) -> Tuple[bool, str]:
        """Initiate lender signing after borrower has signed"""
        try:
            lender_request_id = str(uuid.uuid4())
            callback_url = f"http://localhost:8000/dual-signing/callback/lender"  # Configurable if needed
            
            # Use borrower-signed document for lender signing
            document_url = dual_request.borrower_signed_doc_url or dual_request.document_url
            
            # Create lender signing request
            lender_signing_request = SigningRequest(
                request_id=lender_request_id,
                signer_name=dual_request.lender_name,
                signer_email=dual_request.lender_email,
                signer_phone=dual_request.lender_phone,
                document_url=document_url,
                callback_url=callback_url,
                signer_role=SignerRole.LENDER,
                loan_id=dual_request.loan_id
            )
            
            self.store.create_signing_request(lender_signing_request)

            # Call NSDL to initiate lender signing
            success, nsdl_response = self.nsdl_client.initiate_signing(
                request_id=lender_request_id,
                signer_name=dual_request.lender_name,
                signer_email=dual_request.lender_email,
                signer_phone=dual_request.lender_phone,
                document_url=document_url,
                callback_url=callback_url
            )

            if success:
                # Update signing request
                self.store.update_signing_request(
                    lender_request_id,
                    status=SigningRequestStatus.NSDL_INITIATED,
                    nsdl_request_id=nsdl_response.request_id
                )
                
                # Update dual request
                self.store.update_dual_request(
                    dual_request.loan_id,
                    status=DualSigningStatus.PENDING_LENDER,
                    lender_signing_request_id=lender_request_id
                )
                
                # Optional: Notify lender with signing URL
                logger.info(f"Lender signing URL: {nsdl_response.signing_url}")
                
                return True, "Lender signing initiated successfully"
            else:
                self.store.update_signing_request(
                    lender_request_id,
                    status=SigningRequestStatus.FAILED,
                    error_message=nsdl_response.error_message
                )
                
                self.store.update_dual_request(
                    dual_request.loan_id,
                    status=DualSigningStatus.FAILED,
                    error_message=f"Failed to initiate lender signing: {nsdl_response.error_message}"
                )
                
                return False, f"Failed to initiate lender signing: {nsdl_response.error_message}"

        except Exception as e:
            logger.error(f"Error initiating lender signing: {str(e)}")
            return False, f"Failed to initiate lender signing: {str(e)}"

    def handle_lender_signing_callback(self, callback_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Handle callback from lender signing completion"""
        try:
            callback = SigningCallbackData(**callback_data)
            
            # Find signing request
            signing_request = self.store.get_signing_request(callback.request_id)
            if not signing_request:
                return False, "Signing request not found"

            if callback.is_successful():
                # Update signing request
                self.store.update_signing_request(
                    callback.request_id,
                    status=SigningRequestStatus.SIGNED,
                    signed_document_url=callback.signed_document_url
                )
                
                # Update dual request and merge documents
                dual_request = self.store.get_dual_request(signing_request.loan_id)
                if dual_request:
                    # Merge both signed documents
                    merged_doc_url = None
                    if dual_request.borrower_signed_doc_url and callback.signed_document_url:
                        merged_doc_url = self.pdf_merger.merge_signed_documents(
                            dual_request.borrower_signed_doc_url,
                            callback.signed_document_url,
                            dual_request.loan_id
                        )
                    
                    self.store.update_dual_request(
                        signing_request.loan_id,
                        status=DualSigningStatus.FULLY_SIGNED,
                        lender_signed_at=datetime.utcnow(),
                        lender_signed_doc_url=callback.signed_document_url,
                        fully_signed_doc_url=merged_doc_url
                    )
                    
                    # Persist merged signed agreement URL to Loan model
                    from database import SessionLocal
                    from models import Loan
                    
                    db = SessionLocal()
                    try:
                        loan = db.query(Loan).filter(Loan.id == signing_request.loan_id).first()
                        if loan:
                            loan.signed_agreement_url = merged_doc_url
                            db.commit()
                    except Exception as db_exc:
                        logger.error(f"Failed to update Loan with signed agreement URL: {db_exc}")
                        db.rollback()
                    finally:
                        db.close()
                
                return True, "Lender signing completed successfully. Loan agreement is now fully signed."
            else:
                # Handle failed signing
                self.store.update_signing_request(
                    callback.request_id,
                    status=SigningRequestStatus.FAILED,
                    error_message=callback.error_message
                )
                
                self.store.update_dual_request(
                    signing_request.loan_id,
                    status=DualSigningStatus.FAILED,
                    error_message=f"Lender signing failed: {callback.error_message}"
                )
                
                return False, f"Lender signing failed: {callback.error_message}"

        except Exception as e:
            logger.error(f"Error handling lender callback: {str(e)}")
            return False, f"Error processing lender signing callback: {str(e)}"

    def get_dual_signing_status(self, loan_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of dual signing process"""
        dual_request = self.store.get_dual_request(loan_id)
        if not dual_request:
            return None
        
        return dual_request.to_dict()

    def get_all_dual_signing_requests(self) -> List[Dict[str, Any]]:
        """Get all dual signing requests"""
        all_requests = self.store.get_all_dual_requests()
        return [request.to_dict() for request in all_requests.values()]

    def retry_failed_signing(self, loan_id: str, callback_base_url: str) -> Tuple[bool, str]:
        """Retry failed dual signing process"""
        dual_request = self.store.get_dual_request(loan_id)
        if not dual_request:
            return False, "Dual signing request not found"
        
        if not dual_request.can_retry():
            return False, "Maximum retry attempts exceeded"
        
        if dual_request.status == DualSigningStatus.FULLY_SIGNED:
            return False, "Signing already completed"
        
        # Increment retry count
        self.store.update_dual_request(loan_id, retry_count=dual_request.retry_count + 1)
        
        # Retry based on current status
        if dual_request.status in [DualSigningStatus.PENDING_BORROWER, DualSigningStatus.FAILED]:
            success, message, signing_url = self._initiate_borrower_signing(dual_request, callback_base_url)
            if success:
                self.store.update_dual_request(loan_id, status=DualSigningStatus.PENDING_BORROWER)
            return success, message
        elif dual_request.status == DualSigningStatus.BORROWER_SIGNED:
            success, message = self._initiate_lender_signing(dual_request)
            return success, message
        
        return False, "Cannot retry in current status"

    def cancel_dual_signing(self, loan_id: str, reason: str) -> Tuple[bool, str]:
        """Cancel dual signing process"""
        dual_request = self.store.get_dual_request(loan_id)
        if not dual_request:
            return False, "Dual signing request not found"
        
        if dual_request.status == DualSigningStatus.FULLY_SIGNED:
            return False, "Cannot cancel completed signing"
        
        self.store.update_dual_request(
            loan_id,
            status=DualSigningStatus.FAILED,
            error_message=f"Cancelled: {reason}"
        )
        
        return True, "Dual signing cancelled successfully"

    def cleanup_expired_requests(self) -> int:
        """Clean up expired signing requests"""
        return self.store.mark_expired_requests()

    def get_signing_statistics(self) -> Dict[str, Any]:
        """Get signing statistics"""
        return self.store.get_statistics()


def initiate_after_borrower_request(db, loan):
    """
    Initiates dual e-signing after a borrower creates a loan request.
    Uses either real or mock NSDL client based on environment config.
    """
    from dual_signing.nsdl_client import get_nsdl_client  # ⬅️ correct path to factory
    from document_generator import DocumentGenerator
    from dual_signing.pdf_merger import PDFMerger
    from dual_signing.dual_signing_service import DualSigningService

    # Construct the dual signing service with proper client
    service = DualSigningService(
        nsdl_client=get_nsdl_client(),
        pdf_merger=PDFMerger(),
        document_generator=DocumentGenerator()
    )

    # Extract all relevant data from the loan object
    loan_data = {
        "loan_id": str(loan.id),
        "borrower_name": loan.borrower.name,
        "borrower_email": loan.borrower.email,
        "borrower_phone": loan.borrower.phone,
        "lender_name": loan.lender.name,
        "lender_email": loan.lender.email,
        "lender_phone": loan.lender.phone,
        "description": loan.description,
        "principal_amount": str(loan.principal_amount),
        "interest_rate": str(loan.interest_rate),
        "payment_frequency": loan.payment_frequency,
        "number_of_payments": loan.number_of_payments,
    }

    # Start dual signing
    success, msg, _ = service.create_and_initiate_dual_signing(loan_data)

    if not success:
        raise Exception(f"Dual signing initiation failed: {msg}")
