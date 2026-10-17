"""Storage interface. All file access in the app goes through this.

Keys are always relative paths with forward slashes, e.g.
    demands/AA00001/inputs/inquiry.docx
never absolute paths, so moving from local folders to Google Cloud Storage
later only means adding another implementation of this class.
"""

from abc import ABC, abstractmethod


class StorageError(Exception):
    """A storage operation failed (disk error, permissions, network...)."""


def demand_folder(demand_code: str) -> str:
    """Folder (key prefix) holding every file of one demand letter."""
    return f"demands/{demand_code}"


class Storage(ABC):
    @abstractmethod
    async def ensure_folder(self, prefix: str) -> None:
        """Create the folder if the backend has real folders (no-op for object stores)."""

    @abstractmethod
    async def write(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete_file(self, key: str) -> None:
        """Delete one file. Succeeds if it is already gone."""

    @abstractmethod
    async def delete_folder(self, prefix: str) -> None:
        """Delete everything under prefix. Succeeds if it is already gone.

        Raises StorageError if anything could not be removed.
        """
