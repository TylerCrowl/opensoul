"""OpenSoul node pack for ComfyUI: Kokoro / Chatterbox TTS, LatentSync lip-sync and an
ArcFace identity-consistency gate. Heavy models run in their own Python envs via small
runner scripts, so this pack adds no dependencies to the ComfyUI env."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
