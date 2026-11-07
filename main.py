import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL.")
if len(JWT_SECRET) < 32 or len(ADMIN_SECRET) < 24:
    raise RuntimeError("Configura JWT_SECRET (32+ caracteres) y ADMIN_SECRET (24+ caracteres).")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
password_hash = PasswordHash.recommended()

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "store_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    referral_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    referred_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("store_users.id"), nullable=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Coupon(Base):
    __tablename__ = "store_coupons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("store_users.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    amount_off: Mapped[int] = mapped_column(Integer, default=3000)
    redeemed: Mapped[bool] = mapped_column(Boolean, default=False)
    order_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Order(Base):
    __tablename__ = "store_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("store_users.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(20))
    product_name: Mapped[str] = mapped_column(String(180))
    subtotal: Mapped[int] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    discount_label: Mapped[str] = mapped_column(String(100), default="")
    total: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    coupon_id: Mapped[Optional[str]] = mapped_column(ForeignKey("store_coupons.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="KrmaVerso Store API", version="1.0.0")
allowed_origins = [v.strip() for v in os.getenv(
    "CORS_ORIGINS",
    "https://krmaverse.github.io,http://localhost:8000"
).split(",") if v.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Secret"],
)

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    referral_code: Optional[str] = Field(default=None, max_length=20)
    accept_data_policy: bool

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class OrderIn(BaseModel):
    product_id: str = Field(min_length=3, max_length=20)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def make_referral_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "KRMA-" + "".join(secrets.choice(alphabet) for _ in range(7))
        if not db.scalar(select(User).where(User.referral_code == code)):
            return code
    raise HTTPException(500, "No fue posible crear tu código. Intenta de nuevo.")

def token_for(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user.id, "iat": now, "exp": now + timedelta(hours=12)},
        JWT_SECRET, algorithm="HS256"
    )

def get_current_user(authorization: Optional[str] = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Inicia sesión para continuar.")
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(401, "Sesión vencida. Inicia sesión nuevamente.")
    user = db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(401, "No se encontró la cuenta.")
    return user

def require_admin(x_admin_secret: Optional[str] = Header(default=None)):
    if not secrets.compare_digest(x_admin_secret or "", ADMIN_SECRET):
        raise HTTPException(403, "No autorizado.")

def catalog():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))

def make_coupon_code():
    chars = string.ascii_uppercase + string.digits
    return "AMIGO-" + "".join(secrets.choice(chars) for _ in range(7))

def public_user(user: User, db: Session):
    now = datetime.now(timezone.utc)
    paid_count = len(db.scalars(select(Order).where(
        Order.user_id == user.id, Order.status == "paid"
    )).all())
    coupons = db.scalars(select(Coupon).where(
        Coupon.user_id == user.id,
        Coupon.redeemed == False,
        Coupon.expires_at > now
    )).all()
    orders = db.scalars(select(Order).where(
        Order.user_id == user.id
    ).order_by(Order.created_at.desc()).limit(15)).all()
    return {
        "name": user.name,
        "email": user.email,
        "referral_code": user.referral_code,
        "referral_link": "https://krmaverse.github.io/KrmaVerso-Store/tienda.html?ref=" + user.referral_code + "#cuenta",
        "first_purchase_available": paid_count == 0,
        "coupons": [{
            "code": c.code,
            "amount_off": c.amount_off,
            "expires_at": c.expires_at.isoformat()
        } for c in coupons],
        "orders": [{
            "id": o.id, "product_name": o.product_name,
            "subtotal": o.subtotal, "discount": o.discount,
            "total": o.total, "status": o.status,
            "created_at": o.created_at.isoformat()
        } for o in orders]
    }

@app.get("/")
def home():
    return {"service": "KrmaVerso Store API", "status": "ok", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/auth/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if not data.accept_data_policy:
        raise HTTPException(400, "Debes aceptar el tratamiento de datos.")
    email = str(data.email).lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Ese correo ya está registrado. Inicia sesión.")
    referrer = None
    if data.referral_code:
        referrer = db.scalar(select(User).where(
            User.referral_code == data.referral_code.strip().upper()
        ))
        if not referrer:
            raise HTTPException(400, "El código de referido no existe.")
    user = User(
        name=data.name.strip(), email=email,
        password_hash=password_hash.hash(data.password),
        referral_code=make_referral_code(db),
        referred_by_id=referrer.id if referrer else None
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": token_for(user), "token_type": "bearer", "user": public_user(user, db)}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower().strip()))
    if not user or not password_hash.verify(data.password, user.password_hash):
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    return {"access_token": token_for(user), "token_type": "bearer", "user": public_user(user, db)}

@app.get("/api/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return public_user(user, db)

@app.post("/api/orders")
def create_order(data: OrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pending = db.scalar(select(Order).where(
        Order.user_id == user.id, Order.status == "pending"
    ))
    if pending:
        raise HTTPException(409, "Tienes un pedido pendiente. Contacta con soporte para revisarlo.")
    item = next((p for p in catalog() if p["id"] == data.product_id), None)
    if not item or item.get("precio") is None:
        raise HTTPException(404, "Este artículo requiere cotización por WhatsApp.")
    subtotal = int(item["precio"])
    paid_count = len(db.scalars(select(Order).where(
        Order.user_id == user.id, Order.status == "paid"
    )).all())
    discount, label, coupon = 0, "", None
    if paid_count == 0:
        discount = round(subtotal * 0.10)
        label = "Descuento de primera compra (10%)"
    else:
        now = datetime.now(timezone.utc)
        coupon = db.scalar(select(Coupon).where(
            Coupon.user_id == user.id,
            Coupon.redeemed == False,
            Coupon.expires_at > now
        ).order_by(Coupon.amount_off.desc()))
        if coupon:
            discount = min(subtotal, coupon.amount_off)
            label = "Cupón de referido"
    total = max(0, subtotal - discount)
    order = Order(
        user_id=user.id, product_id=item["id"], product_name=item["nombre"],
        subtotal=subtotal, discount=discount, discount_label=label,
        total=total, coupon_id=coupon.id if coupon else None
    )
    db.add(order)
    if coupon:
        coupon.redeemed = True
        coupon.order_id = order.id
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id, "product_name": order.product_name,
        "subtotal": subtotal, "discount": discount,
        "discount_label": label or "Sin descuento",
        "total": total, "currency": "COP", "status": "pending",
        "message": "Pedido creado. Confirma el total con KrmaVerso Store antes de pagar."
    }

@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(
        Order.id == order_id, Order.user_id == user.id
    ))
    if not order or order.status != "pending":
        raise HTTPException(404, "No se encontró el pedido pendiente.")
    if order.coupon_id:
        coupon = db.get(Coupon, order.coupon_id)
        if coupon:
            coupon.redeemed = False
            coupon.order_id = None
    order.status = "cancelled"
    db.commit()
    return {"ok": True}

@app.get("/api/admin/orders", dependencies=[Depends(require_admin)])
def admin_orders(db: Session = Depends(get_db)):
    rows = db.scalars(select(Order).where(
        Order.status == "pending"
    ).order_by(Order.created_at.asc()).limit(200)).all()
    return [{
        "id": o.id, "user_id": o.user_id, "product_name": o.product_name,
        "subtotal": o.subtotal, "discount": o.discount, "total": o.total,
        "created_at": o.created_at.isoformat()
    } for o in rows]

@app.post("/api/admin/orders/{order_id}/paid", dependencies=[Depends(require_admin)])
def mark_paid(order_id: str, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or order.status != "pending":
        raise HTTPException(404, "Pedido pendiente no encontrado.")
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    buyer = db.get(User, order.user_id)
    if buyer and buyer.referred_by_id and not buyer.referral_rewarded:
        expiry = datetime.now(timezone.utc) + timedelta(days=90)
        for user_id in (buyer.id, buyer.referred_by_id):
            db.add(Coupon(
                user_id=user_id, code=make_coupon_code(),
                amount_off=3000, expires_at=expiry
            ))
        buyer.referral_rewarded = True
    db.commit()
    return {"ok": True, "message": "Pago confirmado manualmente y referidos procesados si aplicaba."}
