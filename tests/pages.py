"""HTML builders mimicking the GovQA/DevExpress markup the scraper targets."""

DOMAIN = "https://example.govqa.us"
BASE = f"{DOMAIN}/WEBAPP/_rs/"

LOGGED_IN = '<script>dtrum.identifyUser("1234;user@example.com");</script>'
LOGGED_OUT = '<script>dtrum.identifyUser("1234;");</script>'


def secrets(viewstate_fields=None):
    """Hidden ASP.NET state inputs; pass a list to split __VIEWSTATE across fields."""
    if viewstate_fields is None:
        return (
            '<input type="hidden" id="__VIEWSTATE" name="__VIEWSTATE" value="vs0">'
            '<input type="hidden" id="__VIEWSTATEGENERATOR" name="__VIEWSTATEGENERATOR" value="gen">'
            '<input type="hidden" name="__RequestVerificationToken" value="token">'
        )

    fields = "".join(
        f'<input type="hidden" id="__VIEWSTATE{i or ""}" value="{value}">'
        for i, value in enumerate(viewstate_fields)
    )
    return (
        f'<input type="hidden" id="__VIEWSTATEFIELDCOUNT" value="{len(viewstate_fields)}">'
        + fields
        + '<input type="hidden" id="__VIEWSTATEGENERATOR" value="gen">'
        '<input type="hidden" name="__RequestVerificationToken" value="token">'
    )


def page(*parts, logged_in=True):
    auth = LOGGED_IN if logged_in else LOGGED_OUT
    return f"<html><head>{auth}</head><body><form>{''.join(parts)}</form></body></html>"


def text_field(prefix, name, label, required=True):
    em = "<em>*</em>" if required else ""
    return (
        f'<table><tr><td><label for="{prefix}_{name}">{label}:</label>{em}</td></tr>'
        f'<tr><td><input type="text" name="{prefix}${name}"></td></tr></table>'
    )


def textarea_field(prefix, name, label):
    return (
        f'<table><tr><td><label for="{prefix}_{name}">{label}:</label><em>*</em></td></tr>'
        f'<tr><td><textarea name="{prefix}${name}"></textarea></td></tr></table>'
    )


def radio_field(prefix, name, label, options):
    radios = "".join(
        f'<tr><td><input type="radio" name="{prefix}${name}$RB{i}"></td></tr>'
        for i in range(len(options))
    )
    items = ",".join(f"[{i},'{option}']" for i, option in enumerate(options))
    script = (
        f"<script>ASPx.createControl({{'uniqueID':'{prefix}${name}',"
        f"'items':[{items}]}});</script>"
    )
    return (
        f'<table><tr><td><span id="{prefix}_{name}_lbl">{label}:</span><em>*</em></td></tr>'
        f'<tr><td><table role="radiogroup">'
        f'<tr><td><input type="hidden" name="{prefix}${name}" value=""></td></tr>'
        f"{radios}</table></td></tr></table>{script}"
    )


def combo_field(prefix, name, label, options):
    items = ",".join(["{'value':'','text':''}"] + [f"{{'value':'{o}','text':'{o}'}}" for o in options])
    script = (
        f"<script>ASPx.createControl({{'uniqueID':'{prefix}${name}$DDD$L',"
        f"'itemsInfo':[{items}]}});</script>"
    )
    return (
        f'<table><tr><td><label for="{prefix}_{name}">{label}:</label><em>*</em></td></tr>'
        f'<tr><td><input type="hidden" name="{prefix}${name}$VI" value="">'
        f'<input type="text" role="combobox" name="{prefix}${name}"></td></tr></table>{script}'
    )


def checkbox_field(prefix, name, label):
    return (
        f'<table><tr><td><span id="{prefix}_{name}_lbl">{label}:</span><em>*</em></td></tr>'
        f'<tr><td><span role="checkbox"></span>'
        f'<input type="hidden" name="{prefix}${name}" value="U"></td></tr></table>'
    )


def captcha(prefix, captcha_name, hash_value="hash1"):
    element = f"c_{prefix}_captchaformlayout_{captcha_name}"
    return (
        f'<img id="{element}_CaptchaImage" src="/captcha.jpg">'
        f'<a id="{element}_SoundLink" href="/captcha.wav">audio</a>'
        f'<input type="hidden" name="BDC_VCID_{element}" value="{hash_value}">'
    )


def form_errors(*messages):
    items = "".join(f"<li>{m}</li>" for m in messages)
    return f'<div id="header_errors1"><ul>{items}</ul></div>'
