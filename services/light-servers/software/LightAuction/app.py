from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightAuctionSession
except ImportError:
    from software.LightAuction.session import LightAuctionSession
import logging, colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightAuction")
session_dict: Dict[str, LightAuctionSession] = {}

def get_session(session_id: str):
    s = session_dict.get(session_id)
    if s is None: return None, {"status": "failed", "output": "session not found"}
    return s, None

@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    s = LightAuctionSession(os_cfg=os_cfg, seed=seed)
    session_dict[s.session_id] = s
    return {"status": "ok", "session_id": s.session_id, "session_info": {"status": "ok", "output": s.auction_session.get_session_dict()}}

@mcp.tool
async def logout(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    info = {"status": "ok", "output": s.auction_session.get_session_dict()}
    del session_dict[session_id]
    return info

@mcp.tool
async def list_listings(session_id: str, status: Optional[str] = None, category: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.list_listings(status=status, category=category)

@mcp.tool
async def get_listing(lid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.get_listing(lid)

@mcp.tool
async def create_listing(title: str, description: str, seller: str, starting_price: float, end_time: str, session_id: str, category: str = "general"):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.create_listing(title, description, seller, starting_price, end_time, category)

@mcp.tool
async def cancel_listing(lid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.cancel_listing(lid)

@mcp.tool
async def end_listing(lid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.end_listing(lid)

@mcp.tool
async def place_bid(listing_id: str, bidder: str, amount: float, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.place_bid(listing_id, bidder, amount)

@mcp.tool
async def list_bids(session_id: str, listing_id: Optional[str] = None, bidder: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.list_bids(listing_id, bidder)

@mcp.tool
async def get_bid(bid_id: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.get_bid(bid_id)

@mcp.tool
async def highest_bid(listing_id: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.highest_bid(listing_id)

@mcp.tool
async def add_to_watchlist(lid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.add_to_watchlist(lid)

@mcp.tool
async def remove_from_watchlist(lid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.remove_from_watchlist(lid)

@mcp.tool
async def get_watchlist(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.get_watchlist()

@mcp.tool
async def search_listings(query: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.search_listings(query)

@mcp.tool
async def get_stats(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.auction_session.get_stats()
