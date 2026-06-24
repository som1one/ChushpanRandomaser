import json
import os
from typing import Literal

SupportedLanguage = Literal["RU", "EN"]


class Localization:
    def __init__(self, languages_dir: str = None):
        if languages_dir is None:
            languages_dir = os.path.dirname(__file__)
        self._messages: dict[str, dict] = {}
        for lang in ("RU", "EN"):
            path = os.path.join(languages_dir, f"{lang}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._messages[lang] = json.load(f)

    def get(self, key: str, lang: SupportedLanguage = "RU", **kwargs) -> str:
        messages = self._messages.get(lang, self._messages.get("RU", {}))
        text = messages.get(key, key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text
