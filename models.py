from __future__ import annotations
from pydantic import BaseModel, HttpUrl

class Listing(BaseModel):
    source: str
    url: HttpUrl
    price: int | None = None
    beds: int | None = None
    baths: float | None = None
    address: str | None = None
    neighborhood: str | None = None
    thumbnail_url: str | None = None

    def matches(self, *, min_beds: int, min_baths: int, max_rent: int) -> bool:
        if self.price is not None and self.price > max_rent:
            return False
        if self.beds is not None and self.beds < min_beds:
            return False
        if self.baths is not None and self.baths < float(min_baths):
            return False
        return True