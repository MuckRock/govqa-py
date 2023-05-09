import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import lxml.html
import scrapelib
import jsonschema


class UnauthenticatedError(RuntimeError):
    def __init__(self):
        # Call the base class constructor with the parameters it needs
        super().__init__(
            "This method requires authentication, please run the `login` method before calling this method"
        )


class GovQA(scrapelib.Scraper):
    """
    Client for programmatically interacting with GovQA instances.

    :param domain: Root domain of the GovQA instance to interact with, e.g.,
        https://governorny.govqa.us
    :type domain: str
    :param username: GovQA username
    :type username: str
    :param password: GovQA password
    :type password: str
    """

    # do i need this, i don't think so.
    ENDPOINTS = {
        "home": "SupportHome.aspx",
        "login": "Login.aspx",
        "create_account": "CustomerDetails.aspx",
        "logged_in_home": "CustomerHome.aspx",
        "messages": "CustomerIssues.aspx",
        "message": "RequestEdit.aspx",
    }

    def __init__(self, domain, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.domain = domain.rstrip("/")

        self.headers.update(
            {
                "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36",
            }
        )

    def request(self, *args, **kwargs):
        response = super().request(*args, **kwargs)

        if "There was a problem serving the requested page" in response.text:
            response.status_code = 500
            raise scrapelib.HTTPError(response)

        elif "Page Temporarily Unavailable" in response.text:
            response.status_code = 503
            raise scrapelib.HTTPError(response)

        return response

    def url_from_endpoint(self, endpoint):
        return f"{self.domain}/WEBAPP/_rs/{endpoint}"

    def new_account_form(self):
        response = self.get(self.url_from_endpoint("Login.aspx"), allow_redirects=True)

        tree = lxml.html.fromstring(response.text)

        (create_user_link,) = tree.xpath("//a[@id='lnkCreateUser']")

        response = self.get(
            self.url_from_endpoint(create_user_link.attrib["href"]),
            allow_redirects=True,
        )

        tree = lxml.html.fromstring(response.text)

        # find the table elements that are direct ancestors of labels
        # that have an <em> next to them indicating a required field,
        # and then find the non-hidden inputs descendants of those
        # tables
        required_inputs = tree.xpath(
            ".//table[tr/td/label[starts-with(@for, 'customer') and following-sibling::em]]//input[not(@type='hidden')]"
        )

        properties = {}
        post_keys = {}
        for element in required_inputs:
            label = element.attrib["aria-label"].lower().replace(' ', '_')
            properties[label] = {"type": "string"}
            if element.attrib.get("role") == "combobox":
                # need to get valid options here
                raise NotImplementedError

            post_keys[label] = element.attrib["name"]

        schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
        }

        form = CreateAccountForm(schema, post_keys, create_user_link, self, None)
        return form

    def login(self, username, password):
        response = self.get(
            self.url_from_endpoint("Login.aspx"),
            allow_redirects=True,
        )

        tree = lxml.html.fromstring(response.text)

        viewstate = tree.xpath("//input[@id='__VIEWSTATE']")[0].value
        viewstategenerator = tree.xpath("//input[@id='__VIEWSTATEGENERATOR']")[0].value
        request_verification_token = tree.xpath(
            "//input[@name='__RequestVerificationToken']"
        )[0].value

        payload = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__RequestVerificationToken": request_verification_token,
            "ASPxFormLayout1$txtUsername": username,
            "ASPxFormLayout1$txtPassword": password,
            "ASPxFormLayout1$btnLogin": "Submit",
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__VIEWSTATEENCRYPTED": "",
        }

        return self.post(response.url, data=payload, allow_redirects=True)

    def reset_password(self):
        ...

    def submit_request(self):
        """
        Text and attachments
        """
        ...

    def update_request(self, request_id):
        ...

    def list_requests(self):
        """
        Retrieve the id, reference number, and status of each request
        submitted by the authenticated account.

        :return: List of dictionaries, each containing the id,
            reference number, and status of all requests.
        :rtype: list

        """

        response = self.get(
            self.url_from_endpoint("CustomerIssues.aspx"),
        )

        self._check_logged_in(response)

        tree = lxml.html.fromstring(response.text)

        request_links = tree.xpath("//a[contains(@id, 'referenceLnk')]")

        requests = []

        for link in request_links:
            requests.append(
                {
                    "id": parse_qs(urlparse(link.attrib["href"]).query)["rid"][0],
                    "reference_number": link.text,
                    "status": link.xpath(
                        "//ancestor::div[@class='innerlist']/descendant::div[starts-with(@class, 'list_status')]/text()"
                    )[0],
                }
            )

        return requests

    def get_request(self, request_id):
        """
        Retrieve detailed information, included messages and
        attachments, about a request.

        :param request_id: Identifier of the request, i.e., the "id"
            from a request dictionary returned by
            list_requests(). N.b., the reference number is not the
            identifier.
        :type request_id: int
        :return: Dictionary of request metadata, correspondence, and
            attachments.
        :rtype: dict

        """

        response = self.get(
            self.url_from_endpoint("RequestEdit.aspx"), params={"rid": request_id}
        )

        self._check_logged_in(response)

        tree = lxml.html.fromstring(response.text)

        request = {
            "id": request_id,
            "request_type": tree.xpath(
                "//span[@id='RequestEditFormLayout_roType']/text()"
            )[0],
            "contact_email": tree.xpath(
                "//span[@id='RequestEditFormLayout_roContactEmail']/text()"
            )[0],
            "reference_number": tree.xpath(
                "//span[@id='RequestEditFormLayout_roReferenceNo']/text()"
            )[0],
            "messages": [],
            "attachments": [],
        }

        for message in tree.xpath("//table[contains(@id, 'rptMessageHistory')]"):
            (sender,) = message.xpath(".//span[contains(@class, 'dxrpHT')]/text()")

            parsed_sender = re.match(
                r"^ On (?P<date>\d{1,2}\/\d{1,2}\/\d{4}) (?P<time>\d{1,2}:\d{1,2}:\d{1,2} (A|P)M), (?P<name>.*) wrote:$",
                sender,
            )

            body = message.xpath(
                ".//div[contains(@class, 'dxrpCW')]/text()"
            ) + message.xpath(".//div[contains(@class, 'dxrpCW')]/descendant::*/text()")

            if "Click Here to View Entire Message" in body:
                (link,) = message.xpath(".//div[contains(@class, 'dxrpCW')]/a")
                onclick = link.attrib["onclick"]
                truncated_message_path = re.search(r"\('(.*)'\)", onclick).group(1)
                body = self._parse_truncated_message(truncated_message_path)

            request["messages"].append(
                {
                    "id": message.attrib["id"].split("_")[-1],
                    "sender": parsed_sender.group("name"),
                    "date": parsed_sender.group("date"),
                    "time": parsed_sender.group("time"),
                    "body": re.sub(r"\s+", " ", " ".join(body)).strip(),
                }
            )

        attachment_links = tree.xpath(
            "//div[@id='dvAttachments']/descendant::div[@class='qac_attachment']/input[contains(@id, 'hdnAWSUrl') or contains(@id, 'hdnAzureURL')]"
        )

        for link in attachment_links:
            if "value" in link.attrib:
                url = link.attrib["value"]
                uploaded_at_str = link.xpath("../../../td[1]/text()")[0].strip()
                metadata = parse_qs(urlparse(url).query)
                request["attachments"].append(
                    {
                        "url": link.attrib["value"],
                        "content-disposition": metadata["response-content-disposition"][
                            0
                        ],
                        "expires": datetime.fromtimestamp(int(metadata["Expires"][0])),
                        "uploaded_at": datetime.strptime(
                            uploaded_at_str, "%m/%d/%Y"
                        ).date(),
                    }
                )

        return request

    def _parse_truncated_message(self, truncated_message_endpoint):
        truncated_message_url = self.url_from_endpoint(truncated_message_endpoint)
        response = self.get(truncated_message_url)
        tree = lxml.html.fromstring(response.text)
        body = tree.xpath(".//div[@id='divMessage']//text()")
        return body

    def _check_logged_in(self, response):
        if "If you have used this service previously, please log in" in response.text:
            raise UnauthenticatedError


class CreateAccountForm:
    def __init__(self, schema, post_keys, url, session, captcha=None):
        jsonschema.Draft7Validator.check_schema(schema)
        self.schema = schema
        self.captcha = captcha
        self._url = url
        self._post_keys = post_keys
        self._session = session

    def submit(self, required_inputs):
        jsonschema.validate(required_inputs, self.schema)

        # make the post
        # catch errors and return useful error message
        ...
