# services.py
# Production-level Business Logic Layer
# Rocky Trendy Realities - Pure E-Commerce & AI Customizer

import logging
import os
import yaml
from datetime import datetime, timedelta
from decimal import Decimal
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
    AdminRole,
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
    log_action,
    generate_random_token
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
    """Registers a new user and triggers email verification via secure OTP."""
    email_clean = email.strip().lower()
    
    query = select(User).where(User.email == email_clean)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists."
        )
        
    hashed = hash_password(password)
    
    new_user = User(
        email=email_clean,
        password_hash=hashed,
        country=country,
        is_verified=False,
        balance=Decimal('0.00')
    )
    
    db.add(new_user)
    await db.flush()
    
    otp_code = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=15)
    
    await db.execute(
        update(User)
        .where(User.id == new_user.id)
        .values(email_otp=otp_code, otp_expiry=expires_at)
    )
    
    try:
        await send_email_otp(email_clean, otp_code, OTPPurpose.EMAIL_VERIFY)
    except Exception as e:
        logger.error(f"Failed to send activation email to user {email_clean}: {e}")
        
    await db.commit()
    log_action("user_registered", actor=f"user_{new_user.id}", metadata={"email": email_clean})
    return new_user

async def verify_user_email_service(db: AsyncSession, email: str, otp: str) -> Dict[str, Any]:
    """Validates user's email address via the generated activation code."""
    email_clean = email.strip().lower()
    query = select(User).where(User.email == email_clean)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")
        
    if user.is_verified:
        return {"status": "already_verified", "message": "Email is already verified."}
        
    if not user.email_otp or user.email_otp != otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code provided.")
        
    if user.otp_expiry and user.otp_expiry < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code has expired.")
        
    user.is_verified = True
    user.email_otp = None
    user.otp_expiry = None
    
    await db.commit()
    log_action("user_email_verified", actor=f"user_{user.id}", metadata={"email": email_clean})
    
    token_payload = {"sub": user.email, "id": user.id, "role": "user"}
    access_token = create_access_token(data=token_payload)
    
    return {
        "status": "success",
        "message": "Email verified successfully.",
        "access_token": access_token,
        "token_type": "bearer"
    }

async def resend_otp_service(db: AsyncSession, email: str, purpose: OTPPurpose = OTPPurpose.EMAIL_VERIFY) -> Dict[str, str]:
    """Regenerates and dispatches a fresh security token to the target inbox."""
    email_clean = email.strip().lower()
    query = select(User).where(User.email == email_clean)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")
        
    otp_code = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=15)
    
    user.email_otp = otp_code
    user.otp_expiry = expires_at
    await db.commit()
    
    try:
        await send_email_otp(email_clean, otp_code, purpose)
    except Exception as e:
        logger.error(f"Error resending OTP code to {email_clean}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to dispatch verification email. Please try again."
        )
        
    return {"detail": "Verification code has been successfully resent."}

# =========================================================
# 2. SEEDING & ADMINISTRATIVE BOOTSTRAPPING
# =========================================================

async def bootstrap_admins(db: AsyncSession) -> None:
    """Bootstraps default administrator configurations into persistent state safely."""
    
    admin_users_env = getattr(settings, "ADMIN_USERNAMES", None) or os.getenv("ADMIN_USERNAMES", "")
    admin_passwords_env = getattr(settings, "ADMIN_PASSWORDS", None) or os.getenv("ADMIN_PASSWORDS", "")
    
    if not admin_users_env or not admin_passwords_env:
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            admin_yaml_path = os.path.join(base_dir, "admin_credentials.yaml")
            if os.path.exists(admin_yaml_path):
                with open(admin_yaml_path, "r") as file:
                    creds = yaml.safe_load(file)
                    admin_users_env = creds.get("ADMIN_USERNAMES", "")
                    admin_passwords_env = creds.get("ADMIN_PASSWORDS", "")
            else:
                logger.warning(f"Administration bootstrap skipped: credentials file not found ({admin_yaml_path}).")
                return
        except Exception as e:
            logger.warning(f"Administration bootstrap skipped due to YAML parse error: {e}")
            return

    admin_users = [u.strip() for u in admin_users_env.split(",") if u.strip()]
    admin_passwords = [p.strip() for p in admin_passwords_env.split(",") if p.strip()]
    
    if len(admin_users) != len(admin_passwords):
        logger.error("Admin user and password counts do not match in configuration.")
        return
        
    try:
        for username, password in zip(admin_users, admin_passwords):
            existing = await db.execute(select(Admin).where(Admin.username == username))
            admin_record = existing.scalar_one_or_none()
            
            if not admin_record:
                new_admin = Admin(
                    username=username,
                    password_hash=password, 
                    role=AdminRole.SUPERADMIN
                )
                db.add(new_admin)
                logger.info(f"Administrative account bootstrapped successfully: '{username}'")
                
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to cleanly execute administrative bootsrap operations: {e}")
        await db.rollback()

# =========================================================
# 3. CORE E-COMMERCE & ORDER CHECKOUT DISPATCH
# =========================================================

async def create_order_service(
    db: AsyncSession, 
    order_data: CheckoutRequest, 
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validates inventory stock, aggregates totals using high-precision Decimal, constructs systemic 
    instances, and issues transactional hooks for automated payment processing or manual WhatsApp routing.
    """
    order_ref = f"RTR-{int(datetime.utcnow().timestamp())}-{generate_random_token(4).upper()}"
    total_amount = Decimal('0.00')
    order_items_to_create = []

    # Production Fix: Sort items by product_id to prevent database deadlocks 
    # during high-concurrency cart processing with pessimistic locks.
    sorted_items = sorted(order_data.items, key=lambda x: x.product_id)

    try:
        for item in sorted_items:
            prod_query = select(Product).where(Product.id == item.product_id).with_for_update()
            prod_res = await db.execute(prod_query)
            product = prod_res.scalar_one_or_none()
            
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product with reference identifier #{item.product_id} was not found."
                )
                
            if product.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product '{product.name}' is no longer active in our catalog."
                )
                
            if product.quantity < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient inventory on '{product.name}'. Remaining stock: {product.quantity} units."
                )
                
            product.quantity -= item.quantity
            item_total = product.price * Decimal(str(item.quantity))
            total_amount += item_total
            
            order_item = OrderItem(
                product_id=product.id,
                product_name_snapshot=product.name,
                product_image_snapshot=product.image_url,
                quantity=item.quantity,
                unit_price_at_purchase=product.price,
                is_customized=item.is_customized,
                customization_notes=item.customization_notes,
                custom_image_url=item.custom_image_url
            )
            order_items_to_create.append(order_item)

        new_order = Order(
            order_reference=order_ref,
            user_id=user_id,
            customer_email=order_data.customer_email,
            customer_phone=order_data.customer_phone,
            shipping_address=order_data.shipping_address,
            total_amount=total_amount,
            status=OrderStatus.PENDING,
            payment_method=order_data.payment_method,
        )
        
        new_order.items = order_items_to_create
        db.add(new_order)
        await db.flush()

        if order_data.payment_method == PaymentMethod.WHATSAPP:
            await db.commit()
            log_action(
                "order_created_whatsapp", 
                actor=f"user_{user_id}" if user_id else "guest", 
                order_reference=order_ref, 
                metadata={"total": float(total_amount)}
            )
            return {
                "order_reference": order_ref,
                "whatsapp_redirect": True
            }
            
        else:
            amount_kobo = int(total_amount * 100)
            
            try:
                paystack_res = await initialize_transaction(
                    email=order_data.customer_email,
                    amount=amount_kobo,
                    reference=order_ref,
                    metadata={"user_id": user_id, "phone": order_data.customer_phone}
                )
            except Exception as err:
                logger.error(f"Paystack payment initiation failed for reference {order_ref}: {str(err)}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Payment Gateway is currently unresponsive. Your cart state has been preserved."
                )
                
            if not paystack_res or not paystack_res.get("status"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Paystack Initialization Error: {paystack_res.get('message', 'Unknown failure')}"
                )
                
            data = paystack_res["data"]
            checkout_url = data["authorization_url"]
            payment_ref = data["reference"]
            
            new_order.payment_reference = payment_ref
            
            tx_record = Transaction(
                order_id=new_order.id,
                user_id=user_id,
                tx_hash=payment_ref,
                amount=total_amount,
                status="pending",
                provider="Paystack"
            )
            db.add(tx_record)
            
            await db.commit()
            log_action(
                "order_created_paystack", 
                actor=f"user_{user_id}" if user_id else "guest", 
                order_reference=order_ref, 
                metadata={"payment_ref": payment_ref, "total": float(total_amount)}
            )
            
            return {
                "checkout_url": checkout_url,
                "order_reference": order_ref,
                "access_code": data.get("access_code"),
                "authorization_url": checkout_url,
                "reference": payment_ref
            }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as err:
        logger.error(f"Unexpected error during checkout pipeline: {str(err)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to finalize the checkout sequence."
        )

# =========================================================
# 4. CONTENT MANAGEMENT SERVICES (CMS)
# =========================================================

async def create_banner_service(db: AsyncSession, banner_data: BannerCreateSchema, admin_username: str = "system") -> Banner:
    """Inserts an active marketing asset link or slider reference inside the global store front."""
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
    log_action("banner_created", actor=admin_username, metadata={"section": banner_data.section_type.value})
    return new_banner

# =========================================================
# 5. USER MODERATION & ADMINISTRATION CONTROLS
# =========================================================

async def moderate_user_service(db: AsyncSession, user_id: int, action: str, admin_username: str = "system") -> Dict[str, str]:
    """Suspends, activates, or limits actions on customer accounts."""
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target customer account does not exist.")
        
    if action == "ban" or action == "suspend":
        user.is_banned = True
        await db.commit()
        log_action("user_suspended", actor=admin_username, metadata={"target_user": user_id})
        return {"status": "suspended", "detail": "User has been suspended successfully."}
        
    elif action == "unban" or action == "activate":
        user.is_banned = False
        await db.commit()
        log_action("user_activated", actor=admin_username, metadata={"target_user": user_id})
        return {"status": "activated", "detail": "User has been activated successfully."}
        
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported moderation command.")

# =========================================================
# 6. SYSTEM ORDER FULFILLMENT ROUTINES
# =========================================================

async def process_admin_order_action(
    db: AsyncSession, 
    order_id: int, 
    action: str, 
    manual_content: Optional[str] = None
) -> Dict[str, str]:
    """Manages order pipelines, processing status triggers, cancellations, and manual confirmations."""
    query = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order instance was not found.")
        
    if action == "cancel":
        for item in order.items:
            prod_query = select(Product).where(Product.id == item.product_id).with_for_update()
            prod_res = await db.execute(prod_query)
            product = prod_res.scalar_one_or_none()
            if product:
                product.quantity += item.quantity
                
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
        
    if action in ["complete", "deliver"]:
        order.status = OrderStatus.DELIVERED
        order.updated_at = datetime.utcnow()
        await db.commit()
        log_action("order_delivered", actor="admin", order_reference=order.order_reference)
        return {"status": "delivered", "detail": "Order marked as delivered."}
        
    if action == "reject":
        order.status = OrderStatus.FAILED
        order.updated_at = datetime.utcnow()
        await db.commit()
        log_action("order_rejected", actor="admin", order_reference=order.order_reference)
        return {"status": "rejected", "detail": "Order marked as rejected."}
        
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid fulfillment action.")
