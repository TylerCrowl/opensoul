"""Music tab (docs/MUSIC.md): song -> beats, bars and sections -> a shot list cut to the beat.

CPU-only scaffolding: ``registry`` (presets/music_models.json, swappable song / stem / analysis models),
``beats`` (numpy beat, bar and section detection on an audio file), ``shotlist`` (bars -> shot durations that
fit LTX clip lengths) and ``export`` (keepers trimmed to the cut, the song laid under them). No model is
imported or loaded here; song generation and stem separation run behind the registry's runners on the GPU side.
"""
