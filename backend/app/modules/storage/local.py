"""Local-folder storage, used for development and the first deployment."""

import asyncio
import shutil
from pathlib import Path, PurePosixPath

from app.modules.storage.base import Storage, StorageError


class LocalStorage(Storage):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        # Reject absolute keys and ".." so a key can never escape the storage root.
        posix = PurePosixPath(key)
        if posix.is_absolute() or ".." in posix.parts or not posix.parts:
            raise StorageError(f"Invalid storage key: {key!r}")
        path = (self.root / Path(*posix.parts)).resolve()
        if self.root not in path.parents and path != self.root:
            raise StorageError(f"Invalid storage key: {key!r}")
        return path

    async def ensure_folder(self, prefix: str) -> None:
        try:
            await asyncio.to_thread(self._path(prefix).mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def write(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic on the same disk

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def read(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    async def delete_file(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def delete_folder(self, prefix: str) -> None:
        path = self._path(prefix)

        def _delete() -> None:
            if path.exists():
                shutil.rmtree(path)

        try:
            await asyncio.to_thread(_delete)
        except OSError as exc:
            raise StorageError(str(exc)) from exc
