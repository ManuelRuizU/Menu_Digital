"""BEHIND_PROXY=1: behind nginx, the rate limits see each customer's real IP (the last
X-Forwarded-For hop, the one nginx appended); without it, the header is ignored."""
import pytest

from app import create_app

LOGIN_LIMIT = 10  # @limiter.limit('10 per minute') on /login


def _app(tmp_path, behind_proxy):
    return create_app({
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "proxy.db"}', 'TESTING': True,
        'WTF_CSRF_ENABLED': False, 'SESSION_COOKIE_SECURE': False, 'SECRET_KEY': 'test',
        'BEHIND_PROXY': behind_proxy,
    })


def _login_from(client, forwarded_for):
    return client.get('/login', headers={'X-Forwarded-For': forwarded_for}).status_code


def test_behind_proxy_each_ip_has_its_own_limit(tmp_path):
    client = _app(tmp_path, behind_proxy=True).test_client()
    assert [_login_from(client, '203.0.113.7') for _ in range(LOGIN_LIMIT)] == [200] * LOGIN_LIMIT
    assert _login_from(client, '203.0.113.7') == 429
    # Another customer is not blocked by the first one's attempts.
    assert _login_from(client, '198.51.100.9') == 200


def test_behind_proxy_a_spoofed_first_hop_does_not_dodge_the_limit(tmp_path):
    # nginx appends the real IP last ($proxy_add_x_forwarded_for); a browser can only add
    # fake ones in front, which x_for=1 never reads.
    client = _app(tmp_path, behind_proxy=True).test_client()
    for n in range(LOGIN_LIMIT):
        assert _login_from(client, f'10.0.0.{n}, 203.0.113.7') == 200
    assert _login_from(client, '10.0.0.99, 203.0.113.7') == 429


def test_without_proxy_the_header_is_ignored(tmp_path):
    client = _app(tmp_path, behind_proxy=False).test_client()
    for _ in range(LOGIN_LIMIT):
        assert _login_from(client, '203.0.113.7') == 200
    # Everyone is the same remote address (the test client's), whatever the header says.
    assert _login_from(client, '198.51.100.9') == 429


@pytest.mark.parametrize('behind_proxy, expected', [(True, '203.0.113.7'), (False, '127.0.0.1')])
def test_limiter_key_is_the_address_proxyfix_resolved(tmp_path, behind_proxy, expected):
    from flask_limiter.util import get_remote_address
    application = _app(tmp_path, behind_proxy)

    @application.route('/_ip')
    def _ip():
        return get_remote_address()

    response = application.test_client().get('/_ip', headers={'X-Forwarded-For': '203.0.113.7'})
    assert response.get_data(as_text=True) == expected
