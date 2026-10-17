from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings
from app.modules.storage.base import Storage, StorageError, demand_folder
from app.modules.storage.local import LocalStorage

__all__ = ["Storage", "StorageError", "demand_folder", "get_storage", "StorageDep"]


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> Storage:
    # Later: return GcsStorage(...) when settings say so.
    return LocalStorage(settings.storage_root)


StorageDep = Annotated[Storage, Depends(get_storage)]
