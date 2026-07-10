# services.py
# Production-level Business Logic Layer
# Rocky Trendy Realities - Physical Furniture & AI Customizer

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update

# IMPORT MODELS
from models_schemas import (
    User,
    Admin,
    Product,
    Order,
    OrderItem,
    Transaction,
    Banner,
    BannerType,
    OrderStatus,
    PaymentMethod,
    OTPPurpose,
    CheckoutRequest
)

# IMPORT UTILS & CORE
from utils import (
    generate_otp,
    send_email_otp,
    send_fulfillment_email,
    log_action
)

from core import (
    create_access_token,
    hash_password,
    verify_password,
    settings
)

# IMPORT PAYSTACK (From your newly added paystack.py)
from paystack import initialize_transaction

# =========================================================
# CONFIG & LOGGING
# =========================================================

logger = logging.getLogger("app.services")
logger.setLevel(logging.INFO)

# =========================================================
# 1. USER AUTHENTICATION & RECOVERY SERVICES
# =========================================================

async def create_user_service(db: AsyncSession, email: str, password: str, country: str):
    """Registers a new user and triggers email verification."""
    result = await db.execute(select(User).where(User.email == email))
    existing_user = result.scalar_one_or_none()

    hashed_pw = hash_password(password)
    otp_code = generate_otp()
    otp_expiry_dt = datetime.utcnow() + timedelta(minutes=10)

    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(status_code=400, detail="User with this email already exists.")
        
        # Treat as a new attempt for unverified users
        existing_user.password_hash = hashed_pw
        existing_user.country = country
        existing_user.email_otp = otp_code
        existing_user.otp_expiry = otp_expiry_dt
        
        await db.commit()
        
        try:
            await send_email_otp(email, otp_code, OTPPurpose.EMAIL_VERIFY)
        except Exception as e:
            logger.error(f"Failed to resend welcome email to {email}: {e}")
        
        return existing_user

    new_user = User(
        email=email,
        password_hash=hashed_pw,
        country=country,
        email_otp=otp_code,
        otp_expiry=otp_expiry_dt,
        is_verified=False,
        balance=0.0
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    try:
        await send_email_otp(email, otp_code, OTPPurpose.EMAIL_VERIFY)
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {e}")
    
    return new_user

async def verify_user_email_service(db: AsyncSession, email: str, otp: str):
    """Verifies a user's email address and clears the OTP fields."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_verified:
        return {"message": "User already verified"}
    if user.email_otp != otp:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    if user.otp_expiry and datetime.utcnow() > user.otp_expiry:
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    user.is_verified = True
    user.email_otp = None
    user.otp_expiry = None
    
    await db.commit()
    return {"message": "Email verified successfully"}

# =========================================================
# 2. ADMIN & CMS SERVICES
# =========================================================

async def bootstrap_admins(db: AsyncSession):
    """Seeds admin accounts on startup using .env credentials."""
    # Assuming credentials are provided in settings.ADMIN_USERNAMES / ADMIN_PASSWORDS
    # This is a simplified bootstrap implementation
    admin_users = settings.ADMIN_USERNAMES.split(",") if hasattr(settings, 'ADMIN_USERNAMES') else []
    admin_passwords = settings.ADMIN_PASSWORDS.split(",") if hasattr(settings, 'ADMIN_PASSWORDS') else []

    admin_credentials = dict(zip([u.strip() for u in admin_users], [p.strip() for p in admin_passwords]))

    for username, password in admin_credentials.items():
        if not username or not password:
            continue
        result = await db.execute(select(Admin).where(Admin.username == username))
        if not result.scalar_one_or_none():
            logger.info(f"Seeding admin: {username}")
            role = "superadmin" if username == "admin" else "admin"
            new_admin = Admin(
                username=username, 
                password_hash=hash_password(password), 
                role=role, 
                is_active=True
            )
            db.add(new_admin)
            
    await db.commit()

async def admin_login_service(db: AsyncSession, username: str, password: str):
    """Authenticates admin and returns JWT."""
    result = await db.execute(select(Admin).where(Admin.username == username))
    admin = result.scalar_one_or_none()
    
    if not admin or not verify_password(password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")
    
    admin.last_login = datetime.utcnow()
    await db.commit()
    
    return create_access_token({"sub": admin.username, "role": admin.role.value})

async def process_admin_order_action(
    db: AsyncSession, 
    order_id: int, 
    action: str, 
    manual_content: Optional[str] = None
):
    """Handles Admin manual fulfillment steps for physical logistics."""
    stmt = (
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if action == "cancel":
        order.status = OrderStatus.CANCELLED
        await db.commit()
        return {"status": "cancelled", "detail": "Order cancelled."}

    if action == "ship":
        order.status = OrderStatus.SHIPPED
        order.fulfillment_note = manual_content or "Your order has been shipped."
        order.updated_at = datetime.utcnow()
        await db.commit()
        
        # Optionally trigger shipping email
        await send_fulfillment_email(
            user_email=order.customer_email,
            product_name="Your Rocky Trendy Realities Order",
            order_reference=order.order_reference,
            manual_text=order.fulfillment_note
        )
        return {"status": "shipped", "detail": "Order marked as shipped."}

    if action == "deliver":
        order.status = OrderStatus.DELIVERED
        order.updated_at = datetime.utcnow()
        await db.commit()
        return {"status": "delivered", "detail": "Order marked as delivered."}

    raise HTTPException(status_code=400, detail="Invalid action")

# =========================================================
# 3. ORDER CREATION & CHECKOUT SERVICES
# =========================================================

async def create_order_service(db: AsyncSession, user_id: int, order_data: CheckoutRequest) -> str:
    """
    Orchestrates order creation for Physical Items.
    1. Validates Stock.
    2. Calculates Total (Snapshotting AI Customizations).
    3. Calls Paystack API.
    4. Returns Authorization URL.
    """
    if not order_data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one_or_none()

    # Pre-fetch Products
    product_ids = [item.product_id for item in order_data.items]
    stmt = select(Product).where(Product.id.in_(product_ids)).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None)))
    result = await db.execute(stmt)
    products_db = {p.id: p for p in result.scalars().all()}
    
    if len(products_db) != len(product_ids):
        raise HTTPException(status_code=404, detail="One or more products not found.")

    total_amount = 0.0
    order_items_objects = []

    # 1. Validation & Calculation
    for item in order_data.items:
        product = products_db[item.product_id]
        
        # Atomic Pre-Checkout Stock Validation
        if product.quantity < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for '{product.name}'")
        
        total_amount += product.price * item.quantity
        
        # Prepare OrderItem with AI Snapshots
        order_items_objects.append(
            OrderItem(
                product_id=product.id,
                quantity=item.quantity,
                unit_price_at_purchase=product.price,
                product_name_snapshot=product.name,
                product_image_snapshot=product.image_url,
                is_customized=item.is_customized,
                customization_notes=item.customization_notes,
                custom_image_url=item.custom_image_url
            )
        )

    # 2. Create Order Placeholder
    order_ref = f"RTR-{generate_otp(length=10)}"
    
    new_order = Order(
        user_id=user_id,
        order_reference=order_ref,
        customer_email=order_data.customer_email,
        customer_phone=order_data.customer_phone,
        shipping_address=order_data.shipping_address,
        total_amount=round(total_amount, 2),
        status=OrderStatus.PENDING,
        payment_method=PaymentMethod.PAYSTACK,
        customer_ip="0.0.0.0"
    )
    db.add(new_order)
    await db.flush()

    for order_item in order_items_objects:
        order_item.order_id = new_order.id
        db.add(order_item)

    try:
        # 3. Initialize Paystack
        # Paystack requires the amount in the lowest currency unit (Kobo for NGN)
        amount_in_kobo = int(total_amount * 100)
        
        # You can define a fallback callback_url in your environment variables
        frontend_callback = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000') + "/checkout/callback"
        
        paystack_data = await initialize_transaction(
            email=order_data.customer_email,
            amount=amount_in_kobo,
            reference=order_ref,
            callback_url=frontend_callback,
            metadata={
                "custom_fields": [
                    {"display_name": "Customer Phone", "variable_name": "phone", "value": order_data.customer_phone}
                ]
            }
        )

        await db.commit()
        return paystack_data.get("authorization_url")

    except Exception as e:
        await db.rollback()
        logger.error(f"Order creation failed during Paystack initialization: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to initialize payment gateway.")


# =========================================================
# 4. FULFILLMENT & INVENTORY DEDUCTION
# =========================================================

async def process_successful_payment(db: AsyncSession, order_ref: str, tx_hash: str):
    """
    Called by the Paystack webhook when a charge is confirmed successful.
    1. Locates the Pending order.
    2. Deducts physical inventory atomically.
    3. Updates order status to PAID.
    4. Records the transaction & sends the confirmation email.
    """
    stmt = (
        select(Order)
        .where(Order.order_reference == order_ref)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    # Idempotency Check to prevent double deduction
    if not order or order.status in [OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
        return

    # Atomic Physical Stock Deduction
    for item in order.items:
        await db.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(quantity=Product.quantity - item.quantity)
        )

    # Update Status
    order.status = OrderStatus.PAID
    order.payment_reference = tx_hash

    # Record Transaction
    db.add(Transaction(
        user_id=order.user_id, 
        order_id=order.id, 
        amount=order.total_amount,
        status="confirmed", 
        provider="Paystack", 
        tx_hash=str(tx_hash)
    ))
    
    await db.commit()

    # Send Success Email
    await send_fulfillment_email(
        user_email=order.customer_email,
        product_name="Your Rocky Trendy Realities Order",
        order_reference=order_ref,
        manual_text="We have received your payment. Our design team is currently processing your items for fulfillment."
    )
    
    log_action("payment_confirmed", actor="webhook", order_reference=order_ref)
