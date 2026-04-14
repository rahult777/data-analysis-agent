import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY: str | None = os.getenv("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_SECRET_KEY: str | None = os.getenv("SUPABASE_SECRET_KEY")
LANGSMITH_API_KEY: str | None = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT: str | None = os.getenv("LANGSMITH_PROJECT")
LANGCHAIN_TRACING_V2: str | None = os.getenv("LANGCHAIN_TRACING_V2")

_REQUIRED_VARS: list[str] = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_TRACING_V2",
]


def validate_config() -> None:
    for var in _REQUIRED_VARS:
        if not os.getenv(var):
            raise ValueError(
                f"Missing required environment variable: {var}. "
                f"Check your .env file and ensure {var} is set."
            )


validate_config()
