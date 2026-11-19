"""MCP tool tests with a mocked HTTP transport (offline)."""
import asyncio

import httpx

import server
from test_crawler import make_site


def _patch(monkeypatch, handler):
    real = server._client

    def fake_client(**kw):
        return real(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, '_client', fake_client)
    orig = server._scan

    async def scan_no_guard(urls, max_pages, include_phones, same_domain, scanner_kw=None):
        return await orig(urls, max_pages, include_phones, same_domain,
                          scanner_kw={'delay': (0.0, 0.0), 'guard_private': False})
    monkeypatch.setattr(server, '_scan', scan_no_guard)


def test_tools_listed():
    tools = asyncio.run(server.mcp.list_tools())
    assert sorted(t.name for t in tools) == ['get_website_contacts', 'get_websites_contacts']


def test_get_website_contacts(monkeypatch):
    handler, log = make_site()
    _patch(monkeypatch, handler)
    row = asyncio.run(server.get_website_contacts('https://www.palmbay-resort.test'))
    assert row['error'] is None
    assert 'info@palmbay-resort.test' in row['emails']
    assert not any('smith' in e or 'gmail' in e for e in row['emails'])
    assert row['line'] and row['whatsapp'] and row['facebook']
    assert '/our-team/' not in log  # robots.txt disallows it


def test_get_websites_contacts_dedup_and_limit(monkeypatch):
    handler, _ = make_site()
    _patch(monkeypatch, handler)
    urls = ['https://www.palmbay-resort.test'] * 3 + [f'https://site{i}.test' for i in range(20)]
    rows = asyncio.run(server.get_websites_contacts(urls, max_pages=0))
    assert len(rows) == server.MAX_SITES
    assert rows[0]['domain'] == 'palmbay-resort.test'


def test_include_phones_false(monkeypatch):
    handler, _ = make_site()
    _patch(monkeypatch, handler)
    row = asyncio.run(server.get_website_contacts('https://www.palmbay-resort.test', include_phones=False))
    assert row['phones'] == [] and row['whatsapp'] == []
