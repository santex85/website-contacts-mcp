"""Offline end-to-end tests of the polite scanner with a mocked HTTP transport."""
import asyncio

import httpx

from conftest import fixture
from crawler import Scanner, normalize_start

SITE = 'https://www.palmbay-resort.test'


def make_site(robots_txt='User-agent: *\nDisallow: /our-team/\n', extra=None):
    log = []
    pages = {
        '/robots.txt': (200, robots_txt.encode(), 'text/plain'),
        '/': (200, fixture('home.html'), 'text/html; charset=utf-8'),
        '/en/contact-us/': (301, b'', 'text/html'),
        '/th/contact-us/': (200, fixture('contact.html'), 'text/html; charset=utf-8'),
        '/about/': (200, b'<html><body><h1>About</h1><p>Since 1999.</p></body></html>', 'text/html'),
        '/our-team/': (200, fixture('team.html'), 'text/html'),
    }
    pages.update(extra or {})

    def handler(request: httpx.Request):
        log.append(request.url.path)
        status, body, ctype = pages.get(request.url.path, (404, b'not found', 'text/html'))
        headers = {'content-type': ctype}
        if status in (301, 302):
            headers['location'] = '/th/contact-us/'
        return httpx.Response(status, content=body, headers=headers)
    return handler, log


def run(handler, url=SITE, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sc = Scanner(client, delay=(0.0, 0.0), guard_private=False)
            return await sc.scan(url, **kw)
    return asyncio.run(go())


def test_full_scan_respects_robots_and_collects_role_contacts():
    handler, log = make_site()
    row = run(handler)
    assert row['error'] is None
    assert log[0] == '/robots.txt'
    assert '/our-team/' not in log  # disallowed: never requested
    assert row['robotsBlocked'] == ['https://www.palmbay-resort.test/our-team/']
    assert row['contactPages'] == ['https://www.palmbay-resort.test/th/contact-us/',
                                   'https://www.palmbay-resort.test/about/']
    assert row['pagesScanned'] == 3
    assert 'info@palmbay-resort.test' in row['emails'] and 'rsvn@palmbay-resort.test' in row['emails']
    assert not any('smith' in e or 'gmail' in e for e in row['emails'])
    assert row['phones'][0] == '+6677123456'
    assert row['phonesNote']
    assert row['domain'] == 'palmbay-resort.test'


def test_start_page_disallowed():
    handler, log = make_site(robots_txt='User-agent: *\nDisallow: /\n')
    row = run(handler)
    assert row['error'].startswith('start page not scanned')
    assert log == ['/robots.txt']
    assert row['emails'] == []


def test_robots_403_means_no_crawl():
    handler, log = make_site(extra={'/robots.txt': (403, b'forbidden', 'text/html')})
    row = run(handler)
    assert 'robots.txt returned HTTP 403' in row['error']
    assert log == ['/robots.txt']


def test_blocked_by_challenge_is_error():
    page = b'<html><head><title>Just a moment...</title></head><body>cf-chl-bypass</body></html>'
    handler, _ = make_site(extra={'/': (403, page, 'text/html')})
    row = run(handler)
    assert row['error'].startswith('blocked: HTTP 403')


def test_cloudflare_script_on_normal_page_is_not_a_block():
    page = (b'<html><body><a href="mailto:info@palmbay-resort.test">mail</a>'
            b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body></html>')
    handler, _ = make_site(extra={'/': (200, page, 'text/html')})
    row = run(handler, max_pages=0)
    assert row['error'] is None and row['emails'] == ['info@palmbay-resort.test']


def test_challenge_page_with_200_is_blocked():
    page = b'<html><head><title>Just a moment...</title></head><body>window._cf_chl_opt={}</body></html>'
    handler, _ = make_site(extra={'/': (200, page, 'text/html')})
    assert run(handler)['error'].startswith('blocked: HTTP 200')


def test_link_redirecting_to_home_is_not_a_contact_page():
    home = b'<html><body><a href="/contact">Contact</a><a href="mailto:info@palmbay-resort.test">m</a></body></html>'
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.path == '/contact':
            return httpx.Response(301, headers={'location': 'https://www.palmbay-resort.test'})
        return httpx.Response(200, content=home, headers={'content-type': 'text/html'})
    row = run(handler)
    assert row['contactPages'] == [] and row['pagesScanned'] == 1


def test_not_html():
    handler, _ = make_site(extra={'/': (200, b'%PDF-1.4', 'application/pdf')})
    row = run(handler)
    assert row['error'].startswith('not an HTML page')


def test_bare_domain_and_max_pages_zero():
    handler, log = make_site()
    row = run(handler, 'palmbay-resort.test', max_pages=0)
    assert row['error'] is None and row['pagesScanned'] == 1
    assert row['url'] == 'https://palmbay-resort.test/'
    assert log == ['/robots.txt', '/']


def test_include_phones_false():
    handler, _ = make_site()
    row = run(handler, include_phones=False)
    assert row['phones'] == [] and row['whatsapp'] == [] and row['phonesNote'] is None


def test_guessed_contact_page_when_home_has_no_links():
    handler, log = make_site(extra={'/': (200, fixture('spa_no_links.html'), 'text/html'),
                                    '/contact': (200, fixture('contact.html'), 'text/html')})
    row = run(handler)
    assert row['contactPages'] == ['https://www.palmbay-resort.test/contact']
    assert '/contact-us' not in log  # second guess skipped once the first one worked
    assert 'rsvn@palmbay-resort.test' in row['emails']


def test_redirect_to_disallowed_path_is_not_followed():
    handler, log = make_site(robots_txt='User-agent: *\nDisallow: /th/\n')
    row = run(handler)
    assert '/th/contact-us/' not in log
    assert 'https://www.palmbay-resort.test/th/contact-us/' in row['robotsBlocked']


def test_normalize_start():
    assert normalize_start('Example.COM')[0] == 'https://example.com/'
    assert normalize_start('http://example.com/contact')[0] == 'http://example.com/contact'
    assert normalize_start('ftp://example.com')[2]
    assert normalize_start('localhost')[2] == 'invalid host name'
    assert normalize_start('')[2] == 'empty URL'


def test_private_hosts_refused():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
            sc = Scanner(client, delay=(0.0, 0.0))
            return await sc.scan('http://127.0.0.1/'), await sc.scan('http://169.254.169.254/latest/')
    a, b = asyncio.run(go())
    assert 'private or local' in a['error'] and 'private or local' in b['error']
