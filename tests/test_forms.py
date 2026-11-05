from urllib.parse import parse_qs

import jsonschema
import pytest
import scrapelib

from govqa import (
    EmailAlreadyExists,
    FormValidationError,
    IncorrectCaptcha,
    UnauthenticatedError,
)
from tests import pages
from tests.pages import BASE, DOMAIN

REQ = "requestFormLayout"
CUST = "customerInfo$CustomerFormLayout"
REQUEST_URL = f"{BASE}RequestOpen.aspx?rqst=1"
ACCOUNT_URL = f"{BASE}CustomerDetails.aspx"


def request_form_page(captcha=False, extra=""):
    return pages.page(
        pages.secrets(),
        pages.text_field(REQ, "txtName", "Name"),
        pages.text_field(REQ, "txtNickname", "Nickname", required=False),
        pages.textarea_field(REQ, "txtDescription", "Description"),
        pages.radio_field(REQ, "rblDelivery", "Delivery", ["Electronic", "Paper"]),
        pages.combo_field(REQ, "cbState", "State", ["IL", "NY"]),
        pages.captcha("requestopen", "reqstopencaptcha") if captcha else "",
        extra,
    )


def mock_captcha_files(requests_mock):
    requests_mock.get(
        f"{DOMAIN}/captcha.jpg",
        [{"content": b"first-jpeg"}, {"content": b"second-jpeg"}],
    )
    requests_mock.get(f"{DOMAIN}/captcha.wav", content=b"wav")


@pytest.fixture
def request_form(client, requests_mock):
    requests_mock.get(REQUEST_URL, text=request_form_page())
    return client.request_form()


VALID_REQUEST = {
    "name": "Ada Lovelace",
    "description": "All emails about engines",
    "delivery": "Paper",
    "state": "IL",
}


def sent_form(requests_mock):
    """Fields of the most recent POST, which may be followed by captcha or redirect GETs."""
    *_, post = (r for r in requests_mock.request_history if r.method == "POST")
    return {k: v[0] for k, v in parse_qs(post.text).items()}


def test_request_form_schema_lists_only_required_fields(request_form):
    assert request_form.schema == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "delivery": {"type": "string", "enum": ["Electronic", "Paper"]},
            "state": {"type": "string", "enum": ["IL", "NY"]},
        },
        "required": ["name", "description", "delivery", "state"],
        "additionalProperties": False,
    }


def test_request_form_without_captcha_has_empty_captcha(request_form):
    assert request_form.captcha == {}


def test_request_form_requires_login(client, requests_mock):
    requests_mock.get(REQUEST_URL, text=pages.page(logged_in=False))

    with pytest.raises(UnauthenticatedError):
        client.request_form()


def test_request_form_uses_requested_request_type(client, requests_mock):
    requests_mock.get(f"{BASE}RequestOpen.aspx?rqst=2", text=request_form_page())

    form = client.request_form(request_type=2)

    assert form.request_url == f"{BASE}RequestOpen.aspx?rqst=2"


def test_request_form_with_captcha_requires_captcha_answer(client, requests_mock):
    requests_mock.get(REQUEST_URL, text=request_form_page(captcha=True))
    mock_captcha_files(requests_mock)

    form = client.request_form()

    assert form.captcha["jpeg"].read() == b"first-jpeg"
    assert form.captcha["wav"].read() == b"wav"
    assert form.schema["properties"]["captcha"] == {
        "type": "string",
        "pattern": "^[A-Z0-9]{4,6}$",
    }
    assert "captcha" in form.schema["required"]


def test_request_submit_returns_reference_number(request_form, requests_mock):
    requests_mock.post(
        REQUEST_URL,
        text=pages.page(
            '<span id="ConfirmFormLayout_roReferenceNo">R000999-010123</span>'
        ),
    )

    assert request_form.submit(VALID_REQUEST) == "R000999-010123"


def test_request_submit_posts_filled_fields_and_hidden_state(
    request_form, requests_mock
):
    requests_mock.post(
        REQUEST_URL,
        text=pages.page('<span id="ConfirmFormLayout_roReferenceNo">R1</span>'),
    )

    request_form.submit(VALID_REQUEST)

    sent = sent_form(requests_mock)
    assert sent[f"{REQ}$txtName"] == "Ada Lovelace"
    assert sent[f"{REQ}$txtDescription"] == "All emails about engines"
    assert sent[f"{REQ}$rblDelivery"] == "1"
    assert sent[f"{REQ}$rblDelivery$RB1"] == "C"
    assert sent[f"{REQ}$rblDelivery$RB0"] == "U"
    assert sent[f"{REQ}$cbState"] == "IL"
    assert sent[f"{REQ}$cbState$VI"] == "IL"
    assert sent[f"{REQ}$txtNickname$State"] == '{"validationState":""}'
    assert sent["__EVENTTARGET"] == "btnSaveData"
    assert sent["__VIEWSTATE"] == "vs0"


@pytest.mark.parametrize(
    "bad_input",
    [
        {k: v for k, v in VALID_REQUEST.items() if k != "name"},
        {**VALID_REQUEST, "delivery": "Carrier pigeon"},
        {**VALID_REQUEST, "unexpected": "field"},
    ],
    ids=["missing-field", "invalid-option", "extra-field"],
)
def test_request_submit_validates_against_schema_before_posting(
    request_form, requests_mock, bad_input
):
    post = requests_mock.post(REQUEST_URL, text=pages.page())

    with pytest.raises(jsonschema.ValidationError):
        request_form.submit(bad_input)

    assert not post.called


def test_request_submit_raises_site_validation_error(request_form, requests_mock):
    requests_mock.post(
        REQUEST_URL,
        text=pages.page(pages.secrets(), pages.form_errors("Description is too long")),
    )

    with pytest.raises(FormValidationError, match="Description is too long"):
        request_form.submit(VALID_REQUEST)


def test_request_submit_raises_when_page_has_no_reference_or_errors(
    request_form, requests_mock
):
    requests_mock.post(REQUEST_URL, text=pages.page(pages.secrets()))

    with pytest.raises(FormValidationError, match="unknown reason"):
        request_form.submit(VALID_REQUEST)


def test_request_submit_with_wrong_captcha_refreshes_captcha_and_state(
    client, requests_mock
):
    requests_mock.get(REQUEST_URL, text=request_form_page(captcha=True))
    mock_captcha_files(requests_mock)
    form = client.request_form()
    requests_mock.post(
        REQUEST_URL,
        text=pages.page(
            pages.secrets(["new-vs"]),
            pages.captcha("requestopen", "reqstopencaptcha", hash_value="hash2"),
            pages.form_errors("The submitted CAPTCHA code is incorrect"),
        ),
    )

    with pytest.raises(IncorrectCaptcha):
        form.submit({**VALID_REQUEST, "captcha": "ABCD"})

    assert form.captcha["jpeg"].read() == b"second-jpeg"
    assert form._payload["__VIEWSTATE"] == "new-vs"
    assert (
        "BDC_VCID_c_requestopen_captchaformlayout_reqstopencaptcha",
        "hash2",
    ) in form.required_inputs["captcha"].fill("ABCD")


def test_request_submit_sends_captcha_answer(client, requests_mock):
    requests_mock.get(REQUEST_URL, text=request_form_page(captcha=True))
    mock_captcha_files(requests_mock)
    form = client.request_form()
    requests_mock.post(
        REQUEST_URL,
        text=pages.page('<span id="ConfirmFormLayout_roReferenceNo">R1</span>'),
    )

    form.submit({**VALID_REQUEST, "captcha": "AB12"})

    sent = sent_form(requests_mock)
    assert sent["captchaFormLayout$reqstOpenCaptchaTextBox"] == "AB12"
    assert sent["BDC_VCID_c_requestopen_captchaformlayout_reqstopencaptcha"] == "hash1"


def account_form_page(captcha=True, extra=""):
    return pages.page(
        pages.secrets(),
        pages.text_field(CUST, "txtEmail", "Email Address"),
        pages.text_field(CUST, "txtPhoneMask", "Phone"),
        pages.text_field(CUST, "txtPassword", "Password"),
        pages.text_field(CUST, "txtConfirmPassword", "Confirm Password"),
        pages.checkbox_field(CUST, "chkTerms", "Terms"),
        pages.captcha("customerdetails", "captcha") if captcha else "",
        extra,
        logged_in=False,
    )


@pytest.fixture
def account_form(client, requests_mock):
    requests_mock.get(
        f"{BASE}Login.aspx",
        text=pages.page('<a id="lnkCreateUser" href="CustomerDetails.aspx">Create</a>'),
    )
    requests_mock.get(ACCOUNT_URL, text=account_form_page())
    mock_captcha_files(requests_mock)
    return client.new_account_form()


VALID_ACCOUNT = {
    "email_address": "ada@example.com",
    "phone": "3125550100",
    "password": "s3cret",
    "terms": "C",
    "captcha": "AB12",
}


def test_account_form_schema_folds_confirm_password_into_password(account_form):
    assert account_form.schema["required"] == [
        "email_address",
        "phone",
        "password",
        "terms",
        "captcha",
    ]
    assert account_form.schema["properties"]["phone"]["pattern"] == "^[0-9]{10}$"
    assert account_form.schema["properties"]["terms"]["enum"] == ["U", "C"]
    assert account_form.account_creation_page == ACCOUNT_URL


def test_account_submit_returns_true_when_redirected_to_customer_home(
    account_form, requests_mock
):
    requests_mock.post(
        ACCOUNT_URL, status_code=302, headers={"Location": f"{BASE}CustomerHome.aspx"}
    )
    # GovQA serves an error page right after account creation.
    requests_mock.get(
        f"{BASE}CustomerHome.aspx",
        text="There was a problem serving the requested page",
    )

    assert account_form.submit(VALID_ACCOUNT) is True

    sent = sent_form(requests_mock)
    assert sent[f"{CUST}$txtEmail"] == "ada@example.com"
    assert sent[f"{CUST}$txtPassword"] == "s3cret"
    assert sent[f"{CUST}$txtConfirmPassword"] == "s3cret"
    assert (
        sent[f"{CUST}$txtPhoneMask$State"]
        == '{"rawValue":"3125550100","validationState":""}'
    )
    assert sent[f"{CUST}$chkTerms"] == "C"
    assert sent["captchaFormLayout$CaptchaCodeTextBox"] == "AB12"


def test_account_submit_sends_account_captcha_workaround_field(
    account_form, requests_mock
):
    requests_mock.post(
        ACCOUNT_URL, text=pages.page(pages.secrets(), pages.form_errors("x"))
    )

    with pytest.raises(FormValidationError):
        account_form.submit(VALID_ACCOUNT)

    assert (
        "BDC_BackWorkaround_c_customerdetails_captchaformlayout_captcha"
        in sent_form(requests_mock)
    )


def test_account_submit_reraises_errors_not_from_customer_home(
    account_form, requests_mock
):
    requests_mock.post(
        ACCOUNT_URL, text="There was a problem serving the requested page"
    )

    with pytest.raises(scrapelib.HTTPError):
        account_form.submit(VALID_ACCOUNT)


def test_account_submit_raises_when_email_exists(account_form, requests_mock):
    requests_mock.post(
        ACCOUNT_URL,
        text=pages.page(
            pages.secrets(), pages.form_errors("Email address already exists.")
        ),
    )

    with pytest.raises(EmailAlreadyExists):
        account_form.submit(VALID_ACCOUNT)


def test_account_submit_with_wrong_captcha_refreshes_captcha(
    account_form, requests_mock
):
    requests_mock.post(
        ACCOUNT_URL,
        text=pages.page(
            pages.secrets(),
            pages.captcha("customerdetails", "captcha"),
            pages.form_errors("The submitted code is incorrect."),
        ),
    )

    with pytest.raises(IncorrectCaptcha):
        account_form.submit(VALID_ACCOUNT)

    assert account_form.captcha["jpeg"].read() == b"second-jpeg"


def test_account_submit_raises_site_validation_error(account_form, requests_mock):
    requests_mock.post(
        ACCOUNT_URL,
        text=pages.page(pages.secrets(), pages.form_errors("Password is too weak")),
    )

    with pytest.raises(FormValidationError, match="Password is too weak"):
        account_form.submit(VALID_ACCOUNT)


def test_account_submit_raises_when_page_has_no_errors(account_form, requests_mock):
    requests_mock.post(ACCOUNT_URL, text=pages.page(pages.secrets()))

    with pytest.raises(FormValidationError, match="unknown reason"):
        account_form.submit(VALID_ACCOUNT)
