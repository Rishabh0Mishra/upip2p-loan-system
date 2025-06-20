from typing import Dict, Optional, List
import threading
import logging
from datetime import datetime, timedelta

from .dual_signing_models import DualSigningRequest, SigningRequest, DualSigningStatus, SigningRequestStatus

logger = logging.getLogger(__name__)

class DualSigningStore:
    def __init__(self):
        self._dual_requests: Dict[str, DualSigningRequest] = {}
        self._signing_requests: Dict[str, SigningRequest] = {}
        self._lock = threading.RLock()

    def create_dual_request(self, dual_request: DualSigningRequest) -> None:
        with self._lock:
            loan_id = str(dual_request.loan_id)
            self._dual_requests[loan_id] = dual_request
            logger.info(f"Created dual signing request for loan {loan_id}")

    def get_dual_request(self, loan_id: str) -> Optional[DualSigningRequest]:
        with self._lock:
            return self._dual_requests.get(str(loan_id))

    def update_dual_request(self, loan_id: str, **kwargs) -> bool:
        loan_id = str(loan_id)
        with self._lock:
            if loan_id in self._dual_requests:
                for k, v in kwargs.items():
                    if hasattr(self._dual_requests[loan_id], k):
                        setattr(self._dual_requests[loan_id], k, v)
                    else:
                        logger.warning(f"Attribute {k} not found in DualSigningRequest")
                logger.info(f"Updated dual signing request for loan {loan_id}: {kwargs}")
                return True
            return False

    def delete_dual_request(self, loan_id: str) -> bool:
        with self._lock:
            return self._dual_requests.pop(str(loan_id), None) is not None

    def create_signing_request(self, signing_request: SigningRequest) -> None:
        with self._lock:
            self._signing_requests[str(signing_request.request_id)] = signing_request
            logger.info(f"Created signing request {signing_request.request_id} for {signing_request.signer_role.value}")

    def get_signing_request(self, request_id: str) -> Optional[SigningRequest]:
        with self._lock:
            return self._signing_requests.get(str(request_id))

    def get_signing_request_by_nsdl_id(self, nsdl_request_id: str) -> Optional[SigningRequest]:
        with self._lock:
            for request in self._signing_requests.values():
                if request.nsdl_request_id == nsdl_request_id:
                    return request
            return None

    def update_signing_request(self, request_id: str, **kwargs) -> bool:
        request_id = str(request_id)
        with self._lock:
            if request_id in self._signing_requests:
                for k, v in kwargs.items():
                    if hasattr(self._signing_requests[request_id], k):
                        setattr(self._signing_requests[request_id], k, v)
                    else:
                        logger.warning(f"Attribute {k} not found in SigningRequest")
                logger.info(f"Updated signing request {request_id}: {kwargs}")
                return True
            return False

    def delete_signing_request(self, request_id: str) -> bool:
        with self._lock:
            return self._signing_requests.pop(str(request_id), None) is not None

    def get_all_dual_requests(self) -> Dict[str, DualSigningRequest]:
        with self._lock:
            return self._dual_requests.copy()

    def get_all_signing_requests(self) -> Dict[str, SigningRequest]:
        with self._lock:
            return self._signing_requests.copy()

    def get_expired_dual_requests(self) -> List[DualSigningRequest]:
        with self._lock:
            return [
                req for req in self._dual_requests.values()
                if req.is_expired() and req.status not in [DualSigningStatus.FULLY_SIGNED, DualSigningStatus.EXPIRED]
            ]

    def get_expired_signing_requests(self) -> List[SigningRequest]:
        with self._lock:
            return [
                req for req in self._signing_requests.values()
                if req.is_expired() and req.status not in [SigningRequestStatus.SIGNED, SigningRequestStatus.EXPIRED]
            ]

    def mark_expired_requests(self) -> int:
        with self._lock:
            count = 0
            for req in self._dual_requests.values():
                if req.is_expired() and req.status not in [DualSigningStatus.FULLY_SIGNED, DualSigningStatus.EXPIRED]:
                    req.status = DualSigningStatus.EXPIRED
                    count += 1
                    logger.info(f"Marked dual signing request {req.loan_id} as expired")

            for req in self._signing_requests.values():
                if req.is_expired() and req.status not in [SigningRequestStatus.SIGNED, SigningRequestStatus.EXPIRED]:
                    req.status = SigningRequestStatus.EXPIRED
                    count += 1
                    logger.info(f"Marked signing request {req.request_id} as expired")

            return count

    def get_signing_requests_by_loan_id(self, loan_id: str) -> List[SigningRequest]:
        loan_id = str(loan_id)
        with self._lock:
            return [req for req in self._signing_requests.values() if str(req.loan_id) == loan_id]

    def get_statistics(self) -> Dict[str, int]:
        with self._lock:
            dual_status_counts = {}
            signing_status_counts = {}

            for req in self._dual_requests.values():
                dual_status_counts[req.status.value] = dual_status_counts.get(req.status.value, 0) + 1

            for req in self._signing_requests.values():
                signing_status_counts[req.status.value] = signing_status_counts.get(req.status.value, 0) + 1

            return {
                "total_dual_requests": len(self._dual_requests),
                "total_signing_requests": len(self._signing_requests),
                "dual_status_counts": dual_status_counts,
                "signing_status_counts": signing_status_counts
            }

    def cleanup_old_requests(self, days_old: int = 30) -> int:
        with self._lock:
            cutoff = datetime.utcnow() - timedelta(days=days_old)
            count = 0

            to_delete = [k for k, v in self._dual_requests.items() if v.created_at < cutoff]
            for k in to_delete:
                del self._dual_requests[k]
                count += 1

            to_delete = [k for k, v in self._signing_requests.items() if v.created_at < cutoff]
            for k in to_delete:
                del self._signing_requests[k]
                count += 1

            if count > 0:
                logger.info(f"Cleaned up {count} old requests")
            return count

# Global instance
dual_signing_store = DualSigningStore()
