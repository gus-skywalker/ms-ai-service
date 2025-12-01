from __future__ import annotations

import pickle
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.core.config import get_settings


@dataclass(frozen=True)
class ModelKey:
    feature: str
    version: str
    user_id: Optional[str] = None

    @property
    def scope(self) -> str:
        return "user" if self.user_id else "global"


class ModelRegistry:
    """Filesystem-backed registry for feature models."""

    def __init__(
        self,
        base_dir: Path,
        cache_enabled: bool = True,
        max_cache_entries: int = 32,
    ) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._cache_enabled = cache_enabled
        self._max_cache_entries = max_cache_entries
        self._cache: "OrderedDict[ModelKey, Any]" = OrderedDict()

    # Public API ------------------------------------------------------------
    def load_model(self, key: ModelKey) -> Any | None:
        if self._cache_enabled:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        path = self._resolve_path(key)
        if not path.exists():
            return None

        with path.open("rb") as fh:
            model = pickle.load(fh)

        self._remember_cache(key, model)
        return model

    def save_model(self, key: ModelKey, model: Any) -> Path:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("wb") as fh:
            pickle.dump(model, fh)

        self._remember_cache(key, model)
        return path

    def delete_model(self, key: ModelKey) -> None:
        path = self._resolve_path(key)
        if path.exists():
            path.unlink()
        self._forget_cache(key)

    def list_user_ids(self, feature: str, version: str) -> Iterable[str]:
        user_dir = self._base_dir / feature / version / "user"
        if not user_dir.exists():
            return []
        return [p.stem for p in user_dir.glob("*.pkl")]

    # Internal helpers ------------------------------------------------------
    def _resolve_path(self, key: ModelKey) -> Path:
        base = self._base_dir / key.feature / key.version
        if key.user_id:
            return base / "user" / f"{key.user_id}.pkl"
        return base / "global.pkl"

    def _remember_cache(self, key: ModelKey, model: Any) -> None:
        if not self._cache_enabled:
            return
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = model
        if len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)

    def _forget_cache(self, key: ModelKey) -> None:
        if not self._cache_enabled:
            return
        self._cache.pop(key, None)


_registry_singleton: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    global _registry_singleton
    if _registry_singleton is None:
        settings = get_settings()
        base_dir = Path(settings.AI_MODEL_DIR)
        _registry_singleton = ModelRegistry(base_dir=base_dir)
    return _registry_singleton

