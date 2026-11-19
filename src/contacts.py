"""Pure parsing for company contact details. No network access in this module.

Policy (by design, not configurable):
- Emails: only role addresses (info@, sales@, reservations@ ...). Anything that looks like a
  person's mailbox (john.smith@, j.smith@, anna@) and every address on a free-mail provider
  (gmail, yahoo, hotmail, outlook, icloud ...) is dropped.
- Addresses the site deliberately hides from bots (Cloudflare email protection, "info [at] x")
  are not decoded.
- Phones come only from explicit tel: links and WhatsApp click-to-chat links.
- Social profiles: company pages only; LinkedIn personal profiles (/in/) are never returned.
- People's names are never collected.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urldefrag

import phonenumbers
import tldextract
from bs4 import BeautifulSoup

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)

# ------------------------------------------------------------------ domains

def host_of(url: str) -> str:
    return (urlsplit(url).hostname or '').lower().rstrip('.')


def registrable(host: str) -> str:
    """example.co.th for www.mail.example.co.th; the bare host if there is no public suffix."""
    host = (host or '').lower().rstrip('.')
    r = _TLD(host)
    if r.suffix and r.domain:
        return f'{r.domain}.{r.suffix}'
    return host.removeprefix('www.')


def on_domain(host: str, domains) -> bool:
    host = (host or '').lower().rstrip('.')
    return any(host == d or host.endswith('.' + d) for d in domains if d)


def site_label(domain: str) -> str:
    """'tembo-samui' for www.tembo-samui.co.th (first label when there is no public suffix)."""
    r = _TLD(domain)
    return (r.domain if r.suffix else domain.removeprefix('www.').split('.')[0]).lower()


def brand_tokens(domains) -> set:
    """Brand words from the site's domain: 'tembo-samui.com' -> {'tembosamui', 'tembo', 'samui'}."""
    out = set()
    for d in domains:
        label = site_label(d)
        if len(label) >= 3:
            out.add(label.replace('-', ''))
        for part in re.split(r'[-_]', label):
            if len(part) >= 3:
                out.add(part)
    return out


# ------------------------------------------------------------------ emails

ROLE_WORDS = {
    'info', 'information', 'infos', 'contact', 'contacts', 'contactus', 'hello', 'hi', 'hey', 'ask', 'welcome',
    'sales', 'sale', 'support', 'help', 'helpdesk', 'office', 'admin', 'administration', 'booking', 'bookings',
    'book', 'reservations', 'reservation', 'reserve', 'reservas', 'reserva', 'rsvn', 'rsv', 'resv', 'resa',
    'enquiries', 'enquiry', 'enquire', 'inquiries', 'inquiry', 'inquire', 'marketing', 'press', 'media', 'pr',
    'news', 'careers', 'career', 'jobs', 'job', 'hr', 'recruitment', 'recruiting', 'talent', 'team', 'service',
    'services', 'customerservice', 'customercare', 'care', 'cs', 'orders', 'order', 'shop', 'store', 'events',
    'event', 'weddings', 'wedding', 'partners', 'partner', 'partnerships', 'partnership', 'business', 'biz',
    'general', 'mail', 'email', 'frontdesk', 'frontoffice', 'front', 'desk', 'fo', 'reception', 'guest', 'guests',
    'guestservice', 'guestservices', 'guestrelations', 'relations', 'concierge', 'spa', 'dining', 'restaurant',
    'fnb', 'groups', 'group', 'mice', 'tours', 'tour', 'travel', 'trips', 'charter', 'charters', 'rentals',
    'rental', 'accounts', 'accounting', 'billing', 'finance', 'invoices', 'invoice', 'legal', 'privacy',
    'compliance', 'dpo', 'gdpr', 'security', 'abuse', 'webmaster', 'feedback', 'community', 'social',
    'affiliates', 'affiliate', 'sponsorship', 'investors', 'ir', 'purchasing', 'procurement', 'operations',
    'ops', 'management', 'quotes', 'quote', 'request', 'requests', 'questions', 'customers',
    'clients', 'membership', 'members', 'academy', 'school', 'admissions', 'registrar', 'enrol', 'enroll',
    'kontakt', 'kontakte', 'anfrage', 'buero', 'presse', 'vertrieb', 'contacto', 'ventas', 'contato', 'contatti',
    'bonjour', 'hola', 'accueil', 'emploi', 'salesteam', 'teamsales',
}
NOT_USEFUL = {'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply', 'mailer-daemon', 'postmaster',
              'hostmaster', 'bounce', 'bounces', 'unsubscribe', 'example', 'test', 'user', 'username', 'name',
              'your', 'youremail', 'yourname', 'email-address', 'someone', 'somebody', 'me', 'you'}
PLACE_WORDS = {
    'samui', 'kohsamui', 'phangan', 'kohphangan', 'kohtao', 'phuket', 'bangkok', 'krabi', 'aonang', 'phiphi',
    'kohlanta', 'chiangmai', 'chiangrai', 'pattaya', 'huahin', 'khaolak', 'kohchang', 'chaweng', 'maenam',
    'bophut', 'patong', 'thailand', 'bali', 'singapore', 'penang', 'langkawi', 'hanoi', 'saigon', 'danang',
    'hoian', 'manila', 'cebu', 'boracay', 'tokyo', 'osaka', 'seoul', 'hongkong', 'taipei', 'dubai', 'london',
    'paris', 'berlin', 'sydney', 'melbourne', 'asia', 'apac', 'emea', 'europe', 'global', 'intl',
    'international', 'worldwide', 'hq', 'head', 'main', 'resort', 'resorts', 'hotel', 'hotels', 'villa', 'villas',
    'beach', 'club', 'online', 'web', 'website', 'digital', 'dive', 'diving', 'yacht', 'yachts', 'clinic',
    'studio', 'center', 'centre', 'property', 'properties', 'realestate', 'estate', 'homes', 'boutique',
}
THREE_LETTER = {'bkk', 'hkt', 'usm', 'kbv', 'cnx', 'dmk', 'sin', 'kul', 'hkg', 'dps', 'sgn', 'han', 'mnl', 'icn',
                'nrt', 'hnd', 'dxb', 'lhr', 'cdg', 'eng', 'rus', 'chn', 'tha', 'ger', 'fra', 'esp', 'ita', 'jpn',
                'kor', 'usa', 'uae', 'aus', 'eur'}
TWO_LETTER = {r.lower() for r in phonenumbers.SUPPORTED_REGIONS} | {'uk', 'eu', 'en', 'ru', 'zh', 'ja', 'ko', 'de',
                                                                     'fr', 'es', 'it', 'th', 'vi', 'id'}
FREE_MAIL = {
    'gmail.com', 'googlemail.com', 'ymail.com', 'rocketmail.com', 'msn.com', 'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'proton.me', 'pm.me', 'protonmail.com', 'protonmail.ch', 'web.de', 'mail.ru', 'inbox.ru', 'bk.ru',
    'list.ru', 'rambler.ru', 'ya.ru', 'qq.com', '163.com', '126.com', 'yeah.net', 'sina.com', 'sina.cn',
    'sohu.com', 'naver.com', 'hanmail.net', 'daum.net', 'rediffmail.com', 'zohomail.com', 'tutanota.com',
    'tuta.io', 'fastmail.com', 'hey.com', 'seznam.cz', 'libero.it', 'orange.fr', 'free.fr', 'laposte.net',
    't-online.de', 'btinternet.com', 'comcast.net', 'verizon.net', 'att.net', 'sbcglobal.net', 'bigpond.com',
    'optusnet.com.au', 'shaw.ca', 'rogers.com', 'mail.com', 'email.com', 'usa.com', 'post.com', 'gmx.com',
    'gmx.net', 'gmx.de', 'windowslive.com', 'lycos.com', 'excite.com', 'hushmail.com', 'trueinternet.co.th',
    'loxinfo.co.th', 'ksc.th.com', 'csloxinfo.com', 'singnet.com.sg', 'pacific.net.sg', 'streamyx.com',
}
FREE_MAIL_LABELS = {'yahoo', 'hotmail', 'outlook', 'live', 'gmx', 'yandex', 'aol', 'protonmail', 'icloud', 'gmail',
                    'googlemail', 'ymail', 'msn', 'rediffmail'}
JUNK_EMAIL_DOMAINS = {'example.com', 'example.org', 'example.net', 'domain.com', 'yourdomain.com', 'yoursite.com',
                      'mysite.com', 'website.com', 'company.com', 'sentry.io', 'wixpress.com', 'test.com',
                      'sentry-next.wixpress.com', 'email.tld', 'domain.tld', 'mail.tld'}
FILE_TLDS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'css', 'js', 'ico', 'bmp', 'tif', 'tiff', 'avif', 'mp4',
             'webm', 'pdf', 'woff', 'woff2', 'ttf', 'eot', 'json', 'xml', 'php', 'html', 'htm'}

EMAIL_RE = re.compile(
    r'(?<![A-Za-z0-9._%+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+'
    r'[A-Za-z]{2,24})(?![A-Za-z0-9-])')
JSON_ESCAPE_PREFIX = re.compile(r'^(?:u00[0-9a-f]{2})+(?=[a-z])')  # 'u003einfo@' from JSON-escaped HTML


def is_free_mail(domain: str) -> bool:
    domain = domain.lower()
    if domain in FREE_MAIL:
        return True
    r = _TLD(domain)
    return (r.domain or '') in FREE_MAIL_LABELS


def _segments(token: str, vocab: set, memo=None):
    """Split a concatenated token ('reservationssamui') into vocabulary words, or None."""
    if memo is None:
        memo = {}
    if token in memo:
        return memo[token]
    if not token:
        return []
    for i in range(len(token), 1, -1):
        head = token[:i]
        if head in vocab:
            rest = _segments(token[i:], vocab, memo)
            if rest is not None:
                memo[token] = [head] + rest
                return memo[token]
    memo[token] = None
    return None


def is_role_local(local: str, brands=frozenset()) -> bool:
    """True when the local part is a role mailbox (info, sales.th, reservations-samui, booking2...)."""
    local = local.lower().split('+', 1)[0]
    if not local or local in NOT_USEFUL:
        return False
    if local in ROLE_WORDS:
        return True
    tokens = [t for t in re.split(r'[._-]+', local) if t]
    if not tokens:
        return False
    vocab = ROLE_WORDS | PLACE_WORDS | set(brands)
    has_role = False
    for i, tok in enumerate(tokens):
        core = tok.rstrip('0123456789')
        if not core:  # digits only: 'sales.2'
            if i == 0:
                return False
            continue
        if core in ROLE_WORDS:
            has_role = True
            continue
        if i > 0 and (core in TWO_LETTER or core in THREE_LETTER):
            continue
        if core in PLACE_WORDS or core in brands:
            continue
        # role word glued to a short location code: infosm, salesbkk, rsvnth
        if any(core.startswith(w) and len(core) - len(w) in (2, 3) and core[len(w):] in (TWO_LETTER | THREE_LETTER)
               for w in ROLE_WORDS if len(w) >= 4):
            has_role = True
            continue
        seg = _segments(core, vocab)
        if seg is None:
            return False
        if any(s in ROLE_WORDS for s in seg):
            has_role = True
    return has_role


def classify_email(addr: str, site_domains, same_domain_only: bool = True):
    """Return (normalised address, None) if kept, or (None, reason) if dropped."""
    addr = addr.strip().strip('.').lower()
    if '@' not in addr:
        return None, 'not an email'
    local, domain = addr.rsplit('@', 1)
    local = JSON_ESCAPE_PREFIX.sub('', local)
    domain = domain.strip('.')
    tld = domain.rsplit('.', 1)[-1]
    if tld in FILE_TLDS or '..' in addr or not local:
        return None, 'not an email'
    if domain in JUNK_EMAIL_DOMAINS or domain.endswith(('.sentry.io', '.wixpress.com')):
        return None, 'placeholder or third-party service address'
    if is_free_mail(domain):
        return None, 'free-mail provider (personal mailbox)'
    if same_domain_only and not on_domain(domain, site_domains):
        return None, 'not on the site domain'
    if local.split('+', 1)[0] in NOT_USEFUL:
        return None, 'system or placeholder address'
    brands = brand_tokens(set(site_domains) | {registrable(domain)})
    if not is_role_local(local, brands):
        return None, 'not a role address (may identify a person)'
    return f'{local}@{domain}', None


# ------------------------------------------------------------------ phones

CCTLD_REGION = {'uk': 'GB'}
# ccTLDs widely used as generic domains: they say nothing about where the phone line is
GENERIC_CCTLDS = {'io', 'co', 'ai', 'me', 'tv', 'cc', 'ly', 'fm', 'gg', 'to', 'ws', 'sh', 'ac', 'vc', 'gl', 'gd', 'am',
                  'nu', 'tk', 'ml', 'ga', 'cf', 'st', 'so', 'la', 'is', 'it', 'im', 'ag', 'sc', 'cx', 'bz'}
# Languages spoken (almost) only in one country. 'en-US' style tags are ignored on purpose:
# CMS defaults put en-US on sites everywhere.
LANG_REGION = {'th': 'TH', 'vi': 'VN', 'id': 'ID', 'ja': 'JP', 'ko': 'KR'}


def region_from_tld(host: str) -> str | None:
    suffix = (_TLD(host).suffix or '').rsplit('.', 1)[-1].lower()
    if len(suffix) == 2 and suffix not in GENERIC_CCTLDS:
        reg = CCTLD_REGION.get(suffix, suffix.upper())
        if reg in phonenumbers.SUPPORTED_REGIONS:
            return reg
    return None


def region_from_lang(lang: str | None) -> str | None:
    return LANG_REGION.get((lang or '').strip().lower()[:2]) if lang else None


def clean_tel(raw: str) -> str | None:
    """Digits (with a leading +) from a tel: href, or None if it cannot be a phone number."""
    s = unquote(raw).strip()
    s = re.sub(r'^(tel|callto|phone):(//)?', '', s, flags=re.I)
    s = re.split(r'[;,?]|ext|x(?=\d)', s, maxsplit=1, flags=re.I)[0]
    s = re.sub(r'\(0\)', '', s)
    plus = s.strip().startswith('+')
    digits = re.sub(r'\D', '', s)
    if digits.startswith('00') and not plus:
        digits, plus = digits[2:], True
    if not 6 <= len(digits) <= 15:
        return None
    return ('+' if plus else '') + digits


def to_e164(cleaned: str, region: str | None) -> str | None:
    """E.164 when the number can be placed in a country, else None."""
    try:
        if cleaned.startswith('+'):
            p = phonenumbers.parse(cleaned, None)
            if not phonenumbers.is_possible_number(p):
                return None
        else:
            p = None
            if region:
                p = phonenumbers.parse(cleaned, region)
                if not phonenumbers.is_valid_number(p):  # stricter: the country is only a guess
                    p = None
            if p is None and not cleaned.startswith('0') and len(cleaned) >= 10:
                # international number written without '+': 1-888-..., 66 77 ...
                q = phonenumbers.parse('+' + cleaned, None)
                p = q if phonenumbers.is_valid_number(q) else None
            if p is None:
                return None
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)


# ------------------------------------------------------------------ messengers & socials

def _q(url):
    return parse_qs(urlsplit(url).query)


def whatsapp_link(url: str):
    """('https://wa.me/66812345678', '+66812345678') for click-to-chat links; (link, None) for links
    without a number (wa.me/message/..., chat.whatsapp.com group invites, wa.link); None otherwise."""
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    scheme = p.scheme.lower()
    num = None
    if scheme == 'whatsapp':
        num = (_q(url).get('phone') or [''])[0]
    elif host in ('wa.me', 'www.wa.me'):
        seg = unquote(p.path).strip('/').split('/')[0]
        if seg == 'message':
            code = unquote(p.path).strip('/').split('/')[1:2]
            return (f'https://wa.me/message/{code[0]}', None) if code else None
        if seg == 'qr':
            return None
        num = seg
    elif host in ('api.whatsapp.com', 'web.whatsapp.com', 'whatsapp.com', 'www.whatsapp.com'):
        if not p.path.rstrip('/').endswith('/send'):
            return None
        num = (_q(url).get('phone') or [''])[0]
    elif host == 'chat.whatsapp.com':
        code = p.path.strip('/').split('/')[0]
        return (f'https://chat.whatsapp.com/{code}', None) if code else None
    elif host == 'wa.link':
        code = p.path.strip('/').split('/')[0]
        return (f'https://wa.link/{code}', None) if code else None
    else:
        return None
    digits = re.sub(r'\D', '', unquote(num or ''))
    if not 7 <= len(digits) <= 15:
        return None
    e164 = to_e164('+' + digits, None)
    return f'https://wa.me/{digits}', e164


LINE_TEXT_RE = re.compile(r'(?:\bLINE\b|ไลน์)\s*(?:ID|OA|official(?: account)?)?\s*[:：]?\s*(@[A-Za-z0-9._-]{3,30})', re.I)


def line_link(url: str):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    path = unquote(p.path)
    if p.scheme.lower() == 'line':
        path = '/' + (p.netloc or '') + path
        host = 'line.me'
    if host == 'lin.ee':
        code = path.strip('/').split('/')[0]
        return f'https://lin.ee/{code}' if code else None
    if host == 'page.line.me':
        code = path.strip('/').split('/')[0]
        return f'https://page.line.me/{code}' if code else None
    if host in ('line.me', 'www.line.me'):
        m = re.search(r'/(?:R/)?(?:ti/p|oaMessage)/([@~][A-Za-z0-9._-]{2,40})', path)
        if m:
            return f'https://line.me/R/ti/p/{m.group(1)}'
    return None


TG_RESERVED = {'share', 'iv', 'addstickers', 'addemoji', 'proxy', 'socks', 'setlanguage', 'login', 'bg', 'confirmphone',
               'addtheme', 'boost', 'contact', 'addlist', 'invoice', 'k', 'z', 'a'}


def telegram_link(url: str):
    p = urlsplit(url)
    host = (p.hostname or '').lower().removeprefix('www.')
    if p.scheme.lower() == 'tg':
        dom = (_q(url).get('domain') or [''])[0]
        return f'https://t.me/{dom.lower()}' if re.fullmatch(r'[A-Za-z0-9_]{4,32}', dom or '') else None
    if host not in ('t.me', 'telegram.me', 'telegram.dog'):
        return None
    segs = [s for s in unquote(p.path).split('/') if s]
    if not segs:
        return None
    if segs[0] == 's' and len(segs) > 1:
        segs = segs[1:]
    first = segs[0]
    if first == 'joinchat' and len(segs) > 1:
        return f'https://t.me/joinchat/{segs[1]}'
    if first.startswith('+') and len(first) > 5:
        return f'https://t.me/{first}'
    if first.lower() in TG_RESERVED or not re.fullmatch(r'[A-Za-z0-9_]{4,32}', first):
        return None
    return f'https://t.me/{first.lower()}'


PLATFORM_HANDLES = {'wix', 'wixcom', 'wordpress', 'wordpressdotcom', 'wordpresscom', 'squarespace', 'shopify',
                    'elegantthemes', 'envato', 'themeforest', 'godaddy', 'hostinger', 'elementor', 'weebly', 'jimdo',
                    'webflow', 'duda', 'booking', 'bookingcom', 'tripadvisor', 'airbnb', 'agoda', 'expedia',
                    'google', 'youtube', 'instagram', 'facebook', 'meta', 'linkedin', 'twitter', 'x', 'tiktok',
                    'whatsapp', 'apple', 'microsoft', 'cloudflare', 'automattic', 'yoast', 'hubspot', 'mailchimp',
                    'canva', 'strikingly', 'hpage', 'ucraft', 'zyro', 'framer', 'siteground', 'bluehost'}
FB_SKIP = {'sharer', 'sharer.php', 'share', 'share.php', 'dialog', 'plugins', 'tr', 'login', 'login.php', 'policies',
           'policy', 'policy.php', 'privacy', 'help', 'legal', 'terms', 'settings', 'watch', 'events', 'groups',
           'hashtag', 'photo.php', 'photo', 'photos', 'story.php', 'permalink.php', 'l.php', 'ads', 'business',
           'people', 'search', 'home.php', 'v2.0', 'v3.0', 'docs', 'marketplace', 'gaming', 'reel', 'reels', 'media',
           'notes', 'video.php', 'messages', 'recover', 'r.php', 'signup', 'campaign', 'about', 'pg', 'profile'}
IG_SKIP = {'p', 'reel', 'reels', 'tv', 'explore', 'accounts', 'about', 'developer', 'legal', 'direct', 'stories', 's',
           'web', 'privacy', 'terms', 'emails', 'challenge', 'oauth', 'embed.js'}
X_SKIP = {'intent', 'share', 'home', 'hashtag', 'search', 'i', 'explore', 'settings', 'privacy', 'tos', 'login', 'signup',
          'widgets.js', 'notifications', 'messages', 'compose', 'account', 'status', 'statuses'}
YT_SKIP = {'watch', 'embed', 'shorts', 'playlist', 'results', 'feed', 'redirect', 'about', 'premium', 'kids',
           'account', 'live', 'iframe_api', 'yts', 'howyoutubeworks', 'creators', 't', 'signin', 'sw.js', 'player_api'}
SOCIALS = ('facebook', 'instagram', 'linkedin', 'x', 'youtube', 'tiktok')


def _host_is(host: str, *domains) -> bool:
    return any(host == d or host.endswith('.' + d) for d in domains)


def social_link(url: str):
    """(platform, normalised company URL, handle) or None. Share/intent/plugin links and
    personal LinkedIn profiles are rejected."""
    p = urlsplit(url)
    if p.scheme.lower() not in ('http', 'https'):
        return None
    host = (p.hostname or '').lower()
    segs = [s for s in unquote(p.path).split('/') if s]
    if _host_is(host, 'facebook.com', 'fb.com', 'fb.me') and not host.startswith(('developers.', 'l.', 'lm.')):
        if _host_is(host, 'fb.me'):
            return ('facebook', f'https://fb.me/{segs[0]}', segs[0].lower()) if segs else None
        if not segs:
            return None
        first = segs[0]
        if first == 'profile.php':
            pid = (_q(url).get('id') or [''])[0]
            return ('facebook', f'https://www.facebook.com/profile.php?id={pid}', pid) if pid.isdigit() else None
        if first == 'pg' and len(segs) >= 2:
            first = segs[1]
        elif first == 'pages' and len(segs) >= 2:
            return 'facebook', 'https://www.facebook.com/' + '/'.join(segs[:3]), segs[1].lower()
        if first.lower() in FB_SKIP or not re.fullmatch(r'[A-Za-z0-9.\-]{2,80}', first):
            return None
        return 'facebook', f'https://www.facebook.com/{first}', first.lower()
    if _host_is(host, 'instagram.com', 'instagr.am'):
        if not segs or segs[0].lower() in IG_SKIP or not re.fullmatch(r'[A-Za-z0-9._]{1,30}', segs[0]):
            return None
        h = segs[0].lower()
        return 'instagram', f'https://www.instagram.com/{h}/', h
    if _host_is(host, 'linkedin.com'):
        if len(segs) >= 2 and segs[0].lower() in ('company', 'school', 'showcase'):
            slug = segs[1]
            return 'linkedin', f'https://www.linkedin.com/{segs[0].lower()}/{slug}/', slug.lower()
        return None  # /in/ (people), /pub/, shareArticle, feed ...
    if host in ('twitter.com', 'www.twitter.com', 'mobile.twitter.com', 'x.com', 'www.x.com', 'mobile.x.com'):
        if not segs or segs[0].lower() in X_SKIP or not re.fullmatch(r'[A-Za-z0-9_]{1,15}', segs[0]):
            return None
        if len(segs) >= 2 and segs[1].lower() in ('status', 'statuses'):
            pass  # a tweet: the account is still segs[0]
        h = segs[0]
        return 'x', f'https://x.com/{h}', h.lower()
    if _host_is(host, 'youtube.com'):
        if not segs:
            return None
        first = segs[0]
        if first.startswith('@') and len(first) > 1:
            return 'youtube', f'https://www.youtube.com/{first}', first[1:].lower()
        if first in ('channel', 'c', 'user') and len(segs) >= 2:
            return 'youtube', f'https://www.youtube.com/{first}/{segs[1]}', segs[1].lower()
        return None
    if _host_is(host, 'tiktok.com'):
        if segs and segs[0].startswith('@') and len(segs[0]) > 1:
            h = segs[0][1:]
            return 'tiktok', f'https://www.tiktok.com/@{h}', h.lower()
        return None
    return None


# ------------------------------------------------------------------ contact pages

CONTACT_KEYS = ('contact', 'kontakt', 'contacto', 'contato', 'contatti', 'contactez', 'nous-contacter', 'get-in-touch',
                'getintouch', 'reach-us', 'find-us', 'enquir', 'inquir', 'lien-he', 'lienhe', 'hubungi', 'kontak',
                'ติดต่อ', 'お問い合わせ', 'otoiawase', '联系', '聯絡', '聯繫', '문의', 'контакт', 'связаться')
LEGAL_EXACT = {'legal', 'legal-notice', 'legal_notice', 'legalnotice', 'legal-information', 'mentions-legales',
               'mentions-légales', 'aviso-legal', 'colophon', 'impressum', 'imprint'}
LEGAL_PREFIX = ('impressum', 'imprint')
ABOUT_PREFIX = ('about', 'who-we-are', 'ueber-uns', 'uber-uns', 'über-uns', 'a-propos', 'quienes-somos', 'sobre-nos',
                'chi-siamo', 'gioi-thieu', 'tentang', 'เกี่ยวกับ', '会社概要', '关于', '關於', 'о-нас', 'o-nas',
                'o-kompanii')
ABOUT_EXACT = {'team', 'our-team', 'the-team', 'meet-the-team', 'meet-our-team', 'company', 'our-company',
               'company-profile', 'unternehmen', 'our-story'}
TEXT_CONTACT = ('contact', 'kontakt', 'get in touch', 'reach us', 'find us', 'enquir', 'inquir', 'ติดต่อ', 'お問い合わせ',
                '联系', 'контакт', 'liên hệ', 'hubungi')
TEXT_LEGAL = ('imprint', 'impressum', 'legal notice', 'mentions légales', 'aviso legal')
TEXT_ABOUT = {'about', 'about us', 'about the company', 'our team', 'the team', 'team', 'meet the team', 'company',
              'our company', 'who we are', 'our story', 'เกี่ยวกับเรา', 'über uns', 'à propos', 'о нас', 'o nas'}
PAGE_SKIP = re.compile(r'privacy|cookie|terms|polic|login|signin|sign-in|register|cart|checkout|wp-admin|wp-login|'
                       r'/feed|/tag/|/category/|/author/|replytocom|/comment|/challenge|captcha', re.I)
FILE_EXT = re.compile(r'\.(pdf|jpe?g|png|gif|svg|webp|zip|gz|rar|mp4|mp3|xml|css|js|docx?|xlsx?|pptx?|ics|vcf)$', re.I)


def page_kind(url: str, text: str = '') -> tuple | None:
    """('contact'|'legal'|'about', score) when the link looks like a contact-type page.
    Looks at the last path segment and at short anchor texts only (not at long titles)."""
    segs = [x for x in unquote(urlsplit(url).path).lower().split('/') if x]
    seg = re.sub(r'\.(html?|php|aspx?|jsp)$', '', segs[-1]) if segs else ''
    if seg:
        if any(k in seg for k in CONTACT_KEYS):
            return 'contact', 3
        if seg in LEGAL_EXACT or seg.startswith(LEGAL_PREFIX):
            return 'legal', 2
        if seg.startswith(ABOUT_PREFIX) or seg in ABOUT_EXACT:
            return 'about', 1
    t = re.sub(r'\s+', ' ', (text or '').strip().lower())
    if t and len(t) <= 30:
        if any(k in t for k in TEXT_CONTACT):
            return 'contact', 3
        if any(k in t for k in TEXT_LEGAL):
            return 'legal', 2
        if t in TEXT_ABOUT:
            return 'about', 1
    return None


def select_contact_pages(links, site_domains, start_url: str, limit: int):
    """Choose up to `limit` same-site contact/legal/about pages from (url, anchor text) links.
    Returns [(url, kind)] best first; language duplicates (/en/contact, /th/contact) count once."""
    if limit <= 0:
        return []
    start_norm = _norm_url(start_url)
    start_host = (urlsplit(start_url).hostname or '').removeprefix('www.')
    cands = {}
    for order, (url, text) in enumerate(links):
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not on_domain(p.hostname or '', site_domains):
            continue
        if FILE_EXT.search(p.path) or PAGE_SKIP.search(p.path + '?' + p.query):
            continue
        n = _norm_url(url)
        if n == start_norm or (p.path in ('', '/') and not p.query):
            continue
        k = page_kind(url, text)
        if not k:
            continue
        kind, score = k
        other_host = (p.hostname or '').removeprefix('www.') != start_host
        if n not in cands or cands[n][0] < score:
            cands[n] = (score, other_host, order, urldefrag(url)[0], kind)
    ranked = sorted(cands.values(), key=lambda c: (-c[0], c[1], len(urlsplit(c[3]).path), c[2]))
    out, slugs = [], set()
    for score, _, _, url, kind in ranked:
        slug = unquote(urlsplit(url).path).rstrip('/').rsplit('/', 1)[-1].lower()
        if slug in slugs:
            continue
        slugs.add(slug)
        out.append((url, kind))
        if len(out) >= limit:
            break
    return out


def _norm_url(url: str) -> str:
    """Comparable form: no scheme, no www., no trailing slash, no fragment."""
    u = urldefrag(url)[0]
    p = urlsplit(u)
    return f'{(p.hostname or "").removeprefix("www.")}{p.path.rstrip("/")}?{p.query}'


# ------------------------------------------------------------------ page parsing

@dataclass
class Page:
    url: str
    kind: str = 'home'
    lang: str | None = None
    links: list = field(default_factory=list)          # [(abs url, anchor text)]
    emails: list = field(default_factory=list)         # raw candidates, mailto first
    tel: list = field(default_factory=list)            # cleaned tel: values
    whatsapp: list = field(default_factory=list)       # [(link, e164|None)]
    line: list = field(default_factory=list)
    telegram: list = field(default_factory=list)
    socials: list = field(default_factory=list)        # [(platform, url, handle, source)]


def _walk_jsonld(node, emails, same_as, skip=False):
    if isinstance(node, list):
        for n in node:
            _walk_jsonld(n, emails, same_as, skip)
        return
    if not isinstance(node, dict):
        return
    t = node.get('@type')
    types = {str(x).rsplit('/', 1)[-1].lower() for x in (t if isinstance(t, list) else [t]) if x}
    person = skip or bool(types & {'person', 'profilepage', 'author'})
    if not person:
        e = node.get('email')
        for v in (e if isinstance(e, list) else [e]):
            if isinstance(v, str):
                emails.append(v.replace('mailto:', '').strip())
        s = node.get('sameAs')
        for v in (s if isinstance(s, list) else [s]):
            if isinstance(v, str):
                same_as.append(v.strip())
    for k, v in node.items():
        if isinstance(v, (dict, list)) and k not in ('@context',):
            # anything below an author/employee/founder/person node is about people: skip it
            child_skip = person or k.lower() in ('author', 'employee', 'employees', 'founder', 'founders', 'member',
                                                  'members', 'creator', 'editor', 'contributor', 'reviewedby',
                                                  'accountableperson', 'alumni', 'director', 'ceo')
            _walk_jsonld(v, emails, same_as, child_skip)


def parse_page(html, url: str, kind: str = 'home', encoding: str | None = None) -> Page:
    """Extract raw contact candidates from one HTML page (bytes or str)."""
    if isinstance(html, bytes):
        soup = BeautifulSoup(html, 'lxml', from_encoding=encoding)
    else:
        soup = BeautifulSoup(html, 'lxml')
    pg = Page(url=url, kind=kind)
    html_tag = soup.find('html')
    pg.lang = (html_tag.get('lang') or '').strip() or None if html_tag else None
    base = url
    b = soup.find('base', href=True)
    if b:
        base = urljoin(url, b['href'].strip())

    mail_seen = []
    for a in soup.find_all(['a', 'area', 'link'], href=True):
        href = a['href'].strip()
        if not href or href.startswith('#') or href.lower().startswith(('javascript:', 'data:')):
            continue
        low = href.lower()
        if low.startswith('mailto:'):
            addrs = unquote(href[7:].split('?', 1)[0])
            for addr in re.split(r'[,;]', addrs):
                if addr.strip():
                    mail_seen.append(addr.strip())
            continue
        if low.startswith(('tel:', 'callto:')):
            c = clean_tel(href)
            if c:
                pg.tel.append(c)
            continue
        absu = urljoin(base, href)
        if a.name == 'a':
            pg.links.append((absu, a.get_text(' ', strip=True)[:80]))
        wa = whatsapp_link(absu)
        if wa:
            pg.whatsapp.append(wa)
            continue
        ln = line_link(absu)
        if ln:
            pg.line.append(ln)
            continue
        tg = telegram_link(absu)
        if tg:
            pg.telegram.append(tg)
            continue
        so = social_link(absu)
        if so:
            pg.socials.append((*so, 'link'))

    # JSON-LD (Organization / LocalBusiness ...): email + sameAs, never Person nodes
    jl_emails, same_as = [], []
    for s in soup.find_all('script', type=lambda v: v and 'ld+json' in v.lower()):
        txt = (s.string or s.get_text() or '').strip()
        if not txt:
            continue
        try:
            _walk_jsonld(json.loads(txt), jl_emails, same_as)
        except ValueError:
            continue
    for u in same_as:
        so = social_link(u)
        if so:
            pg.socials.append((*so, 'schema.org sameAs'))
        for fn, bucket in ((line_link, pg.line), (telegram_link, pg.telegram)):
            v = fn(u)
            if v:
                bucket.append(v)

    # Plain addresses in the page source (visible text, attributes, inline JSON). Deliberately
    # hidden ones ([at], Cloudflare email protection) do not match and are not decoded.
    raw = str(soup)
    text_emails = EMAIL_RE.findall(raw)
    pg.emails = mail_seen + jl_emails + text_emails

    body = soup.find('body') or soup
    visible = body.get_text(' ', strip=True)
    for m in LINE_TEXT_RE.finditer(visible):
        pg.line.append(f'https://line.me/R/ti/p/{m.group(1)}')
    return pg


# ------------------------------------------------------------------ merge

def _uniq(seq):
    return list(dict.fromkeys(x for x in seq if x))


def _alnum(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def pick_social(cands, labels, parts=()):
    """cands: [(url, handle, page_index)] -> best URL.
    Order: handle matches the full domain label > matches a part of it > found on the home page > frequency."""
    if not cands:
        return None
    stats = {}
    for i, (url, handle, page_idx) in enumerate(cands):
        s = stats.setdefault(url, {'n': 0, 'first': i, 'home': False, 'handle': _alnum(handle)})
        s['n'] += 1
        s['home'] = s['home'] or page_idx == 0

    def score(item):
        _, s = item
        h = s['handle']
        full = any(lb and (lb in h or (len(h) >= 4 and h in lb)) for lb in labels)
        part = any(pt and len(pt) >= 4 and pt in h for pt in parts)
        return (full, part, s['home'], s['n'], -s['first'])
    return max(stats.items(), key=score)[0]


PEOPLE_KINDS = {'about'}  # about/team pages: emails only, no phones/messengers/socials (staff profiles live there)
STOP_PARTS = {'the', 'and', 'www', 'com', 'net', 'org', 'hotel', 'hotels', 'resort', 'resorts', 'villa', 'villas',
              'samui', 'kohsamui', 'phuket', 'bangkok', 'thailand', 'thai', 'beach', 'group', 'official'}


def detect_region(pages) -> str | None:
    """Country for national-format numbers: ccTLD, else the country of the site's own
    international numbers, else a single-country page language (th, vi, id, ja, ko)."""
    for pg in pages:
        r = region_from_tld(host_of(pg.url))
        if r:
            return r
    for pg in pages:
        intl = [t for t in pg.tel if t.startswith('+')] + [n for _, n in pg.whatsapp if n]
        for t in intl:
            try:
                r = phonenumbers.region_code_for_number(phonenumbers.parse(t, None))
            except phonenumbers.NumberParseException:
                continue
            if r and r != 'ZZ':
                return r
    for pg in pages:
        r = region_from_lang(pg.lang)
        if r:
            return r
    return None


def merge(pages, site_domains, include_phones=True, same_domain_emails_only=True):
    """Combine parsed pages (home first) into the output fields."""
    site_domains = _uniq(site_domains)
    labels = {_alnum(site_label(d)) for d in site_domains}
    parts = {p for p in brand_tokens(site_domains) if p not in STOP_PARTS}
    emails, skipped = [], {}
    for pg in pages:
        for e in pg.emails:
            kept, why = classify_email(e, site_domains, same_domain_emails_only)
            if kept:
                emails.append(kept)
            elif why and why != 'not an email':
                skipped[why] = skipped.get(why, 0) + 1
    trusted = [pg for pg in pages if pg.kind not in PEOPLE_KINDS]

    phones, whatsapp = [], []
    if include_phones:
        region = detect_region(trusted)
        for pg in trusted:
            for t in pg.tel:
                phones.append(to_e164(t, region) or t)
            for link, num in pg.whatsapp:
                whatsapp.append(link)
                if num:
                    phones.append(num)
    by_platform = {k: [] for k in SOCIALS}
    for idx, pg in enumerate(pages):
        for platform, url, handle, source in pg.socials:
            if _alnum(handle) in PLATFORM_HANDLES:
                continue
            if pg.kind in PEOPLE_KINDS and source != 'schema.org sameAs':
                continue
            by_platform[platform].append((url, handle, idx))
    out = {
        'emails': _uniq(emails)[:25],
        'phones': _uniq(phones)[:15],
        'whatsapp': _uniq(whatsapp)[:10],
        'line': _uniq(x for pg in trusted for x in pg.line)[:10],
        'telegram': _uniq(x for pg in trusted for x in pg.telegram)[:10],
    }
    for k in SOCIALS:
        out[k] = pick_social(by_platform[k], labels, parts)
    out['emailsSkipped'] = skipped
    return out


def has_contacts(row: dict) -> bool:
    return any(row.get(k) for k in ('emails', 'phones', 'whatsapp', 'line', 'telegram', *SOCIALS))
