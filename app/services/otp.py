from enum import Enum
from typing import Optional
from app.redis_client import redis_client


class OTPPurpose(str, Enum):
    PASSWORD_RESET = "password_reset"
    PROFILE_PASSWORD_RESET = "profile_password_reset"
    LOGIN = "login"
    REGISTER = "register"


class OTPService:
    PREFIX = "pagewise_otp"

    @classmethod
    def key(cls, purpose: OTPPurpose | str, email: str) -> str:
        purpose_str = purpose.value if isinstance(purpose, Enum) else str(purpose)
        return f"{cls.PREFIX}:{purpose_str}:{email.lower().strip()}"

    @classmethod
    async def save(cls, purpose: OTPPurpose | str, email: str, otp: str, expire_seconds: int = 600):
        await redis_client.set(cls.key(purpose, email), str(otp), ex=expire_seconds)

    @classmethod
    async def get(cls, purpose: OTPPurpose | str, email: str) -> Optional[str]:
        return await redis_client.get(cls.key(purpose, email))

    @classmethod
    async def delete(cls, purpose: OTPPurpose | str, email: str):
        await redis_client.delete(cls.key(purpose, email))
