
from urllib.parse import urlparse

from app.collector import robots_allows


class FakeResponse:
    def __init__(self, status_code=200, text="User-agent: *\nAllow: /\n"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.headers = {}

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return self.response
        return FakeResponse()


def test_robots_allows_public_page():
    session = FakeSession()
    assert robots_allows("https://example.com/opportunities", session) is True


def test_robots_blocks_disallowed_page():
    response = FakeResponse(
        text="User-agent: *\nDisallow: /opportunities\n"
    )
    session = FakeSession(response)
    assert robots_allows("https://example.com/opportunities", session) is False

def test_redirect_is_blocked():
    class RedirectSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            if url.endswith("/robots.txt"):
                return FakeResponse()
            return FakeResponse(status_code=302)

    from app.collector import fetch_url

    result = fetch_url(
        "https://example.com/opportunities",
        retries=0,
        session=RedirectSession(),
    )

    assert result.status == "blocked"
    assert "Redirect" in result.error
def test_robots_redirect_is_not_allowed():
    class RedirectRobotsSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            if url.endswith("/robots.txt"):
                return FakeResponse(status_code=302)
            return FakeResponse()

    from app.collector import robots_allows

    session = RedirectRobotsSession()

    result = robots_allows(
        "https://example.com/opportunities",
        session,
    )

    assert result is None