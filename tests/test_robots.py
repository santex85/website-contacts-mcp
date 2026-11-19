import robots as R

TOKEN = 'WebsiteContactsBot'


def test_wildcards_and_longest_match():
    rb = R.parse("""
User-agent: *
Disallow: /private
Disallow: /*?sessionid=
Disallow: /*.pdf$
Allow: /private/contact
""", TOKEN)
    assert rb.can_fetch('https://x.test/contact')
    assert not rb.can_fetch('https://x.test/private/team')
    assert rb.can_fetch('https://x.test/private/contact')  # longer Allow wins
    assert not rb.can_fetch('https://x.test/page?sessionid=1')
    assert not rb.can_fetch('https://x.test/files/a.pdf')
    assert rb.can_fetch('https://x.test/files/a.pdf?x=1')  # $ anchors the end
    assert rb.can_fetch('https://x.test/robots.txt')


def test_specific_group_beats_star():
    rb = R.parse("""
User-agent: *
Disallow: /

User-agent: websitecontactsbot
Disallow: /admin
Crawl-delay: 4
""", TOKEN)
    assert rb.can_fetch('https://x.test/contact')
    assert not rb.can_fetch('https://x.test/admin/x')
    assert rb.crawl_delay == 4.0


def test_disallow_all_for_star():
    rb = R.parse('User-agent: *\nDisallow: /\n', TOKEN)
    assert not rb.can_fetch('https://x.test/')
    assert not rb.can_fetch('https://x.test/contact')


def test_grouped_agents_and_empty_disallow():
    rb = R.parse('User-agent: foo\nUser-agent: *\nDisallow:\n', TOKEN)
    assert rb.can_fetch('https://x.test/anything')


def test_tie_goes_to_allow():
    rb = R.parse('User-agent: *\nDisallow: /page\nAllow: /page\n', TOKEN)
    assert rb.can_fetch('https://x.test/page')


def test_percent_encoded_paths():
    rb = R.parse('User-agent: *\nDisallow: /ติดต่อ\n', TOKEN)
    assert not rb.can_fetch('https://x.test/%E0%B8%95%E0%B8%B4%E0%B8%94%E0%B8%95%E0%B9%88%E0%B8%AD')


def test_status_handling():
    assert R.from_status(404, None, TOKEN).can_fetch('https://x.test/a')
    assert not R.from_status(403, None, TOKEN).can_fetch('https://x.test/a')
    assert not R.from_status(503, None, TOKEN).can_fetch('https://x.test/a')
    assert not R.from_status(None, None, TOKEN).can_fetch('https://x.test/a')
    assert R.from_status(200, '', TOKEN).can_fetch('https://x.test/a')
