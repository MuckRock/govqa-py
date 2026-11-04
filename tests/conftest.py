import pytest

from govqa import GovQA
from tests.pages import BASE, DOMAIN, page


def mock_home(requests_mock):
    requests_mock.get(BASE, status_code=302, headers={"Location": f"{BASE}SupportHome.aspx"})
    requests_mock.get(f"{BASE}SupportHome.aspx", text=page())


@pytest.fixture
def make_client(requests_mock):
    def make(domain=DOMAIN, **kwargs):
        mock_home(requests_mock)
        # No retries or throttling, so failures surface immediately.
        kwargs.setdefault("retry_attempts", 0)
        kwargs.setdefault("requests_per_minute", 0)
        return GovQA(domain, **kwargs)

    return make


@pytest.fixture
def client(make_client):
    return make_client()
