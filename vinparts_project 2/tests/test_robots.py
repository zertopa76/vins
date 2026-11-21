from vinparts.robots import RobotsRules

UA = "VinPartsHelper/0.1.0 (personal workshop tool; rate-limited)"


def test_documentation_pages_allowed_for_generic_client(robots_text):
    rules = RobotsRules.from_text(robots_text)
    assert rules.is_allowed(UA, "/")
    assert rules.is_allowed(UA, "/vw_golf7_5g.html")
    assert rules.is_allowed(UA, "/petrol-engine-vw-audi-skoda-repair-manual.html")


def test_service_paths_disallowed_with_wildcards(robots_text):
    rules = RobotsRules.from_text(robots_text)
    assert not rules.is_allowed(UA, "/forum/search/")
    assert not rules.is_allowed(UA, "/site-search.html")          # /*search.html
    assert not rules.is_allowed(UA, "/forum/members/42")          # /*members/
    assert not rules.is_allowed(UA, "/forum/index.php?act=Search")  # /*index.php?act=Search


def test_named_bots_fully_disallowed(robots_text):
    rules = RobotsRules.from_text(robots_text)
    for agent in ("GPTBot/1.0", "ClaudeBot", "Mozilla/5.0 (compatible; Bytespider)"):
        assert not rules.is_allowed(agent, "/vw_golf7_5g.html"), agent
    # В файле записано «Linux Wget» (с пробелом); настоящий User-Agent «Wget/1.x» под эту запись
    # по стандарту не подпадает, поэтому для него действует общая группа «*».
    assert rules.is_allowed("Wget/1.21 (linux-gnu)", "/vw_golf7_5g.html")


def test_yandex_shares_group_with_star(robots_text):
    rules = RobotsRules.from_text(robots_text)
    assert rules.is_allowed("Mozilla/5.0 (compatible; YandexBot/3.0)", "/vw_golf7_5g.html")
    assert not rules.is_allowed("Mozilla/5.0 (compatible; YandexBot/3.0)", "/forum/search/")


def test_longest_match_and_allow_wins_on_tie():
    rules = RobotsRules.from_text("User-agent: *\nDisallow: /a/\nAllow: /a/public\n")
    assert not rules.is_allowed("x", "/a/secret")
    assert rules.is_allowed("x", "/a/public/page")
    tie = RobotsRules.from_text("User-agent: *\nDisallow: /p\nAllow: /p\n")
    assert tie.is_allowed("x", "/p")


def test_end_anchor_and_empty_disallow():
    rules = RobotsRules.from_text("User-agent: *\nDisallow: /*.pdf$\n")
    assert not rules.is_allowed("x", "/docs/a.pdf")
    assert rules.is_allowed("x", "/docs/a.pdf?x=1")
    assert RobotsRules.from_text("User-agent: *\nDisallow:\n").is_allowed("x", "/anything")


def test_modes():
    assert RobotsRules.allow_all().is_allowed("x", "/y")
    assert not RobotsRules.disallow_all().is_allowed("x", "/y")
