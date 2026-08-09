"""Proxy URL helpers."""

from scalping.exchanges.proxy import choose_proxy, parse_proxy_list, proxy_log_label


def test_parse_proxy_list_comma_and_newline():
    assert parse_proxy_list("http://a:1@h:80, http://b:2@h:81") == [
        "http://a:1@h:80",
        "http://b:2@h:81",
    ]
    assert parse_proxy_list("http://a:1@h:80\nhttp://b:2@h:81") == [
        "http://a:1@h:80",
        "http://b:2@h:81",
    ]


def test_choose_proxy_sticky_stable():
    proxies = [f"http://u:p@h:{i}" for i in range(5)]
    a = choose_proxy(proxies, sticky="scalping-run")
    b = choose_proxy(proxies, sticky="scalping-run")
    assert a == b
    assert a in proxies


def test_proxy_log_label_strips_secrets():
    assert proxy_log_label("http://user:secret@p.webshare.io:80") == "p.webshare.io:80"
