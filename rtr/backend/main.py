# main.py
# Production-level FastAPI Entry Point
# Rocky Trendy Realities — Pure E-Commerce & AI Customization

import os
import time
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
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
    Body
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, or_, func
from sqlalchemy.orm import selectinload

# --- LOCAL MODULES ---
from .db import get_db, init_db, ping_db
from .core import (
    settings, 
    get_current_admin, 
    get_current_user,
    verify_password,
    create_access_token
)
from .utils import logger

# --- SERVICES ---
from .services import (
    create_user_service,
    resend_otp_service,
    verify_user_email_service,
    admin_login_service,
    bootstrap_admins,
    create_order_service,
    create_banner_service,
    process_admin_order_action,
    moderate_user_service
)
from .ai_services import get_ai_service, AIService

# --- SCHEMAS & MODELS ---
from .models_schemas import (
    UserCreateSchema, 
    AdminLoginSchema, 
    CheckoutRequest,
    PhysicalOrderCreate,
    Admin,
    User,
    UserResponse,
    Product, 
    OrderItem,
    ProductSchema,
    Banner,
    BannerSchema,
    BannerCreateSchema,
    Order,
    OrderResponse,
    OrderStatus,
    ProductCategory
)

# =========================================================
# 1. SETUP & PATH RESOLUTION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent      
PROJECT_ROOT = BASE_DIR.parent                  
FRONTEND_DIR = PROJECT_ROOT / "frontend"        
UPLOAD_DIR = BASE_DIR / "temp_uploads"          

os.makedirs(UPLOAD_DIR, exist_ok=True)

if not FRONTEND_DIR.exists():
    logger.warning(f"Frontend directory not detected at {FRONTEND_DIR}. Static serving will be disabled.")

# --- CLOUDINARY CONFIGURATION ---
cloudinary_url = os.getenv("CLOUDINARY_URL")
if cloudinary_url:
    cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
    logger.info("Cloudinary media engine initialized successfully.")
else:
    logger.critical("CRITICAL: CLOUDINARY_URL missing from environment. Image uploads will fail.")

# =========================================================
# 2. LIFESPAN MANAGEMENT & BACKGROUND TASKS
# =========================================================

async def cleanup_unverified_users():
    """Background garbage collector: Prunes abandoned unverified accounts older than 24 hours."""
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
                    logger.info(f"Garbage Collector: Pruned {result.rowcount} unverified account(s).")
                break 
        except Exception as e:
            logger.error(f"Background cleanup task exception: {e}")
        await asyncio.sleep(3600)  # Run hourly

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rocky Trendy Realities system startup initiated...")
    
    # Initialize DB Schema and verify connectivity
    await init_db()
    is_db_up = await ping_db()
    if not is_db_up:
        logger.critical("Database connectivity check failed during startup.")
    
    # Seed administrative accounts
    async for db in get_db():
        await bootstrap_admins(db)
        break 
        
    # Launch background worker
    cleanup_task = asyncio.create_task(cleanup_unverified_users())
    logger.info("Background cleanup worker initialized.")
    logger.info(f"System startup complete. Serving API v{app.version}")
    
    yield
    
    logger.info("System shutdown sequence initiated...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Background cleanup worker cleanly terminated.")
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    logger.info("Shutdown complete.")

# =========================================================
# 3. APPLICATION FACTORY
# =========================================================

app = FastAPI(
    title="Rocky Trendy Realities E-Commerce API",
    version="2.0.0", 
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan
)

# =========================================================
# 4. MIDDLEWARE & GLOBAL HANDLERS
# =========================================================

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Permissive CORS for decoupled external storefront APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled system exception on {request.method} {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Our engineering team has been notified."}
    )

# =========================================================
# 5. API ROUTERS
# =========================================================

# --- A. AI CUSTOMIZATION ROUTER ---
ai_router = APIRouter(prefix="/api/ai", tags=["AI Design Studio"])

@ai_router.post("/generate-customization")
async def generate_design_customization(
    prompt: str = Body(..., embed=True),
    product_context: Optional[str] = Body(None, embed=True),
    user: User = Depends(get_current_user),
    ai_service: AIService = Depends(get_ai_service)
):
    """Generates a custom furniture rendering via AI and streams it directly to Cloudinary."""
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
        raise HTTPException(status_code=500, detail="Failed to synthesize custom design rendering.")


# --- B. CATALOG ROUTER ---
catalog_router = APIRouter(prefix="/api", tags=["Product Catalog"])

@catalog_router.get("/products", response_model=List[ProductSchema])
async def get_products(
    category: Optional[str] = None, 
    limit: int = 50, 
    db: AsyncSession = Depends(get_db)
):
    query = select(Product).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None)))
    if category and category != "all":
        query = query.where(Product.product_category == category)
    
    query = query.order_by(desc(Product.id)).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

@catalog_router.get("/products/{product_id}", response_model=ProductSchema)
async def get_product_detail(product_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Product).where(Product.id == product_id).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None)))
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Requested product not found or is no longer available.")
    return product

@catalog_router.get("/banners", response_model=List[BannerSchema])
async def get_banners(active: bool = True, db: AsyncSession = Depends(get_db)):
    query = select(Banner)
    if active:
        query = query.where(Banner.is_active == True)
    query = query.order_by(Banner.display_order)
    result = await db.execute(query)
    return result.scalars().all()


# --- C. AUTHENTICATION ROUTER ---
auth_router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(data: UserCreateSchema, db: AsyncSession = Depends(get_db)):
    user = await create_user_service(db, data.email, data.password, data.country)
    time_since_creation = (datetime.utcnow() - user.created_at).total_seconds()
    is_existing_resend = time_since_creation > 10

    response_payload = {
        "pending_verification": True,
        "user_email": user.email
    }

    if is_existing_resend:
        response_payload["message"] = "Verification code has been resent to your email."
        return JSONResponse(status_code=status.HTTP_200_OK, content=response_payload)
    else:
        response_payload["message"] = "Account created successfully. Please check your email for the verification code."
        return response_payload

@auth_router.post("/login")
async def login_user(data: AdminLoginSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email address or password.")
    
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your email address has not been verified. Please verify your account to proceed.")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact customer support.")

    access_token = create_access_token({"sub": user.email, "type": "access", "role": "user"})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "full_name": user.full_name,
            "country": user.country
        }
    }

@auth_router.get("/me", response_model=UserResponse)
async def get_my_profile(user: User = Depends(get_current_user)):
    return user

@auth_router.post("/verify-email")
async def verify_email(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    email = payload.get("email")
    otp = payload.get("otp")
    if not email or not otp:
        raise HTTPException(status_code=400, detail="Both email and OTP code are required.")
    return await verify_user_email_service(db, email, otp)

@auth_router.post("/resend-otp")
async def resend_otp(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required.")
    return await resend_otp_service(db, email)


# --- D. ORDER & CHECKOUT ROUTER ---
order_router = APIRouter(prefix="/api/orders", tags=["Orders & Checkout"])

@order_router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def checkout_route(
    order_data: PhysicalOrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        checkout_url = await create_order_service(db, user.id, order_data)
        return {"checkout_url": checkout_url}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Checkout initialization failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize checkout gateway.")

@order_router.get("", response_model=List[OrderResponse])
async def get_user_orders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Order)
        .where(Order.user_id == user.id)
        .options(selectinload(Order.items))
        .order_by(desc(Order.created_at))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# --- E. ADMINISTRATIVE ROUTER ---
admin_router = APIRouter(prefix="/api/admin", tags=["Store Administration"])

@admin_router.post("/login")
async def admin_login_route(data: AdminLoginSchema, db: AsyncSession = Depends(get_db)):
    token = await admin_login_service(db, data.username, data.password)
    result = await db.execute(select(Admin).where(Admin.username == data.username))
    admin = result.scalar_one_or_none()
    role = admin.role.value if admin and hasattr(admin.role, 'value') else str(admin.role)
    
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
        Order.status.in_([OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED])
    )
    total_revenue = (await db.execute(revenue_query)).scalar() or 0.0

    total_orders = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    open_orders = (await db.execute(
        select(func.count(Order.id)).where(Order.status.in_([OrderStatus.PAID, OrderStatus.PROCESSING]))
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
    query = (
        select(Order)
        .options(
            selectinload(Order.user),
            selectinload(Order.items)
        )
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()

@admin_router.post("/orders/{order_id}/action")
async def admin_order_action(
    order_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    action = payload.get("action")
    manual_content = payload.get("manual_content")
    if action not in ["complete", "deliver", "reject", "cancel", "ship"]:
        raise HTTPException(status_code=400, detail="Invalid fulfillment action specified.")
    return await process_admin_order_action(db, order_id, action, manual_content)

@admin_router.get("/products", response_model=List[ProductSchema])
async def get_admin_products(db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    query = select(Product).where(or_(Product.is_deleted == False, Product.is_deleted.is_(None))).order_by(desc(Product.id))
    result = await db.execute(query)
    return result.scalars().all()

@admin_router.post("/products", response_model=ProductSchema, status_code=status.HTTP_201_CREATED)
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    quantity: int = Form(...),
    product_category: ProductCategory = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    is_featured: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    try:
        # Offload synchronous Cloudinary API call to a background thread
        upload_result = await asyncio.to_thread(
            cloudinary.uploader.upload, file.file, folder="rtr_products"
        )
        secure_url = upload_result.get("secure_url")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image CDN Upload Error: {str(e)}")

    new_product = Product(
        name=name,
        price=price,
        quantity=quantity,
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
    quantity: int = Form(...),
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
        raise HTTPException(status_code=404, detail="Target product not found.")

    if file:
        try:
            # Offload synchronous Cloudinary API call to a background thread
            upload_result = await asyncio.to_thread(
                cloudinary.uploader.upload, file.file, folder="rtr_products"
            )
            product.image_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Image CDN Update Error: {str(e)}")

    product.name = name
    product.price = price
    product.quantity = quantity
    product.description = description
    product.is_featured = is_featured
    if product_category:
        product.product_category = product_category

    await db.commit()
    await db.refresh(product)
    return product

@admin_router.delete("/products/{product_id}")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    
    product.is_deleted = True
    product.deleted_at = datetime.utcnow()
    await db.commit()
    return {"status": "success", "detail": "Product removed from active catalog."}

@admin_router.post("/banners", response_model=BannerSchema, status_code=status.HTTP_201_CREATED)
async def create_banner_route(
    banner_data: BannerCreateSchema,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    return await create_banner_service(db, banner_data, admin.username)


# =========================================================
# 6. REGISTER API ROUTERS
# =========================================================

app.include_router(ai_router)
app.include_router(catalog_router)
app.include_router(auth_router)
app.include_router(order_router)
app.include_router(admin_router)

# =========================================================
# 7. FRONTEND PAGE ROUTES (ADMIN PORTAL ONLY)
# =========================================================

@app.get("/")
async def serve_admin_root():
    """Redirects or serves the admin login page when accessing the root domain."""
    admin_login = FRONTEND_DIR / "admin-login.html"
    if admin_login.exists():
        return FileResponse(admin_login)
    return JSONResponse(status_code=404, content={"detail": "Admin login interface not found."})

@app.get("/admin")
async def serve_admin_alias():
    """Allows accessing the admin login via /admin directly."""
    admin_login = FRONTEND_DIR / "admin-login.html"
    if admin_login.exists():
        return FileResponse(admin_login)
    return JSONResponse(status_code=404, content={"detail": "Admin login interface not found."})

@app.get("/{page_name}.html")
async def serve_html_pages(page_name: str):
    """
    Dynamically captures and serves specific admin pages 
    (e.g., admin-dashboard.html, admin-products.html, admin-content.html)
    """
    file_path = FRONTEND_DIR / f"{page_name}.html"
    if file_path.exists():
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"detail": f"Admin page '{page_name}.html' not found."})

# =========================================================
# 8. STATIC FILES (CSS, JS, Images for Admin Panel)
# =========================================================

# Ensure your CSS/JS assets inside frontend/static are accessible
static_dir = FRONTEND_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
elif FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# =========================================================
# 9. LOCAL EXECUTION ENTRY POINT
# =========================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
