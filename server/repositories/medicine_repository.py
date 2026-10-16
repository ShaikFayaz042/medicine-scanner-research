"""Read queries for normalized medicine regulatory data."""
from sqlalchemy import and_, case, desc, func, literal, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import joinedload

from server.database.medicine_models import (
    MedicineBatch,
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


def _is_missing_word_similarity(error: DBAPIError) -> bool:
    original = error.orig
    code = getattr(original, "pgcode", None)
    message = str(original).casefold()
    return (code == "42883" and "word_similarity" in message) or (
        "no such function: word_similarity" in message
    )


def search_medicine_products(
    db, fields: dict[str, str], limit: int, *, use_fuzzy: bool = True
):
    """Return (product, relevance, match_type) rows and a has-more flag."""
    query = db.query(MedicineProduct).options(*_product_options())

    name = fields.get("name", "")
    name_lower = " ".join(name.lower().split())
    compact_name = "".join(name_lower.split())
    exact_conditions = []
    partial_conditions = []
    fuzzy_match = literal(False)
    fuzzy_relevance = literal(60)

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
        if use_fuzzy:
            fuzzy_similarities = [
                func.word_similarity(name_lower, MedicineProduct.product_name),
                func.word_similarity(
                    name_lower, func.coalesce(MedicineProduct.brand_name, "")
                ),
                func.word_similarity(name_lower, MedicineProduct.normalized_search_name),
            ]
            fuzzy_similarity = fuzzy_similarities[0]
            for similarity in fuzzy_similarities[1:]:
                fuzzy_similarity = case(
                    (fuzzy_similarity >= similarity, fuzzy_similarity),
                    else_=similarity,
                )
            fuzzy_match = fuzzy_similarity >= 0.55
            fuzzy_relevance = func.round(60 + fuzzy_similarity * 20)
        query = query.filter(or_(and_(*token_conditions), fuzzy_match))

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
        exact_conditions.extend((exact_name, exact_ingredient))
        partial_conditions.extend((prefix_name, contains_name))

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
        exact_conditions.append(
            MedicineProduct.organizations.any(
                func.lower(MedicineOrganization.name) == manufacturer.casefold()
            )
        )
        partial_conditions.append(
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
        exact_conditions.append(func.lower(MedicineProduct.dosage_form) == dosage_form.casefold())
        partial_conditions.append(
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
        exact_conditions.append(
            and_(
                *[
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.ingredient.has(
                            or_(
                                func.lower(MedicineIngredient.name) == token.casefold(),
                                func.lower(MedicineIngredient.normalized_name) == token.casefold(),
                            )
                        )
                    )
                    for token in ingredient.split()
                ]
            )
        )
        partial_conditions.append(
            and_(
                *[
                    MedicineProduct.ingredients.any(
                        MedicineProductIngredient.ingredient.has(
                            or_(
                                MedicineIngredient.name.ilike(_contains(token), escape="\\"),
                                MedicineIngredient.normalized_name.ilike(_contains(token), escape="\\"),
                            )
                        )
                    )
                    for token in ingredient.split()
                ]
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
        exact_conditions.append(
            or_(
                func.lower(func.coalesce(MedicineProduct.strength, "")) == strength.casefold(),
                MedicineProduct.ingredients.any(
                    func.lower(func.coalesce(MedicineProductIngredient.strength_text, ""))
                    == strength.casefold()
                ),
            )
        )
        partial_conditions.append(
            or_(
                MedicineProduct.strength.ilike(_contains(strength), escape="\\"),
                MedicineProduct.ingredients.any(
                    MedicineProductIngredient.strength_text.ilike(
                        _contains(strength), escape="\\"
                    )
                ),
            )
        )

    batch_number = fields.get("batch_number", "")
    if batch_number:
        query = query.filter(
            MedicineProduct.batches.any(
                MedicineBatch.batch_number.ilike(_contains(batch_number), escape="\\")
            )
        )
        exact_conditions.append(
            MedicineProduct.batches.any(
                func.lower(MedicineBatch.batch_number) == batch_number.casefold()
            )
        )
        partial_conditions.append(
            MedicineProduct.batches.any(
                MedicineBatch.batch_number.ilike(_contains(batch_number), escape="\\")
            )
        )

    exact_match = or_(*exact_conditions) if exact_conditions else literal(False)
    exact_name_match = or_(exact_name, exact_ingredient) if name else literal(False)
    partial_match = or_(*partial_conditions) if partial_conditions else literal(False)
    relevance_conditions = [(exact_name_match, 100), (exact_match, 95)]
    if partial_conditions:
        relevance_conditions.append((partial_match, 80))
    relevance_conditions.append((fuzzy_match, fuzzy_relevance))
    relevance = case(*relevance_conditions, else_=60)
    match_type = case(
        (exact_match, "EXACT"),
        (partial_match, "PARTIAL"),
        (fuzzy_match, "FUZZY"),
        else_="PARTIAL",
    )
    try:
        rows = (
            query.add_columns(relevance.label("relevance"), match_type.label("match_type"))
            .distinct()
            .order_by(
                desc("relevance"),
                MedicineProduct.product_name.asc(),
                MedicineProduct.id.asc(),
            )
            .limit(limit + 1)
            .all()
        )
    except DBAPIError as error:
        if not use_fuzzy or not name or not _is_missing_word_similarity(error):
            raise
        db.rollback()
        return search_medicine_products(db, fields, limit, use_fuzzy=False)

    has_more = len(rows) > limit
    matches = [
        (product, int(round(float(score or 0))), match)
        for product, score, match in rows[:limit]
    ]
    return matches, has_more


def find_product_by_id(db, product_id: int):
    return db.query(MedicineProduct).options(*_product_options()).filter(MedicineProduct.id == product_id).first()
