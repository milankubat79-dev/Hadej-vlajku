"""
Test skript - diagnostika stahování fotek měst
Spusť: py test_city.py
"""
import asyncio
import aiohttp
import json
from urllib.parse import quote
import sys, io

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

API_HEADERS = {
    'User-Agent': 'HadejVlajkuBot/1.0 (milan.kubat@marketup.cz)',
    'Accept': 'application/json',
}
IMG_HEADERS = {
    'User-Agent': 'HadejVlajkuBot/1.0 (milan.kubat@marketup.cz)',
}

TEST_CITIES = ['London', 'Prague', 'Paris', 'Tokyo', 'Cairo', 'Nairobi']

async def test():
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:

        print("=== TEST 1: Wikipedia REST summary API ===")
        for city in TEST_CITIES:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(city)}"
            try:
                async with session.get(url, headers=API_HEADERS) as r:
                    print(f"  {city}: HTTP {r.status}, content-type={r.headers.get('content-type','?')[:40]}")
                    if r.status == 200:
                        d = await r.json(content_type=None)
                        thumb = (d.get('thumbnail') or {}).get('source', '')
                        print(f"    thumbnail: {thumb[:80] if thumb else 'NONE'}")
            except Exception as e:
                print(f"  {city}: EXCEPTION {e}")

        print()
        print("=== TEST 2: Wikipedia pageimages API ===")
        for city in TEST_CITIES[:3]:
            url = (f"https://en.wikipedia.org/w/api.php?action=query"
                   f"&titles={quote(city)}&prop=pageimages&format=json"
                   f"&pithumbsize=800&pilicense=any&redirects=1&origin=*")
            try:
                async with session.get(url, headers=API_HEADERS) as r:
                    print(f"  {city}: HTTP {r.status}")
                    if r.status == 200:
                        d = await r.json(content_type=None)
                        page = list((d.get('query', {}).get('pages', {})).values())[0]
                        src = (page.get('thumbnail') or {}).get('source', '')
                        print(f"    pageimage: {src[:80] if src else 'NONE'}")
            except Exception as e:
                print(f"  {city}: EXCEPTION {e}")

        print()
        print("=== TEST 3: Wikimedia Commons search ===")
        for city in TEST_CITIES[:3]:
            url = (f"https://commons.wikimedia.org/w/api.php?action=query"
                   f"&list=search&srnamespace=6&srsearch={quote(city + ' panorama')}"
                   f"&format=json&origin=*&srlimit=3")
            try:
                async with session.get(url, headers=API_HEADERS) as r:
                    print(f"  {city}: HTTP {r.status}")
                    if r.status == 200:
                        d = await r.json(content_type=None)
                        results = (d.get('query') or {}).get('search') or []
                        for res in results[:2]:
                            print(f"    -> {res['title']}")
            except Exception as e:
                print(f"  {city}: EXCEPTION {e}")

        print()
        print("=== DONE ===")

asyncio.run(test())
