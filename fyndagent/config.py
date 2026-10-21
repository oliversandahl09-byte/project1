"""Settings for fyndagent. Shares .env (and the Claude key) with ytagent."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ytagent.config import Settings, load_settings

# Rough rates to the user's currency; override with e.g. FX_USD=10.4 in .env.
DEFAULT_RATES_TO_SEK = {"SEK": 1.0, "EUR": 11.3, "USD": 10.5, "GBP": 13.6, "DKK": 1.52, "NOK": 0.98, "PLN": 2.65}


@dataclass
class FyndSettings:
    base: Settings
    currency: str = "SEK"
    vinted_domain: str = "www.vinted.se"
    depop_country: str = "se"
    grailed_app_id: str = "MNRWEFSS2Q"
    grailed_api_key: str = ""
    rates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATES_TO_SEK))
    use_images: bool = True

    @property
    def out_dir(self):
        return self.base.output_dir / "fynd"

    @property
    def watches_path(self):
        return self.base.data_dir / "fynd_watches.json"

    def to_local(self, amount: float, currency: str) -> float:
        """Converts via SEK so the default table works for any FYND_CURRENCY it contains."""
        cur = (currency or self.currency).upper()
        if cur == self.currency:
            return amount
        if cur not in self.rates or self.currency not in self.rates:
            return amount
        return round(amount * self.rates[cur] / self.rates[self.currency], 2)


def load_fynd_settings(base: Settings | None = None) -> FyndSettings:
    base = base or load_settings()
    env = os.environ.get
    s = FyndSettings(base=base)
    s.currency = (env("FYND_CURRENCY") or s.currency).upper()
    s.vinted_domain = env("VINTED_DOMAIN") or s.vinted_domain
    s.depop_country = env("DEPOP_COUNTRY") or s.depop_country
    s.grailed_app_id = env("GRAILED_ALGOLIA_APP_ID") or s.grailed_app_id
    s.grailed_api_key = env("GRAILED_ALGOLIA_KEY", "")
    for cur in list(s.rates):
        if env(f"FX_{cur}"):
            s.rates[cur] = float(env(f"FX_{cur}"))
    s.use_images = (env("FYND_IMAGES") or "true").strip().lower() in {"1", "true", "yes", "on", "ja"}
    return s
