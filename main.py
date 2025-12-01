from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import os
import asyncpg

# ===== CONFIG =====
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI(title="Lichen Social – Premier réseau social symbiotique")

# ===== MODELS =====
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str

class PostCreate(BaseModel):
    content: str

class PostOut(BaseModel):
    id: int
    content: str
    user_id: int
    created_at: datetime

# ===== UTILS =====
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
        if user_id is None:
            raise HTTPException(status_code=401)
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# ===== ROUTES =====
@app.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Vérif user existe pas déjà
    result = await db.execute("SELECT id FROM users WHERE username = $1 OR email = $2", user.username, user.email)
    if result.fetchone():
        raise HTTPException(status_code=400, detail="User already exists")
    
    hashed = get_password_hash(user.password)
    await db.execute(
        "INSERT INTO users (username, email, password_hash) VALUES ($1, $2, $3)",
        user.username, user.email, hashed
    )
    await db.commit()
    return {"msg": "User created – welcome to Lichen Social 🌱"}

@app.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute("SELECT id, password_hash FROM users WHERE username = $1", form.username)
    user = result.fetchone()
    if not user or not verify_password(form.password, user[1]):
        raise HTTPException(status_code=401, detail="Mauvais combo")
    
    token = create_access_token({"sub": str(user[0])})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/posts")
async def create_post(post: PostCreate, user_id: int = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        "INSERT INTO posts (user_id, content) VALUES ($1, $2) RETURNING id, created_at",
        user_id, post.content
    )
    await db.commit()
    new_post = result.fetchone()
    return {"id": new_post[0], "content": post.content, "created_at": new_post[1]}

@app.get("/feed")
async def feed(user_id: int = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = """
    SELECT p.id, p.content, p.user_id, p.created_at 
    FROM posts p
    JOIN follows f ON p.user_id = f.following_id
    WHERE f.follower_id = $1
    ORDER BY p.created_at DESC
    LIMIT 50
    """
    result = await db.execute(query, user_id)
    posts = result.fetchall()
    return [{"id": p[0], "content": p[1], "user_id": p[2], "created_at": p[3]} for p in posts]

@app.post("/follow/{target_id}")
async def follow(target_id: int, user_id: int = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(
        "INSERT INTO follows (follower_id, following_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id, target_id
    )
    await db.commit()
    return {"msg": f"Tu suis maintenant l'utilisateur {target_id}"}

# Route test
@app.get("/")
async def root():
    return {"message": "Lichen Social est LIVE – premier réseau social symbiotique 🌱🤖"}
