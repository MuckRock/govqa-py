import io

import lxml.html
import pytest

from govqa.input_types import (
    Captcha,
    CheckBox,
    ComboBox,
    Input,
    Password,
    Phone,
    RadioGroup,
    TextArea,
)
from tests import pages

PREFIX = "requestFormLayout"


def parse(html):
    """Return the outermost field table and the full page source, as Form passes them."""
    source = pages.page(html)
    tree = lxml.html.fromstring(source)
    return tree.xpath("//form/table")[0], source


def test_input_normalizes_label_into_schema_key():
    table, source = parse(pages.text_field(PREFIX, "txtName", "Your Full Name"))

    field = Input(table, source)

    assert field.label == "your_full_name"
    assert field.properties == {"type": "string"}


def test_input_fills_its_named_post_key():
    table, source = parse(pages.text_field(PREFIX, "txtName", "Name"))

    assert Input(table, source).fill("Ada") == [(f"{PREFIX}$txtName", "Ada")]


def test_input_requires_exactly_one_required_label():
    table, source = parse(pages.text_field(PREFIX, "txtName", "Name", required=False))

    with pytest.raises(ValueError):
        Input(table, source)


def test_textarea_fills_the_textarea():
    table, source = parse(pages.textarea_field(PREFIX, "txtDescription", "Description"))

    field = TextArea(table, source)

    assert field.label == "description"
    assert field.fill("All emails") == [(f"{PREFIX}$txtDescription", "All emails")]


def test_phone_requires_ten_digits_and_sends_devexpress_state():
    table, source = parse(
        pages.text_field("customerInfo_CustomerFormLayout", "txtPhoneMask", "Phone")
    )

    field = Phone(table, source)

    assert field.properties["pattern"] == "^[0-9]{10}$"
    assert field.fill("3125550100") == [
        ("customerInfo_CustomerFormLayout$txtPhoneMask", "3125550100"),
        (
            "customerInfo_CustomerFormLayout$txtPhoneMask$State",
            '{"rawValue":"3125550100","validationState":""}',
        ),
    ]


def test_password_fills_confirmation_field_too():
    password_table, source = parse(pages.text_field("c", "txtPassword", "Password"))
    confirm_table, _ = parse(
        pages.text_field("c", "txtConfirmPassword", "Confirm Password")
    )

    field = Password(password_table, source)
    field.add_confirmation(confirm_table)

    assert field.fill("s3cret") == [
        ("c$txtPassword", "s3cret"),
        ("c$txtConfirmPassword", "s3cret"),
    ]


def test_radio_group_reads_options_from_devexpress_script():
    table, source = parse(
        pages.radio_field(PREFIX, "rblDelivery", "Delivery", ["Electronic", "Paper"])
    )

    field = RadioGroup(table, source)

    assert field.label == "delivery"
    assert field.properties == {"type": "string", "enum": ["Electronic", "Paper"]}


def test_radio_group_fills_option_index_and_checks_its_radio():
    table, source = parse(
        pages.radio_field(PREFIX, "rblDelivery", "Delivery", ["Electronic", "Paper"])
    )

    assert RadioGroup(table, source).fill("Paper") == [
        (f"{PREFIX}$rblDelivery", "1"),
        (f"{PREFIX}$rblDelivery$RB1", "C"),
    ]


def test_combo_box_reads_options_skipping_blank_first_item():
    table, source = parse(pages.combo_field(PREFIX, "cbState", "State", ["IL", "NY"]))

    field = ComboBox(table, source)

    assert field.properties == {"type": "string", "enum": ["IL", "NY"]}


def test_combo_box_fills_visible_and_hidden_inputs():
    table, source = parse(pages.combo_field(PREFIX, "cbState", "State", ["IL", "NY"]))

    assert ComboBox(table, source).fill("NY") == [
        (f"{PREFIX}$cbState", "NY"),
        (f"{PREFIX}$cbState$VI", "NY"),
    ]


def test_checkbox_accepts_checked_or_unchecked_and_fills_hidden_input():
    table, source = parse(pages.checkbox_field(PREFIX, "chkAgree", "I Agree"))

    field = CheckBox(table, source)

    assert field.label == "i_agree"
    assert field.properties == {"type": "string", "enum": ["U", "C"]}
    assert field.fill("C") == [(f"{PREFIX}$chkAgree", "C")]


class FakeSession:
    domain = pages.DOMAIN

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def get(self, url):
        self.requested.append(url)

        class Response:
            content = self.responses[url]

        return Response()


CAPTCHA_CONFIG = {
    "img_id": "c_requestopen_captchaformlayout_reqstopencaptcha_CaptchaImage",
    "wav_link_id": "c_requestopen_captchaformlayout_reqstopencaptcha_SoundLink",
    "input_name": "captchaFormLayout$reqstOpenCaptchaTextBox",
    "captcha_hash_input_name": "BDC_VCID_c_requestopen_captchaformlayout_reqstopencaptcha",
    "workaround_input_name": "BDC_BackWorkaround_c_requestopen_captchaformlayout_reqstopencaptcha",
}


def test_captcha_downloads_image_and_audio():
    tree = lxml.html.fromstring(
        pages.page(pages.captcha("requestopen", "reqstopencaptcha"))
    )
    session = FakeSession(
        {
            f"{pages.DOMAIN}/captcha.jpg": b"jpeg-bytes",
            f"{pages.DOMAIN}/captcha.wav": b"wav-bytes",
        }
    )

    captcha = Captcha(session, tree, **CAPTCHA_CONFIG)

    assert isinstance(captcha.info["jpeg"], io.BytesIO)
    assert captcha.info["jpeg"].read() == b"jpeg-bytes"
    assert captcha.info["wav"].read() == b"wav-bytes"


def test_captcha_fills_answer_with_hash_and_workaround():
    tree = lxml.html.fromstring(
        pages.page(
            pages.captcha("requestopen", "reqstopencaptcha", hash_value="abc123")
        )
    )
    session = FakeSession(
        {f"{pages.DOMAIN}/captcha.jpg": b"", f"{pages.DOMAIN}/captcha.wav": b""}
    )

    captcha = Captcha(session, tree, **CAPTCHA_CONFIG)

    assert captcha.fill("XY12") == [
        ("BDC_VCID_c_requestopen_captchaformlayout_reqstopencaptcha", "abc123"),
        ("BDC_BackWorkaround_c_requestopen_captchaformlayout_reqstopencaptcha", "1"),
        ("captchaFormLayout$reqstOpenCaptchaTextBox", "XY12"),
    ]


def test_captcha_info_is_empty_when_page_has_no_captcha():
    tree = lxml.html.fromstring(pages.page())
    session = FakeSession({})

    captcha = Captcha(session, tree, **CAPTCHA_CONFIG)

    assert captcha.info == {}
    assert session.requested == []
