"""Read queries for normalized medicine regulatory data."""
from sqlalchemy import and_, case, desc, func, literal, or_
from sqlalchemy.orm import joinedload

from server.database.medicine_models import (
    MedicineIngredient,
    MedicineOrganization,
    MedicineProduct,
    MedicineProductIngredient,
    MedicineRegulatoryEvent,
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _contains(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _product_options():
    return (
        joinedload(MedicineProduct.organizations),
        joinedload(MedicineProduct.ingredients).joinedload(MedicineProductIngredient.ingredient),
        joinedload(MedicineProduct.regulatory_events).joinedload(MedicineRegulatoryEvent.document),
        joinedload(MedicineProduct.regulatory_events).joinedload(MedicineRegulatoryEvent.batch),
        joinedload(MedicineProduct.batches),
    )


def search_medicine_products(db, fields: dict[str, str], limit: int):
    """Return (product, relevance, match_type) rows and a has-more flag."""
    query = db.query(MedicineProduct).options(*_product_options())

    name = fields.get("name", "")
    name_lower = " ".join(name.lower().split())
    compact_name = "".join(name_lower.split())
    exact_name = literal(False)
    exact_ingredient = literal(False)
    prefix_name = literal(False)
    contains_name = literal(False)

    if name:
        token_conditions = []
        for token in name_lower.split():
            term = _contains(token)
            token_conditions.append(
                or_(
                    MedicineProduct.product_name.ilike(term, escape="\\"),
                    MedicineProduct.brand_name.ilike(term, escape="\\"),
                    MedicineProduct.normalized_search_name.ilike(term, escape="\\"),
                    func.replace(func.lower(MedicineProduct.product_name), " ", "").ilike(
                        _contains(token.replace(" ", "")), escape="\\"
                    ),
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.ingredient.has(
                            or_(
                                MedicineIngredient.name.ilike(term, escape="\\"),
                                MedicineIngredient.normalized_name.ilike(term, escape="\\"),
                            )
                        )
                    ),
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.strength_text.ilike(term, escape="\\")
                    ),
                )
            )
        query = query.filter(or_(and_(*token_conditions)))

        exact_name = or_(
            func.lower(MedicineProduct.product_name) == name_lower,
            func.lower(MedicineProduct.brand_name) == name_lower,
            func.lower(MedicineProduct.normalized_search_name) == name_lower,
            func.replace(
                func.lower(func.coalesce(MedicineProduct.normalized_search_name, "")), " ", ""
            ) == compact_name,
        )
        exact_ingredient = MedicineProduct.ingredients.any(
            MedicineProductIngredient.ingredient.has(
                or_(
                    func.lower(MedicineIngredient.name) == name_lower,
                    func.lower(MedicineIngredient.normalized_name) == name_lower,
                )
            )
        )
        prefix_name = or_(
            MedicineProduct.product_name.ilike(f"{_escape_like(name_lower)}%", escape="\\"),
            MedicineProduct.brand_name.ilike(f"{_escape_like(name_lower)}%", escape="\\"),
            MedicineProduct.normalized_search_name.ilike(
                f"{_escape_like(name_lower)}%", escape="\\"
            ),
        )
        contains_name = or_(
            MedicineProduct.product_name.ilike(_contains(name_lower), escape="\\"),
            MedicineProduct.brand_name.ilike(_contains(name_lower), escape="\\"),
            MedicineProduct.normalized_search_name.ilike(_contains(name_lower), escape="\\"),
        )

    manufacturer = fields.get("manufacturer", "")
    if manufacturer:
        term = _contains(manufacturer)
        query = query.filter(
            MedicineProduct.organizations.any(
                or_(
                    MedicineOrganization.name.ilike(term, escape="\\"),
                    MedicineOrganization.normalized_name.ilike(term, escape="\\"),
                )
            )
        )

    dosage_form = fields.get("dosage_form", "")
    if dosage_form:
        query = query.filter(
            MedicineProduct.dosage_form.ilike(_contains(dosage_form), escape="\\")
        )

    ingredient = fields.get("ingredient", "")
    if ingredient:
        for token in ingredient.split():
            term = _contains(token)
            query = query.filter(
                MedicineProduct.ingredients.any(
                    MedicineProductIngredient.ingredient.has(
                        or_(
                            MedicineIngredient.name.ilike(term, escape="\\"),
                            MedicineIngredient.normalized_name.ilike(term, escape="\\"),
                        )
                    )
                )
            )

    strength = fields.get("strength", "")
    if strength:
        compact_strength = "".join(strength.lower().split())
        query = query.filter(
            or_(
                MedicineProduct.strength.ilike(_contains(strength), escape="\\"),
                func.replace(
                    func.lower(func.coalesce(MedicineProduct.strength, "")), " ", ""
                ).ilike(_contains(compact_strength), escape="\\"),
                MedicineProduct.ingredients.any(
                    or_(
                        MedicineProductIngredient.strength_text.ilike(
                            _contains(strength), escape="\\"
                        ),
                        func.replace(
                            func.lower(
                                func.coalesce(MedicineProductIngredient.strength_text, "")
                            ),
                            " ",
                            "",
                        ).ilike(_contains(compact_strength), escape="\\"),
                    )
                ),
            )
        )

    batch_number = fields.get("batch_number", "")
    if batch_number:
        query = query.filter(
            MedicineProduct.batches.any(
                MedicineProduct.batches.property.mapper.class_.batch_number.ilike(
                    _contains(batch_number), escape="\\"
                )
            )
        )

    if name:
        relevance = case(
            (exact_name, 100),
            (prefix_name, 90),
            (contains_name, 80),
            (exact_ingredient, 75),
            else_=50,
        )
        match_type = case(
            (or_(exact_name, exact_ingredient), "EXACT"),
            (or_(prefix_name, contains_name), "PARTIAL"),
            else_="PARTIAL",
        )
    else:
        relevance = literal(50)
        match_type = literal("PARTIAL")

    match_priority = case(
        (match_type == "EXACT", 3),
        (match_type == "PARTIAL", 2),
        else_=1,
    )
    rows = (
        query.add_columns(relevance.label("relevance"), match_type.label("match_type"))
        .distinct()
        .order_by(
            desc(match_priority),
            desc("relevance"),
            MedicineProduct.product_name.asc(),
            MedicineProduct.id.asc(),
        )
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    matches = [
        (product, int(round(float(score or 0))), match)
        for product, score, match in rows[:limit]
    ]
    return matches, has_more


def find_product_by_id(db, product_id: int):
    return db.query(MedicineProduct).options(*_product_options()).filter(MedicineProduct.id == product_id).first()
