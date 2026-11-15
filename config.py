import os
from dataclasses import dataclass
from sqlalchemy.engine import URL
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "")
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_name: str = os.getenv("DB_NAME", "")
    db_user: str = os.getenv("DB_USER", "")
    db_password: str = os.getenv("DB_PASSWORD", "")
    admin_ids: tuple[int, ...] = tuple(int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit())
    premium_price_stars: int = int(os.getenv("PREMIUM_PRICE_STARS", "150"))
    premium_days: int = int(os.getenv("PREMIUM_DAYS", "30"))
    broadcast_delay_seconds: float = float(os.getenv("BROADCAST_DELAY_SECONDS", "0.05"))

    @property
    def database_url(self):
        if not all((self.db_name, self.db_user, self.db_password)):
            raise RuntimeError("Set DB_NAME, DB_USER and DB_PASSWORD in HOKAS Environment Variables.")
        return URL.create(
            "mysql+aiomysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

config = Config()
if not config.bot_token:
    raise RuntimeError("BOT_TOKEN is missing. Add it in HOKAS Environment Variables.")
