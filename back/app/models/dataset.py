"""Dataset and cutoff ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.protein import Protein, Proteoform, Prsm


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cutoffs: Mapped[list["Cutoff"]] = relationship(back_populates="dataset", cascade="all,delete-orphan")


class Cutoff(Base):
    __tablename__ = "cutoffs"
    __table_args__ = (UniqueConstraint("dataset_id", "kind", name="uq_cutoff_dataset_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # "prsm" | "proteoform"
    label: Mapped[str] = mapped_column(String(128))
    data_path: Mapped[str] = mapped_column(Text)

    dataset: Mapped[Dataset] = relationship(back_populates="cutoffs")
    proteins: Mapped[list["Protein"]] = relationship(back_populates="cutoff", cascade="all,delete-orphan")
    proteoforms: Mapped[list["Proteoform"]] = relationship(back_populates="cutoff", cascade="all,delete-orphan")
    prsms: Mapped[list["Prsm"]] = relationship(back_populates="cutoff", cascade="all,delete-orphan")
