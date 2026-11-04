import datetime

import pytest

from govqa import UnauthenticatedError
from tests.pages import BASE, page

S3_URL = (
    "https://bucket.s3.amazonaws.com/records.pdf"
    "?response-content-disposition=attachment%3B%20filename%3D%22records.pdf%22"
    "&Expires=1700000000&Signature=abc"
)
AZURE_URL = (
    "https://acct.blob.core.windows.net/c/notes.docx"
    "?se=2023-11-14T22%3A13%3A20Z&rscd=attachment%3B%20filename%3Dnotes.docx&sig=xyz"
)


def request_row(rid, reference, status):
    return (
        '<div class="innerlist">'
        f'<a id="rptIssues_ctl0{rid}_referenceLnk" href="RequestEdit.aspx?rid={rid}">{reference}</a>'
        f'<div class="list_status col">{status}</div>'
        "</div>"
    )


def message(message_id, header, body):
    return (
        f'<table id="rptMessageHistory_ctl00_{message_id}"><tr><td>'
        f'<span class="dxrpHT">{header}</span>'
        f'<div class="dxrpCW">{body}</div>'
        "</td></tr></table>"
    )


def attachment(uploaded_at, input_id, url=None):
    value = f' value="{url}"' if url else ""
    return (
        f"<tr><td> {uploaded_at} </td><td>"
        f'<div class="qac_attachment"><input type="hidden" id="{input_id}"{value}></div>'
        "</td></tr>"
    )


def request_page(messages="", attachments=""):
    return page(
        '<span id="RequestEditFormLayout_roType">Public Records Request</span>',
        '<span id="RequestEditFormLayout_roContactEmail">user@example.com</span>',
        '<span id="RequestEditFormLayout_roReferenceNo">R000123-010123</span>',
        messages,
        f'<div id="dvAttachments"><table>{attachments}</table></div>',
    )


def test_lists_request_ids_and_reference_numbers(client, requests_mock):
    requests_mock.get(
        f"{BASE}CustomerIssues.aspx",
        text=page(request_row(101, "R000101", "Open"), request_row(102, "R000102", "Open")),
    )

    requests = client.list_requests()

    assert requests == [
        {"id": "101", "reference_number": "R000101", "status": "Open"},
        {"id": "102", "reference_number": "R000102", "status": "Open"},
    ]


@pytest.mark.xfail(
    strict=True,
    reason="status XPath starts with '//', so every request gets the first request's status",
)
def test_lists_each_requests_own_status(client, requests_mock):
    requests_mock.get(
        f"{BASE}CustomerIssues.aspx",
        text=page(request_row(101, "R000101", "Open"), request_row(102, "R000102", "Closed")),
    )

    statuses = [r["status"] for r in client.list_requests()]

    assert statuses == ["Open", "Closed"]


def test_gets_request_metadata(client, requests_mock):
    requests_mock.get(f"{BASE}RequestEdit.aspx?rid=101", text=request_page())

    request = client.get_request(101)

    assert request == {
        "id": 101,
        "request_type": "Public Records Request",
        "contact_email": "user@example.com",
        "reference_number": "R000123-010123",
        "messages": [],
        "attachments": [],
    }


def test_get_request_requires_login(client, requests_mock):
    requests_mock.get(f"{BASE}RequestEdit.aspx?rid=101", text=page(logged_in=False))

    with pytest.raises(UnauthenticatedError):
        client.get_request(101)


def test_parses_message_sender_date_and_collapses_body_whitespace(client, requests_mock):
    requests_mock.get(
        f"{BASE}RequestEdit.aspx?rid=101",
        text=request_page(
            messages=message(
                "555",
                " On 1/2/2023 10:11:12 AM, Jane Clerk wrote:",
                "Hello,<br>\n   Your records\n are ready.",
            )
        ),
    )

    (msg,) = client.get_request(101)["messages"]

    assert msg == {
        "id": "555",
        "sender": "Jane Clerk",
        "date": "1/2/2023",
        "time": "10:11:12 AM",
        "body": "Hello, Your records are ready.",
    }


def test_fetches_full_body_of_truncated_messages(client, requests_mock):
    requests_mock.get(
        f"{BASE}RequestEdit.aspx?rid=101",
        text=request_page(
            messages=message(
                "556",
                " On 12/31/2022 9:00:00 PM, Jane Clerk wrote:",
                "Beginning of a long... "
                "<a onclick=\"ShowMessage('ViewMessage.aspx?mid=556')\">"
                "Click Here to View Entire Message</a>",
            )
        ),
    )
    requests_mock.get(
        f"{BASE}ViewMessage.aspx?mid=556",
        text='<html><body><div id="divMessage"><p>The full</p> <p>message.</p></div></body></html>',
    )

    (msg,) = client.get_request(101)["messages"]

    assert msg["body"] == "The full message."


def test_parses_s3_and_azure_attachment_urls(client, requests_mock):
    requests_mock.get(
        f"{BASE}RequestEdit.aspx?rid=101",
        text=request_page(
            attachments=attachment("01/05/2023 3:04 PM", "rpt_ctl00_hdnAWSUrl", S3_URL)
            + attachment("02/06/2023", "rpt_ctl01_hdnAzureURL", AZURE_URL)
        ),
    )

    s3, azure = client.get_request(101)["attachments"]

    assert s3 == {
        "url": S3_URL,
        "content-disposition": 'attachment; filename="records.pdf"',
        "expires": datetime.datetime.fromtimestamp(1700000000),
        "uploaded_at": datetime.date(2023, 1, 5),
    }
    assert azure == {
        "url": AZURE_URL,
        "content-disposition": "attachment; filename=notes.docx",
        "expires": datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc),
        "uploaded_at": datetime.date(2023, 2, 6),
    }


def test_skips_attachment_inputs_without_a_url(client, requests_mock):
    requests_mock.get(
        f"{BASE}RequestEdit.aspx?rid=101",
        text=request_page(attachments=attachment("01/05/2023", "rpt_ctl00_hdnAWSUrl")),
    )

    assert client.get_request(101)["attachments"] == []
