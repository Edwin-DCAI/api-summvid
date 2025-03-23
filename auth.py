# FastAPI Backend (auth.py)
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import os
from datetime import datetime, timedelta
import jwt

class AuthMiddleware(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self.secret_key = os.getenv('JWT_SECRET_KEY')
        self.allowed_services = {
            'frontend': os.getenv('FRONTEND_API_KEY'),
            # Add more services as needed
        }

    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        
        if not credentials:
            raise HTTPException(
                status_code=403,
                detail="Invalid authorization credentials"
            )

        # Verify the API key
        if request.headers.get('x-api-key') not in self.allowed_services.values():
            raise HTTPException(
                status_code=403,
                detail="Invalid API key"
            )

        try:
            payload = jwt.decode(
                credentials.credentials,
                self.secret_key,
                algorithms=["HS256"]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=403,
                detail="Token has expired"
            )
        except jwt.JWTError:
            raise HTTPException(
                status_code=403,
                detail="Invalid token"
            )

    @staticmethod
    def create_token(service_name: str, secret_key: str, expires_delta: timedelta = timedelta(hours=1)):
        expire = datetime.utcnow() + expires_delta
        to_encode = {
            "sub": service_name,
            "exp": expire
        }
        return jwt.encode(to_encode, secret_key, algorithm="HS256")