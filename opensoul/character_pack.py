"""Character pack: refs, prompt lock, seeds, optional LoRA path."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CharacterPack:
    name: str
    prompt_lock: str
    negative_prompt: str = (
        "deformed, extra fingers, bad anatomy, lowres, watermark, text, logo"
    )
    seed: int = 42
    ref_images: list[str] = field(default_factory=list)
    lora_path: str | None = None
    lora_strength: float = 0.8
    notes: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    meta: dict[str, Any] = field(default_factory=dict)
    # Optional: the pronoun the lip-sync prompt uses ('she', 'he', 'they'; free text like 'she/her' is fine).
    # Older packs without it load as 'they', or from a legacy "pronouns" key / meta (opensoul.lipsync.pronoun_from_meta).
    pronoun: str = "they"
    # Top-level keys this class doesn't model (e.g. voice_label, voice_label_notes): kept as loaded and written back
    # by save(), after the modelled keys, so a load + save never drops them. Not a pack.json key itself.
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def save(self, directory: str | Path) -> Path:
        """Write pack.json and copy reference images into directory."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        refs_dir = root / "refs"
        refs_dir.mkdir(exist_ok=True)

        copied: list[str] = []
        for i, src in enumerate(self.ref_images):
            src_p = Path(src)
            if not src_p.is_file():
                raise FileNotFoundError(f"reference image not found: {src}")
            dest_name = f"ref_{i:02d}{src_p.suffix.lower() or '.png'}"
            dest = refs_dir / dest_name
            shutil.copy2(src_p, dest)
            copied.append(str(Path("refs") / dest_name))

        payload = asdict(self)
        extra = payload.pop("extra", None) or {}
        payload["ref_images"] = copied
        for k, v in extra.items():  # unknown keys round-trip; a modelled key always wins
            payload.setdefault(k, v)
        out = root / "pack.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out

    @classmethod
    def load(cls, directory: str | Path) -> CharacterPack:
        root = Path(directory)
        data = json.loads((root / "pack.json").read_text(encoding="utf-8"))
        refs = [str(root / r) if not Path(r).is_absolute() else r for r in data.get("ref_images", [])]
        data["ref_images"] = refs
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        # dataclass fields
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in fields and k != "extra"}
        filtered["extra"] = {k: v for k, v in data.items() if k not in fields or k == "extra"}
        if not str(filtered.get("pronoun") or "").strip():
            from opensoul.lipsync import pronoun_from_meta

            filtered["pronoun"] = pronoun_from_meta(data)
        return cls(**filtered)

    def prompt_with_lock(self, scene: str) -> str:
        scene = scene.strip()
        lock = self.prompt_lock.strip()
        if not lock:
            return scene
        if not scene:
            return lock
        return f"{lock}, {scene}"
