# esign_service.py - Complete NSDL eSign Integration

import hashlib
import uuid
import json
import os
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

class SigningStatus(Enum):
    PENDING = "pending"
    SIGNED = "signed"
    FAILED = "failed"
    EXPIRED = "expired"

@dataclass
class SigningRequest:
    transaction_id: str
    loan_id: str
    pdf_path: str
    pdf_hash: str
    signer_name: str
    signer_email: str
    signer_phone: str
    status: SigningStatus
    created_at: datetime
    signed_at: Optional[datetime] = None
    signing_url: Optional[str] = None
    nsdl_response: Optional[Dict] = None

class NSDLESignService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = config.get('nsdl_base_url', 'https://api.nsdl.co.in/esign')
        self.api_key = config.get('api_key')
        self.secret_key = config.get('secret_key')
        self.callback_url = config.get('callback_url', 'http://localhost:8000/api/esign/callback')
        self.success_url = config.get('success_url', 'http://localhost:3000/sign-success')
        self.failure_url = config.get('failure_url', 'http://localhost:3000/sign-failed')
        self.mock_mode = config.get('mock_mode', True)  # For development
        
        # Storage for signing requests (in production, use database)
        self.signing_requests = {}
    
    def calculate_pdf_hash(self, pdf_path: str) -> str:
        """Calculate SHA256 hash of PDF file"""
        try:
            with open(pdf_path, 'rb') as f:
                pdf_content = f.read()
                return hashlib.sha256(pdf_content).hexdigest()
        except FileNotFoundError:
            raise Exception(f"PDF file not found: {pdf_path}")
    
    def create_signing_request(self, loan_data: Dict[str, Any], pdf_path: str) -> SigningRequest:
        """Create a new signing request"""
        transaction_id = f"TXN-{str(uuid.uuid4())[:8].upper()}"
        pdf_hash = self.calculate_pdf_hash(pdf_path)
        
        signing_request = SigningRequest(
            transaction_id=transaction_id,
            loan_id=loan_data['loan_id'],
            pdf_path=pdf_path,
            pdf_hash=pdf_hash,
            signer_name=loan_data['borrower_name'],  # or lender_name based on flow
            signer_email=loan_data['borrower_email'],
            signer_phone=loan_data['borrower_phone'],
            status=SigningStatus.PENDING,
            created_at=datetime.now()
        )
        
        # Store the request
        self.signing_requests[transaction_id] = signing_request
        
        return signing_request
    
    def send_for_signing(self, signing_request: SigningRequest, aadhaar_last_4: str) -> Dict[str, Any]:
        """Send PDF to NSDL for signing"""
        
        if self.mock_mode:
            return self._mock_nsdl_request(signing_request, aadhaar_last_4)
        else:
            return self._real_nsdl_request(signing_request, aadhaar_last_4)
    
    def _mock_nsdl_request(self, signing_request: SigningRequest, aadhaar_last_4: str) -> Dict[str, Any]:
        """Mock NSDL API for development"""
        
        # Simulate NSDL response
        mock_response = {
            "status": "success",
            "transaction_id": signing_request.transaction_id,
            "signing_url": f"http://localhost:3000/mock-sign/{signing_request.transaction_id}",
            "message": "Document ready for signing",
            "expires_in": 1800  # 30 minutes
        }
        
        # Update signing request
        signing_request.signing_url = mock_response["signing_url"]
        signing_request.nsdl_response = mock_response
        
        print(f"🔥 MOCK NSDL: Created signing URL for {signing_request.transaction_id}")
        
        return {
            "success": True,
            "signing_url": mock_response["signing_url"],
            "transaction_id": signing_request.transaction_id,
            "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat()
        }
    
    def _real_nsdl_request(self, signing_request: SigningRequest, aadhaar_last_4: str) -> Dict[str, Any]:
        """Real NSDL API implementation"""
        
        # Prepare NSDL payload
        payload = {
            "aspId": self.api_key,
            "authMode": "otp",  # Aadhaar OTP mode
            "responseUrl": self.callback_url,
            "successUrl": self.success_url,
            "failureUrl": self.failure_url,
            "signerName": signing_request.signer_name,
            "signerEmail": signing_request.signer_email,
            "signerMobile": signing_request.signer_phone,
            "aadhaarNumber": f"XXXX-XXXX-{aadhaar_last_4}",  # Masked Aadhaar
            "reason": "Loan Agreement Signing",
            "transactionId": signing_request.transaction_id,
            "docInfo": [{
                "docName": f"loan_agreement_{signing_request.loan_id}.pdf",
                "docType": "pdf",
                "docHash": signing_request.pdf_hash,
                "docHashAlgo": "SHA256"
            }]
        }
        
        # Add authentication headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._generate_auth_token()}",
            "X-API-Key": self.api_key
        }
        
        try:
            # Make request to NSDL
            response = requests.post(
                f"{self.base_url}/sign",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                nsdl_response = response.json()
                
                # Update signing request
                signing_request.signing_url = nsdl_response.get("signingUrl")
                signing_request.nsdl_response = nsdl_response
                
                return {
                    "success": True,
                    "signing_url": nsdl_response.get("signingUrl"),
                    "transaction_id": signing_request.transaction_id,
                    "expires_at": nsdl_response.get("expiresAt")
                }
            else:
                return {
                    "success": False,
                    "error": f"NSDL API error: {response.status_code}",
                    "message": response.text
                }
                
        except requests.RequestException as e:
            return {
                "success": False,
                "error": "Network error",
                "message": str(e)
            }
    
    def handle_callback(self, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle NSDL callback after signing"""
        
        transaction_id = callback_data.get("transactionId")
        status = callback_data.get("status")
        
        if transaction_id not in self.signing_requests:
            return {"success": False, "error": "Invalid transaction ID"}
        
        signing_request = self.signing_requests[transaction_id]
        
        if status == "SUCCESS":
            return self._handle_successful_signing(signing_request, callback_data)
        else:
            return self._handle_failed_signing(signing_request, callback_data)
    
    def _handle_successful_signing(self, signing_request: SigningRequest, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle successful signing"""
        
        signing_request.status = SigningStatus.SIGNED
        signing_request.signed_at = datetime.now()
        
        # Download signed document (if NSDL provides URL)
        signed_doc_url = callback_data.get("signedDocUrl")
        if signed_doc_url:
            self._download_signed_document(signing_request, signed_doc_url)
        
        print(f"✅ Document signed successfully: {signing_request.transaction_id}")
        
        return {
            "success": True,
            "transaction_id": signing_request.transaction_id,
            "loan_id": signing_request.loan_id,
            "signed_at": signing_request.signed_at.isoformat(),
            "message": "Document signed successfully"
        }
    
    def _handle_failed_signing(self, signing_request: SigningRequest, callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle failed signing"""
        
        signing_request.status = SigningStatus.FAILED
        error_message = callback_data.get("errorMessage", "Signing failed")
        
        print(f"❌ Signing failed: {signing_request.transaction_id} - {error_message}")
        
        return {
            "success": False,
            "transaction_id": signing_request.transaction_id,
            "loan_id": signing_request.loan_id,
            "error": error_message
        }
    
    def _download_signed_document(self, signing_request: SigningRequest, signed_doc_url: str):
        """Download the signed document from NSDL"""
        
        try:
            response = requests.get(signed_doc_url, timeout=30)
            
            if response.status_code == 200:
                # Save signed document (overwrite original or create new version)
                signed_pdf_path = signing_request.pdf_path.replace('.pdf', '_signed.pdf')
                
                with open(signed_pdf_path, 'wb') as f:
                    f.write(response.content)
                
                print(f"📄 Signed document downloaded: {signed_pdf_path}")
                
        except Exception as e:
            print(f"❌ Error downloading signed document: {e}")
    
    def get_signing_status(self, transaction_id: str) -> Optional[SigningRequest]:
        """Get current status of signing request"""
        return self.signing_requests.get(transaction_id)
    
    def _generate_auth_token(self) -> str:
        """Generate authentication token for NSDL API"""
        # Implementation depends on NSDL's auth mechanism
        # Usually involves JWT or similar
        timestamp = str(int(datetime.now().timestamp()))
        raw_token = f"{self.api_key}:{timestamp}:{self.secret_key}"
        return hashlib.sha256(raw_token.encode()).hexdigest()

# Configuration
NSDL_CONFIG = {
    "nsdl_base_url": "https://api.nsdl.co.in/esign",  # Real URL
    "api_key": "your_nsdl_api_key",
    "secret_key": "your_nsdl_secret_key",
    "callback_url": "http://localhost:8000/api/esign/callback",
    "success_url": "http://localhost:3000/sign-success",
    "failure_url": "http://localhost:3000/sign-failed",
    "mock_mode": True  # Set to False for production
}

# Usage Example
def example_usage():
    """Example of how to use the eSign service"""
    
    # Initialize service
    esign_service = NSDLESignService(NSDL_CONFIG)
    
    # Sample loan data
    loan_data = {
        "loan_id": "LOAN-12345",
        "borrower_name": "John Doe",
        "borrower_email": "john@example.com",
        "borrower_phone": "+91 9876543210"
    }
    
    # Step 1: Create signing request
    signing_request = esign_service.create_signing_request(
        loan_data, 
        "./agreements/loan_agreement_LOAN-12345.pdf"
    )
    
    print(f"Created signing request: {signing_request.transaction_id}")
    
    # Step 2: Send for signing
    result = esign_service.send_for_signing(signing_request, "1234")  # Last 4 digits of Aadhaar
    
    if result["success"]:
        print(f"Signing URL: {result['signing_url']}")
        print(f"Expires at: {result['expires_at']}")
    else:
        print(f"Error: {result['error']}")
    
    # Step 3: Simulate callback (this would come from NSDL)
    mock_callback = {
        "transactionId": signing_request.transaction_id,
        "status": "SUCCESS",
        "signedDocUrl": "https://nsdl.example.com/signed-doc.pdf",
        "timestamp": datetime.now().isoformat()
    }
    
    callback_result = esign_service.handle_callback(mock_callback)
    print(f"Callback result: {callback_result}")

if __name__ == "__main__":
    example_usage()