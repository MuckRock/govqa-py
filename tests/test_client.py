from urllib.parse import parse_qs

import lxml.html
import pytest
import scrapelib

from govqa import GovQA, UnauthenticatedError, UnsupportedSite
from tests.pages import BASE, DOMAIN, page, secrets


def test_connects_when_site_redirects_to_support_home(client):
    assert client.domain == DOMAIN


def test_strips_trailing_slash_from_domain(make_client):
    gq = make_client(domain=DOMAIN + "/")
    assert gq.url_from_endpoint("Login.aspx") == f"{BASE}Login.aspx"


def test_raises_unsupported_site_when_not_redirected_to_support_home(requests_mock):
    requests_mock.get(BASE, text="<html>Some other site</html>")

    with pytest.raises(UnsupportedSite):
        GovQA(DOMAIN, retry_attempts=0, requests_per_minute=0)


def test_builds_endpoint_urls_under_webapp_rs(client):
    assert client.url_from_endpoint("Login.aspx") == f"{BASE}Login.aspx"


def test_sends_browser_user_agent(client, requests_mock):
    requests_mock.get(f"{BASE}Anything.aspx", text=page())
    client.get(f"{BASE}Anything.aspx")
    assert "Firefox" in requests_mock.last_request.headers["User-Agent"]


@pytest.mark.parametrize(
    "text,status",
    [
        ("There was a problem serving the requested page", 500),
        ("Page Temporarily Unavailable", 503),
    ],
)
def test_turns_govqa_error_pages_into_http_errors(client, requests_mock, text, status):
    requests_mock.get(f"{BASE}Broken.aspx", text=f"<html>{text}</html>")

    with pytest.raises(scrapelib.HTTPError) as excinfo:
        client.get(f"{BASE}Broken.aspx")

    assert excinfo.value.response.status_code == status


def test_collects_aspnet_hidden_state(client):
    tree = lxml.html.fromstring(page(secrets()))

    assert client._secrets(tree, None) == {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": "vs0",
        "__RequestVerificationToken": "token",
        "__VIEWSTATEGENERATOR": "gen",
        "__VIEWSTATEENCRYPTED": "",
    }


def test_collects_viewstate_split_across_multiple_fields(client):
    tree = lxml.html.fromstring(page(secrets(["vs0", "vs1", "vs2"])))

    payload = client._secrets(tree, None)

    assert payload["__VIEWSTATE"] == "vs0"
    assert payload["__VIEWSTATE1"] == "vs1"
    assert payload["__VIEWSTATE2"] == "vs2"
    assert payload["__VIEWSTATEFIELDCOUNT"] == "3"


def test_login_posts_credentials_with_hidden_state(client, requests_mock):
    requests_mock.get(f"{BASE}Login.aspx", text=page(secrets(), logged_in=False))
    requests_mock.post(f"{BASE}Login.aspx", text=page())

    client.login("user@example.com", "hunter2")

    sent = parse_qs(requests_mock.last_request.text)
    assert sent["ASPxFormLayout1$txtUsername"] == ["user@example.com"]
    assert sent["ASPxFormLayout1$txtPassword"] == ["hunter2"]
    assert sent["ASPxFormLayout1$btnLogin"] == ["Submit"]
    assert sent["__VIEWSTATE"] == ["vs0"]
    assert sent["__RequestVerificationToken"] == ["token"]


def test_login_raises_when_site_does_not_identify_user(client, requests_mock):
    requests_mock.get(f"{BASE}Login.aspx", text=page(secrets(), logged_in=False))
    requests_mock.post(f"{BASE}Login.aspx", text=page(logged_in=False))

    with pytest.raises(UnauthenticatedError, match="check your username and password"):
        client.login("user@example.com", "wrong")


def test_authenticated_methods_raise_when_logged_out(client, requests_mock):
    requests_mock.get(f"{BASE}CustomerIssues.aspx", text=page(logged_in=False))

    with pytest.raises(UnauthenticatedError):
        client.list_requests()


def test_skips_login_check_when_disabled(make_client, requests_mock):
    gq = make_client(check_login=False)
    requests_mock.get(f"{BASE}CustomerIssues.aspx", text="<html><body></body></html>")

    assert gq.list_requests() == []
