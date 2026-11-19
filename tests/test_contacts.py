"""Parser tests on saved HTML fixtures (a fictional resort; no real people)."""
import pytest

import contacts as C
from conftest import fixture

SITE = 'https://www.palmbay-resort.test/'
DOMAINS = ['palmbay-resort.test']


@pytest.fixture(scope='module')
def home():
    return C.parse_page(fixture('home.html'), SITE, 'home')


@pytest.fixture(scope='module')
def merged(home):
    contact = C.parse_page(fixture('contact.html'), SITE + 'th/contact-us/', 'contact')
    team = C.parse_page(fixture('team.html'), SITE + 'our-team/', 'about')
    return C.merge([home, contact, team], DOMAINS)


# ---------------------------------------------------------------- emails

@pytest.mark.parametrize('addr', [
    'info@palmbay-resort.test', 'sales@palmbay-resort.test', 'reservations@palmbay-resort.test',
    'weddings.samui@palmbay-resort.test', 'rsvn@palmbay-resort.test', 'frontoffice@palmbay-resort.test',
    'customerservice@palmbay-resort.test', 'sales1@palmbay-resort.test', 'info.th@palmbay-resort.test',
    'front.desk@palmbay-resort.test', 'booking-phuket@palmbay-resort.test', 'hr@mail.palmbay-resort.test',
    'reservations.palmbay@palmbay-resort.test', 'Info@PalmBay-Resort.test', 'infosm@palmbay-resort.test',
    'salesbkk@palmbay-resort.test', 'rsvn.samui@palmbay-resort.test',
])
def test_role_addresses_kept(addr):
    kept, why = C.classify_email(addr, DOMAINS)
    assert kept == addr.lower(), why


@pytest.mark.parametrize('addr,reason', [
    ('john.smith@palmbay-resort.test', 'not a role'),
    ('j.smith@palmbay-resort.test', 'not a role'),
    ('jsmith@palmbay-resort.test', 'not a role'),
    ('anna@palmbay-resort.test', 'not a role'),
    ('info.anna@palmbay-resort.test', 'not a role'),
    ('sales.john@palmbay-resort.test', 'not a role'),
    ('salesjohn@palmbay-resort.test', 'not a role'),
    ('infoanna@palmbay-resort.test', 'not a role'),
    ('admissionsmanager@palmbay-resort.test', 'not a role'),  # a job title points to one person
    ('palmbay@palmbay-resort.test', 'not a role'),
    ('noreply@palmbay-resort.test', 'system'),
    ('info@gmail.com', 'free-mail'),
    ('reservations@yahoo.co.th', 'free-mail'),
    ('booking@hotmail.co.uk', 'free-mail'),
    ('info@outlook.com', 'free-mail'),
    ('sales@icloud.com', 'free-mail'),
    ('info@otherhotel.test', 'not on the site domain'),
    ('abc@o123.ingest.sentry.io', 'third-party'),
])
def test_personal_or_foreign_addresses_dropped(addr, reason):
    kept, why = C.classify_email(addr, DOMAINS)
    assert kept is None
    assert reason in why


def test_other_domain_allowed_when_same_domain_off():
    kept, _ = C.classify_email('groups@palmbay-group.test', DOMAINS, same_domain_only=False)
    assert kept == 'groups@palmbay-group.test'
    kept, _ = C.classify_email('info@gmail.com', DOMAINS, same_domain_only=False)
    assert kept is None  # free mail is never returned
    kept, _ = C.classify_email('john.smith@palmbay-group.test', DOMAINS, same_domain_only=False)
    assert kept is None  # role rule still applies


def test_not_emails():
    assert C.classify_email('logo@2x.png', DOMAINS)[0] is None
    assert C.classify_email('u003esupport@palmbay-resort.test', DOMAINS)[0] == 'support@palmbay-resort.test'


def test_merged_emails_are_role_only(merged):
    assert merged['emails'] == [
        'info@palmbay-resort.test', 'reservations@palmbay-resort.test', 'sales@palmbay-resort.test',
        'weddings.samui@palmbay-resort.test', 'support@palmbay-resort.test', 'rsvn@palmbay-resort.test',
        'frontoffice@palmbay-resort.test', 'careers@palmbay-resort.test', 'jobs@palmbay-resort.test',
    ]
    joined = ' '.join(merged['emails'])
    for bad in ('john', 'smith', 'gmail', 'yahoo', 'test.person', 'test.manager', 'sentry', 'groups@'):
        assert bad not in joined
    assert merged['emailsSkipped']['not a role address (may identify a person)'] >= 3
    assert merged['emailsSkipped']['free-mail provider (personal mailbox)'] == 2


def test_hidden_addresses_not_decoded(home):
    # Cloudflare email protection and "[at]" spelling are left alone
    assert not any(e.startswith('spa') for e in home.emails)
    assert 'cdn-cgi' not in ' '.join(home.emails)


# ---------------------------------------------------------------- phones & messengers

def test_phones_e164_from_tel_and_whatsapp_only(merged):
    # home tel links (one international, one national -> region borrowed from +66), contact tel, WhatsApp numbers
    assert merged['phones'] == ['+6677123456', '+6677123457', '+66812345678', '+6677123458', '+66899999999']
    # the team page's personal mobile / WhatsApp are not taken
    assert '+66811111111' not in merged['phones']


def test_messengers(merged):
    assert merged['whatsapp'] == ['https://wa.me/66812345678', 'https://wa.me/66899999999']
    assert merged['line'] == ['https://line.me/R/ti/p/@palmbayresort', 'https://line.me/R/ti/p/@palmbaysamui',
                              'https://lin.ee/AbCdEf1']
    assert merged['telegram'] == ['https://t.me/palmbayresort']


def test_include_phones_false_drops_numbers(home):
    out = C.merge([home], DOMAINS, include_phones=False)
    assert out['phones'] == [] and out['whatsapp'] == []
    assert out['line']  # LINE / Telegram are account links, not numbers


def test_clean_tel():
    assert C.clean_tel('tel:+66%2077%20123%20456') == '+6677123456'
    assert C.clean_tel('tel:0066-77-123-456') == '+6677123456'
    assert C.clean_tel('tel:+44 (0)20 7946 0000') == '+442079460000'
    assert C.clean_tel('tel:12') is None
    assert C.clean_tel('tel:+1 555 0100;ext=12') == '+15550100'


def test_to_e164():
    assert C.to_e164('077123456', 'TH') == '+6677123456'
    assert C.to_e164('077123456', None) is None
    assert C.to_e164('+66812345678', None) == '+66812345678'
    assert C.to_e164('18884827768', None) == '+18884827768'  # 1-888-... written without '+'
    assert C.to_e164('18884827768', 'IE') == '+18884827768'
    assert C.to_e164('0812345678', None) is None


def test_region_detection():
    assert C.region_from_tld('www.hotel.co.th') == 'TH'
    assert C.region_from_tld('startup.io') is None  # generic ccTLD
    assert C.region_from_tld('hotel.com') is None
    assert C.region_from_lang('th') == 'TH'
    assert C.region_from_lang('en-US') is None  # CMS default, says nothing


def test_whatsapp_links():
    assert C.whatsapp_link('https://wa.me/66812345678?text=hi') == ('https://wa.me/66812345678', '+66812345678')
    assert C.whatsapp_link('https://api.whatsapp.com/send/?phone=%2B66812345678') == ('https://wa.me/66812345678',
                                                                                     '+66812345678')
    assert C.whatsapp_link('whatsapp://send?phone=66812345678')[1] == '+66812345678'
    assert C.whatsapp_link('https://wa.me/message/ABCDEF123') == ('https://wa.me/message/ABCDEF123', None)
    assert C.whatsapp_link('https://chat.whatsapp.com/InviteCode1') == ('https://chat.whatsapp.com/InviteCode1', None)
    assert C.whatsapp_link('https://www.whatsapp.com/legal') is None


def test_line_and_telegram_links():
    assert C.line_link('https://line.me/ti/p/~someid') == 'https://line.me/R/ti/p/~someid'
    assert C.line_link('line://ti/p/@shop') == 'https://line.me/R/ti/p/@shop'
    assert C.line_link('https://page.line.me/abc123') == 'https://page.line.me/abc123'
    assert C.line_link('https://line.me/en/') is None
    assert C.telegram_link('https://t.me/share/url?url=x') is None
    assert C.telegram_link('https://t.me/s/SamuiNews') == 'https://t.me/samuinews'
    assert C.telegram_link('tg://resolve?domain=samuinews') == 'https://t.me/samuinews'
    assert C.telegram_link('https://t.me/+AbCdEfGh') == 'https://t.me/+AbCdEfGh'


# ---------------------------------------------------------------- socials

def test_socials(merged):
    assert merged['facebook'] == 'https://www.facebook.com/PalmBayResortSamui'
    assert merged['instagram'] == 'https://www.instagram.com/palmbayresort/'
    assert merged['linkedin'] == 'https://www.linkedin.com/company/palm-bay-resort/'
    assert merged['x'] == 'https://x.com/PalmBayResort'
    assert merged['youtube'] == 'https://www.youtube.com/@palmbayresort'
    assert merged['tiktok'] == 'https://www.tiktok.com/@palmbayresort'


@pytest.mark.parametrize('url', [
    'https://www.linkedin.com/in/some-employee-123/',
    'https://www.facebook.com/sharer/sharer.php?u=x',
    'https://twitter.com/intent/tweet?url=x',
    'https://www.youtube.com/watch?v=abc',
    'https://www.instagram.com/p/Cxyz/',
    'https://notfacebook.com/page',
])
def test_social_rejects(url):
    assert C.social_link(url) is None


def test_person_jsonld_and_team_socials_ignored(merged):
    joined = ' '.join(str(v) for v in merged.values())
    assert 'test.person.private' not in joined
    assert 'authorhandle' not in joined
    assert 'test.manager.personal' not in joined
    assert 'testmanagerpersonal' not in joined


def test_builder_footer_ignored(home):
    out = C.merge([home], DOMAINS)
    assert out['facebook'] == 'https://www.facebook.com/PalmBayResortSamui'


# ---------------------------------------------------------------- contact pages

def test_contact_page_selection(home):
    pages = C.select_contact_pages(home.links, DOMAINS, SITE, 5)
    urls = [u for u, _ in pages]
    assert urls[0] == 'https://www.palmbay-resort.test/en/contact-us/'
    assert 'https://www.palmbay-resort.test/th/contact-us/' not in urls  # language duplicate
    assert 'https://www.palmbay-resort.test/about/' in urls
    assert 'https://www.palmbay-resort.test/our-team/' in urls
    assert not any('privacy' in u or u.endswith('.pdf') or 'booking-engine' in u for u in urls)
    assert C.select_contact_pages(home.links, DOMAINS, SITE, 1) == [
        ('https://www.palmbay-resort.test/en/contact-us/', 'contact')]
    assert C.select_contact_pages(home.links, DOMAINS, SITE, 0) == []


@pytest.mark.parametrize('url,text,kind', [
    ('https://x.test/contact', '', 'contact'),
    ('https://x.test/en/contact-us.html', '', 'contact'),
    ('https://x.test/%E0%B8%95%E0%B8%B4%E0%B8%94%E0%B8%95%E0%B9%88%E0%B8%AD', '', 'contact'),
    ('https://x.test/impressum', '', 'legal'),
    ('https://x.test/about-us/', '', 'about'),
    ('https://x.test/page?id=7', 'Contact us', 'contact'),
    ('https://x.test/news/2026/a-long-story', 'Read all about our new pool and spa opening', None),
    ('https://x.test/tours/team-building-island', 'Team building tour', None),
])
def test_page_kind(url, text, kind):
    k = C.page_kind(url, text)
    assert (k[0] if k else None) == kind


def test_page_without_links():
    pg = C.parse_page(fixture('spa_no_links.html'), 'https://app.test/', 'home')
    assert pg.links == [] and pg.emails == []


def test_registrable_and_brand():
    assert C.registrable('www.mail.example.co.th') == 'example.co.th'
    assert C.registrable('www.palmbay-resort.test') == 'palmbay-resort.test'
    assert C.brand_tokens(['tembo-samui.com']) == {'tembosamui', 'tembo', 'samui'}
