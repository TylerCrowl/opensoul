"""OpenSoul — consistent-character toolkit on the Comfy Developer Platform."""

__version__ = "0.1.0"

from opensoul.character_pack import CharacterPack
from opensoul.consistency import ConsistencyResult, score_consistency

__all__ = [
    "__version__",
    "CharacterPack",
    "ConsistencyResult",
    "score_consistency",
]
