import uuid
import os
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from models import Loan, LoanStatus, LoanSubStatus
from dual_signing.dual_signing_models import (
    DualSigningRequest,
    SigningRequest,
    DualSigningStatus,
    SigningRequestStatus,
    SignerRole,
    SigningCallbackData
)

import dual_signing_crud as crud

from .nsdl_client import NSDLClient
from .pdf_merger import PDFMerger
from document_generator import DocumentGenerator
from emi_scheduler import create_repayment_schedule  
logger = logging.getLogger(__name__)


class DualSigningService:
    def __init__(self, nsdl_client: NSDLClient, db: Session,
                 pdf_merger: PDFMerger = None,
                 document_generator: DocumentGenerator = None):
        self.nsdl_client = nsdl_client
        self.pdf_merger = pdf_merger or PDFMerger()
        self.document_generator = document_generator or DocumentGenerator()
        self.db = db

    def _safe_commit(self, loan_id: str = None) -> bool:
        """Safely commit with automatic rollback on failure"""
        try:
            self.db.commit()
            return True
        except Exception as commit_err:
            self.db.rollback()
            log_prefix = f"[LOAN_ID:{loan_id}] " if loan_id else ""
            logger.error(f"{log_prefix}Commit failed: {commit_err}")
            return False

    def _resolve_document_path(self, document_path: str) -> Optional[str]:
        """
        Resolve document path by checking multiple possible locations.
        Accepts both absolute paths and static-like relative paths.
        """
        if not document_path:
            return None
            
        # Path candidates to check
        candidates = []
        
        # 1. Use the path as-is (absolute path)
        candidates.append(document_path)
        
        # 2. If it's a relative path, try common base directories
        if not os.path.isabs(document_path):
            # Try with uploaded_docs/public_docs prefix
            candidates.append(os.path.join("uploaded_docs", "public_docs", document_path))
            
            # Try with just the filename in uploaded_docs/public_docs
            candidates.append(os.path.join("uploaded_docs", "public_docs", os.path.basename(document_path)))
        else:
            # For absolute paths, also try the filename in uploaded_docs/public_docs
            candidates.append(os.path.join("uploaded_docs", "public_docs", os.path.basename(document_path)))
        
        # 3. Try static directory (common for web applications)
        candidates.append(os.path.join("static", os.path.basename(document_path)))
        
        # 4. Try current directory with just filename
        candidates.append(os.path.basename(document_path))
        
        # Check each candidate and return the first one that exists
        for candidate in candidates:
            if os.path.exists(candidate) and os.path.isfile(candidate):
                logger.info(f"Document resolved to: {candidate}")
                return candidate
        
        # Log all attempted paths for debugging
        logger.error(f"Document not found in any of these locations: {candidates}")
        return None

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
        loan_id = loan_data.get('loan_id')
        try:
            # Step 1: Generate loan agreement PDF
            logger.info(f"[LOAN_ID:{loan_id}] Generating loan agreement")
            document_url = self.document_generator.generate_loan_agreement(loan_data)
            
            if not document_url:
                logger.error(f"[LOAN_ID:{loan_id}] Failed to generate loan agreement document")
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
            logger.error(f"[LOAN_ID:{loan_id}] Error in create_and_initiate_dual_signing: {str(e)}")
            # Ensure session is rolled back on error
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"[LOAN_ID:{loan_id}] Error during rollback: {str(rollback_error)}")
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
            existing_request = crud.get_dual_request(self.db, loan_id)
            if existing_request:
                if existing_request.status == DualSigningStatus.FULLY_SIGNED:
                    logger.warning(f"[LOAN_ID:{loan_id}] Loan agreement already fully signed")
                    return True, "Loan agreement already fully signed– no action taken", existing_request
                elif existing_request.status in [DualSigningStatus.PENDING_BORROWER, DualSigningStatus.BORROWER_SIGNED]:
                    logger.warning(f"[LOAN_ID:{loan_id}] Dual signing already in progress")
                    return True, "Dual signing already in progress", existing_request

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
            
            crud.create_dual_request(self.db, dual_request)
            logger.info(f"[LOAN_ID:{loan_id}] Created dual signing request")

            # Initiate borrower signing first
            success, message, signing_url = self._initiate_borrower_signing(
                dual_request, callback_base_url
            )
            
            if success:
                logger.info(f"[LOAN_ID:{loan_id}] Dual signing initiated successfully")
                return True, "Dual signing initiated successfully", signing_url
            else:
                logger.error(f"[LOAN_ID:{loan_id}] Failed to initiate borrower signing: {message}")
                try:
                    crud.update_dual_request_status(
                        db=self.db,
                        loan_id=loan_id,
                        status=DualSigningStatus.FAILED,
                        error_message=message
                    )
                    if not self._safe_commit(loan_id):
                        logger.error(f"[LOAN_ID:{loan_id}] Failed to update dual request status in DB")
                except SQLAlchemyError as db_error:
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to update dual request status: {str(db_error)}")
                    self.db.rollback()

                return False, message, None

        except Exception as e:
            logger.error(f"[LOAN_ID:{loan_id}] Error initiating dual signing: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"[LOAN_ID:{loan_id}] Error during rollback: {str(rollback_error)}")
            return False, f"Failed to initiate dual signing: {str(e)}", None

    def _initiate_borrower_signing(self, dual_request: DualSigningRequest, 
                                  callback_base_url: str) -> Tuple[bool, str, Optional[str]]:
        """Initiate borrower signing process"""
        loan_id = dual_request.loan_id
        try:
            borrower_request_id = str(uuid.uuid4())
            callback_url = f"{callback_base_url}/dual-signing/callback/borrower"
            
            logger.info(f"[LOAN_ID:{loan_id}] Initiating borrower signing with request_id: {borrower_request_id}")
            
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
            
            crud.create_signing_request(self.db, borrower_signing_request)

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
                crud.update_signing_request(
                    self.db,
                    borrower_request_id,
                    {
                        "status": SigningRequestStatus.NSDL_INITIATED,
                        "nsdl_request_id": nsdl_response.request_id
                    }
                )
                
                # Update dual request
                crud.update_dual_request(
                    self.db,
                    dual_request.loan_id,
                    {
                        "borrower_signing_request_id": borrower_request_id
                    }
                )
                
                # Update loan sub_status to borrower_pending_signature
                loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                if loan:
                    loan.sub_status = LoanSubStatus.borrower_pending_signature
                
                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to commit borrower signing initiation")
                    return False, "Failed to save borrower signing request", None
                
                logger.info(f"[LOAN_ID:{loan_id}] Borrower signing initiated successfully")
                return True, "Borrower signing initiated", nsdl_response.signing_url
            else:
                logger.error(f"[LOAN_ID:{loan_id}] NSDL failed to initiate borrower signing: {nsdl_response.error_message}")
                crud.update_signing_request(
                    self.db,
                    borrower_request_id,
                    {
                        "status": SigningRequestStatus.FAILED,
                        "error_message": nsdl_response.error_message
                    }
                )
                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to commit failed borrower signing status")
                return False, f"Failed to initiate borrower signing: {nsdl_response.error_message}", None

        except Exception as e:
            logger.error(f"[LOAN_ID:{loan_id}] Error initiating borrower signing: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"[LOAN_ID:{loan_id}] Error during rollback: {str(rollback_error)}")
            return False, f"Failed to initiate borrower signing: {str(e)}", None

    def handle_borrower_signing_callback(self, callback_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Handle callback from borrower signing completion"""
        signing_request = None
        loan_id = None

        try:
            callback = SigningCallbackData(**callback_data)

            # Get signing request from DB
            signing_request = crud.get_signing_request(self.db, callback.request_id)
            if not signing_request:
                logger.error(f"[REQUEST_ID:{callback.request_id}] Signing request not found")
                return False, "Signing request not found"

            loan_id = signing_request.loan_id
            logger.info(f"[LOAN_ID:{loan_id}] Processing borrower signing callback")

            if signing_request.signer_role != SignerRole.BORROWER:
                logger.error(f"[LOAN_ID:{loan_id}] Invalid signer role for borrower callback")
                return False, "Invalid signer role for borrower callback"

            if callback.is_successful():
                # ✅ Patch begins here: normalize the path
                signed_url = callback.signed_document_url
                if signed_url.startswith("/"):
                    signed_url = signed_url.lstrip("/")
                resolved_path = signed_url if os.path.exists(signed_url) else None
                # ✅ Patch ends here

                if not resolved_path:
                    logger.error(f"[LOAN_ID:{loan_id}] Signed document not found at any expected location")
                    return False, "Signed document file does not exist in expected locations"

                # Update signed request
                crud.update_signing_request(
                    self.db,
                    callback.request_id,
                    {
                        "status": SigningRequestStatus.SIGNED,
                        "signed_document_url": resolved_path
                    }
                )

                dual_request = crud.get_dual_request(self.db, signing_request.loan_id)
                if dual_request:
                    crud.update_dual_request(
                        self.db,
                        signing_request.loan_id,
                        {
                            "status": DualSigningStatus.BORROWER_SIGNED,
                            "borrower_signed_at": datetime.utcnow(),
                            "borrower_signed_doc_url": resolved_path
                        }
                    )

                    loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                    if loan:
                        loan.sub_status = LoanSubStatus.lender_pending_signature

                    lender_success, lender_message = self._initiate_lender_signing(dual_request)
                    if not lender_success:
                        logger.error(f"[LOAN_ID:{loan_id}] Failed to initiate lender signing: {lender_message}")
                        self.db.rollback()
                        return False, lender_message

                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Commit failed after borrower signing")
                    return False, "Failed to save borrower signing completion"

                logger.info(f"[LOAN_ID:{loan_id}] Borrower signing completed successfully")
                return True, "Borrower signing completed successfully"

            else:
                logger.error(f"[LOAN_ID:{loan_id}] Borrower signing failed: {callback.error_message}")
                crud.update_signing_request(
                    self.db,
                    callback.request_id,
                    {
                        "status": SigningRequestStatus.FAILED,
                        "error_message": callback.error_message
                    }
                )
                crud.update_dual_request(
                    self.db,
                    signing_request.loan_id,
                    {
                        "status": DualSigningStatus.FAILED,
                        "error_message": f"Borrower signing failed: {callback.error_message}"
                    }
                )

                loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                if loan:
                    loan.sub_status = LoanSubStatus.waiting_reinitiation

                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Commit failed for borrower signing failure")
                    return False, "Failed to save borrower signing failure"

                return False, f"Borrower signing failed: {callback.error_message}"

        except Exception as e:
            logger.error(f"Error handling borrower callback: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {str(rollback_error)}")
            return False, f"Error processing borrower signing callback: {str(e)}"

    def _initiate_lender_signing(self, dual_request: DualSigningRequest) -> Tuple[bool, str]:
        """Initiate lender signing after borrower has signed"""
        loan_id = dual_request.loan_id
        try:
            lender_request_id = str(uuid.uuid4())
            callback_url = "http://localhost:8000/dual-signing/callback/lender"

            # Use the enhanced path resolution for lender signing
            primary_path = dual_request.borrower_signed_doc_url or dual_request.document_url
            document_url = self._resolve_document_path(primary_path)

            if not document_url:
                logger.error(f"[LOAN_ID:{loan_id}] Signed document not found for lender signing.")
                return False, "Signed document not found for lender"

            lender_signing_request = SigningRequest(
                request_id=lender_request_id,
                signer_name=dual_request.lender_name,
                signer_email=dual_request.lender_email,
                signer_phone=dual_request.lender_phone,
                document_url=document_url,
                callback_url=callback_url,
                signer_role=SignerRole.LENDER,
                loan_id=loan_id
            )
            crud.create_signing_request(self.db, lender_signing_request)

            success, nsdl_response = self.nsdl_client.initiate_signing(
                request_id=lender_request_id,
                signer_name=dual_request.lender_name,
                signer_email=dual_request.lender_email,
                signer_phone=dual_request.lender_phone,
                document_url=document_url,
                callback_url=callback_url
            )

            if success:
                crud.update_signing_request(
                    self.db,
                    lender_request_id,
                    {
                        "status": SigningRequestStatus.NSDL_INITIATED,
                        "nsdl_request_id": nsdl_response.request_id
                    }
                )
                crud.update_dual_request(
                    self.db,
                    loan_id,
                    {
                        "status": DualSigningStatus.PENDING_LENDER,
                        "lender_signing_request_id": lender_request_id
                    }
                )
                logger.info(f"[LOAN_ID:{loan_id}] Lender signing successfully initiated")
                return True, "Lender signing initiated successfully"

            else:
                crud.update_signing_request(
                    self.db,
                    lender_request_id,
                    {
                        "status": SigningRequestStatus.FAILED,
                        "error_message": nsdl_response.error_message
                    }
                )
                crud.update_dual_request(
                    self.db,
                    loan_id,
                    {
                        "status": DualSigningStatus.FAILED,
                        "error_message": f"NSDL failed: {nsdl_response.error_message}"
                    }
                )
                return False, f"NSDL failed to initiate signing: {nsdl_response.error_message}"

        except Exception as e:
            logger.error(f"[LOAN_ID:{loan_id}] Exception during lender signing: {str(e)}")
            return False, f"Failed to initiate lender signing: {str(e)}"

    def handle_lender_signing_callback(self, callback_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Handle callback from lender signing completion"""
        signing_request = None
        loan_id = None

        try:
            callback = SigningCallbackData(**callback_data)

            # Get signing request from DB
            signing_request = crud.get_signing_request(self.db, callback.request_id)
            if not signing_request:
                logger.error(f"[REQUEST_ID:{callback.request_id}] Signing request not found")
                return False, "Signing request not found"

            loan_id = signing_request.loan_id
            logger.info(f"[LOAN_ID:{loan_id}] Processing lender signing callback")

            if signing_request.signer_role != SignerRole.LENDER:
                logger.error(f"[LOAN_ID:{loan_id}] Invalid signer role for lender callback")
                return False, "Invalid signer role for lender callback"

            if callback.is_successful():
                # Resolve lender's signed PDF path
                resolved_path = self._resolve_document_path(callback.signed_document_url)
                if not resolved_path:
                    logger.error(f"[LOAN_ID:{loan_id}] Lender signed document not found")
                    return False, "Lender signed document file does not exist in expected locations"

                # Update lender signing request
                crud.update_signing_request(
                    self.db,
                    callback.request_id,
                    {
                        "status": SigningRequestStatus.SIGNED,
                        "signed_document_url": resolved_path
                    }
                )

                dual_request = crud.get_dual_request(self.db, loan_id)
                if not dual_request or not dual_request.borrower_signed_doc_url:
                    logger.error(f"[LOAN_ID:{loan_id}] Borrower document missing, cannot merge")
                    return False, "Cannot merge without borrower signed document"

                # Merge PDFs
                from .pdf_merger import PDFMerger
                merger = PDFMerger()
                merged_path = merger.merge_signed_documents(
                    borrower_signed_url=dual_request.borrower_signed_doc_url,
                    lender_signed_url=resolved_path,
                    loan_id=str(loan_id)
                )

                if not merged_path:
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to merge signed documents")
                    return False, "Failed to merge signed documents"

                # Update dual signing request
                crud.update_dual_request(
                    self.db,
                    loan_id,
                    {
                        "status": DualSigningStatus.FULLY_SIGNED,
                        "lender_signed_at": datetime.utcnow(),
                        "lender_signed_doc_url": resolved_path,
                        "final_signed_doc_url": merged_path
                    }
                )

                # Mark loan as fully signed
                loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                if loan:
                    loan.status = LoanStatus.active
                    loan.sub_status = LoanSubStatus.none

                try:
                    create_repayment_schedule(self.db, loan)  # 🔥 This generates EMI records
                except Exception as emi_err:
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to generate EMI schedule: {str(emi_err)}")
                    return False, "Loan activated, but EMI schedule generation failed"


                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Commit failed after lender signing")
                    return False, "Failed to save lender signing completion"

                logger.info(f"[LOAN_ID:{loan_id}] Lender signing completed and documents merged")
                return True, "Lender signing completed successfully - loan fully signed"

            else:
                logger.error(f"[LOAN_ID:{loan_id}] Lender signing failed: {callback.error_message}")
                crud.update_signing_request(
                    self.db,
                    callback.request_id,
                    {
                        "status": SigningRequestStatus.FAILED,
                        "error_message": callback.error_message
                    }
                )
                crud.update_dual_request(
                    self.db,
                    signing_request.loan_id,
                    {
                        "status": DualSigningStatus.FAILED,
                        "error_message": f"Lender signing failed: {callback.error_message}"
                    }
                )

                loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                if loan:
                    loan.sub_status = LoanSubStatus.waiting_reinitiation

                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Commit failed for lender signing failure")
                    return False, "Failed to save lender signing failure"

                return False, f"Lender signing failed: {callback.error_message}"

        except Exception as e:
            logger.error(f"Error handling lender callback: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {str(rollback_error)}")
            return False, f"Error processing lender signing callback: {str(e)}"

    def get_dual_signing_status(self, loan_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of dual signing process"""
        dual_request = crud.get_dual_request(self.db, loan_id)
        if not dual_request:
            return None
        
        return dual_request.to_dict()

    def get_all_dual_signing_requests(self) -> List[Dict[str, Any]]:
        """Get all dual signing requests"""
        all_requests = crud.get_all_dual_requests(self.db)
        return [request.to_dict() for request in all_requests]

    def retry_failed_signing(self, loan_id: str, callback_base_url: str) -> Tuple[bool, str]:
        """Retry failed dual signing process"""
        try:
            dual_request = crud.get_dual_request(self.db, loan_id)
            if not dual_request:
                logger.warning(f"[LOAN_ID:{loan_id}] Dual signing request not found for retry")
                return False, "Dual signing request not found"
            
            if not dual_request.can_retry():
                logger.warning(f"[LOAN_ID:{loan_id}] Maximum retry attempts exceeded")
                return False, "Maximum retry attempts exceeded"
            
            if dual_request.status == DualSigningStatus.FULLY_SIGNED:
                logger.warning(f"[LOAN_ID:{loan_id}] Cannot retry - signing already completed")
                return False, "Signing already completed"
            
            # Increment retry count
            crud.update_dual_request(
                self.db, 
                loan_id, 
                {
                    "retry_count": dual_request.retry_count + 1
                }
            )
            
            logger.info(f"[LOAN_ID:{loan_id}] Retrying dual signing process (attempt {dual_request.retry_count + 1})")
            
            # Re-fetch dual_request to get the updated retry_count
            dual_request = crud.get_dual_request(self.db, loan_id) 

            if not dual_request.can_retry():
                return False, "Retry limit reached"

            # Retry based on current status
            if dual_request.status in [DualSigningStatus.PENDING_BORROWER, DualSigningStatus.FAILED]:
                success, message, signing_url = self._initiate_borrower_signing(dual_request, callback_base_url)
                if success and dual_request.status != DualSigningStatus.PENDING_BORROWER:
                    crud.update_dual_request(
                        self.db, 
                        loan_id, 
                        {
                            "status": DualSigningStatus.PENDING_BORROWER
                        }
                    )
                    
                    # Update loan sub_status to borrower_pending_signature
                    loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                    if loan:
                        loan.sub_status = LoanSubStatus.borrower_pending_signature
                        
                # Safe commit with rollback handling
                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to commit borrower retry")
                    return False, "Failed to save retry attempt"
                return success, message

            elif dual_request.status == DualSigningStatus.BORROWER_SIGNED:
                success, message = self._initiate_lender_signing(dual_request)
                
                # Update loan sub_status to lender_pending_signature
                loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
                if loan:
                    loan.sub_status = LoanSubStatus.lender_pending_signature
                    
                # Safe commit with rollback handling
                if not self._safe_commit(loan_id):
                    logger.error(f"[LOAN_ID:{loan_id}] Failed to commit lender retry")
                    return False, "Failed to save retry attempt"
                return success, message
            
            return False, "Cannot retry in current status"
            
        except Exception as e:
            logger.error(f"[LOAN_ID:{loan_id}] Error during retry: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"[LOAN_ID:{loan_id}] Error during rollback: {str(rollback_error)}")
            return False, f"Error during retry: {str(e)}"
        # Also update the loan's sub_status to indicate it's waiting for reinitiation
            loan = self.db.query(Loan).filter(Loan.id == int(loan_id)).first()
            if loan:
                loan.sub_status = LoanSubStatus.waiting_reinitiation

        # Safe commit
            if not self._safe_commit(loan_id):
                logger.error(f"[LOAN_ID:{loan_id}] Failed to commit cancellation")
                return False, "Failed to save cancellation"
        
            logger.info(f"[LOAN_ID:{loan_id}] Dual signing cancelled: {reason}")
            return True, "Dual signing cancelled successfully"
        
        except Exception as e:
            logger.error(f"[LOAN_ID:{loan_id}] Error cancelling dual signing: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"[LOAN_ID:{loan_id}] Error during rollback: {str(rollback_error)}")
            return False, f"Error cancelling dual signing: {str(e)}"


    def cleanup_expired_requests(self) -> int:
        """Clean up expired signing requests"""
        try:
            expired_count = crud.mark_expired_requests(self.db)
            self.db.commit()
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired signing requests")
            return expired_count
        except Exception as e:
            logger.error(f"Error cleaning up expired requests: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {str(rollback_error)}")
            return 0

    def get_signing_statistics(self) -> Dict[str, Any]:
        """Get signing statistics"""
        return crud.get_statistics(self.db)


def initiate_after_borrower_request(db: Session, loan: Loan):
    """
    Initiates dual e-signing after a borrower creates a loan request.
    Uses either real or mock NSDL client based on environment config.
    """
    from dual_signing.nsdl_client import get_nsdl_client
    from document_generator import DocumentGenerator
    from dual_signing.pdf_merger import PDFMerger

    # Store loan_id before any potential rollback
    loan_id = str(loan.id)
    
    try:
        # Construct the dual signing service with proper client
        service = DualSigningService(
            nsdl_client=get_nsdl_client(),
            db=db,
            pdf_merger=PDFMerger(),
            document_generator=DocumentGenerator()
        )

        # Extract all relevant data from the loan object
        loan_data = {
            "loan_id": loan_id,
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
            
    except Exception as e:
        logger.error(f"Exception during dual signing initiation for loan {loan_id}: {str(e)}")
        # Ensure session is rolled back before raising
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during rollback for loan {loan_id}: {str(rollback_error)}")
        raise Exception(f"Dual signing initiation failed: {str(e)}")
    

def get_dual_signing_service(db: Session) -> DualSigningService:
    """
    Factory function to create a properly configured DualSigningService instance
    """
    # Import exactly like your initiate_after_borrower_request function does:
    from dual_signing.nsdl_client import get_nsdl_client
    from document_generator import DocumentGenerator
    from dual_signing.pdf_merger import PDFMerger
    
    return DualSigningService(
        nsdl_client=get_nsdl_client(),
        db=db,
        pdf_merger=PDFMerger(),
        document_generator=DocumentGenerator()
    )
    