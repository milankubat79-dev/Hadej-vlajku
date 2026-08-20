#!/usr/bin/env python3
"""
Downloader všech obrázků pro hru Hádej Vlajku! v2
=================================================
Stahuje:
  - loga aut        → logos/cars/<slug>.{png|svg|webp}
  - loga klubů      → logos/clubs/<slug>.{png|svg|webp}
  - fotky hráčů     → players/<slug>.{png|jpg|webp}
  - vlajky          → flags/<iso>.png
  - fotky měst      → cities/<key>.{png|jpg|webp}

Požadavky:
  pip install aiohttp  (nebo: pip3 install aiohttp)

Spuštění:
  python3 download_all_images.py
  python3 download_all_images.py --only cars       # jen auta
  python3 download_all_images.py --only clubs      # jen kluby
  python3 download_all_images.py --only players    # jen hráči
  python3 download_all_images.py --only flags      # jen vlajky
  python3 download_all_images.py --only cities     # jen města
  python3 download_all_images.py --redownload      # ignoruj cache, znovu stáhni vše

Výstup se ukládá do složky 'github_images/' vedle tohoto skriptu.
Po stažení nahrej celou složku github_images/ do rootu svého GitHub repozitáře.
"""

import asyncio
import aiohttp
import json
import os
import re
import sys
import argparse
from pathlib import Path
from urllib.parse import quote

# ─── NASTAVENÍ ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
BASE         = SCRIPT_DIR / 'github_images'
CARS_DIR     = BASE / 'logos' / 'cars'
CLUBS_DIR    = BASE / 'logos' / 'clubs'
PLAYERS_DIR  = BASE / 'players'
CITIES_DIR   = BASE / 'cities'
FLAGS_DIR    = BASE / 'flags'

DATA_FILE    = SCRIPT_DIR / 'all_data.json'

HEADERS = {
    'User-Agent': 'HadejVlajkuBot/1.0 (milan.kubat@marketup.cz; image downloader for game)',
    'Accept': 'image/*,*/*;q=0.8',
}
TIMEOUT    = aiohttp.ClientTimeout(total=30)
CONCURRENT = 6   # max souběžných požadavků (buď hodný k API)

# ─── GLOBÁLNÍ STATISTIKY ──────────────────────────────────────────────────────
stats = {'ok': 0, 'fail': 0, 'skip': 0}
SEM = None  # inicializuje se v main()

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def slug_from_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[àáâãäå]', 'a', s)
    s = re.sub(r'[èéêë]',   'e', s)
    s = re.sub(r'[ìíîï]',   'i', s)
    s = re.sub(r'[òóôõö]',  'o', s)
    s = re.sub(r'[ùúûü]',   'u', s)
    s = re.sub(r'[ýÿ]',     'y', s)
    s = re.sub(r'[ñ]',      'n', s)
    s = re.sub(r'[ç]',      'c', s)
    s = re.sub(r'[ß]',      'ss', s)
    s = re.sub(r"['’ʼ]", '', s)
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+',   '-', s)
    s = re.sub(r'-+',       '-', s).strip('-')
    return s

def ext_from_url(url: str, ct: str) -> str:
    u = url.lower().split('?')[0]
    if '.svg'  in u: return '.svg'
    if '.png'  in u: return '.png'
    if '.webp' in u: return '.webp'
    if '.gif'  in u: return '.gif'
    if '.jpg'  in u or '.jpeg' in u: return '.jpg'
    if 'png'  in ct: return '.png'
    if 'svg'  in ct: return '.svg'
    if 'webp' in ct: return '.webp'
    if 'jpeg' in ct or 'jpg' in ct: return '.jpg'
    return '.png'

# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────
async def download_bytes(session, url: str):
    async with session.get(url, headers=HEADERS, allow_redirects=True) as r:
        if r.status != 200:
            raise Exception(f"HTTP {r.status}")
        ct = r.headers.get('content-type', '')
        if 'html' in ct:
            raise Exception("got HTML, not image")
        data = await r.read()
        if len(data) < 500:
            raise Exception(f"too small ({len(data)} bytes), probably an error page")
        return data, ct

async def save_img(session, img_url: str, dest_no_ext: Path) -> str | None:
    try:
        data, ct = await download_bytes(session, img_url)
        ext  = ext_from_url(img_url, ct)
        path = Path(str(dest_no_ext) + ext)
        path.write_bytes(data)
        stats['ok'] += 1
        return str(path)
    except Exception as e:
        stats['fail'] += 1
        return None

# ─── WIKIPEDIA SOURCES ────────────────────────────────────────────────────────
async def wiki_summary_img(session, title: str) -> str:
    """Wikipedia REST summary → thumbnail/original image URL."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            raise Exception(f"HTTP {r.status}")
        d = await r.json()
        src = (d.get('thumbnail') or {}).get('source') or \
              (d.get('originalimage') or {}).get('source')
        if not src:
            raise Exception("no image in summary")
        return re.sub(r'/\d{2,4}px-', '/800px-', src)

async def wiki_pageimages(session, title: str) -> str:
    """Wikipedia pageimages API → thumbnail."""
    url = (f"https://en.wikipedia.org/w/api.php?action=query"
           f"&titles={quote(title)}&prop=pageimages&format=json"
           f"&pithumbsize=800&pilicense=any&redirects=1&origin=*")
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            raise Exception(f"HTTP {r.status}")
        d    = await r.json()
        page = list((d.get('query', {}).get('pages', {})).values())[0]
        src  = (page.get('thumbnail') or {}).get('source')
        if not src:
            raise Exception("no pageimage")
        return re.sub(r'/\d{2,4}px-', '/800px-', src)

async def wiki_logo_scan(session, title: str) -> str:
    """Skenuj obrázky ve Wikipedia článku, hledej logo/badge/crest."""
    url = (f"https://en.wikipedia.org/w/api.php?action=query"
           f"&titles={quote(title)}&prop=images&imlimit=50"
           f"&format=json&redirects=1&origin=*")
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            raise Exception(f"HTTP {r.status}")
        d    = await r.json()
        page = list((d.get('query', {}).get('pages', {})).values())[0]
        imgs = page.get('images', [])
    logo_re = re.compile(
        r'logo|badge|crest|emblem|shield|wappen|stemma|escudo|blason', re.I
    )
    found = next((i['title'] for i in imgs if logo_re.search(i['title'])), None)
    if not found:
        raise Exception("no logo file found in article")
    url2 = (f"https://en.wikipedia.org/w/api.php?action=query"
            f"&titles={quote(found)}&prop=imageinfo&iiprop=url"
            f"&iiurlwidth=400&format=json&origin=*")
    async with session.get(url2, headers=HEADERS) as r2:
        d2  = await r2.json()
        p2  = list((d2.get('query', {}).get('pages', {})).values())[0]
        url_val = ((p2.get('imageinfo') or [{}])[0]).get('url')
        if not url_val:
            raise Exception("no URL for logo file")
        return url_val

async def sportsdb_logo(session, team_name: str) -> str:
    """TheSportsDB → badge URL (free tier)."""
    url = f"https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={quote(team_name)}"
    async with session.get(url, headers=HEADERS) as r:
        if r.status != 200:
            raise Exception(f"HTTP {r.status}")
        d = await r.json()
        badge = ((d.get('teams') or [{}])[0]).get('strBadge')
        if not badge:
            raise Exception("no badge in SportsDB")
        return badge + '/preview'  # smaller version

# ─── DOWNLOADERS ──────────────────────────────────────────────────────────────

async def download_car(session, car: dict, redownload: bool):
    slug = car['slug']
    wiki = car['wiki']
    name = car['name']

    if not redownload:
        existing = list(CARS_DIR.glob(f"{slug}.*"))
        if existing:
            stats['skip'] += 1
            return

    async with SEM:
        img_url = None
        for attempt in [
            lambda: wiki_summary_img(session, wiki),
            lambda: wiki_pageimages(session, wiki),
            lambda: wiki_logo_scan(session, wiki),
        ]:
            try:
                img_url = await attempt()
                break
            except:
                pass

        if img_url:
            result = await save_img(session, img_url, CARS_DIR / slug)
            status = '✓' if result else '✗'
        else:
            status = '✗ (no URL)'
            stats['fail'] += 1

        mark = '🟢' if status == '✓' else '🔴'
        print(f"  {mark} {name} ({slug})", flush=True)


async def download_club(session, club: dict, redownload: bool):
    name = club['name']
    wiki = club['wiki']
    sdb  = club.get('sdb') or name
    slug = club.get('slug') or slug_from_name(name)

    if not redownload:
        existing = list(CLUBS_DIR.glob(f"{slug}.*"))
        if existing:
            stats['skip'] += 1
            return

    async with SEM:
        img_url = None
        for attempt in [
            lambda: sportsdb_logo(session, sdb),
            lambda: wiki_logo_scan(session, wiki),
            lambda: wiki_summary_img(session, wiki),
            lambda: wiki_pageimages(session, wiki),
        ]:
            try:
                img_url = await attempt()
                break
            except:
                pass

        if img_url:
            result = await save_img(session, img_url, CLUBS_DIR / slug)
            status = '✓' if result else '✗'
        else:
            status = '✗ (no URL)'
            stats['fail'] += 1

        mark = '🟢' if status == '✓' else '🔴'
        print(f"  {mark} {name}", flush=True)


async def download_player(session, wiki_title: str, redownload: bool):
    slug = slug_from_name(wiki_title)

    if not redownload:
        existing = list(PLAYERS_DIR.glob(f"{slug}.*"))
        if existing:
            stats['skip'] += 1
            return

    async with SEM:
        img_url = None
        for attempt in [
            lambda: wiki_summary_img(session, wiki_title),
            lambda: wiki_pageimages(session, wiki_title),
        ]:
            try:
                img_url = await attempt()
                break
            except:
                pass

        if img_url:
            result = await save_img(session, img_url, PLAYERS_DIR / slug)
            status = '✓' if result else '✗'
        else:
            status = '✗ (no URL)'
            stats['fail'] += 1

        mark = '🟢' if status == '✓' else '🔴'
        print(f"  {mark} {wiki_title}", flush=True)


async def download_flag(session, iso: str, redownload: bool):
    if not redownload:
        existing = list(FLAGS_DIR.glob(f"{iso}.*"))
        if existing:
            stats['skip'] += 1
            return

    async with SEM:
        url    = f"https://flagcdn.com/w320/{iso}.png"
        result = await save_img(session, url, FLAGS_DIR / iso)
        mark   = '🟢' if result else '🔴'
        print(f"  {mark} {iso}", flush=True)


async def download_city(session, city: dict, redownload: bool):
    key  = city['key']
    name = city['name']

    if not redownload:
        existing = list(CITIES_DIR.glob(f"{key}.*"))
        if existing:
            stats['skip'] += 1
            return

    async with SEM:
        img_url = None
        # Try several Wikipedia title variants
        for wiki_title in [key, f"{key} capital city", name, f"{name} city"]:
            for attempt in [
                lambda t=wiki_title: wiki_summary_img(session, t),
                lambda t=wiki_title: wiki_pageimages(session, t),
            ]:
                try:
                    img_url = await attempt()
                    break
                except:
                    pass
            if img_url:
                break

        if img_url:
            result = await save_img(session, img_url, CITIES_DIR / key)
            status = '✓' if result else '✗'
        else:
            status = '✗ (no URL)'
            stats['fail'] += 1

        mark = '🟢' if status == '✓' else '🔴'
        print(f"  {mark} {name} ({key})", flush=True)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    global SEM

    parser = argparse.ArgumentParser(description='Downloader obrázků pro Hádej Vlajku!')
    parser.add_argument('--only', choices=['cars', 'clubs', 'players', 'flags', 'cities'],
                        help='Stáhni jen tuto kategorii')
    parser.add_argument('--redownload', action='store_true',
                        help='Ignoruj existující soubory, stáhni znovu')
    args = parser.parse_args()

    # Create directories
    for d in [CARS_DIR, CLUBS_DIR, PLAYERS_DIR, CITIES_DIR, FLAGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Load data
    if not DATA_FILE.exists():
        print(f"❌ Soubor {DATA_FILE} nenalezen!")
        print("   Ujisti se, že all_data.json je ve stejné složce jako tento skript.")
        sys.exit(1)

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        DATA = json.load(f)

    SEM = asyncio.Semaphore(CONCURRENT)

    connector = aiohttp.TCPConnector(limit=CONCURRENT + 4, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector, timeout=TIMEOUT) as session:

        only = args.only
        rd   = args.redownload

        # 1) CAR LOGOS
        if not only or only == 'cars':
            stats.update({'ok': 0, 'fail': 0, 'skip': 0})
            print(f"\n🚗 Stahuju loga aut ({len(DATA['cars'])}) ...")
            tasks = [download_car(session, c, rd) for c in DATA['cars']]
            await asyncio.gather(*tasks)
            print(f"   ✅ OK: {stats['ok']}  ❌ Chyb: {stats['fail']}  ⏭ Přeskočeno: {stats['skip']}")

        # 2) CLUB LOGOS
        if not only or only == 'clubs':
            stats.update({'ok': 0, 'fail': 0, 'skip': 0})
            print(f"\n🏆 Stahuju loga klubů ({len(DATA['clubs'])}) ...")
            tasks = [download_club(session, c, rd) for c in DATA['clubs']]
            await asyncio.gather(*tasks)
            print(f"   ✅ OK: {stats['ok']}  ❌ Chyb: {stats['fail']}  ⏭ Přeskočeno: {stats['skip']}")

        # 3) PLAYER PHOTOS
        if not only or only == 'players':
            stats.update({'ok': 0, 'fail': 0, 'skip': 0})
            players = DATA['players']
            # Handle both formats: list of strings OR list of dicts
            if players and isinstance(players[0], dict):
                titles = [p.get('wiki', p.get('name', '')) for p in players]
            else:
                titles = players
            print(f"\n⚽ Stahuju fotky hráčů ({len(titles)}) ...")
            tasks = [download_player(session, t, rd) for t in titles if t]
            await asyncio.gather(*tasks)
            print(f"   ✅ OK: {stats['ok']}  ❌ Chyb: {stats['fail']}  ⏭ Přeskočeno: {stats['skip']}")

        # 4) FLAGS
        if not only or only == 'flags':
            stats.update({'ok': 0, 'fail': 0, 'skip': 0})
            flags = DATA['flags']
            print(f"\n🏳️  Stahuju vlajky ({len(flags)}) ...")
            tasks = [download_flag(session, iso, rd) for iso in flags]
            await asyncio.gather(*tasks)
            print(f"   ✅ OK: {stats['ok']}  ❌ Chyb: {stats['fail']}  ⏭ Přeskočeno: {stats['skip']}")

        # 5) CITY PHOTOS
        if not only or only == 'cities':
            stats.update({'ok': 0, 'fail': 0, 'skip': 0})
            print(f"\n🏙️  Stahuju fotky hlavních měst ({len(DATA['cities'])}) ...")
            tasks = [download_city(session, c, rd) for c in DATA['cities']]
            await asyncio.gather(*tasks)
            print(f"   ✅ OK: {stats['ok']}  ❌ Chyb: {stats['fail']}  ⏭ Přeskočeno: {stats['skip']}")

    # ─── SUMMARY ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"📁 Výsledná složka: {BASE}")
    total_files = 0
    total_kb    = 0
    for d, label in [
        (CARS_DIR,    '🚗 logos/cars'),
        (CLUBS_DIR,   '🏆 logos/clubs'),
        (PLAYERS_DIR, '⚽ players'),
        (FLAGS_DIR,   '🏳  flags'),
        (CITIES_DIR,  '🏙  cities'),
    ]:
        files = list(d.glob('*'))
        kb    = sum(f.stat().st_size for f in files) // 1024
        print(f"  {label:20s}: {len(files):4d} souborů  ({kb:6d} KB)")
        total_files += len(files)
        total_kb    += kb
    print(f"  {'CELKEM':20s}: {total_files:4d} souborů  ({total_kb:6d} KB)")
    print(f"{'─'*60}")
    print()
    print("📤 Další krok: nahraj složku github_images/ do GitHub repozitáře")
    print("   git add github_images/")
    print("   git commit -m 'Add game images'")
    print("   git push")
    print()


if __name__ == '__main__':
    asyncio.run(main())
