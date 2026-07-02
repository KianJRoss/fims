from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.store_time import store_now
from app.db.session import get_db
from app.models.discount import Deal, DealCondition, DealReward

router = APIRouter()


class DealConditionPayload(BaseModel):
    condition_type: str
    quantity: int | None = None
    min_amount: float | None = None
    product_id: str | None = None
    category_id: int | None = None


class DealRewardPayload(BaseModel):
    reward_type: str
    percent_off: float | None = None
    flat_off: float | None = None
    product_id: str | None = None
    category_id: int | None = None
    quantity: int = 1


class DealCreatePayload(BaseModel):
    name: str
    deal_type: str
    priority: int = 0
    is_active: bool = True
    is_stackable: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    notes: str | None = None
    conditions: list[DealConditionPayload] = Field(default_factory=list)
    rewards: list[DealRewardPayload] = Field(default_factory=list)


class DealUpdatePayload(BaseModel):
    name: str | None = None
    deal_type: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    is_stackable: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    notes: str | None = None


class DealApplyItem(BaseModel):
    product_id: str
    quantity: int
    unit_price: float
    category_id: int | None = None


class DealApplyPayload(BaseModel):
    items: list[DealApplyItem] = Field(default_factory=list)


def _serialize_condition(condition: DealCondition) -> dict[str, Any]:
    return {
        "id": condition.id,
        "condition_type": condition.condition_type,
        "product_id": condition.product_id,
        "category_id": condition.category_id,
        "quantity": condition.quantity,
        "min_amount": float(condition.min_amount) if condition.min_amount is not None else None,
    }


def _serialize_reward(reward: DealReward) -> dict[str, Any]:
    return {
        "id": reward.id,
        "reward_type": reward.reward_type,
        "product_id": reward.product_id,
        "category_id": reward.category_id,
        "percent_off": float(reward.percent_off) if reward.percent_off is not None else None,
        "flat_off": float(reward.flat_off) if reward.flat_off is not None else None,
        "quantity": reward.quantity,
    }


def _serialize_deal(deal: Deal) -> dict[str, Any]:
    return {
        "id": deal.id,
        "name": deal.name,
        "deal_type": deal.deal_type,
        "priority": deal.priority,
        "is_active": deal.is_active,
        "is_stackable": deal.is_stackable,
        "valid_from": deal.valid_from,
        "valid_until": deal.valid_until,
        "notes": deal.notes,
        "conditions": [_serialize_condition(condition) for condition in deal.conditions],
        "rewards": [_serialize_reward(reward) for reward in deal.rewards],
    }


def _load_deal(db: Session, deal_id: int) -> Deal:
    deal = (
        db.execute(
            select(Deal)
            .options(joinedload(Deal.conditions), joinedload(Deal.rewards))
            .where(Deal.id == deal_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


def _cart_totals(items: list[DealApplyItem]) -> tuple[float, int, dict[str, int], dict[int, int], dict[str, list[float]]]:
    subtotal = 0.0
    total_quantity = 0
    product_quantities: dict[str, int] = {}
    category_quantities: dict[int, int] = {}
    unit_prices_by_product: dict[str, list[float]] = {}

    for item in items:
        quantity = max(int(item.quantity), 0)
        unit_price = float(item.unit_price)
        subtotal += quantity * unit_price
        total_quantity += quantity
        product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + quantity
        if item.category_id is not None:
            category_quantities[item.category_id] = category_quantities.get(item.category_id, 0) + quantity
        unit_prices_by_product.setdefault(item.product_id, []).extend([unit_price] * quantity)

    return subtotal, total_quantity, product_quantities, category_quantities, unit_prices_by_product


def _matches_condition(
    condition: DealCondition,
    subtotal: float,
    total_quantity: int,
    product_quantities: dict[str, int],
    category_quantities: dict[int, int],
) -> bool:
    condition_type = (condition.condition_type or "").upper()
    if condition_type == "MIN_QUANTITY":
        required_quantity = condition.quantity or 0
        return total_quantity >= required_quantity
    if condition_type == "MIN_AMOUNT":
        return subtotal >= float(condition.min_amount or 0)
    if condition_type == "PRODUCT":
        quantity = product_quantities.get(condition.product_id or "", 0)
        required_quantity = condition.quantity or 1
        return quantity >= required_quantity
    if condition_type == "CATEGORY":
        quantity = category_quantities.get(condition.category_id or -1, 0)
        required_quantity = condition.quantity or 1
        return quantity >= required_quantity
    return False


def _expanded_prices(prices: list[float], quantity: int) -> float:
    if quantity <= 0 or not prices:
        return 0.0
    return sum(sorted(prices)[:quantity])


def _reward_discount(
    reward: DealReward,
    current_subtotal: float,
    product_quantities: dict[str, int],
    category_quantities: dict[int, int],
    unit_prices_by_product: dict[str, list[float]],
    cart_items: list[DealApplyItem],
    bundle_member_ids: set[str] | None = None,
) -> float:
    reward_type = (reward.reward_type or "").upper()
    if reward_type == "PERCENT_OFF":
        percent = float(reward.percent_off or 0)
        multiplier = percent if percent <= 1 else percent / 100.0
        return current_subtotal * multiplier
    if reward_type == "FLAT_OFF":
        return float(reward.flat_off or 0)
    if reward_type == "CHEAPEST_FREE":
        prices: list[float] = []
        for item in cart_items:
            quantity = max(int(item.quantity), 0)
            prices.extend([float(item.unit_price)] * quantity)
        return _expanded_prices(prices, max(int(reward.quantity or 1), 1))
    if reward_type == "FREE_ITEM":
        prices: list[float] = []
        target_quantity = max(int(reward.quantity or 1), 1)
        if reward.product_id:
            prices = unit_prices_by_product.get(reward.product_id, [])
        elif reward.category_id is not None:
            for item in cart_items:
                if item.category_id == reward.category_id:
                    prices.extend([float(item.unit_price)] * max(int(item.quantity), 0))
        else:
            for item in cart_items:
                prices.extend([float(item.unit_price)] * max(int(item.quantity), 0))
        return _expanded_prices(prices, target_quantity)
    if reward_type == "BUNDLE_PRICE":
        group_size = max(int(reward.quantity or 1), 1)
        bundle_price = float(reward.flat_off or 0)
        member_ids = bundle_member_ids or set(unit_prices_by_product)
        pooled_prices: list[float] = []
        for product_id in member_ids:
            pooled_prices.extend(unit_prices_by_product.get(product_id, []))
        groups = len(pooled_prices) // group_size
        if groups <= 0:
            return 0.0
        taken = sorted(pooled_prices, reverse=True)[: groups * group_size]
        return max(0.0, sum(taken) - bundle_price * groups)
    return 0.0


@router.get("/")
def list_deals(db: Session = Depends(get_db)):
    deals = (
        db.execute(
            select(Deal)
            .options(joinedload(Deal.conditions), joinedload(Deal.rewards))
            .order_by(Deal.priority.desc(), func.lower(Deal.name), Deal.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )
    return [_serialize_deal(deal) for deal in deals]


@router.post("/")
def create_deal(payload: DealCreatePayload, db: Session = Depends(get_db)):
    deal = Deal(
        name=payload.name,
        deal_type=payload.deal_type,
        priority=payload.priority,
        is_active=payload.is_active,
        is_stackable=payload.is_stackable,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        notes=payload.notes,
    )
    for condition_payload in payload.conditions:
        deal.conditions.append(
            DealCondition(
                condition_type=condition_payload.condition_type.upper(),
                quantity=condition_payload.quantity,
                min_amount=condition_payload.min_amount,
                product_id=condition_payload.product_id,
                category_id=condition_payload.category_id,
            )
        )
    for reward_payload in payload.rewards:
        deal.rewards.append(
            DealReward(
                reward_type=reward_payload.reward_type.upper(),
                percent_off=reward_payload.percent_off,
                flat_off=reward_payload.flat_off,
                product_id=reward_payload.product_id,
                category_id=reward_payload.category_id,
                quantity=reward_payload.quantity,
            )
        )
    db.add(deal)
    db.commit()
    return _serialize_deal(_load_deal(db, deal.id))


@router.patch("/{deal_id}")
def update_deal(deal_id: int, payload: DealUpdatePayload, db: Session = Depends(get_db)):
    deal = _load_deal(db, deal_id)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(deal, key, value)
    db.commit()
    return _serialize_deal(_load_deal(db, deal_id))


@router.delete("/{deal_id}")
def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = _load_deal(db, deal_id)
    db.delete(deal)
    db.commit()
    return {"deleted": deal_id}


@router.post("/{deal_id}/toggle")
def toggle_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = _load_deal(db, deal_id)
    deal.is_active = not deal.is_active
    db.commit()
    return _serialize_deal(_load_deal(db, deal_id))


@router.post("/apply")
def apply_deals(payload: DealApplyPayload, db: Session = Depends(get_db)):
    return compute_deal_summary(db, payload.items)


def compute_deal_summary(db: Session, items: list[DealApplyItem]) -> dict:
    subtotal, total_quantity, product_quantities, category_quantities, unit_prices_by_product = _cart_totals(items)
    current_subtotal = subtotal
    total_discount = 0.0
    applied_deals: list[dict[str, Any]] = []
    # Deal validity timestamps are stored as naive store-local datetimes.
    now = store_now()

    deals = (
        db.execute(
            select(Deal)
            .options(joinedload(Deal.conditions), joinedload(Deal.rewards))
            .where(
                Deal.is_active.is_(True),
                or_(Deal.valid_from.is_(None), Deal.valid_from <= now),
                or_(Deal.valid_until.is_(None), Deal.valid_until >= now),
            )
            .order_by(Deal.priority.desc(), func.lower(Deal.name), Deal.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )

    for deal in deals:
        pool_conditions = [
            condition for condition in deal.conditions if (condition.condition_type or "").upper() == "PRODUCT_ANY"
        ]
        non_pool_conditions = [
            condition for condition in deal.conditions if (condition.condition_type or "").upper() != "PRODUCT_ANY"
        ]
        qualifies = all(
            _matches_condition(condition, subtotal, total_quantity, product_quantities, category_quantities)
            for condition in non_pool_conditions
        )
        if pool_conditions:
            bundle_reward = next(
                (reward for reward in deal.rewards if (reward.reward_type or "").upper() == "BUNDLE_PRICE"),
                None,
            )
            group_size = max(int(bundle_reward.quantity or 1), 1) if bundle_reward else 1
            pooled_quantity = sum(product_quantities.get(condition.product_id or "", 0) for condition in pool_conditions)
            qualifies = qualifies and pooled_quantity >= group_size
        if not qualifies or not deal.rewards:
            continue

        deal_discount = 0.0
        bundle_member_ids = {condition.product_id for condition in pool_conditions if condition.product_id}
        for reward in deal.rewards:
            deal_discount += _reward_discount(
                reward,
                current_subtotal,
                product_quantities,
                category_quantities,
                unit_prices_by_product,
                items,
                bundle_member_ids,
            )

        deal_discount = max(0.0, min(deal_discount, current_subtotal))
        if deal_discount <= 0:
            continue

        total_discount += deal_discount
        current_subtotal = max(0.0, subtotal - total_discount)
        applied_deals.append(
            {
                "deal_id": deal.id,
                "name": deal.name,
                "discount_amount": deal_discount,
                "reward_type": deal.rewards[0].reward_type if len(deal.rewards) == 1 else "MIXED",
            }
        )

        if not deal.is_stackable:
            break

    total = max(0.0, subtotal - total_discount)
    return {
        "applied_deals": applied_deals,
        "subtotal": subtotal,
        "total_discount": total_discount,
        "total": total,
    }
