import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from collections import deque
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from transformers import pipeline
from pydantic import BaseModel, Field, ConfigDict
import feedparser
from dotenv import load_dotenv
import torch

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# MongoDB
mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))
db = mongo_client[os.getenv("DB_NAME", "sentiment_db")]

# ML Model
device = 0 if torch.cuda.is_available() else "cpu"
sentiment_analyzer = None

LABEL_MAP = {"LABEL_0": "negative", "LABEL_1": "neutral", "LABEL_2": "positive"}

RSS_FEEDS = [
    # International
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "http://rss.cnn.com/rss/edition.rss",
    "http://rss.cnn.com/rss/cnn_topstories.rss",
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/us-news/rss",
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.washingtonpost.com/rss/world",
    "https://feeds.washingtonpost.com/rss/business",
    # Tech
    "https://feeds.feedburner.com/TechCrunch",
    "https://www.wired.com/feed/rss",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    # Finance
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    # India
    "https://feeds.feedburner.com/ndtvnews-top-stories",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://www.thehindu.com/feeder/default.rss",
]

MAX_CONNECTIONS = 50


# --- BoundedSeenSet ---
class BoundedSeenSet:
    """Invariant: set and deque always contain identical elements."""
    def __init__(self, maxlen=1000):
        self._set = set()
        self._deque = deque(maxlen=maxlen)

    def __contains__(self, item):
        return item in self._set

    def add(self, item):
        if item in self._set:
            return
        if len(self._deque) == self._deque.maxlen:
            self._set.discard(self._deque[0])
        self._deque.append(item)
        self._set.add(item)


seen = BoundedSeenSet()


# --- Pydantic Model ---
class SentimentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    title: str
    sentiment: str
    score: float
    url: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)

    async def broadcast(self, message: dict):
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.active_connections -= dead


manager = ConnectionManager()


# --- Sentiment ---
def analyze(text: str) -> dict:
    result = sentiment_analyzer(text[:512])[0]
    label = LABEL_MAP.get(result["label"], result["label"].lower())
    return {"sentiment": label, "score": round(result["score"], 3)}


# --- Background Task ---
async def fetch_loop():
    while True:
        new_articles = []
        for url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                source = feed.feed.get("title", url)
                for entry in feed.entries[:10]:
                    eid = entry.get("id") or entry.get("link")
                    if not eid or eid in seen:
                        continue
                    seen.add(eid)
                    result = analyze(f"{entry.title}. {entry.get('summary', '')}")
                    item = SentimentItem(
                        source=source,
                        title=entry.title,
                        url=entry.get("link"),
                        **result
                    )
                    doc = item.model_dump()
                    await db.sentiments.insert_one(doc)
                    new_articles.append(item.model_dump())
                    await manager.broadcast({"type": "new_sentiment", "data": item.model_dump()})
                    await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"Feed error {url}: {e}")

        # Push updated trends once after all articles
        trends = await compute_trends()
        await manager.broadcast({"type": "trends", "data": trends})
        await asyncio.sleep(5)


async def compute_trends() -> dict:
    pipeline_agg = [{"$group": {"_id": "$sentiment", "count": {"$sum": 1}}}]
    dist = {d["_id"]: d["count"] async for d in db.sentiments.aggregate(pipeline_agg)}

    recent = await db.sentiments.find({}, {"_id": 0}).sort("timestamp", -1).limit(200).to_list(200)
    time_series = []
    for i in range(0, len(recent), 10):
        batch = recent[i:i+10]
        time_series.append({
            "timestamp": batch[0]["timestamp"],
            "positive": sum(1 for a in batch if a["sentiment"] == "positive"),
            "negative": sum(1 for a in batch if a["sentiment"] == "negative"),
            "neutral":  sum(1 for a in batch if a["sentiment"] == "neutral"),
        })

    return {"distribution": dist, "time_series": list(reversed(time_series))}


# --- Startup ---
@app.on_event("startup")
async def startup():
    global sentiment_analyzer
    logger.info("Loading model...")
    sentiment_analyzer = pipeline(
        "sentiment-analysis",
        model="cardiffnlp/twitter-roberta-base-sentiment-latest",
        device=device
    )
    logger.info("Model loaded.")
    await db.sentiments.create_index([("timestamp", -1)])
    await db.sentiments.create_index([("sentiment", 1), ("timestamp", -1)])
    asyncio.create_task(fetch_loop())


# --- REST Endpoints ---
@app.get("/api/sentiment/recent")
async def recent(limit: int = 50):
    return await db.sentiments.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)


@app.get("/api/sentiment/trends")
async def trends():
    return await compute_trends()


# --- WebSocket ---
@app.websocket("/api/ws/sentiment")
async def ws_endpoint(ws: WebSocket):
    if len(manager.active_connections) >= MAX_CONNECTIONS:
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    try:
        recent = await db.sentiments.find({}, {"_id": 0}).sort("timestamp", -1).limit(50).to_list(50)
        trends = await compute_trends()
        await ws.send_json({"type": "init", "articles": recent, "trends": trends})
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
