from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API Key passed in request headers")
api_key_query = APIKeyQuery(name="api_key", auto_error=False, description="API Key passed as a URL query parameter")


async def verify_api_key(
    header_key: str = Security(api_key_header),
    query_key: str = Security(api_key_query),
) -> str:
    """
    Validates API key provided via 'X-API-Key' header or 'api_key' query parameter.
    Raises HTTP 401 Unauthorized if missing or invalid.
    """
    key = header_key or query_key

    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Pass 'X-API-Key' header or '?api_key=' query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key provided.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return key

