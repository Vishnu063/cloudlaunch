import os
import hmac
import hashlib
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, String, Integer, Date, Numeric, DateTime,
    func, select
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


class MedicineInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="General", max_length=100)
    batch_number: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0)
    reorder_level: int = Field(default=10, ge=0)
    unit_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    expiry_date: date
    supplier: str = Field(default="", max_length=160)


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
    if request.session.get("admin") is not True:
        raise HTTPException(status_code=401, detail="Login required")


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
    https_only=False,
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
    return {"authenticated": request.session.get("admin") is True}


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/login")
def login(payload: LoginInput, request: Request):
    if not verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    request.session.clear()
    request.session["admin"] = True
    return {"authenticated": True}


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
    medicine_id: int, payload: MedicineInput, db: Session = Depends(get_db)
):
    medicine = db.get(Medicine, medicine_id)
    if medicine is None:
        raise HTTPException(status_code=404, detail="Medicine not found")
    for key, value in payload.model_dump().items():
        setattr(medicine, key, value)
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
    db.delete(medicine)
    db.commit()


@app.get("/")
def dashboard():
    return FileResponse("app/static/index.html")


app.mount("/static", StaticFiles(directory="app/static"), name="static")
