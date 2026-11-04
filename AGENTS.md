# AGENTS.md

This file provides guidance to AI coding agents working with code in this repository.

## Project

`govqa` is a Python client for GovQA, Granicus's public records request portal. There is no official API: the library logs in, fills out forms and reads pages by scraping the ASP.NET/DevExpress web app under `{domain}/WEBAPP/_rs/`. Most bugs come from GovQA instances whose markup differs from what the XPath selectors and regexes expect.

## Commands

Packaging uses `setup.py`/`setup.cfg` (setuptools). Tests live in `tests/` and run offline against fake GovQA pages built in `tests/pages.py` and served by `requests-mock`. There is no CI test job or lint config yet.

```bash
pip install -e ".[dev]"        # dev extras: sphinx, pytest, requests-mock, black, isort
pytest                         # run the test suite
black govqa && isort govqa     # formatting tools listed in dev extras
make -C docs html              # build Sphinx docs (docs/index.rst holds the usage guide + autodoc API)
```

Release: the version lives in `govqa/__init__.py` (`__version__`) and `setup.cfg` reads it from there. A push to `main` publishes to Test PyPI. Pushing a tag publishes to PyPI (`.github/workflows/`). Read the Docs builds `docs/` using `docs/requirements.txt`.

## Architecture

- **`GovQA` (`govqa/base.py`)** subclasses `scrapelib.Scraper`, so every HTTP call goes through scrapelib's retry and rate limiting. Its constructor makes a request right away and raises `UnsupportedSite` unless the site redirects to `SupportHome.aspx`. `request()` is overridden to turn GovQA's "problem serving the requested page" and "Temporarily Unavailable" HTML pages into `scrapelib.HTTPError` (500 and 503).
- **ASP.NET postbacks**: every form POST needs the hidden state fields that `GovQA._secrets()` collects: `__VIEWSTATE`, which can be split across `__VIEWSTATE1..N` according to `__VIEWSTATEFIELDCOUNT`, plus `__VIEWSTATEGENERATOR` and `__RequestVerificationToken`. After a failed submit, `Form._reset_payload()` refreshes these fields and the captcha.
- **Auth check**: `_check_logged_in()` reads the user identity out of the Dynatrace `dtrum.identifyUser("...")` script in the page. Passing `check_login=False` turns the check off, for sites that don't include that script.
- **Dynamic forms** (`Form`, `CreateAccountForm`, `RequestForm`): each form page is scraped at runtime. A field is required when its label is followed by an `<em>`. Each required field's table is mapped to a class in `govqa/input_types.py` (`Input`, `TextArea`, `Password`, `Phone`, `RadioGroup`, `ComboBox`, `CheckBox`), and those classes build:
  - a JSON Schema (`form.schema`) keyed by the normalized label text (lowercase, spaces → `_`). `submit()` validates the user's dict against this schema.
  - `fill(value)`, which turns one user value into the `(post_key, value)` pairs that DevExpress expects, such as `$State` JSON blobs and `$RB{index}` radio keys. The allowed values for `RadioGroup` and `ComboBox` are taken from inline DevExpress JS (`'uniqueID':...`) with regex plus `ast.literal_eval`.
- **Captcha**: `Captcha` downloads the BotDetect image and audio as `BytesIO` and exposes them as `form.captcha` (`{"jpeg", "wav"}`). When a captcha exists, `captcha` is added as a required schema property. The caller has to solve it; the library does not.
- **Reading requests**: `list_requests()` scrapes `CustomerIssues.aspx`. `get_request()` scrapes `RequestEdit.aspx?rid=`, parses message headers with a regex, follows "View Entire Message" links, and pulls attachment URLs from hidden inputs. It handles both AWS S3 (`response-content-disposition`/`Expires`) and Azure Blob (`rscd`/`se`) signed URL formats.

The public exceptions (`UnauthenticatedError`, `FormValidationError`, `IncorrectCaptcha`, `EmailAlreadyExists`, `UnsupportedSite`) are re-exported from `govqa/__init__.py`.

## Code comments

Comments say **why**, not what. If the code already says it, delete the comment.

- **One or two short sentences.** If it needs a paragraph, it belongs in a
  doc comment, the PR description, or a doc under `docs/`.
- **Keep the consequence, drop the lead-in.** The clause naming what the
  code does is the half to cut; the clause saying what breaks otherwise is
  the half worth keeping.
- **Never describe code that is not there.** No "this used to...", no
  narrating the change, no explaining why something was removed. `git log`
  and the PR hold that.
- **No reasoning out loud.** Don't walk through scenarios, anticipate
  objections, or record the thought process behind a choice.
- **Do comment the surprising**: a constraint an external system imposes,
  an ordering requirement, a failure that cannot be seen locally. That is
  what a reader cannot get from the code.

```typescript
// Good - a constraint you cannot see from here
// The API rejects a redaction whose page range crosses a document split.

// Bad - narrates the change
// `currentPage` is now derived from the store instead of a prop, so
// this component no longer needs to read it from context.
```

## Docstrings / doc comments

One line on what it does. Add more only for a contract a caller needs: what it rejects/throws, what it returns in the edge case, ordering it requires, side effects it has, a cost worth avoiding.

Two tests before you keep a second paragraph:

- Does it restate the first line in more words? Delete it.
- Would a caller behave differently for knowing it? Keep it, in one or two sentences.

```typescript
// Good - the whole contract, one line
/** Does the document still have pages pending OCR? */

// Good - a second paragraph a caller acts on
/**
 * The document's current processing status, or "error" if any page failed.
 *
 * Read from the cached store value; the document list renders one row
 * per document and cannot afford an API call each.
 */
```

## Pull request descriptions

Open with one sentence on what changes. Then:

- **Behaviour changes** — name them, or say "none".
- **Migrations** — what they do, whether they reverse.
- **What to check** — the QA steps, as a checklist.

Bullets, not prose. Don't recount how the change came about or what was tried first.

## Tests

Name the behaviour, not the mechanism: `renders the error state when OCR fails`, not `test handle error`. A test whose assertion would pass against the unfixed code is not a test.
