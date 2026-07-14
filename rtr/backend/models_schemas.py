# models_schemas.py
# Production-level Database Models & Pydantic Schemas
# Rocky Trendy Realities - Physical Furniture, AI Customizer, & CMS

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Any, Dict

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Numeric,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    Index,
    JSON
)
from sqlalchemy.orm import declarative_base, relationship
from pydantic import (
    BaseModel, 
    EmailStr, 
    Field, 
    ConfigDict, 
    model_validator,
    computed_field
)

# ======================================================
# DATABASE BASE & MIXINS
# ======================================================

Base = declarative_base()

class TimestampMixin:
    """Standardizes creation and update timestamps across all models."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

class SoftDeleteMixin:
    """Allows 'soft deleting' records (hiding them) instead of permanent removal."""
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)

# ======================================================
# ENUMS
# ======================================================

class ProductCategory(str, Enum):
    SOFA = "sofa"
    TABLE = "table"
    BEDROOM = "bedroom"
    DINING = "dining"
    OFFICE = "office"
    FINISH = "finish"
    DECOR = "decor"

class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"

class PaymentMethod(str, Enum):
    PAYSTACK = "paystack"
    WALLET = "wallet"
    WHATSAPP = "whatsapp"  # <-- Added WhatsApp checkout path

class AdminRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MANAGER = "manager"

class AddressType(str, Enum):
    BILLING = "billing"
    SHIPPING = "shipping"

class OTPPurpose(str, Enum):
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"
    TWO_FACTOR = "2fa"

class BannerType(str, Enum):
    HERO = "hero"
    ADVERT = "advert"
    LOGO = "logo"
    FLOATING = "floating"

# ======================================================
# AUTH & USER MODELS
# ======================================================

class Admin(Base, TimestampMixin):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True) 
    password_hash = Column(Text, nullable=False) # Note: Stores raw yaml credential per configuration
    role = Column(SQLEnum(AdminRole), default=AdminRole.ADMIN, nullable=False)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    
    # Profile Info
    full_name = Column(String(150))
    phone = Column(String(50))
    country = Column(String(100))
    avatar_url = Column(String(500), nullable=True)
    
    # Status
    is_verified = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False) 
    
    # Security
    email_otp = Column(String(10), nullable=True)
    otp_expiry = Column(DateTime, nullable=True)
    two_factor_enabled = Column(Boolean, default=False)

    # Wallet (Upgraded to high-precision Numeric)
    balance = Column(Numeric(12, 2), default=Decimal('0.00'), nullable=False)

    # Relationships
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    reviews = relationship("ProductReview", back_populates="user")
    wishlist = relationship("Wishlist", back_populates="user", cascade="all, delete-orphan")

class Address(Base, TimestampMixin):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(SQLEnum(AddressType), default=AddressType.SHIPPING)
    
    street_line1 = Column(String(255), nullable=False)
    street_line2 = Column(String(255))
    city = Column(String(100), nullable=False)
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(100), nullable=False)
    
    user = relationship("User", back_populates="addresses")

class OTPRecord(Base):
    __tablename__ = "otp_records"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), index=True, nullable=False)
    otp_hash = Column(String(255), nullable=False)
    purpose = Column(SQLEnum(OTPPurpose))
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# ======================================================
# CATALOG MODELS
# ======================================================

class Product(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    
    name = Column(String(255), nullable=False, index=True)
    product_category = Column(SQLEnum(ProductCategory), default=ProductCategory.DECOR, nullable=False, index=True)
    description = Column(Text)
    
    # Financials (Upgraded to high-precision Numeric)
    price = Column(Numeric(12, 2), nullable=False, default=Decimal('0.00'))
    old_price = Column(Numeric(12, 2), nullable=True)
    badge = Column(String(50), nullable=True)
    
    quantity = Column(Integer, default=0, nullable=False)
    delivery_duration = Column(String(100), nullable=True)
    
    image_url = Column(Text, nullable=True)
    gallery_images = Column(JSON, default=list)
    
    is_featured = Column(Boolean, default=False)
    is_trending = Column(Boolean, default=False)
    
    reviews = relationship("ProductReview", back_populates="product", cascade="all, delete-orphan")
    order_items = relationship("OrderItem", back_populates="product")

class ProductReview(Base, TimestampMixin):
    __tablename__ = "product_reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text)
    is_verified_purchase = Column(Boolean, default=False)

    user = relationship("User", back_populates="reviews")
    product = relationship("Product", back_populates="reviews")

class Wishlist(Base, TimestampMixin):
    __tablename__ = "wishlists"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    user = relationship("User", back_populates="wishlist")
    product = relationship("Product")

# ======================================================
# ORDER & TRANSACTION MODELS
# ======================================================

class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_reference = Column(String(50), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Snapshot customer details for physical fulfillment
    customer_email = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=False)
    shipping_address = Column(Text, nullable=False)
    
    # Financials (Upgraded to high-precision Numeric)
    total_amount = Column(Numeric(12, 2), nullable=False)
    
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING, index=True)
    payment_method = Column(SQLEnum(PaymentMethod), default=PaymentMethod.PAYSTACK)
    payment_reference = Column(String(255), index=True)
    customer_ip = Column(String(50))
    
    fulfillment_note = Column(Text, nullable=True) 

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    quantity = Column(Integer, default=1, nullable=False)
    
    # Financials (Upgraded to high-precision Numeric)
    unit_price_at_purchase = Column(Numeric(12, 2), nullable=False) 
    
    # Catalog snapshot in case product is modified or deleted later
    product_name_snapshot = Column(String(255), nullable=True)
    product_image_snapshot = Column(Text, nullable=True)
    
    # AI Customizer payload
    is_customized = Column(Boolean, default=False)
    customization_notes = Column(Text, nullable=True)
    custom_image_url = Column(String(500), nullable=True)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")

class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    order_id = Column(Integer, ForeignKey("orders.id"))
    
    # Financials (Upgraded to high-precision Numeric)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="NGN")
    tx_hash = Column(String(255))
    status = Column(String(50), default="confirmed")
    provider = Column(String(50), default="Paystack") 

    user = relationship("User", back_populates="transactions")
    order = relationship("Order", back_populates="transactions")

# ======================================================
# CMS MODELS (Hero, Advert, Logo, Floating)
# ======================================================

class Banner(Base, TimestampMixin):
    __tablename__ = "banners"

    id = Column(Integer, primary_key=True)
    image_url = Column(Text, nullable=False)
    section_type = Column(SQLEnum(BannerType), default=BannerType.HERO, index=True)
    
    title = Column(String(255), nullable=True)
    target_url = Column(Text, nullable=True)
    
    display_order = Column(Integer, default=0, index=True)
    is_active = Column(Boolean, default=True)

# ======================================================
# PYDANTIC SCHEMAS (V2)
# ======================================================

class ORMBase(BaseModel):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Auth Schemas ---

class UserCreateSchema(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    country: str
    full_name: Optional[str] = None

class AdminLoginSchema(BaseModel):
    username: str
    password: str

class UserResponse(ORMBase):
    email: EmailStr
    full_name: Optional[str]
    phone: Optional[str]
    country: Optional[str]
    balance: Decimal
    is_verified: bool
    is_banned: bool
    avatar_url: Optional[str]

# --- Product Schemas ---

class ProductBaseSchema(BaseModel):
    name: str
    product_category: ProductCategory = Field(default=ProductCategory.DECOR)
    description: Optional[str] = None
    
    price: Decimal = Field(..., gt=0)
    old_price: Optional[Decimal] = None
    badge: Optional[str] = None
    
    quantity: int = Field(0, ge=0)
    delivery_duration: Optional[str] = None
    
    is_featured: bool = False
    is_trending: bool = False

class ProductCreateSchema(ProductBaseSchema):
    image_url: str 
    
class ProductUpdateSchema(ProductBaseSchema):
    name: Optional[str] = None
    product_category: Optional[ProductCategory] = None
    price: Optional[Decimal] = None
    quantity: Optional[int] = None
    image_url: Optional[str] = None 

class ProductSchema(ORMBase):
    name: str
    product_category: ProductCategory
    description: Optional[str]
    price: Decimal
    old_price: Optional[Decimal]
    badge: Optional[str]
    quantity: int
    delivery_duration: Optional[str]
    image_url: Optional[str]
    is_featured: bool
    is_trending: bool
    
    is_available: bool = True

    @computed_field
    @property
    def optimized_url(self) -> Optional[str]:
        """Automatically injects Cloudinary auto-optimization params if hosted on Cloudinary."""
        if self.image_url and "res.cloudinary.com" in self.image_url and "/upload/" in self.image_url:
            parts = self.image_url.split("/upload/")
            return f"{parts[0]}/upload/f_auto,q_auto/{parts[1]}"
        return self.image_url

    @model_validator(mode='before')
    @classmethod
    def compute_availability(cls, data: Any):
        qty = getattr(data, 'quantity', 0) if not isinstance(data, dict) else data.get('quantity', 0)
        if isinstance(data, dict):
            data['is_available'] = qty > 0
        else:
            data.is_available = qty > 0
        return data

# --- Cart & Order Schemas ---

class CartItemSchema(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1)
    is_customized: bool = False
    customization_notes: Optional[str] = None
    custom_image_url: Optional[str] = None

class CheckoutRequest(BaseModel):
    items: List[CartItemSchema]
    customer_email: EmailStr
    customer_phone: str
    shipping_address: str
    payment_method: PaymentMethod = PaymentMethod.PAYSTACK

class OrderItemResponse(BaseModel):
    product_id: int
    product_name_snapshot: Optional[str]
    product_image_snapshot: Optional[str]
    quantity: int
    unit_price_at_purchase: Decimal
    is_customized: bool
    customization_notes: Optional[str]
    custom_image_url: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)

class OrderResponse(ORMBase):
    order_reference: Optional[str]
    customer_email: str
    customer_phone: str
    shipping_address: str
    total_amount: Decimal
    status: OrderStatus
    payment_method: PaymentMethod
    payment_reference: Optional[str]
    items: List[OrderItemResponse] = [] 

# --- CMS Schemas ---

class BannerCreateSchema(BaseModel):
    image_url: str
    section_type: BannerType = BannerType.HERO
    title: Optional[str] = None
    target_url: Optional[str] = None
    display_order: int = 0
    is_active: bool = True

class BannerUpdateSchema(BannerCreateSchema):
    image_url: Optional[str] = None

class BannerSchema(ORMBase):
    image_url: str
    section_type: BannerType
    title: Optional[str]
    target_url: Optional[str]
    display_order: int
    is_active: bool

# Alias to resolve import errors in main.py or legacy routers
PhysicalOrderCreate = CheckoutRequest
