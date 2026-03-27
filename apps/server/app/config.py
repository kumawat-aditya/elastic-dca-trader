from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # EA & System Params
    EA_TIMEOUT_SECONDS: int = 10
    CROSSOVER_TICK_COUNT: int = 5
    
    # Hedge Math
    HEDGE_TP_PCT: float = 100.0
    HEDGE_SL_PCT: float = 50.0

    class Config:
        env_file = ".env"

settings = Settings()