#!/usr/bin/env python3
"""Fetch financial news via NewsAPI and write the latest summary to a log."""
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_KEY='***' # https://newsapi.org
LOG_FILE = Path(__file__).with_name('financial_news_check.log')

# Keywords to search for financial news
KEYWORDS = 'finance OR investing OR stock OR market OR economy OR ETF OR dividend OR treasury OR bond OR recession OR inflation OR Fed'


def fetch_articles(endpoint, params):
    query = urlencode(params)
    request = Request(
        f'https://newsapi.org/v2/{endpoint}?{query}',
        headers={'X-Api-Key': API_KEY},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('status') != 'ok':
        raise RuntimeError(payload.get('message', 'NewsAPI request failed'))
    return payload.get('articles', [])


def main():
    # Try business headlines first, then keyword search
    articles = []
    sources_used = []
    output_lines = []

    try:
        headlines = fetch_articles('top-headlines', {
            'category': 'business',
            'language': 'en',
            'pageSize': 10,
        })
        for a in headlines:
            articles.append({
                'title': a.get('title', ''),
                'source': a.get('source', {}).get('name', ''),
                'url': a.get('url', ''),
                'published': a.get('publishedAt', ''),
            })
        sources_used.append('business_headlines')
    except Exception as e:
        output_lines.append(f'business headlines error: {e}')

    try:
        keyword = fetch_articles('everything', {
            'q': KEYWORDS,
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': 10,
        })
        for a in keyword:
            articles.append({
                'title': a.get('title', ''),
                'source': a.get('source', {}).get('name', ''),
                'url': a.get('url', ''),
                'published': a.get('publishedAt', ''),
            })
        sources_used.append('keyword_search')
    except Exception as e:
        output_lines.append(f'keyword search error: {e}')

    # Dedupe by URL
    seen = set()
    unique = []
    for a in articles:
        if a['url'] and a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    output_lines.append(
        f'Fetched {len(unique)} unique articles from {", ".join(sources_used)}'
    )
    for a in unique[:5]:
        output_lines.append(
            f"  [{a['source']}] {a['title'][:90]} - {a['url']}"
        )

    output = '\n'.join(output_lines)
    LOG_FILE.write_text(f'{output}\n', encoding='utf-8')
    print(output)
    
if __name__ == '__main__':
    main()