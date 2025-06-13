import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from logging_config import StructuredLogger

logger = StructuredLogger("api_logger")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.time()
        logger.log_event("api_request", {
            "request_id": request_id,
            "method": request.method,
            "path": str(request.url.path),
            "query_params": dict(request.query_params),
            "client_ip": request.client.host,
            "user_agent": request.headers.get("user-agent"),
        })

        response = await call_next(request)

        process_time = time.time() - start_time

        logger.log_event("api_response", {
            "request_id": request_id,
            "status_code": response.status_code,
            "process_time_seconds": round(process_time, 4),
        })

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time, 4))

        return response
