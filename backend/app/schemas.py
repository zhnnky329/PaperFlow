from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class Affiliation(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("authors")
    @classmethod
    def bounded_authors(cls, value):
        if any(len(name) > 500 for name in value):
            raise ValueError("Author name too long")
        return value


class MetadataChoice(BaseModel):
    doi: str = Field(min_length=1, max_length=300)


class PaperPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=1000)
    authors: list[str] | None = Field(None, max_length=100)
    abstract: str | None = Field(None, max_length=30000)
    year: int | None = Field(None, ge=1500, le=2200)
    source_url: str | None = Field(None, max_length=2000)
    read_status: Literal["unread", "reading", "finished"] | None = None
    tags: list[str] | None = Field(None, max_length=100)
    collections: list[str] | None = Field(None, max_length=100)
    collection_ids: list[UUID] | None = Field(None, max_length=100)
    doi: str | None = Field(None, max_length=300)
    venue: str | None = Field(None, max_length=1000)
    venue_kind: Literal["journal", "conference"] | None = None
    affiliations: list[Affiliation] | None = Field(None, max_length=100)

    @field_validator("doi")
    @classmethod
    def valid_doi(cls, value):
        from .metadata import normalize_doi

        if not value:
            return None
        normalized = normalize_doi(value)
        if normalized is None:
            raise ValueError("Invalid DOI")
        return normalized

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value):
        from urllib.parse import urlsplit

        if value and (urlsplit(value).scheme != "https" or not urlsplit(value).hostname):
            raise ValueError("Only HTTPS source links are allowed")
        return value


class ArxivInput(BaseModel):
    input: str = Field(max_length=300)


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CollectionInput(NameInput):
    parent_id: UUID | None = None


class CollectionPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    parent_id: UUID | None = None


class ReadingPosition(BaseModel):
    pdf_page: int = Field(1, ge=1, le=100000)
    pdf_scale: float = Field(1, ge=0.25, le=4)
    html_anchor: str = Field("", max_length=200, pattern=r"^[\w-]*$")
    scroll_ratio: float = Field(0, ge=0, le=1)


class SettingsPatch(BaseModel):
    model_config = {"extra": "forbid"}
    theme: Literal["system", "light", "dark"] | None = None
    font_scale: int | None = Field(None, ge=14, le=24)
    reader_width: int | None = Field(None, ge=600, le=1000)
    marker_mode: Literal["fast", "balanced"] | None = None
    auto_convert_on_import: bool | None = None


class ConvertInput(BaseModel):
    force_rebuild: bool = False
