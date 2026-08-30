import string, secrets, time, uuid, os
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

SQLALCHEMY_DATABASE_URL = "sqlite:///./valentune.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PlaylistModel(Base):
    __tablename__ = "playlists"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String, unique=True, index=True, nullable=False)
    edit_token = Column(String, unique=True, index=True, nullable=False)
    sender_name = Column(String, default="Someone who loves you")
    recipient_name = Column(String, nullable=False)
    message = Column(String, nullable=False)
    theme = Column(String, default="classic_red")
    songs = relationship("SongModel", back_populates="playlist", cascade="all, delete-orphan")

class SongModel(Base):
    __tablename__ = "songs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id = Column(String, ForeignKey("playlists.id"))
    youtube_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    note = Column(String)
    order_index = Column(Integer, nullable=False)
    playlist = relationship("PlaylistModel", back_populates="songs")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Valentune")
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def generate_token(length=8):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

rate_limit_db = defaultdict(list)
def rate_limiter(request: Request):
    ip = request.client.host
    now = time.time()
    rate_limit_db[ip] = [t for t in rate_limit_db[ip] if now - t < 3600]
    if len(rate_limit_db[ip]) >= 5:
        raise HTTPException(status_code=429, detail="Maximum 5 playlists per hour.")
    rate_limit_db[ip].append(now)

class SongSchema(BaseModel):
    youtube_id: str
    title: str
    note: Optional[str] = Field(None, max_length=140)
    order_index: int

class PlaylistSchema(BaseModel):
    recipient_name: str
    sender_name: Optional[str] = "Someone who loves you"
    message: str = Field(..., max_length=500)
    theme: str
    songs: List[SongSchema] = Field(..., min_length=3, max_length=15)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("create.html", {"request": request})

@app.post("/api/playlists", dependencies=[Depends(rate_limiter)])
def create_playlist(data: PlaylistSchema, db: Session = Depends(get_db)):
    slug, edit_token = generate_token(8), generate_token(12)
    new_playlist = PlaylistModel(slug=slug, edit_token=edit_token, **data.model_dump(exclude={'songs'}))
    for song in data.songs:
        new_playlist.songs.append(SongModel(**song.model_dump()))
    db.add(new_playlist)
    db.commit()
    return {"slug": slug, "edit_token": edit_token}

@app.get("/p/{slug}", response_class=HTMLResponse)
def view_playlist(request: Request, slug: str, db: Session = Depends(get_db)):
    playlist = db.query(PlaylistModel).filter(PlaylistModel.slug == slug).first()
    if not playlist:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return templates.TemplateResponse("recipient.html", {"request": request, "playlist": playlist, "songs": sorted(playlist.songs, key=lambda s: s.order_index)})

@app.get("/edit/{edit_token}", response_class=HTMLResponse)
def edit_view(request: Request, edit_token: str, db: Session = Depends(get_db)):
    playlist = db.query(PlaylistModel).filter(PlaylistModel.edit_token == edit_token).first()
    if not playlist:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return templates.TemplateResponse("edit.html", {"request": request, "playlist": playlist, "songs": sorted(playlist.songs, key=lambda s: s.order_index)})

@app.put("/api/playlists/{edit_token}")
def update_playlist(edit_token: str, data: PlaylistSchema, db: Session = Depends(get_db)):
    playlist = db.query(PlaylistModel).filter(PlaylistModel.edit_token == edit_token).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Not found")
    
    playlist.recipient_name = data.recipient_name
    playlist.sender_name = data.sender_name
    playlist.message = data.message
    playlist.theme = data.theme
    
    db.query(SongModel).filter(SongModel.playlist_id == playlist.id).delete()
    for song in data.songs:
        db.add(SongModel(playlist_id=playlist.id, **song.model_dump()))
    
    db.commit()
    return {"status": "updated", "slug": playlist.slug}

@app.get("/api/youtube/search")
async def youtube_search(q: str):
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        return {"items": []}
    async with httpx.AsyncClient() as client:
        res = await client.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={q}&type=video&key={api_key}")
        return res.json()
