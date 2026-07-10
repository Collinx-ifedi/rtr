# main.py
# Production-level Entry Point
# Rocky Trendy Realities — Physical Furniture & AI Customization
# - Integrated Cloudinary for Image Persistence (via CLOUDINARY_URL)
# - AI Design Customization integration via OpenAI
# - Multipart Form Data support for Admin CRUD (Physical Products)
# - Robust Path Resolution for Docker/Render
# - OTP Recovery Endpoint
# - Automatic Background Cleanup of Unverified Users
# - Flexible Blog Creation (Server-side Defaults)
# - Messaging & User Moderation APIs

import os
import shutil
import uuid
import time
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional

import cloudinary
import cloudinary.uploader
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    status,
    APIRouter,
    UploadFile,
    File,
    Form,
    Query,
    Body,
    Response
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, func, case, update, or_
from sqlalchemy.orm import selectinload

# --- LOCAL MODULES ---
from .db import get_db, init_db
from core import (
    settings, 
    get_current_admin, 
    get_current_user,
    verify_password,
    create_access_token, 
    require_superadmin
)
from utils import logger

# --- SERVICES ---
from services import (
    create_user_service,
    resend_otp_service,
    verify_user_email_service,
    admin_login_service,
    bootstrap_admins,
    create_order_service,
    create_banner_service,
    process_admin_order_action,
    send_user_message_service,
    get_user_inbox_service,
    mark_inbox_message_read_service,
    moderate_user_service
)
from ai_services import get_ai_service, AIService

# --- SCHEMAS & MODELS ---
from models_schemas import (
    UserCreateSchema, 
    AdminLoginSchema, 
    PhysicalOrderCreate, 
    Admin,
    User,
    UserResponse,
    Product, 
    OrderItem,
    ProductSchema,
    Banner,
    BannerSchema,
    Order,
    OrderResponse,
    OrderStatus,
    PaymentMethod,
    ProductCategory, 
    # --- BLOG SYSTEM MODELS & SCHEMAS ---
    BlogPost,
    BlogComment,
    BlogReaction, 
    BlogResponse,
    BlogDetailResponse,
    CommentCreate,
    # --- MESSAGING SCHEMAS ---
    InboxMessageCreate,
    InboxMessageResponse
)

# =========================================================
# 1. SETUP & CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent      
PROJECT_ROOT = BASE_DIR.parent                  
FRONTEND_DIR = PROJECT_ROOT / "frontend"        
UPLOAD_DIR = BASE_DIR / "temp_uploads"          

os.makedirs(UPLOAD_DIR, exist_ok=True)

if not FRONTEND_DIR.exists():
    logger.critical(f"CRITICAL: Frontend directory not found at {FRONTEND_DIR}")

# --- CLOUDINARY CONFIGURATION ---
cloudinary_url = os.getenv("CLOUDINARY_URL")

if cloudinary_url:
    cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
    logger.info("Cloudinary initialized successfully via CLOUDINARY_URL.")
else:
    logger.critical("WARNING: CLOUDINARY_URL not found in environment variables. Media uploads will fail.")


# =========================================================
# 2. LIFESPAN MANAGEMENT & BACKGROUND TASKS
# =========================================================

async def cleanup_unverified_users():
    while True:
        try:
            async for db in get_db():
                expiration_limit = datetime.utcnow() - timedelta(hours=24)
                stmt = (
                    delete(User)
                    .where(User.is_verified == False)
                    .where(User.created_at < expiration_limit)
                )
                result = await db.execute(stmt)
                await db.commit()
                if result.rowcount > 0:
                    logger.info(f"Cleanup: Removed {result.rowcount} unverified/abandoned accounts.")
                break 
        except Exception as e:
            logger.error(f"Cleanup task error: {e}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rocky Trendy Realities startup initiated...")
    await init_db()
    async for db in get_db():
        await bootstrap_admins(db)
        break 
    cleanup_task = asyncio.create_task(cleanup_unverified_users())
    logger.info("Background task started: Cleanup unverified users.")
    logger.info(f"System startup complete. Version: {app.version}")
    yield
    logger.info("System shutting down...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Background cleanup task cancelled.")
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


# =========================================================
# 3. APPLICATION FACTORY
# =========================================================

app = FastAPI(
    title="Rocky Trendy Realities Backend",
    version="1.0.0", 
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


# =========================================================
# 4. MIDDLEWARE
# =========================================================

app.add_middleware(GZipMiddleware, minimum_size=1000)

origins = ["*"] 
if settings.ADMIN_FRONTEND_URL:
    origins.append(settings.ADMIN_FRONTEND_URL)
if settings.FRONTEND_URL:
    origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}"
    return response


# =========================================================
# 5. API ROUTERS
# =========================================================

# --- A. AI CUSTOMIZATION ROUTER ---
ai_router = APIRouter(prefix="/api/ai", tags=["AI Generation"])

@ai_router.post("/generate-customization")
async def generate_design_customization(
    prompt: str = Body(..., embed=True),
    product_context: Optional[str] = Body(None, embed=True),
    user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """
    Accepts user prompts for custom furniture alterations and streams
    the resulting high-res rendering directly to Cloudinary.
    """
    try:
        secure_url = await ai_service.generate_custom_furniture_image(
            prompt=prompt,
            user_id=user.id,
            product_context=product_context
        )
        return {"status": "success", "image_url": secure_url}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"AI Generation route failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process custom design.")


# --- B. CATALOG ROUTER ---
catalog_router = APIRouter(prefix="/api", tags=["Catalog"])

@catalog_router.get("/products", response_model=List[ProductSchema])
async def get_products(
    category: Optional[str] = None, 
    limit: int = 50, 
    db: AsyncSession = Depends(get_db)
):
    query = select(Product).where(
        or_(Product.is_deleted == False, Product.is_deleted.is_(None))
    )
    if category:
        query = query.where(Product.product_category == category)
    
    query = query.order_by(desc(Product.id)).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

@catalog_router.get("/products/{product_id}", response_model=ProductSchema)
async def get_product_detail(product_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Product).where(Product.id == product_id)
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@catalog_router.get("/banners", response_model=List[BannerSchema])
async def get_banners(active: bool = True, db: AsyncSession = Depends(get_db)):
    query = select(Banner)
    if active:
        query = query.where(Banner.is_active == True)
    query = query.order_by(Banner.display_order)
    result = await db.execute(query)
    return result.scalars().all()


# --- C. AUTH ROUTER ---
auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])

@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(data: UserCreateSchema, db: AsyncSession = Depends(get_db)):
    try:
        user = await create_user_service(db, data.email, data.password, data.country)
        time_since_creation = (datetime.utcnow() - user.created_at).total_seconds()
        is_existing_resend = time_since_creation > 10

        response_payload = {
            "pending_verification": True,
            "user_email": user.email
        }

        if is_existing_resend:
            response_payload["message"] = "Verification code resent"
            return JSONResponse(status_code=status.HTTP_200_OK, content=response_payload)
        else:
            response_payload["message"] = "Account created. Check email for OTP."
            return response_payload

    except HTTPException as he:
        raise he

@auth_router.post("/login")
async def login_user(data: AdminLoginSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Account suspended")

    access_token = create_access_token(subject=user.id, role="user")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "full_name": user.full_name,
            "country": user.country
        }
    }

@auth_router.get("/me")
async def get_my_profile(user: User = Depends(get_current_user)):
    return {
        "email": user.email,
        "full_name": user.full_name,
        "country": user.country,
        "avatar_url": user.avatar_url
    }

@auth_router.post("/verify-email")
async def verify_email(payload: dict, db: AsyncSession = Depends(get_db)):
    email = payload.get("email")
    otp = payload.get("otp")
    return await verify_user_email_service(db, email, otp)

@auth_router.post("/resend-otp")
async def resend_otp(payload: dict, db: AsyncSession = Depends(get_db)):
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    return await resend_otp_service(db, email)


# --- D. INBOX & USER ROUTER ---
user_router = APIRouter(prefix="/api/user", tags=["User Profile"])
inbox_router = APIRouter(prefix="/api/inbox", tags=["Inbox"])

@user_router.get("/profile", response_model=UserResponse)
async def get_user_profile(user: User = Depends(get_current_user)):
    return user

@inbox_router.get("", response_model=List[InboxMessageResponse])
async def get_my_inbox(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_user_inbox_service(db, user.id)

@inbox_router.post("/{message_id}/read")
async def mark_message_as_read(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await mark_inbox_message_read_service(db, message_id, user.id)


# --- E. ORDER ROUTER ---
order_router = APIRouter(prefix="/api/orders", tags=["Orders"])

@order_router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def checkout_route(
    order_data: PhysicalOrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        checkout_url = await create_order_service(db, user.id, order_data)
        return {"checkout_url": checkout_url}
    except Exception as e:
        logger.error(f"Checkout failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@order_router.get("")
async def get_user_orders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Order).where(Order.user_id == user.id).order_by(desc(Order.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()


# --- F. ADMIN ROUTER ---
admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])

@admin_router.post("/login")
async def admin_login_route(data: AdminLoginSchema, db: AsyncSession = Depends(get_db)):
    token = await admin_login_service(db, data.username, data.password)
    result = await db.execute(select(Admin).where(Admin.username == data.username))
    admin = result.scalar_one_or_none()
    role = admin.role.value if admin and hasattr(admin.role, 'value') else "admin"
    
    return {
        "access_token": token, 
        "token_type": "bearer",
        "admin": {
            "username": data.username,
            "role": role
        }
    }

@admin_router.get("/stats")
async def get_admin_stats(db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    revenue_query = select(func.sum(Order.total_amount)).where(
        Order.status.in_([OrderStatus.PAID, OrderStatus.COMPLETED])
    )
    total_revenue = (await db.execute(revenue_query)).scalar() or 0.0

    total_orders = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    open_orders = (await db.execute(
        select(func.count(Order.id)).where(Order.status == OrderStatus.IN_PROGRESS)
    )).scalar() or 0

    return {
        "total_sales": total_revenue,
        "total_orders": total_orders,
        "total_users": total_users,
        "open_orders": open_orders
    }

@admin_router.get("/users", response_model=List[UserResponse])
async def get_admin_users(
    limit: int = 50, 
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db), 
    admin: Admin = Depends(get_current_admin)
):
    query = select(User).order_by(desc(User.created_at)).limit(limit)
    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
    
    result = await db.execute(query)
    return result.scalars().all()

@admin_router.post("/users/{user_id}/ban")
async def ban_user_route(user_id: int, db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    return await moderate_user_service(db, user_id, "ban", admin_username=admin.username)

@admin_router.post("/users/{user_id}/unban")
async def unban_user_route(user_id: int, db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    return await moderate_user_service(db, user_id, "unban", admin_username=admin.username)

@admin_router.get("/orders", response_model=List[OrderResponse])
async def get_admin_orders(limit: int = 50, db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    try:
        query = (
            select(Order)
            .options(
                selectinload(Order.user),
                selectinload(Order.items).selectinload(OrderItem.product)
            )
            .order_by(desc(Order.created_at))
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Order Fetch Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error while fetching orders.")

@admin_router.post("/orders/{order_id}/action")
async def admin_order_action(
    order_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    action = payload.get("action")
    manual_content = payload.get("manual_content")
    if action not in ["complete", "reject", "ship"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    return await process_admin_order_action(db, order_id, action, manual_content)

# -- PRODUCT CRUD --
@admin_router.get("/products", response_model=List[ProductSchema])
async def get_admin_products(db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    query = select(Product).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None))).order_by(desc(Product.id))
    result = await db.execute(query)
    return result.scalars().all()

@admin_router.post("/products", response_model=ProductSchema)
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    stock_quantity: int = Form(...),
    product_category: ProductCategory = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    is_featured: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    try:
        upload_result = cloudinary.uploader.upload(file.file, folder="rtr_products")
        secure_url = upload_result.get("secure_url")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image Provider Error: {str(e)}")

    new_product = Product(
        name=name,
        price=price,
        stock_quantity=stock_quantity,
        product_category=product_category,
        description=description,
        image_url=secure_url,
        is_featured=is_featured
    )
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)
    return new_product

@admin_router.put("/products/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: int,
    name: str = Form(...),
    price: float = Form(...),
    stock_quantity: int = Form(...),
    product_category: Optional[ProductCategory] = Form(None),
    description: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    is_featured: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if file:
        try:
            upload_result = cloudinary.uploader.upload(file.file, folder="rtr_products")
            product.image_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Image Update Error: {str(e)}")

    product.name = name
    product.price = price
    product.stock_quantity = stock_quantity
    product.description = description
    product.is_featured = is_featured
    if product_category:
        product.product_category = product_category

    await db.commit()
    await db.refresh(product)
    return product


# --- G. BLOG ROUTER (Public) ---
blog_router = APIRouter(prefix="/api/blog", tags=["Blog"])

@blog_router.get("/posts", response_model=List[BlogResponse])
async def get_blog_posts(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(BlogPost)
        .where(BlogPost.is_published == True, BlogPost.is_deleted == False)
        .options(selectinload(BlogPost.author))
        .order_by(desc(BlogPost.created_at))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# =========================================================
# 6. REGISTER API ROUTERS
# =========================================================

app.include_router(ai_router)
app.include_router(catalog_router)
app.include_router(auth_router)
app.include_router(user_router)    
app.include_router(inbox_router)
app.include_router(order_router)
app.include_router(admin_router)
app.include_router(blog_router)

# =========================================================
# 7. FRONTEND PAGE ROUTES
# =========================================================

@app.get("/")
async def serve_index(): return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/{page_name}.html")
async def serve_html_pages(page_name: str):
    file_path = FRONTEND_DIR / f"{page_name}.html"
    if file_path.exists():
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"detail": "Page not found"})

# =========================================================
# 8. STATIC FILES
# =========================================================

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# =========================================================
# EXECUTION
# =========================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
