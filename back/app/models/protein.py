"""Protein / Proteoform / PrSM ORM models.

Heavy nested structures (annotated_protein, matched_ions, envelopes) are stored
as JSONB columns so the detail page can be rendered without touching the raw
``.js`` source files.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.dataset import Cutoff


class Protein(Base):
    __tablename__ = "proteins"
    __table_args__ = (
        UniqueConstraint("cutoff_id", "sequence_id", name="uq_protein_cutoff_seq"),
        Index("ix_protein_cutoff_name", "cutoff_id", "sequence_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cutoff_id: Mapped[int] = mapped_column(ForeignKey("cutoffs.id", ondelete="CASCADE"), index=True)
    sequence_id: Mapped[int] = mapped_column(Integer)
    sequence_name: Mapped[str] = mapped_column(String(255))
    sequence_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    compatible_proteoform_number: Mapped[int] = mapped_column(Integer, default=0)
    prsm_number: Mapped[int] = mapped_column(Integer, default=0)
    best_prsm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_prsm_e_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    cutoff: Mapped[Cutoff] = relationship(back_populates="proteins")
    proteoforms: Mapped[list["Proteoform"]] = relationship(
        back_populates="protein", cascade="all,delete-orphan"
    )


class Proteoform(Base):
    __tablename__ = "proteoforms"
    __table_args__ = (
        UniqueConstraint("cutoff_id", "protein_id", "proteoform_id", name="uq_proteoform_protein_id"),
        Index("ix_proteoform_protein", "protein_id"),
        Index("ix_proteoform_cutoff_seq", "cutoff_id", "sequence_id", "proteoform_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cutoff_id: Mapped[int] = mapped_column(ForeignKey("cutoffs.id", ondelete="CASCADE"), index=True)
    protein_id: Mapped[int] = mapped_column(ForeignKey("proteins.id", ondelete="CASCADE"))
    proteoform_id: Mapped[int] = mapped_column(Integer)
    sequence_id: Mapped[int] = mapped_column(Integer)
    sequence_name: Mapped[str] = mapped_column(String(255))
    proteoform_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    prsm_number: Mapped[int] = mapped_column(Integer, default=0)
    best_prsm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_prsm_e_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_acetylation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unexpected_shift_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    protein: Mapped[Protein] = relationship(back_populates="proteoforms")
    cutoff: Mapped[Cutoff] = relationship(back_populates="proteoforms")
    prsms: Mapped[list["Prsm"]] = relationship(back_populates="proteoform", cascade="all,delete-orphan")


class Prsm(Base):
    __tablename__ = "prsms"
    __table_args__ = (
        UniqueConstraint("cutoff_id", "prsm_id", name="uq_prsm_cutoff_id"),
        Index("ix_prsm_proteoform", "proteoform_id"),
        Index("ix_prsm_evalue", "cutoff_id", "e_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cutoff_id: Mapped[int] = mapped_column(ForeignKey("cutoffs.id", ondelete="CASCADE"), index=True)
    proteoform_id: Mapped[int] = mapped_column(ForeignKey("proteoforms.id", ondelete="CASCADE"))
    prsm_id: Mapped[int] = mapped_column(Integer)
    sequence_id: Mapped[int] = mapped_column(Integer)

    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    e_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    fdr: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_fragment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_peak_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    spectrum_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms1_scans: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms2_scans: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms1_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms2_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    precursor_mono_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    precursor_charge: Mapped[int | None] = mapped_column(Integer, nullable=True)
    precursor_mz: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_inte: Mapped[float | None] = mapped_column(Float, nullable=True)
    proteoform_mass: Mapped[float | None] = mapped_column(Float, nullable=True)

    annotated_protein: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ms_header: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ms_peaks: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    cutoff: Mapped[Cutoff] = relationship(back_populates="prsms")
    proteoform: Mapped[Proteoform] = relationship(back_populates="prsms")
