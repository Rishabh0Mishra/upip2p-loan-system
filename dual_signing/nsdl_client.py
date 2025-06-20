import os
import requests
import logging
import hashlib
import hmac
import json
from typing import Dict, Any, Tuple
from datetime import datetime
from .dual_signing_models import NSDLResponse
from config import settings

logger = logging.getLogger(__name__)

class NSDLClient:
    def __init__(self, base_url: str = None, api_key: str = None, secret_key: str = None):
        self.base_url = base_url or "https://api.nsdl.co.in/esign/v1"
        self.api_key = api_key or "your_nsdl_api_key"
        self.secret_key = secret_key or "your_nsdl_secret_key"
        self.timeout = 30

    def _generate_signature(self, data: str, timestamp: str) -> str:
        message = f"{data}{timestamp}"
        return hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        url = f"{self.base_url}/{endpoint}"
        timestamp = str(int(datetime.utcnow().timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": self._generate_signature(json.dumps(data), timestamp)
        }

        try:
            logger.info(f"Making NSDL API request to {url}")
            response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return True, response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"NSDL API request failed: {str(e)}")
            return False, {"error": str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response: {str(e)}")
            return False, {"error": "Invalid JSON response"}

    def initiate_signing(self, request_id: str, signer_name: str, signer_email: str,
                         signer_phone: str, document_url: str, callback_url: str) -> Tuple[bool, NSDLResponse]:
        data = {
            "requestId": request_id,
            "signerName": signer_name,
            "signerEmail": signer_email,
            "signerPhone": signer_phone,
            "documentUrl": document_url,
            "callbackUrl": callback_url,
            "expiryHours": 24,
            "signerType": "INDIVIDUAL"
        }

        success, response = self._make_request("initiate-signing", data)
        if success and response.get("status") == "SUCCESS":
            return True, NSDLResponse.success(
                request_id=response.get("requestId"),
                signing_url=response.get("signingUrl")
            )
        else:
            msg = response.get("error") or response.get("message", "Unknown error")
            return False, NSDLResponse.error(msg)

    def get_signing_status(self, nsdl_request_id: str) -> Tuple[bool, Dict[str, Any]]:
        data = {"requestId": nsdl_request_id}
        return self._make_request("get-status", data)

    def validate_callback(self, callback_data: Dict[str, Any], signature: str = None) -> bool:
        required_fields = ["requestId", "status"]
        return all(field in callback_data for field in required_fields)

    def download_signed_document(self, signed_doc_url: str) -> Tuple[bool, bytes]:
        try:
            response = requests.get(signed_doc_url, timeout=self.timeout)
            response.raise_for_status()
            return True, response.content
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download signed document: {str(e)}")
            return False, b""


class MockNSDLClient(NSDLClient):
    """Mock NSDL client for development/testing"""

    def __init__(self):
        super().__init__()
        self.mock_requests = {}

    def initiate_signing(self, request_id: str, signer_name: str, signer_email: str,
                         signer_phone: str, document_url: str, callback_url: str) -> Tuple[bool, NSDLResponse]:
        self.mock_requests[request_id] = {
            "status": "INITIATED",
            "signer_name": signer_name,
            "signer_email": signer_email,
            "document_url": document_url,
            "callback_url": callback_url
        }

        mock_nsdl_id = f"NSDL_{request_id}"
        mock_signing_url = f"https://mock-nsdl.com/sign/{mock_nsdl_id}"

        return True, NSDLResponse.success(
            request_id=mock_nsdl_id,
            signing_url=mock_signing_url
        )

    def get_signing_status(self, nsdl_request_id: str) -> Tuple[bool, Dict[str, Any]]:
        return True, {
            "status": "PENDING",
            "requestId": nsdl_request_id
        }

    def simulate_signing_completion(self, nsdl_request_id: str, success: bool = True) -> Dict[str, Any]:
        if success:
            return {
                "requestId": nsdl_request_id,
                "status": "SIGNED",
                "signedDocumentUrl": f"https://mock-nsdl.com/signed/{nsdl_request_id}.pdf"
            }
        else:
            return {
                "requestId": nsdl_request_id,
                "status": "FAILED",
                "errorMessage": "Mock signing failed"
            }


# Factory for switching real vs mock client
def get_nsdl_client() -> NSDLClient:
    if settings.use_nsdl_mock:
        print("⚠️  Using MockNSDLClient")
        return MockNSDLClient()
    
    return NSDLClient(
        base_url=settings.nsdl_esign_base_url,
        api_key=settings.nsdl_api_key,
        secret_key=settings.nsdl_secret_key,
    )