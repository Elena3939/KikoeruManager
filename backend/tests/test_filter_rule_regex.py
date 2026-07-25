import re
from pathlib import Path

import yaml


def test_no_se_filter_does_not_match_se_ari_paths():
    config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    rules = config["filter"]["rules"]
    pattern = next(rule["pattern"] for rule in rules if "无 SE" in rule["name"])

    for path in (
        "wave/02.SEなし/01.wav",
        "voice/SE CUT/01.wav",
        "voice/without-se.wav",
        "voice/不含音效.wav",
        "voice/BGMなし.wav",
    ):
        assert re.search(pattern, path, re.IGNORECASE), path

    for path in (
        "wave/01.SEあり/01.wav",
        "mp3/01.SEあり/01.mp3",
        "voice/SE.wav",
        "voice/soundtrack.wav",
    ):
        assert not re.search(pattern, path, re.IGNORECASE), path
