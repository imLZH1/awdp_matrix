from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AWDP Platform"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "awdp-super-secret-key-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    DATABASE_URL: str = "sqlite+aiosqlite:///./awdp.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Game Config
    TOTAL_TEAMS: int = 50
    BASE_SCORE: float = 500.0
    MIN_SCORE: float = 50.0

    class Config:
        case_sensitive = True

settings = Settings()
