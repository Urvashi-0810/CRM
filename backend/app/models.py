"""Imports every model so SQLAlchemy metadata (and Alembic) sees all tables."""

from app.modules.admin.models import AppSettings  # noqa: F401
from app.modules.auth.models import LoginSession  # noqa: F401
from app.modules.users.models import NameChangeRequest, User  # noqa: F401
from app.modules.demands.models import DemandLetter, DemandTrade, IdempotencyKey, StoredFile  # noqa: F401
from app.modules.chat.models import ChatMessage  # noqa: F401
from app.modules.jobs.models import GenerationJob  # noqa: F401
from app.modules.letters.models import LetterVersion  # noqa: F401
from app.modules.ai_admin.models import (  # noqa: F401
    Letterhead, LlmCall, LlmProviderConfig, PromptVersion, ReferenceLetter,
)
