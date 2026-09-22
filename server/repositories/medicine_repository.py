"""Read queries for normalized medicine regulatory data."""
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from server.database.medicine_models import (
    MedicineIngredient,
    MedicineOrganization,
    MedicineProduct,
    MedicineProductIngredient,
    MedicineRegulatoryEvent,
)


def _product_options():
    return (
        joinedload(MedicineProduct.organizations),
        joinedload(MedicineProduct.ingredients).joinedload(MedicineProductIngredient.ingredient),
        joinedload(MedicineProduct.regulatory_events).joinedload(MedicineRegulatoryEvent.document),
    )


def find_products(db, fields: dict[str, str], limit: int):
    query = db.query(MedicineProduct).options(*_product_options())

    name = fields.get("name", "")
    if name:
        for token in name.split():
            term = f"%{token}%"
            compact_term = f"%{token.replace(' ', '')}%"
            query = query.filter(
                or_(
                    MedicineProduct.product_name.ilike(term),
                    MedicineProduct.brand_name.ilike(term),
                    MedicineProduct.normalized_search_name.ilike(term),
                    MedicineProduct.strength.ilike(term),
                    func.replace(MedicineProduct.product_name, " ", "").ilike(compact_term),
                    func.replace(MedicineProduct.strength, " ", "").ilike(compact_term),
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.ingredient.has(
                            or_(
                                MedicineIngredient.name.ilike(term),
                                MedicineIngredient.normalized_name.ilike(term),
                            )
                        )
                    ),
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.strength_text.ilike(term)
                    ),
                )
            )

    manufacturer = fields.get("manufacturer", "")
    if manufacturer:
        term = f"%{manufacturer}%"
        query = query.join(MedicineProduct.organizations).filter(
            or_(
                MedicineOrganization.name.ilike(term),
                MedicineOrganization.normalized_name.ilike(term),
            )
        )

    dosage_form = fields.get("dosage_form", "")
    if dosage_form:
        query = query.filter(MedicineProduct.dosage_form.ilike(f"%{dosage_form}%"))

    ingredient = fields.get("ingredient", "")
    if ingredient:
        term = f"%{ingredient}%"
        query = query.filter(
            MedicineProduct.ingredients.any(
                MedicineProductIngredient.ingredient.has(
                    or_(MedicineIngredient.name.ilike(term), MedicineIngredient.normalized_name.ilike(term))
                )
            )
        )

    strength = fields.get("strength", "")
    if strength:
        compact_strength = strength.replace(" ", "")
        query = query.filter(
            or_(
                MedicineProduct.strength.ilike(f"%{strength}%"),
                func.replace(MedicineProduct.strength, " ", "").ilike(f"%{compact_strength}%"),
                MedicineProduct.ingredients.any(
                    MedicineProductIngredient.strength_text.ilike(f"%{strength}%")
                ),
            )
        )

    return query.distinct().order_by(MedicineProduct.product_name.asc(), MedicineProduct.id.asc()).limit(limit).all()


def find_product_by_id(db, product_id: int):
    return db.query(MedicineProduct).options(*_product_options()).filter(MedicineProduct.id == product_id).first()
