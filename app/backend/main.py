import os
import hmac
import hashlib
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from app.backend.gst import calculate_gst, money
from app.backend.permissions import can_access

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, String, Integer, Date, Numeric, DateTime,
    func, select, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")
if not ADMIN_PASSWORD_HASH or not SESSION_SECRET:
    raise RuntimeError("ADMIN_PASSWORD_HASH and SESSION_SECRET are required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(100), default="General")
    batch_number: Mapped[str] = mapped_column(String(100), unique=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=10)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expiry_date: Mapped[date] = mapped_column(Date)
    supplier: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="CASCADE"), index=True
    )
    movement_type: Mapped[str] = mapped_column(String(30))
    quantity_change: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MedicineInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="General", max_length=100)
    batch_number: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0)
    reorder_level: int = Field(default=10, ge=0)
    unit_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    expiry_date: date
    supplier: str = Field(default="", max_length=160)


class MedicineUpdateInput(MedicineInput):
    stock_change_reason: str | None = Field(default=None, max_length=200)


def verify_password(password: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected = ADMIN_PASSWORD_HASH.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def require_admin(request: Request):
    """Authorize the owner or staff with explicitly permitted API access.

    Existing route dependencies call this function; unidentified routes remain
    owner-only. Never trust a role supplied by the browser.
    """
    if request.session.get("admin") is True:
        with SessionLocal() as db:
            credential = db.get(AdminCredential, 1)
            if credential is not None:
                if request.session.get("auth_version") != credential.session_version:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired. Please log in again"
                    )
        return

    staff_id = request.session.get("staff_id")
    if not isinstance(staff_id, int) or isinstance(staff_id, bool):
        raise HTTPException(status_code=401, detail="Login required")

    with SessionLocal() as db:
        staff = db.get(StaffUser, staff_id)
        if (
            staff is None
            or not staff.active
            or request.session.get("staff_version") != staff.session_version
        ):
            raise HTTPException(status_code=401, detail="Staff session expired")

        if not can_access(staff.role, request.method, request.url.path):
            raise HTTPException(status_code=403, detail="Insufficient permissions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


app = FastAPI(
    title="CloudLaunch Pharmacy API",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="pharmacy_session",
    max_age=28800,
    same_site="strict",
    https_only=True,
)


def get_db():
    with SessionLocal() as db:
        yield db


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(select(1))
    return {"status": "healthy", "database": "connected"}


@app.get("/api/auth")
def auth_status(request: Request):
    if request.session.get("admin") is True:
        require_admin(request)
        return {"authenticated": True, "role": "owner"}

    staff_id = request.session.get("staff_id")
    if staff_id:
        with SessionLocal() as db:
            staff = db.get(StaffUser, staff_id)

            if (
                staff
                and staff.active
                and request.session.get("staff_version")
                    == staff.session_version
            ):
                return {
                    "authenticated": True,
                    "role": staff.role,
                    "username": staff.username,
                }

    return {"authenticated": False}


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    username: str | None = Field(default=None, max_length=80)


@app.post("/api/login")
def login(payload: LoginInput, request: Request):
    username = (payload.username or "").strip().lower()

    if not username:
        if not verify_active_password(payload.password):
            raise HTTPException(401, "Invalid credentials")

        request.session.clear()
        request.session["admin"] = True

        with SessionLocal() as db:
            credential = db.get(AdminCredential, 1)
            if credential is not None:
                request.session["auth_version"] = credential.session_version

        return {"authenticated": True, "role": "owner"}

    with SessionLocal() as db:
        staff = db.scalar(
            select(StaffUser).where(StaffUser.username == username)
        )

        if (
            staff is None
            or not staff.active
            or not check_hash(payload.password, staff.password_hash)
        ):
            raise HTTPException(401, "Invalid credentials")

        request.session.clear()
        request.session["staff_id"] = staff.id
        request.session["staff_version"] = staff.session_version

        return {
            "authenticated": True,
            "role": staff.role,
            "username": staff.username,
        }


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"authenticated": False}


@app.get("/api/summary", dependencies=[Depends(require_admin)])
def summary(db: Session = Depends(get_db)):
    today = date.today()
    medicines = db.scalars(select(Medicine)).all()
    return {
        "medicine_count": len(medicines),
        "units_in_stock": sum(m.quantity for m in medicines),
        "low_stock_count": sum(
            1 for m in medicines if m.quantity <= m.reorder_level
        ),
        "expiring_soon_count": sum(
            1 for m in medicines
            if today <= m.expiry_date <= date.fromordinal(today.toordinal() + 90)
        ),
        "inventory_value": str(sum(
            (m.unit_price * m.quantity for m in medicines), Decimal("0.00")
        )),
    }


@app.get("/api/medicines", dependencies=[Depends(require_admin)])
def list_medicines(db: Session = Depends(get_db)):
    medicines = db.scalars(select(Medicine).order_by(Medicine.name)).all()
    return [
        {
            "id": m.id, "name": m.name, "category": m.category,
            "batch_number": m.batch_number, "quantity": m.quantity,
            "reorder_level": m.reorder_level, "unit_price": str(m.unit_price),
            "expiry_date": m.expiry_date.isoformat(), "supplier": m.supplier,
        }
        for m in medicines
    ]


@app.post("/api/medicines", status_code=201, dependencies=[Depends(require_admin)])
def add_medicine(payload: MedicineInput, db: Session = Depends(get_db)):
    if payload.expiry_date < date.today():
        raise HTTPException(status_code=422, detail="Cannot add an expired batch")
    medicine = Medicine(**payload.model_dump())
    db.add(medicine)
    try:
        db.flush()
        if medicine.quantity > 0:
            db.add(StockMovement(
                medicine_id=medicine.id,
                movement_type="opening",
                quantity_change=medicine.quantity,
                reason="Initial stock",
            ))
        db.commit()
        db.refresh(medicine)
    except Exception as exc:
        db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Batch number already exists")
        raise HTTPException(status_code=400, detail="Could not save medicine")
    return {"id": medicine.id, "message": "Medicine saved"}


@app.put("/api/medicines/{medicine_id}", dependencies=[Depends(require_admin)])
def update_medicine(
    medicine_id: int, payload: MedicineUpdateInput,
    db: Session = Depends(get_db)
):
    medicine = db.scalars(
        select(Medicine)
        .where(Medicine.id == medicine_id)
        .with_for_update()
    ).first()
    if medicine is None:
        raise HTTPException(status_code=404, detail="Medicine not found")
    quantity_change = payload.quantity - medicine.quantity
    reason = (payload.stock_change_reason or "").strip()

    if quantity_change != 0 and len(reason) < 3:
        raise HTTPException(
            status_code=409,
            detail="Provide a reason of at least 3 characters for the stock change",
        )
    if payload.expiry_date < date.today():
        raise HTTPException(status_code=422, detail="Cannot set an expired batch")

    for key, value in payload.model_dump(
        exclude={"stock_change_reason"}
    ).items():
        setattr(medicine, key, value)

    if quantity_change != 0:
        db.add(StockMovement(
            medicine_id=medicine.id,
            movement_type="adjustment",
            quantity_change=quantity_change,
            reason=reason,
        ))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not update medicine")
    return {"message": "Medicine updated"}


@app.delete(
    "/api/medicines/{medicine_id}",
    status_code=204,
    dependencies=[Depends(require_admin)]
)
def delete_medicine(medicine_id: int, db: Session = Depends(get_db)):
    medicine = db.get(Medicine, medicine_id)
    if medicine is None:
        raise HTTPException(status_code=404, detail="Medicine not found")
    movement_id = db.scalar(
        select(StockMovement.id)
        .where(StockMovement.medicine_id == medicine_id)
        .limit(1)
    )
    if movement_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a medicine with stock movement history",
        )
    db.delete(medicine)
    db.commit()


class StockChangeInput(BaseModel):
    change: int = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=3, max_length=200)


@app.post(
    "/api/medicines/{medicine_id}/stock",
    dependencies=[Depends(require_admin)],
)
def adjust_stock(
    medicine_id: int,
    payload: StockChangeInput,
    db: Session = Depends(get_db),
):
    if payload.change == 0:
        raise HTTPException(status_code=422, detail="Change must not be zero")

    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(
            status_code=422,
            detail="Reason must contain at least 3 non-space characters",
        )

    medicine = db.scalars(
        select(Medicine)
        .where(Medicine.id == medicine_id)
        .with_for_update()
    ).first()

    if medicine is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    new_quantity = medicine.quantity + payload.change
    if new_quantity < 0:
        raise HTTPException(status_code=409, detail="Stock cannot go below zero")

    medicine.quantity = new_quantity
    db.add(StockMovement(
        medicine_id=medicine.id,
        movement_type="adjustment",
        quantity_change=payload.change,
        reason=reason,
    ))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stock adjustment failed")

    return {"quantity": new_quantity}


@app.get(
    "/api/medicines/{medicine_id}/movements",
    dependencies=[Depends(require_admin)],
)
def list_movements(medicine_id: int, db: Session = Depends(get_db)):
    if db.get(Medicine, medicine_id) is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    rows = db.scalars(
        select(StockMovement)
        .where(StockMovement.medicine_id == medicine_id)
        .order_by(StockMovement.id.desc())
        .limit(200)
    ).all()

    return [
        {
            "id": row.id,
            "type": row.movement_type,
            "change": row.quantity_change,
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]



# ===== Supplier Management =====

class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    contact_person: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SupplierInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    contact_person: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=160)
    address: str = Field(default="", max_length=300)


def supplier_dict(s):
    return {
        "id": s.id,
        "name": s.name,
        "contact_person": s.contact_person,
        "phone": s.phone,
        "email": s.email,
        "address": s.address,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@app.get("/api/suppliers", dependencies=[Depends(require_admin)])
def list_suppliers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    return [supplier_dict(s) for s in rows]


@app.post("/api/suppliers", status_code=201,
          dependencies=[Depends(require_admin)])
def create_supplier(payload: SupplierInput, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data = {k: v.strip() for k, v in data.items()}
    if not data["name"]:
        raise HTTPException(422, "Supplier name is required")

    exists = db.scalar(
        select(Supplier.id).where(
            func.lower(Supplier.name) == data["name"].lower()
        )
    )
    if exists is not None:
        raise HTTPException(409, "Supplier name already exists")

    supplier = Supplier(**data)
    db.add(supplier)
    try:
        db.commit()
        db.refresh(supplier)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not create supplier")
    return supplier_dict(supplier)


@app.put("/api/suppliers/{supplier_id}",
         dependencies=[Depends(require_admin)])
def update_supplier(supplier_id: int, payload: SupplierInput,
                    db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(404, "Supplier not found")

    data = {k: v.strip() for k, v in payload.model_dump().items()}
    if not data["name"]:
        raise HTTPException(422, "Supplier name is required")

    exists = db.scalar(
        select(Supplier.id).where(
            func.lower(Supplier.name) == data["name"].lower(),
            Supplier.id != supplier_id
        )
    )
    if exists is not None:
        raise HTTPException(409, "Supplier name already exists")

    for key, value in data.items():
        setattr(supplier, key, value)

    try:
        db.commit()
        db.refresh(supplier)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not update supplier")
    return supplier_dict(supplier)


@app.delete("/api/suppliers/{supplier_id}", status_code=204,
            dependencies=[Depends(require_admin)])
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(404, "Supplier not found")

    linked = db.scalar(
        select(Medicine.id).where(
            func.lower(Medicine.supplier) == supplier.name.lower()
        ).limit(1)
    )
    if linked is not None:
        raise HTTPException(
            409, "Supplier is used by medicine inventory and cannot be deleted"
        )

    db.delete(supplier)
    db.commit()


# ===== End Supplier Management =====


# ===== Purchase Orders =====

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class PurchaseItemInput(BaseModel):
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    unit_cost: Decimal = Field(
        ge=0, max_digits=10, decimal_places=2
    )


class PurchaseOrderInput(BaseModel):
    supplier_id: int = Field(gt=0)
    items: list[PurchaseItemInput] = Field(min_length=1, max_length=100)


def purchase_details(order, db):
    supplier = db.get(Supplier, order.supplier_id)
    items = db.scalars(
        select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == order.id
        ).order_by(PurchaseOrderItem.id)
    ).all()

    result = []
    total = Decimal("0.00")
    for item in items:
        medicine = db.get(Medicine, item.medicine_id)
        line_total = item.unit_cost * item.quantity
        total += line_total
        result.append({
            "id": item.id,
            "medicine_id": item.medicine_id,
            "medicine": medicine.name if medicine else "Unknown",
            "batch_number": medicine.batch_number if medicine else "",
            "quantity": item.quantity,
            "unit_cost": str(item.unit_cost),
            "line_total": str(line_total),
        })

    return {
        "id": order.id,
        "supplier_id": order.supplier_id,
        "supplier": supplier.name if supplier else "Unknown",
        "status": order.status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "received_at": order.received_at.isoformat() if order.received_at else None,
        "items": result,
        "total": str(total),
    }


@app.get("/api/purchase-orders", dependencies=[Depends(require_admin)])
def list_purchase_orders(db: Session = Depends(get_db)):
    orders = db.scalars(
        select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    ).all()
    return [purchase_details(order, db) for order in orders]


@app.get("/api/purchase-orders/{order_id}",
         dependencies=[Depends(require_admin)])
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(404, "Purchase order not found")
    return purchase_details(order, db)


@app.post("/api/purchase-orders", status_code=201,
          dependencies=[Depends(require_admin)])
def create_purchase_order(
    payload: PurchaseOrderInput, db: Session = Depends(get_db)
):
    if db.get(Supplier, payload.supplier_id) is None:
        raise HTTPException(404, "Supplier not found")

    medicine_ids = [item.medicine_id for item in payload.items]
    if len(medicine_ids) != len(set(medicine_ids)):
        raise HTTPException(422, "Duplicate medicine batches in order")

    for item in payload.items:
        if db.get(Medicine, item.medicine_id) is None:
            raise HTTPException(
                404, f"Medicine {item.medicine_id} not found"
            )

    order = PurchaseOrder(
        supplier_id=payload.supplier_id,
        status="pending"
    )
    try:
        db.add(order)
        db.flush()

        for item in payload.items:
            db.add(PurchaseOrderItem(
                purchase_order_id=order.id,
                medicine_id=item.medicine_id,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
            ))

        db.commit()
        db.refresh(order)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not create purchase order")

    return purchase_details(order, db)


@app.post("/api/purchase-orders/{order_id}/receive",
          dependencies=[Depends(require_admin)])
def receive_purchase_order(
    order_id: int, db: Session = Depends(get_db)
):
    order = db.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == order_id)
        .with_for_update()
    ).first()

    if order is None:
        raise HTTPException(404, "Purchase order not found")

    if order.status != "pending":
        raise HTTPException(409, "Purchase order already received")

    items = db.scalars(
        select(PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == order.id
        ).order_by(PurchaseOrderItem.medicine_id)
    ).all()

    if not items:
        raise HTTPException(409, "Purchase order has no items")

    for item in items:
        medicine = db.scalars(
            select(Medicine)
            .where(Medicine.id == item.medicine_id)
            .with_for_update()
        ).first()

        if medicine is None:
            raise HTTPException(409, "Ordered medicine no longer exists")

        if medicine.expiry_date < date.today():
            raise HTTPException(
                409, f"Cannot receive expired batch: {medicine.name}"
            )

        medicine.quantity += item.quantity

        db.add(StockMovement(
            medicine_id=medicine.id,
            movement_type="purchase",
            quantity_change=item.quantity,
            reason=f"Purchase order #{order.id} received",
        ))

    order.status = "received"
    order.received_at = datetime.now().astimezone()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not receive purchase order")

    return {
        "message": "Purchase order received",
        "order_id": order.id,
        "status": order.status,
    }


# ===== End Purchase Orders =====


# ===== FEFO Inventory =====

@app.get("/api/inventory/fefo", dependencies=[Depends(require_admin)])
def fefo_inventory(db: Session = Depends(get_db)):
    batches = db.scalars(
        select(Medicine)
        .where(
            Medicine.quantity > 0,
            Medicine.expiry_date > date.today()
        )
        .order_by(
            Medicine.name,
            Medicine.expiry_date,
            Medicine.id
        )
    ).all()

    return [
        {
            "id": m.id,
            "name": m.name,
            "batch_number": m.batch_number,
            "quantity": m.quantity,
            "expiry_date": m.expiry_date.isoformat(),
            "unit_price": str(m.unit_price),
        }
        for m in batches
    ]


# ===== End FEFO Inventory =====


# ===== Sales and Billing =====

class PharmacySale(Base):
    __tablename__ = "pharmacy_sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True
    )
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    taxable_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PharmacySaleItem(Base):
    __tablename__ = "pharmacy_sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("pharmacy_sales.id", ondelete="RESTRICT"), index=True
    )
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="RESTRICT")
    )
    medicine_name: Mapped[str] = mapped_column(String(160))
    batch_number: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    taxable_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    hsn_code: Mapped[str | None] = mapped_column(String(20))


class SaleItemInput(BaseModel):
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    gst_rate: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, decimal_places=2
    )
    discount_amount: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=12, decimal_places=2
    )
    hsn_code: str | None = Field(default=None, max_length=20)


class SaleInput(BaseModel):
    items: list[SaleItemInput] = Field(min_length=1, max_length=100)
    customer_id: int | None = Field(default=None, gt=0)
    interstate: bool = False


def sale_details(sale, db):
    items = db.scalars(
        select(PharmacySaleItem)
        .where(PharmacySaleItem.sale_id == sale.id)
        .order_by(PharmacySaleItem.id)
    ).all()
    return {
        "id": sale.id,
        "invoice_number": sale.invoice_number,
        "customer_id": sale.customer_id,
        "subtotal": str(sale.subtotal or Decimal("0")),
        "discount_total": str(sale.discount_total or Decimal("0")),
        "taxable_total": str(sale.taxable_total or Decimal("0")),
        "cgst_total": str(sale.cgst_total or Decimal("0")),
        "sgst_total": str(sale.sgst_total or Decimal("0")),
        "igst_total": str(sale.igst_total or Decimal("0")),
        "total": str(sale.total),
        "created_at": sale.created_at.isoformat() if sale.created_at else None,
        "items": [{
            "medicine_id": item.medicine_id,
            "medicine": item.medicine_name,
            "batch_number": item.batch_number,
            "quantity": item.quantity,
            "unit_price": str(item.unit_price),
            "discount_amount": str(item.discount_amount or Decimal("0")),
            "taxable_amount": str(item.taxable_amount or Decimal("0")),
            "gst_rate": str(item.gst_rate or Decimal("0")),
            "cgst_amount": str(item.cgst_amount or Decimal("0")),
            "sgst_amount": str(item.sgst_amount or Decimal("0")),
            "igst_amount": str(item.igst_amount or Decimal("0")),
            "hsn_code": item.hsn_code,
            "line_total": str(money(
                (item.taxable_amount or Decimal("0"))
                + (item.cgst_amount or Decimal("0"))
                + (item.sgst_amount or Decimal("0"))
                + (item.igst_amount or Decimal("0"))
            )),
        } for item in items],
    }


@app.get("/api/sales", dependencies=[Depends(require_admin)])
def list_sales(db: Session = Depends(get_db)):
    sales = db.scalars(
        select(PharmacySale).order_by(PharmacySale.id.desc()).limit(200)
    ).all()
    return [sale_details(s, db) for s in sales]


@app.get("/api/sales/{sale_id}", dependencies=[Depends(require_admin)])
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    sale = db.get(PharmacySale, sale_id)
    if sale is None:
        raise HTTPException(404, "Sale not found")
    return sale_details(sale, db)


@app.post("/api/sales", status_code=201,
          dependencies=[Depends(require_admin)])
def create_sale(payload: SaleInput, db: Session = Depends(get_db)):
    ids = [item.medicine_id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate medicine batches in sale")

    if payload.customer_id is not None:
        if db.get(Customer, payload.customer_id) is None:
            raise HTTPException(404, "Customer not found")

    medicines_by_id = {}
    for medicine_id in sorted(ids):
        medicine = db.scalars(
            select(Medicine)
            .where(Medicine.id == medicine_id)
            .with_for_update()
        ).first()
        if medicine is None:
            raise HTTPException(404, f"Medicine {medicine_id} not found")
        medicines_by_id[medicine_id] = medicine

    # Enforce FEFO, including same-expiry batch ordering.
    requested_quantities = {
        item.medicine_id: item.quantity for item in payload.items
    }

    for medicine in medicines_by_id.values():
        earlier_batches = db.scalars(
            select(Medicine)
            .where(
                func.lower(Medicine.name) == medicine.name.lower(),
                Medicine.id != medicine.id,
                Medicine.expiry_date > date.today(),
                Medicine.quantity > 0,
                (
                    (Medicine.expiry_date < medicine.expiry_date)
                    | (
                        (Medicine.expiry_date == medicine.expiry_date)
                        & (Medicine.id < medicine.id)
                    )
                ),
            )
            .order_by(Medicine.expiry_date, Medicine.id)
            .with_for_update()
        ).all()

        for earlier in earlier_batches:
            remaining = (
                earlier.quantity
                - requested_quantities.get(earlier.id, 0)
            )
            if remaining > 0:
                raise HTTPException(
                    409,
                    f"FEFO: Use batch {earlier.batch_number} "
                    f"of {medicine.name} first"
                )

    calculated = []
    totals = {
        key: Decimal("0.00")
        for key in (
            "subtotal", "discount", "taxable",
            "cgst", "sgst", "igst", "total"
        )
    }

    for item in payload.items:
        medicine = medicines_by_id[item.medicine_id]

        if medicine.expiry_date <= date.today():
            raise HTTPException(409, f"Expired batch: {medicine.name}")

        if medicine.quantity < item.quantity:
            raise HTTPException(409, f"Insufficient stock: {medicine.name}")

        try:
            result = calculate_gst(
                medicine.unit_price,
                item.quantity,
                item.gst_rate,
                item.discount_amount,
                payload.interstate,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        calculated.append((item, medicine, result))
        for key in totals:
            totals[key] += result[key]

    try:
        sale = PharmacySale(
            customer_id=payload.customer_id,
            subtotal=money(totals["subtotal"]),
            discount_total=money(totals["discount"]),
            taxable_total=money(totals["taxable"]),
            cgst_total=money(totals["cgst"]),
            sgst_total=money(totals["sgst"]),
            igst_total=money(totals["igst"]),
            total=money(totals["total"]),
        )
        db.add(sale)
        db.flush()

        sale.invoice_number = f"PC-{date.today().year}-{sale.id:06d}"

        for item, medicine, result in calculated:
            db.add(PharmacySaleItem(
                sale_id=sale.id,
                medicine_id=medicine.id,
                medicine_name=medicine.name,
                batch_number=medicine.batch_number,
                quantity=item.quantity,
                unit_price=medicine.unit_price,
                discount_amount=result["discount"],
                taxable_amount=result["taxable"],
                gst_rate=result["gst_rate"],
                cgst_amount=result["cgst"],
                sgst_amount=result["sgst"],
                igst_amount=result["igst"],
                hsn_code=item.hsn_code,
            ))

            medicine.quantity -= item.quantity
            db.add(StockMovement(
                medicine_id=medicine.id,
                movement_type="sale",
                quantity_change=-item.quantity,
                reason=f"Sale #{sale.id}",
            ))

        db.commit()
        db.refresh(sale)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not complete sale")

    return sale_details(sale, db)


# ===== End Sales and Billing =====


# ===== Sales Returns & Refund Records =====

class SaleReturn(Base):
    __tablename__ = "sale_returns"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("pharmacy_sales.id", ondelete="RESTRICT"),
        index=True
    )
    reason: Mapped[str] = mapped_column(String(200))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SaleReturnItem(Base):
    __tablename__ = "sale_return_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("sale_returns.id", ondelete="RESTRICT"),
        index=True
    )
    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("pharmacy_sale_items.id", ondelete="RESTRICT"),
        index=True
    )
    medicine_name: Mapped[str] = mapped_column(String(160))
    batch_number: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class ReturnItemInput(BaseModel):
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)


class ReturnInput(BaseModel):
    sale_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=200)
    items: list[ReturnItemInput] = Field(min_length=1, max_length=100)


def return_details(record, db):
    rows = db.scalars(
        select(SaleReturnItem)
        .where(SaleReturnItem.return_id == record.id)
        .order_by(SaleReturnItem.id)
    ).all()

    details = []
    for r in rows:
        sold = db.get(PharmacySaleItem, r.sale_item_id)

        previous = db.scalar(
            select(func.coalesce(func.sum(SaleReturnItem.quantity), 0))
            .where(
                SaleReturnItem.sale_item_id == r.sale_item_id,
                SaleReturnItem.return_id < record.id,
            )
        ) or 0

        original_total = money(
            (sold.taxable_amount or Decimal("0"))
            + (sold.cgst_amount or Decimal("0"))
            + (sold.sgst_amount or Decimal("0"))
            + (sold.igst_amount or Decimal("0"))
        )

        refund = (
            money(original_total * (previous + r.quantity) / sold.quantity)
            - money(original_total * previous / sold.quantity)
        )

        details.append({
            "medicine": r.medicine_name,
            "batch_number": r.batch_number,
            "quantity": r.quantity,
            "unit_price": str(r.unit_price),
            "refund_amount": str(refund),
        })

    return {
        "id": record.id,
        "sale_id": record.sale_id,
        "reason": record.reason,
        "refund_amount": str(record.refund_amount),
        "refund_status": "recorded_not_paid",
        "stock_disposition": "not_restocked",
        "created_at": (
            record.created_at.isoformat() if record.created_at else None
        ),
        "items": details,
    }


@app.get("/api/returns", dependencies=[Depends(require_admin)])
def list_returns(db: Session = Depends(get_db)):
    records = db.scalars(
        select(SaleReturn).order_by(SaleReturn.id.desc()).limit(200)
    ).all()
    return [return_details(r, db) for r in records]


@app.get("/api/returns/{return_id}",
         dependencies=[Depends(require_admin)])
def get_return(return_id: int, db: Session = Depends(get_db)):
    record = db.get(SaleReturn, return_id)
    if record is None:
        raise HTTPException(404, "Return not found")
    return return_details(record, db)


@app.post("/api/returns", status_code=201,
          dependencies=[Depends(require_admin)])
def create_return(payload: ReturnInput, db: Session = Depends(get_db)):
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "Reason must have at least 3 characters")

    medicine_ids = [i.medicine_id for i in payload.items]
    if len(medicine_ids) != len(set(medicine_ids)):
        raise HTTPException(422, "Duplicate medicine batches in return")

    # Serialize returns for the same sale to prevent over-returning.
    sale = db.scalars(
        select(PharmacySale)
        .where(PharmacySale.id == payload.sale_id)
        .with_for_update()
    ).first()
    if sale is None:
        raise HTTPException(404, "Sale not found")

    sold_items = db.scalars(
        select(PharmacySaleItem).where(
            PharmacySaleItem.sale_id == sale.id
        )
    ).all()
    sold_by_medicine = {i.medicine_id: i for i in sold_items}

    existing = db.execute(
        select(SaleReturnItem.sale_item_id, func.sum(SaleReturnItem.quantity))
        .join(SaleReturn, SaleReturn.id == SaleReturnItem.return_id)
        .where(SaleReturn.sale_id == sale.id)
        .group_by(SaleReturnItem.sale_item_id)
    ).all()
    already_returned = {item_id: int(qty) for item_id, qty in existing}

    total = Decimal("0.00")
    validated = []
    for requested in payload.items:
        sold = sold_by_medicine.get(requested.medicine_id)
        if sold is None:
            raise HTTPException(
                422, "Medicine was not included in the original sale"
            )

        remaining = sold.quantity - already_returned.get(sold.id, 0)
        if requested.quantity > remaining:
            raise HTTPException(
                409,
                f"Return exceeds remaining sold quantity for {sold.medicine_name}"
            )

        original_total = money(
            (sold.taxable_amount or Decimal("0"))
            + (sold.cgst_amount or Decimal("0"))
            + (sold.sgst_amount or Decimal("0"))
            + (sold.igst_amount or Decimal("0"))
        )
        previously_returned = already_returned.get(sold.id, 0)
        after_return = previously_returned + requested.quantity

        # Cumulative rounding prevents over/under-refunding
        # across multiple partial returns.
        refund = (
            money(original_total * after_return / sold.quantity)
            - money(original_total * previously_returned / sold.quantity)
        )
        total += refund
        validated.append((sold, requested.quantity))

    try:
        record = SaleReturn(
            sale_id=sale.id,
            reason=reason,
            refund_amount=total
        )
        db.add(record)
        db.flush()

        for sold, qty in validated:
            db.add(SaleReturnItem(
                return_id=record.id,
                sale_item_id=sold.id,
                medicine_name=sold.medicine_name,
                batch_number=sold.batch_number,
                quantity=qty,
                unit_price=sold.unit_price,
            ))

        # Returned medicines require separate inspection and
        # disposition. Never auto-add them to sellable stock.
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not record return")

    return return_details(record, db)


# ===== End Sales Returns =====


# ===== Customer Management =====

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CustomerInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=160)
    address: str = Field(default="", max_length=300)


def customer_dict(c):
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@app.get("/api/customers", dependencies=[Depends(require_admin)])
def list_customers(q: str = "", db: Session = Depends(get_db)):
    if len(q) > 160:
        raise HTTPException(422, "Search is too long")

    statement = select(Customer)
    term = q.strip()

    if term:
        pattern = (
            "%" + term.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_") + "%"
        )
        statement = statement.where(
            Customer.name.ilike(pattern, escape="\\") |
            Customer.phone.ilike(pattern, escape="\\") |
            Customer.email.ilike(pattern, escape="\\")
        )

    rows = db.scalars(
        statement.order_by(Customer.name, Customer.id).limit(500)
    ).all()
    return [customer_dict(c) for c in rows]


@app.get("/api/customers/{customer_id}",
         dependencies=[Depends(require_admin)])
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer_dict(customer)


@app.post("/api/customers", status_code=201,
          dependencies=[Depends(require_admin)])
def add_customer(payload: CustomerInput, db: Session = Depends(get_db)):
    data = {k: v.strip() for k, v in payload.model_dump().items()}
    if not data["name"]:
        raise HTTPException(422, "Customer name is required")

    customer = Customer(**data)
    try:
        db.add(customer)
        db.commit()
        db.refresh(customer)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not create customer")

    return customer_dict(customer)


@app.put("/api/customers/{customer_id}",
         dependencies=[Depends(require_admin)])
def update_customer(
    customer_id: int,
    payload: CustomerInput,
    db: Session = Depends(get_db)
):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")

    data = {k: v.strip() for k, v in payload.model_dump().items()}
    if not data["name"]:
        raise HTTPException(422, "Customer name is required")

    for key, value in data.items():
        setattr(customer, key, value)

    try:
        db.commit()
        db.refresh(customer)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not update customer")

    return customer_dict(customer)


@app.delete("/api/customers/{customer_id}", status_code=204,
            dependencies=[Depends(require_admin)])
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Customer not found")

    try:
        db.delete(customer)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not delete customer")


# ===== End Customer Management =====


# ===== Prescription Records =====

class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    prescriber_name: Mapped[str] = mapped_column(String(160))
    prescription_date: Mapped[date] = mapped_column(Date)
    reference_number: Mapped[str] = mapped_column(
        String(100), default=""
    )
    notes: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(
        String(30), default="recorded"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="RESTRICT"),
        index=True
    )
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(
        String(300), default=""
    )


class PrescriptionItemInput(BaseModel):
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    instructions: str = Field(default="", max_length=300)


class PrescriptionInput(BaseModel):
    customer_id: int = Field(gt=0)
    prescriber_name: str = Field(min_length=1, max_length=160)
    prescription_date: date
    reference_number: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=500)
    items: list[PrescriptionItemInput] = Field(
        min_length=1, max_length=100
    )


def prescription_details(record, db):
    customer = db.get(Customer, record.customer_id)
    rows = db.scalars(
        select(PrescriptionItem)
        .where(PrescriptionItem.prescription_id == record.id)
        .order_by(PrescriptionItem.id)
    ).all()

    items = []
    for row in rows:
        medicine = db.get(Medicine, row.medicine_id)
        items.append({
            "medicine_id": row.medicine_id,
            "medicine": medicine.name if medicine else "Unknown",
            "batch_number": (
                medicine.batch_number if medicine else ""
            ),
            "quantity": row.quantity,
            "instructions": row.instructions,
        })

    return {
        "id": record.id,
        "customer_id": record.customer_id,
        "customer": customer.name if customer else "Unknown",
        "prescriber_name": record.prescriber_name,
        "prescription_date": record.prescription_date.isoformat(),
        "reference_number": record.reference_number,
        "notes": record.notes,
        "status": record.status,
        "created_at": (
            record.created_at.isoformat()
            if record.created_at else None
        ),
        "items": items,
    }


@app.get("/api/prescriptions",
         dependencies=[Depends(require_admin)])
def list_prescriptions(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Prescription)
        .order_by(Prescription.id.desc())
        .limit(200)
    ).all()
    return [prescription_details(p, db) for p in rows]


@app.get("/api/prescriptions/{prescription_id}",
         dependencies=[Depends(require_admin)])
def get_prescription(
    prescription_id: int,
    db: Session = Depends(get_db)
):
    record = db.get(Prescription, prescription_id)
    if record is None:
        raise HTTPException(404, "Prescription not found")
    return prescription_details(record, db)


@app.post("/api/prescriptions", status_code=201,
          dependencies=[Depends(require_admin)])
def create_prescription(
    payload: PrescriptionInput,
    db: Session = Depends(get_db)
):
    if db.get(Customer, payload.customer_id) is None:
        raise HTTPException(404, "Customer not found")

    prescriber = payload.prescriber_name.strip()
    if not prescriber:
        raise HTTPException(422, "Prescriber name is required")

    medicine_ids = [i.medicine_id for i in payload.items]
    if len(medicine_ids) != len(set(medicine_ids)):
        raise HTTPException(
            422, "Duplicate medicine batches in prescription"
        )

    for item in payload.items:
        if db.get(Medicine, item.medicine_id) is None:
            raise HTTPException(
                404, f"Medicine {item.medicine_id} not found"
            )

    try:
        record = Prescription(
            customer_id=payload.customer_id,
            prescriber_name=prescriber,
            prescription_date=payload.prescription_date,
            reference_number=payload.reference_number.strip(),
            notes=payload.notes.strip(),
            status="recorded",
        )
        db.add(record)
        db.flush()

        for item in payload.items:
            db.add(PrescriptionItem(
                prescription_id=record.id,
                medicine_id=item.medicine_id,
                quantity=item.quantity,
                instructions=item.instructions.strip(),
            ))

        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise HTTPException(
            409, "Could not save prescription"
        )

    return prescription_details(record, db)


# ===== End Prescription Records =====



# ===== PharmaCare Batch 1: Finance and Profile =====

class PharmacyProfile(Base):
    __tablename__ = "pharmacy_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    pharmacy_name: Mapped[str] = mapped_column(
        String(160), default="PharmaCare"
    )
    pharmacy_phone: Mapped[str] = mapped_column(
        String(30), default=""
    )
    pharmacy_email: Mapped[str] = mapped_column(
        String(160), default=""
    )
    pharmacy_address: Mapped[str] = mapped_column(
        String(300), default=""
    )
    gstin: Mapped[str] = mapped_column(
        String(15), default=""
    )
    owner_name: Mapped[str] = mapped_column(
        String(160), default=""
    )
    owner_phone: Mapped[str] = mapped_column(
        String(30), default=""
    )
    owner_email: Mapped[str] = mapped_column(
        String(160), default=""
    )


class PharmacySettingsInput(BaseModel):
    pharmacy_name: str = Field(min_length=1, max_length=160)
    pharmacy_phone: str = Field(default="", max_length=30)
    pharmacy_email: str = Field(default="", max_length=160)
    pharmacy_address: str = Field(default="", max_length=300)
    gstin: str = Field(default="", max_length=15)


class OwnerProfileInput(BaseModel):
    owner_name: str = Field(min_length=1, max_length=160)
    owner_phone: str = Field(default="", max_length=30)
    owner_email: str = Field(default="", max_length=160)


def profile_data(profile):
    if profile is None:
        return {
            "pharmacy_name": "PharmaCare",
            "pharmacy_phone": "",
            "pharmacy_email": "",
            "pharmacy_address": "",
            "gstin": "",
            "owner_name": "",
            "owner_phone": "",
            "owner_email": "",
        }
    return {
        key: getattr(profile, key)
        for key in (
            "pharmacy_name", "pharmacy_phone",
            "pharmacy_email", "pharmacy_address",
            "gstin", "owner_name", "owner_phone",
            "owner_email",
        )
    }


@app.get("/api/pharmacy-profile",
         dependencies=[Depends(require_admin)])
def get_pharmacy_profile(db: Session = Depends(get_db)):
    return profile_data(db.get(PharmacyProfile, 1))


@app.put("/api/pharmacy-settings",
         dependencies=[Depends(require_admin)])
def save_pharmacy_settings(
    payload: PharmacySettingsInput,
    db: Session = Depends(get_db)
):
    data = {
        key: value.strip()
        for key, value in payload.model_dump().items()
    }
    if not data["pharmacy_name"]:
        raise HTTPException(422, "Pharmacy name is required")

    profile = db.get(PharmacyProfile, 1)
    if profile is None:
        profile = PharmacyProfile(id=1)
        db.add(profile)

    for key, value in data.items():
        setattr(profile, key, value)

    try:
        db.commit()
        db.refresh(profile)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not save pharmacy settings")

    return profile_data(profile)


@app.put("/api/owner-profile",
         dependencies=[Depends(require_admin)])
def save_owner_profile(
    payload: OwnerProfileInput,
    db: Session = Depends(get_db)
):
    data = {
        key: value.strip()
        for key, value in payload.model_dump().items()
    }
    if not data["owner_name"]:
        raise HTTPException(422, "Owner name is required")

    profile = db.get(PharmacyProfile, 1)
    if profile is None:
        profile = PharmacyProfile(id=1)
        db.add(profile)

    for key, value in data.items():
        setattr(profile, key, value)

    try:
        db.commit()
        db.refresh(profile)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not save owner profile")

    return profile_data(profile)




# ===== Inventory Reports =====

@app.get("/api/reports/stock", dependencies=[Depends(require_admin)])
def stock_report(db: Session = Depends(get_db)):
    medicines = db.scalars(
        select(Medicine).order_by(Medicine.name, Medicine.expiry_date)
    ).all()

    today = date.today()
    rows = []
    total_value = Decimal("0.00")

    for m in medicines:
        value = money(m.quantity * m.unit_price)
        total_value += value

        rows.append({
            "medicine_id": m.id,
            "name": m.name,
            "batch_number": m.batch_number,
            "quantity": m.quantity,
            "reorder_level": m.reorder_level,
            "unit_price": str(m.unit_price),
            "stock_value": str(value),
            "expiry_date": m.expiry_date.isoformat(),
            "expired": m.expiry_date <= today,
            "low_stock": m.quantity <= m.reorder_level,
        })

    return {
        "total_batches": len(rows),
        "total_quantity": sum(m.quantity for m in medicines),
        "stock_value": str(money(total_value)),
        "valuation_basis": "selling_price_not_cost",
        "items": rows,
    }


@app.get("/api/reports/expiry", dependencies=[Depends(require_admin)])
def expiry_report(
    days: int = 90,
    db: Session = Depends(get_db),
):
    if days < 0 or days > 3650:
        raise HTTPException(422, "Days must be between 0 and 3650")

    today = date.today()

    medicines = db.scalars(
        select(Medicine)
        .where(Medicine.quantity > 0)
        .order_by(Medicine.expiry_date, Medicine.name)
    ).all()

    expired = []
    expiring = []

    for m in medicines:
        days_left = (m.expiry_date - today).days

        row = {
            "medicine_id": m.id,
            "name": m.name,
            "batch_number": m.batch_number,
            "quantity": m.quantity,
            "expiry_date": m.expiry_date.isoformat(),
            "days_left": days_left,
        }

        if days_left <= 0:
            expired.append(row)
        elif days_left <= days:
            expiring.append(row)

    return {
        "warning_days": days,
        "expired_count": len(expired),
        "expiring_count": len(expiring),
        "expired": expired,
        "expiring": expiring,
    }


# ===== End Inventory Reports =====


# ===== GST Sales Report =====

@app.get("/api/reports/gst", dependencies=[Depends(require_admin)])
def gst_sales_report(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "Invalid date range")

    query = select(PharmacySale)

    if start_date:
        query = query.where(
            func.date(PharmacySale.created_at) >= start_date
        )
    if end_date:
        query = query.where(
            func.date(PharmacySale.created_at) <= end_date
        )

    sales = db.scalars(
        query.order_by(PharmacySale.id)
    ).all()

    fields = (
        "subtotal", "discount_total", "taxable_total",
        "cgst_total", "sgst_total", "igst_total", "total"
    )

    totals = {
        field: money(sum(
            (getattr(sale, field) or Decimal("0")
             for sale in sales),
            Decimal("0")
        ))
        for field in fields
    }

    return {
        "report_type": "gross_sales_gst",
        "note": "Excludes return adjustments and credit notes.",
        "start_date": str(start_date) if start_date else None,
        "end_date": str(end_date) if end_date else None,
        "invoice_count": len(sales),
        "totals": {
            key: str(value)
            for key, value in totals.items()
        },
        "invoices": [
            {
                "invoice_number": sale.invoice_number,
                "date": sale.created_at.isoformat()
                    if sale.created_at else None,
                "total": str(sale.total),
                "cgst": str(sale.cgst_total or 0),
                "sgst": str(sale.sgst_total or 0),
                "igst": str(sale.igst_total or 0),
            }
            for sale in sales
        ],
    }


# ===== End GST Sales Report =====


@app.get("/api/finance/summary",
         dependencies=[Depends(require_admin)])
def finance_summary(db: Session = Depends(get_db)):
    gross = db.scalar(
        select(func.coalesce(func.sum(PharmacySale.total), 0))
    )
    returns = db.scalar(
        select(func.coalesce(func.sum(SaleReturn.refund_amount), 0))
    )
    sales_count = db.scalar(
        select(func.count(PharmacySale.id))
    )

    purchase_items = db.execute(
        select(
            PurchaseOrder.status,
            PurchaseOrderItem.quantity,
            PurchaseOrderItem.unit_cost,
        ).join(
            PurchaseOrderItem,
            PurchaseOrderItem.purchase_order_id == PurchaseOrder.id
        )
    ).all()

    pending_orders = Decimal("0.00")
    received_orders = Decimal("0.00")

    for status, qty, cost in purchase_items:
        amount = Decimal(qty) * cost
        if status == "received":
            received_orders += amount
        elif status == "pending":
            pending_orders += amount

    gross = Decimal(gross)
    returns = Decimal(returns)

    return {
        "sales_count": sales_count,
        "gross_sales": str(gross),
        "recorded_refunds": str(returns),
        "sales_after_recorded_refunds": str(gross - returns),
        "received_purchase_order_value": str(received_orders),
        "pending_purchase_order_value": str(pending_orders),
        "profit_available": False,
        "note": (
            "Refunds are recorded obligations, not confirmed "
            "payments. Purchase order values are not cost of "
            "goods sold. Profit cannot yet be calculated."
        ),
    }


# ===== End PharmaCare Batch 1 =====



# ===== Staff Accounts and Roles =====

class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(default=True)
    session_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


STAFF_ROLES = {"manager", "pharmacist", "cashier", "inventory"}


class StaffCreateInput(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    role: str
    password: str = Field(min_length=12, max_length=128)


class StaffUpdateInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    role: str
    active: bool


class StaffPasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=128)


def staff_details(user):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "active": user.active,
    }


def validate_staff_role(role):
    if role not in STAFF_ROLES:
        raise HTTPException(422, "Invalid staff role")


@app.get("/api/users", dependencies=[Depends(require_admin)])
def list_staff_users(db: Session = Depends(get_db)):
    users = db.scalars(
        select(StaffUser).order_by(StaffUser.id)
    ).all()
    return [staff_details(user) for user in users]


@app.post("/api/users", status_code=201,
          dependencies=[Depends(require_admin)])
def create_staff_user(
    payload: StaffCreateInput,
    db: Session = Depends(get_db)
):
    validate_staff_role(payload.role)

    username = payload.username.strip().lower()
    display_name = payload.display_name.strip()

    if not display_name or not username.isascii() or not all(
        c.islower() or c.isdigit() or c in "._-"
        for c in username
    ):
        raise HTTPException(422, "Invalid username or display name")

    if db.scalar(select(StaffUser.id).where(
        StaffUser.username == username
    )) is not None:
        raise HTTPException(409, "Username already exists")

    user = StaffUser(
        username=username,
        display_name=display_name,
        role=payload.role,
        password_hash=hash_new_password(payload.password),
        active=True,
        session_version=secrets.token_hex(24),
    )

    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Could not create user")

    return staff_details(user)


@app.put("/api/users/{user_id}",
         dependencies=[Depends(require_admin)])
def update_staff_user(
    user_id: int,
    payload: StaffUpdateInput,
    db: Session = Depends(get_db)
):
    validate_staff_role(payload.role)

    user = db.get(StaffUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    if not payload.display_name.strip():
        raise HTTPException(422, "Display name required")

    user.display_name = payload.display_name.strip()
    user.role = payload.role
    user.active = payload.active
    user.session_version = secrets.token_hex(24)

    db.commit()
    return staff_details(user)


@app.post("/api/users/{user_id}/reset-password",
          dependencies=[Depends(require_admin)])
def reset_staff_password(
    user_id: int,
    payload: StaffPasswordInput,
    db: Session = Depends(get_db)
):
    user = db.get(StaffUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    user.password_hash = hash_new_password(payload.password)
    user.session_version = secrets.token_hex(24)
    db.commit()

    return {"message": "Password updated; prior sessions invalidated"}



def require_staff_access(
    request: Request,
    allowed_roles: set[str],
):
    if request.session.get("admin") is True:
        require_admin(request)
        return {"role": "owner"}

    staff_id = request.session.get("staff_id")
    if not staff_id:
        raise HTTPException(401, "Login required")

    with SessionLocal() as db:
        staff = db.get(StaffUser, staff_id)

        if (
            staff is None
            or not staff.active
            or request.session.get("staff_version")
                != staff.session_version
        ):
            raise HTTPException(401, "Staff session expired")

        if staff.role not in allowed_roles:
            raise HTTPException(403, "Insufficient permissions")

        return staff_details(staff)


@app.get("/api/staff/me")
def staff_profile(request: Request):
    return require_staff_access(
        request, STAFF_ROLES
    )


@app.get("/api/staff/inventory")
def staff_inventory(
    request: Request,
    db: Session = Depends(get_db),
):
    require_staff_access(
        request,
        {"manager", "pharmacist", "cashier", "inventory"},
    )

    medicines = db.scalars(
        select(Medicine).order_by(
            Medicine.name, Medicine.expiry_date
        )
    ).all()

    return [
        {
            "id": m.id,
            "name": m.name,
            "batch_number": m.batch_number,
            "quantity": m.quantity,
            "expiry_date": m.expiry_date.isoformat(),
            "unit_price": str(m.unit_price),
        }
        for m in medicines
    ]


# ===== End Staff Accounts =====


# ===== Admin Password and Audit =====
import secrets

class AdminCredential(Base):
    __tablename__ = "admin_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    session_version: Mapped[str] = mapped_column(String(64))


class SecurityAudit(Base):
    __tablename__ = "security_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(160))
    method: Mapped[str] = mapped_column(String(12))
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def check_hash(password, stored):
    try:
        algorithm, iterations, salt_hex, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(iterations)
        if rounds < 100000 or rounds > 2000000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(),
            bytes.fromhex(salt_hex), rounds
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_new_password(password):
    rounds = 310000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, rounds
    ).hex()
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest}"


def verify_active_password(password):
    with SessionLocal() as db:
        record = db.get(AdminCredential, 1)
        if record is not None:
            return check_hash(password, record.password_hash)
    return verify_password(password)


class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


@app.post("/api/security/change-password",
          dependencies=[Depends(require_admin)])
def change_admin_password(
    payload: PasswordChangeInput,
    request: Request,
    db: Session = Depends(get_db)
):
    record = db.scalars(
        select(AdminCredential)
        .where(AdminCredential.id == 1)
        .with_for_update()
    ).first()

    if record is None:
        valid = verify_password(payload.current_password)
    else:
        valid = check_hash(
            payload.current_password, record.password_hash
        )

    if not valid:
        raise HTTPException(403, "Current password is incorrect")

    if payload.new_password == payload.current_password:
        raise HTTPException(422, "New password must be different")

    if record is None:
        record = AdminCredential(
            id=1,
            password_hash="",
            session_version=""
        )
        db.add(record)

    record.password_hash = hash_new_password(payload.new_password)
    record.session_version = secrets.token_hex(24)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Password update failed")

    request.session.clear()
    request.session["admin"] = True
    request.session["auth_version"] = record.session_version

    return {"message": "Password changed successfully"}


@app.get("/api/security/audit",
         dependencies=[Depends(require_admin)])
def get_security_audit(db: Session = Depends(get_db)):
    records = db.scalars(
        select(SecurityAudit)
        .order_by(SecurityAudit.id.desc())
        .limit(200)
    ).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "method": r.method,
            "status_code": r.status_code,
            "created_at": (
                r.created_at.isoformat() if r.created_at else None
            )
        }
        for r in records
    ]


@app.middleware("http")
async def record_admin_mutations(request: Request, call_next):
    response = await call_next(request)

    path = request.url.path
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and path.startswith("/api/")
        and path not in ("/api/login", "/api/logout")
        and 200 <= response.status_code < 400
        and request.scope.get("session", {}).get("admin") is True
    ):
        try:
            with SessionLocal() as db:
                db.add(SecurityAudit(
                    action=path[:160],
                    method=request.method,
                    status_code=response.status_code
                ))
                db.commit()
        except Exception:
            # Audit failures must not turn a committed transaction
            # into a misleading client-side failure.
            pass

    return response


# ===== End Admin Password and Audit =====

@app.get("/")
def dashboard():
    return FileResponse("app/static/index.html")


app.mount("/static", StaticFiles(directory="app/static"), name="static")
