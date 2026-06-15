"""Thin wrapper around law.go.kr target=ordin endpoints."""

import logging
from xml.etree import ElementTree

import requests

from core.http import make_request
from core.throttle import Throttle

from . import cache
from .config import BACKOFF_BASE_SECONDS, LAW_API_BASE, LAW_API_KEY, MAX_RETRIES, REQUEST_DELAY_SECONDS, TYPE_CODES

logger = logging.getLogger(__name__)

_throttle = Throttle(REQUEST_DELAY_SECONDS)

def _request(url: str, params: dict) -> requests.Response:
    return make_request(
        url,
        params,
        throttle=_throttle,
        api_key=LAW_API_KEY,
        max_retries=MAX_RETRIES,
        backoff_base=BACKOFF_BASE_SECONDS,
    )


def _require_no_api_error(root: ElementTree.Element, context: str) -> None:
    result = root.findtext("result")
    if result and "실패" in result:
        raise RuntimeError(f"API error ({context}): {result} - {root.findtext('msg', '')}")


def _list_items(root: ElementTree.Element) -> list[ElementTree.Element]:
    items = root.findall(".//ordin")
    if items:
        return items
    return [item for item in root.iter() if item.findtext("자치법규ID") is not None]


def search_ordinances(
    *,
    page: int = 1,
    display: int = 100,
    org: str = "",
    sborg: str = "",
    ordinance_type: str = "",
    date_range: str = "",
    nw: str = "1",
) -> dict:
    """Search ordinance metadata via lawSearch.do target=ordin."""
    params = {
        "target": "ordin",
        "type": "XML",
        "page": str(page),
        "display": str(display),
        "nw": nw,
    }
    if org:
        params["org"] = org
    if sborg:
        params["sborg"] = sborg
    if ordinance_type:
        params["knd"] = TYPE_CODES.get(ordinance_type, ordinance_type)
    if date_range:
        params["prmlYd"] = date_range

    resp = _request(f"{LAW_API_BASE}/lawSearch.do", params)
    root = ElementTree.fromstring(resp.content)
    _require_no_api_error(root, f"ordin search page {page}")
    total = int(root.findtext("totalCnt", "0") or 0)
    page_num = int(root.findtext("page", str(page)) or page)
    items = []
    for item in _list_items(root):
        items.append({child.tag: child.text or "" for child in item})
    return {"totalCnt": total, "page": page_num, "ordinances": items, "raw_xml": resp.content}


def get_ordinance_detail(ordinance_id: str, *, mst: str = "", refresh: bool = False) -> bytes:
    """Fetch and cache raw ordinance detail XML.

    Cached by MST (자치법규일련번호) when available so that distinct revisions of
    the same 자치법규ID are stored separately. Falls back to keying by ID only
    when no MST is supplied (single-version callers).
    """
    cache_key = str(mst) if mst else str(ordinance_id)
    if not refresh:
        cached = cache.get_detail(cache_key)
        if cached:
            logger.debug("Cache hit: ordinance MST=%s ID=%s", mst, ordinance_id)
            return cached
    params = {"target": "ordin", "type": "XML"}
    if mst:
        params["MST"] = str(mst)
    else:
        params["ID"] = str(ordinance_id)
    resp = _request(f"{LAW_API_BASE}/lawService.do", params)
    root = ElementTree.fromstring(resp.content)
    _require_no_api_error(root, f"ordin detail ID={ordinance_id} MST={mst}")
    cache.put_detail(cache_key, resp.content)
    return resp.content
