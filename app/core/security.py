from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from app.config import settings

_api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="API Key in request header",
)
_api_key_query = APIKeyQuery(
    name="api_key",
    auto_error=False,
    description="API Key as query parameter",
)


async def verify_api_key(
    header_key: str = Security(_api_key_header),
    query_key: str = Security(_api_key_query),
) -> str:
    """Validates API key from header or query param. Raises HTTP 401 if invalid."""
    key = header_key or query_key
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Provide 'X-API-Key' header or '?api_key=' query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key

