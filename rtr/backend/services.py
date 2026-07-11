# services.py
# Production-level Business Logic Layer
# Rocky Trendy Realities - Pure E-Commerce & AI Customizer

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update, delete, or_

# IMPORT MODELS & SCHEMAS
from .models_schemas import (
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
    CheckoutRequest,
    BannerCreateSchema
)

# IMPORT UTILS & CORE
from .utils import (
    generate_otp,
    send_email_otp,
    send_fulfillment_email,
    log_action
)

from .core import (
    create_access_token,
    hash_password,
    verify_password,
    settings
)

# IMPORT PAYSTACK
from .paystack import initialize_transaction

# =========================================================
# CONFIG & LOGGING
# =========================================================

logger = logging.getLogger("app.services")
logger.setLevel(logging.INFO)

# =========================================================
# 1. USER AUTHENTICATION & RECOVERY SERVICES
# =========================================================

async def create_user_service(db: AsyncSession, email: str, password: str, country: str) -> User:
    """Registers a new user and triggers email verification."""
    result = await db.execute(select(User).where(User.email == email))
    existing_user = result.scalar_one_or_none()

    hashed_pw = hash_password(password)
    otp_code = generate_otp()
    otp_expiry_dt = datetime.utcnow() + timedelta(minutes=10)

    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="An account with this email address already exists."
            )
        
        # Treat as a verification resend/retry for unverified accounts
        existing_user.password_hash = hashed_pw
        existing_user.country = country
        existing_user.email_otp = otp_code
        existing_user.otp_expiry = otp_expiry_dt
        
        await db.commit()
        await db.refresh(existing_user)
        
        try:
            await send_email_otp(email, otp_code, OTPPurpose.EMAIL_VERIFY)
            log_action("resend_verification_otp", actor=f"user_{existing_user.id}", metadata={"email": email})
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
        log_action("user_registered", actor=f"user_{new_user.id}", metadata={"email": email, "country": country})
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {e}")
    
    return new_user

async def verify_user_email_service(db: AsyncSession, email: str, otp: str) -> Dict[str, str]:
    """Verifies a user's email address and clears transient OTP fields."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")
    if user.is_verified:
        return {"message": "Account is already verified. Please log in."}
    if user.email_otp != otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code.")
    if user.otp_expiry and datetime.utcnow() > user.otp_expiry:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code has expired. Please request a new one.")

    user.is_verified = True
    user.email_otp = None
    user.otp_expiry = None
    
    await db.commit()
    log_action("email_verified", actor=f"user_{user.id}", metadata={"email": email})
    return {"message": "Email verified successfully."}

async def resend_otp_service(db: AsyncSession, email: str) -> Dict[str, str]:
    """Generates a new OTP for an unverified user and resends the verification email."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account with this email was not found.")
    
    if user.is_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This account is already verified. Please log in.")

    new_otp = generate_otp()
    user.email_otp = new_otp
    user.otp_expiry = datetime.utcnow() + timedelta(minutes=10)

    await db.commit()

    try:
        await send_email_otp(email, new_otp, OTPPurpose.EMAIL_VERIFY)
        log_action("resend_otp", actor=f"user_{user.id}", metadata={"email": email})
    except Exception as e:
        logger.error(f"Failed to resend OTP email to {email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again later."
        )

    return {"message": "A new verification code has been sent to your email."}

# =========================================================
# 2. ADMIN, MODERATION & CMS SERVICES
# =========================================================

async def bootstrap_admins(db: AsyncSession) -> None:
    """Seeds admin accounts on startup using environment credentials."""
    admin_users = settings.ADMIN_USERNAMES.split(",") if hasattr(settings, 'ADMIN_USERNAMES') and settings.ADMIN_USERNAMES else []
    admin_passwords = settings.ADMIN_PASSWORDS.split(",") if hasattr(settings, 'ADMIN_PASSWORDS') and settings.ADMIN_PASSWORDS else []

    admin_credentials = dict(zip([u.strip() for u in admin_users], [p.strip() for p in admin_passwords]))

    for username, password in admin_credentials.items():
        if not username or not password:
            continue
        result = await db.execute(select(Admin).where(Admin.username == username))
        if not result.scalar_one_or_none():
            logger.info(f"Seeding administrative account: {username}")
            role = "superadmin" if username == "admin" else "admin"
            new_admin = Admin(
                username=username, 
                password_hash=hash_password(password), 
                role=role, 
                is_active=True
            )
            db.add(new_admin)
            
    await db.commit()

async def admin_login_service(db: AsyncSession, username: str, password: str) -> str:
    """Authenticates admin user and returns a secure JWT access token."""
    result = await db.execute(select(Admin).where(Admin.username == username))
    admin = result.scalar_one_or_none()
    
    if not admin or not verify_password(password, admin.password_hash):
        log_action("admin_login_failed", actor=username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid administrative credentials.")
    if not admin.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This administrative account has been deactivated.")
    
    admin.last_login = datetime.utcnow()
    await db.commit()
    
    log_action("admin_login_success", actor=f"admin_{admin.username}")
    return create_access_token({"sub": admin.username, "role": admin.role.value if hasattr(admin.role, 'value') else str(admin.role)})

async def moderate_user_service(
    db: AsyncSession, 
    user_id: int, 
    action: str, 
    admin_username: str
) -> Dict[str, str]:
    """Allows administrators to ban or unban users from the platform."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found.")

    if action == "ban":
        user.is_banned = True
        detail_msg = f"User {user.email} has been suspended."
    elif action == "unban":
        user.is_banned = False
        detail_msg = f"User {user.email} has been reinstated."
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid moderation action.")

    await db.commit()
    
    log_action(
        action=f"user_{action}", 
        actor=f"admin_{admin_username}", 
        metadata={"target_user_id": user_id, "target_email": user.email}
    )
    
    return {"status": "success", "detail": detail_msg}

async def create_banner_service(db: AsyncSession, banner_data: BannerCreateSchema, admin_username: str) -> Banner:
    """Creates a new promotional banner for the storefront carousel."""
    new_banner = Banner(
        image_url=banner_data.image_url,
        section_type=banner_data.section_type,
        title=banner_data.title,
        target_url=banner_data.target_url,
        display_order=banner_data.display_order,
        is_active=banner_data.is_active
    )
    db.add(new_banner)
    await db.commit()
    await db.refresh(new_banner)
    
    log_action("banner_created", actor=f"admin_{admin_username}", metadata={"banner_id": new_banner.id, "section": str(banner_data.section_type)})
    return new_banner

# =========================================================
# 3. ORDER CREATION & CHECKOUT SERVICES
# =========================================================

async def create_order_service(db: AsyncSession, user_id: int, order_data: CheckoutRequest) -> str:
    """
    Orchestrates order creation for physical catalog items.
    1. Validates stock availability atomically.
    2. Calculates total cost (including AI customization snapshots).
    3. Initializes Paystack payment gateway transaction.
    4. Returns authorization checkout URL.
    """
    if not order_data.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your checkout cart is empty.")

    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")

    # Pre-fetch catalog items
    product_ids = [item.product_id for item in order_data.items]
    stmt = select(Product).where(Product.id.in_(product_ids)).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None)))
    result = await db.execute(stmt)
    products_db = {p.id: p for p in result.scalars().all()}
    
    if len(products_db) != len(product_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more items in your cart are no longer available.")

    total_amount = 0.0
    order_items_objects = []

    # Validate stock quantities and calculate financial totals
    for item in order_data.items:
        product = products_db[item.product_id]
        
        if product.quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Insufficient stock available for '{product.name}'. Only {product.quantity} remaining."
            )
        
        total_amount += product.price * item.quantity
        
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

    # Generate unique order reference
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
        # Paystack expects amounts in the lowest currency denomination (kobo for NGN)
        amount_in_kobo = int(total_amount * 100)
        frontend_callback = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000') + "/checkout/callback"
        
        paystack_data = await initialize_transaction(
            email=order_data.customer_email,
            amount=amount_in_kobo,
            reference=order_ref,
            callback_url=frontend_callback,
            metadata={
                "custom_fields": [
                    {"display_name": "Customer Phone", "variable_name": "phone", "value": order_data.customer_phone},
                    {"display_name": "Order Reference", "variable_name": "order_ref", "value": order_ref}
                ]
            }
        )

        await db.commit()
        log_action("order_initialized", actor=f"user_{user_id}", order_reference=order_ref, metadata={"total": total_amount})
        return paystack_data.get("authorization_url")

    except Exception as e:
        await db.rollback()
        logger.error(f"Order creation failed during Paystack initialization: {str(e)}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to communicate with payment gateway. Please try again.")

# =========================================================
# 4. FULFILLMENT & INVENTORY MANAGEMENT
# =========================================================

async def process_successful_payment(db: AsyncSession, order_ref: str, tx_hash: str) -> None:
    """
    Called by Paystack webhook handlers when a charge is confirmed successful.
    1. Locates the pending order.
    2. Deducts physical inventory atomically.
    3. Updates order status to PAID.
    4. Records the financial transaction and triggers customer email notifications.
    """
    stmt = (
        select(Order)
        .where(Order.order_reference == order_ref)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    # Idempotency check to prevent duplicate inventory deduction on retried webhooks
    if not order or order.status in [OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
        logger.warning(f"Webhook processing skipped for reference {order_ref}: Order not found or already processed.")
        return

    # Atomic physical inventory deduction
    for item in order.items:
        await db.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(quantity=Product.quantity - item.quantity)
        )

    order.status = OrderStatus.PAID
    order.payment_reference = tx_hash

    db.add(Transaction(
        user_id=order.user_id, 
        order_id=order.id, 
        amount=order.total_amount,
        status="confirmed", 
        provider="Paystack", 
        tx_hash=str(tx_hash)
    ))
    
    await db.commit()

    try:
        await send_fulfillment_email(
            user_email=order.customer_email,
            product_name="Your Rocky Trendy Realities Order",
            order_reference=order_ref,
            manual_text="We have successfully received your payment. Our logistics and design teams are currently processing your items for fulfillment."
        )
    except Exception as e:
        logger.error(f"Failed to send payment confirmation email for order {order_ref}: {e}")
    
    log_action("payment_confirmed", actor="paystack_webhook", order_reference=order_ref, metadata={"tx_hash": tx_hash})

async def process_admin_order_action(
    db: AsyncSession, 
    order_id: int, 
    action: str, 
    manual_content: Optional[str] = None
) -> Dict[str, str]:
    """Handles admin manual fulfillment workflows for physical logistics."""
    stmt = (
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    if action == "reject" or action == "cancel":
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()
        await db.commit()
        log_action("order_cancelled_by_admin", actor="admin", order_reference=order.order_reference)
        return {"status": "cancelled", "detail": "Order has been cancelled."}

    if action == "ship":
        order.status = OrderStatus.SHIPPED
        order.fulfillment_note = manual_content or "Your order has been shipped and is on its way."
        order.updated_at = datetime.utcnow()
        await db.commit()
        
        try:
            await send_fulfillment_email(
                user_email=order.customer_email,
                product_name="Your Rocky Trendy Realities Order",
                order_reference=order.order_reference,
                manual_text=order.fulfillment_note
            )
        except Exception as e:
            logger.error(f"Failed to send shipping notification email for order {order.order_reference}: {e}")

        log_action("order_shipped", actor="admin", order_reference=order.order_reference)
        return {"status": "shipped", "detail": "Order marked as shipped."}

    if action == "complete" or action == "deliver":
        order.status = OrderStatus.DELIVERED
        order.updated_at = datetime.utcnow()
        await db.commit()
        log_action("order_delivered", actor="admin", order_reference=order.order_reference)
        return {"status": "delivered", "detail": "Order marked as delivered."}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid fulfillment action.")