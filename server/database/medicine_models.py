"""Read models for the deployed normalized medicine regulatory schema."""
from sqlalchemy import BigInteger, Column, Date, ForeignKey, String, Table, Text, and_
from sqlalchemy.orm import relationship

from server.config import MEDICINE_DB_SCHEMA
from server.database.database import Base


MEDICINE_SCHEMA = MEDICINE_DB_SCHEMA


product_organizations = Table(
    "product_organizations",
    Base.metadata,
    Column("product_id", BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.products.product_id")),
    Column("organization_id", BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.organizations.organization_id")),
    Column("role", String(50)),
    schema=MEDICINE_SCHEMA,
)


class MedicineOrganization(Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    id = Column("organization_id", BigInteger, primary_key=True)
    name = Column("organization_name", Text, nullable=False)
    normalized_name = Column(Text, nullable=False)


class MedicineIngredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    id = Column("ingredient_id", BigInteger, primary_key=True)
    name = Column("ingredient_name", Text, nullable=False)
    normalized_name = Column(Text, nullable=False)


class MedicineProduct(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    id = Column("product_id", BigInteger, primary_key=True)
    product_name = Column(Text, nullable=False)
    normalized_search_name = Column("normalized_name", Text, nullable=False)
    brand_name = Column(Text)
    dosage_form = Column(Text)
    strength = Column(Text)

    organizations = relationship(
        "MedicineOrganization",
        secondary=product_organizations,
        primaryjoin=id == product_organizations.c.product_id,
        secondaryjoin=and_(
            MedicineOrganization.id == product_organizations.c.organization_id,
            product_organizations.c.role == "MANUFACTURER",
        ),
        viewonly=True,
    )
    ingredients = relationship("MedicineProductIngredient", back_populates="product")
    regulatory_events = relationship("MedicineRegulatoryEvent", back_populates="product")

    @property
    def manufacturer(self):
        return next(iter(self.organizations), None)


class MedicineProductIngredient(Base):
    __tablename__ = "product_ingredients"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    product_id = Column(BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.products.product_id"), primary_key=True)
    ingredient_id = Column(BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.ingredients.ingredient_id"), primary_key=True)
    strength_text = Column("ingredient_strength", Text)

    product = relationship("MedicineProduct", back_populates="ingredients")
    ingredient = relationship("MedicineIngredient")


class MedicineRegulatoryDocument(Base):
    __tablename__ = "regulatory_documents"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    id = Column("document_id", BigInteger, primary_key=True)
    source_org = Column("source_organization", Text, nullable=False)
    document_type = Column(String(100), nullable=False)
    title = Column("document_title", Text)
    publication_date = Column(Date)
    source_url = Column(Text)
    pdf_filename = Column("filename", Text)


class MedicineRegulatoryEvent(Base):
    __tablename__ = "regulatory_events"
    __table_args__ = {"schema": MEDICINE_SCHEMA}

    id = Column("event_id", BigInteger, primary_key=True)
    document_id = Column(BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.regulatory_documents.document_id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey(f"{MEDICINE_SCHEMA}.products.product_id"))
    source_record_id = Column(Text)
    event_type = Column(String(100), nullable=False)
    status = Column(String(50))
    legal_status = Column(Text)
    reason = Column(Text)
    effective_date = Column("event_date", Date)
    action = Column(Text)

    product = relationship("MedicineProduct", back_populates="regulatory_events")
    document = relationship("MedicineRegulatoryDocument")


__all__ = [
    "MedicineIngredient",
    "MedicineOrganization",
    "MedicineProduct",
    "MedicineProductIngredient",
    "MedicineRegulatoryDocument",
    "MedicineRegulatoryEvent",
]
