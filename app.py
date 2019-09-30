import logging
import os
import configparser

from flask import Flask
from flask import request
from flask import url_for
from twilio.rest import Client
import phonenumbers as ph
import sendgrid
import simplejson

from konfig import Konfig


def warn(message):
    logging.warning(message)
    return message


address_book = {}
address_book_file = "address-book.cfg"
try:
    user_list = configparser.ConfigParser()
    user_list.read(address_book_file)
    for user in user_list.items("users"):
        address_book[user[0]] = user[1]
except:
    template = "{} does not exist"
    warn(template.format(address_book_file))

app = Flask(__name__)
konf = Konfig()
twilio_api = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])

sendgrid_api = sendgrid.SendGridClient(konf.sendgrid_username, konf.sendgrid_password)


class InvalidInput(Exception):
    def __init__(self, invalid_input):
        self.invalid_input = invalid_input


class NoEmailForNumber(InvalidInput):
    def __str__(self):
        template = (
            "No email address is configured to receive "
            "SMS messages sent to '{}' - "
            "Try updating the 'address-book.cfg' file?"
        )
        return template.format(self.invalid_input)


class NoNumberForEmail(InvalidInput):
    def __str__(self):
        template = (
            "The email address '{}' is not "
            "configured to send SMS via this application - "
            "Try updating the 'address-book.cfg' file?"
        )
        return template.format(self.invalid_input)


class InvalidPhoneNumberInEmail(InvalidInput):
    def __str__(self):
        template = "Invalid phone number in email address: {}"
        return template.format(self.invalid_input)


class InvalidPhoneNumber(InvalidInput):
    def __str__(self):
        template = "Invalid phone number in HTTP POST: {}"
        return template.format(self.invalid_input)


class Lookup:
    def __init__(self):
        self.by_phone_number = address_book
        self.by_email_address = {}
        for phone_number in address_book.keys():
            email_address = address_book[phone_number]
            self.by_email_address[email_address] = phone_number
        print("Lookup.__init__ ok")

    def phone_for_email(self, email_address):
        """Which phone number do we send this SMS message from?"""
        if email_address in self.by_email_address:
            return self.by_email_address[email_address]
        else:
            raise NoNumberForEmail(email_address)

    def email_for_phone(self, potential_number):
        """Which email address do we forward this SMS message to?"""

        try:
            number = ph.parse(potential_number, "US")
            phone_number = ph.format_number(number, ph.PhoneNumberFormat.E164)
        except Exception as e:
            raise InvalidPhoneNumber(str(e))

        if phone_number in self.by_phone_number:
            return self.by_phone_number[phone_number]
        else:
            raise NoEmailForNumber(phone_number)


def phone_to_email(potential_number):
    """Converts a phone number like +14155551212
       into an email address like 14155551212@sms.example.com"""
    warn(f"phone_to_email -> {potential_number}")
    try:
        number = ph.parse(potential_number, "US")
        phone_number = ph.format_number(number, ph.PhoneNumberFormat.E164)
    except Exception as e:
        warn(e)
        raise InvalidPhoneNumber(str(e))
    phone_number = phone_number.replace("+", "")
    return "{}@{}".format(phone_number, konf.email_domain)


def email_to_phone(from_email):
    """Converts an email address like 14155551212@sms.example.com
       into a phone number like +14155551212"""
    warn(f"email_to_phone -> {from_email}")
    (username, domain) = from_email.split("@")
    warn(f"username: {username}")
    warn(f"domain: {domain}")

    potential_number = "+" + username
    try:
        ph_num = ph.parse(potential_number, "US")
        return ph.format_number(ph_num, ph.PhoneNumberFormat.E164)
    except:
        warn("invalid phone number in email")
        raise InvalidPhoneNumberInEmail(from_email)


def check_for_missing_settings():
    rv = []
    for required in [
        "EMAIL_DOMAIN",
        "SENDGRID_USERNAME",
        "SENDGRID_PASSWORD",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
    ]:
        value = getattr(konf, required)
        if not value:
            rv.append(required)
    return rv


def duplicates_in_address_book():
    duplcates_found = False
    values = address_book.values()
    if len(values) != len(set(values)):
        duplcates_found = True
    return duplcates_found


@app.route("/")
def main():
    missing_settings = check_for_missing_settings()
    print("printed: hello, we're in main")
    warn("warn: hello, we're in main")
    if len(missing_settings) > 0:
        template = "The following settings are missing: {}"
        missing = ", ".join(missing_settings)
        error_message = template.format(missing)
        return warn(error_message), 500
    elif duplicates_in_address_book():
        print(str(address_book))
        error_message = (
            "Only one email address can be configured per "
            "phone number. Please update the 'address-book.cfg' "
            "file so that each phone number "
            "matches exactly one email address."
        )
        return warn(error_message), 500
    else:
        template = (
            "Congratulations, "
            "this software appears to be configured correctly."
            "<br/><br/>"
            "Use the following URLs to configure SendGrid "
            "and Twilio:"
            "<br/><br/>"
            "SendGrid Inbound Parse Webhook URL: {}"
            "<br/>"
            "Twilio Messaging Request URL: {}"
        )
        message = template.format(
            url_for("handle_email", _external=True),
            url_for("handle_sms", _external=True),
        )
        return message


@app.route("/handle-sms", methods=["POST"])
def handle_sms():
    lookup = Lookup()
    print(f"lookup: {lookup}")
    try:
        email = {
            "text": request.form["Body"],
            "subject": "Text message",
            "from_email": phone_to_email(request.form["From"]),
            "to": lookup.email_for_phone(request.form["To"]),
        }
    except InvalidInput as e:
        print(f"error: {e}")
        return warn(str(e)), 400
    warn("email ok:")
    warn(email)

    message = sendgrid.Mail(**email)
    (status, msg) = sendgrid_api.send(message)
    print(status)
    print(msg)
    if "errors" in msg.decode():
        template = "Error sending message to SendGrid: {}"
        errors = ", ".join(msg["errors"])
        error_message = template.format(errors)
        return warn(error_message), 400
    else:
        return "<Response></Response>"


@app.route("/handle-email", methods=["POST"])
def handle_email():
    lookup = Lookup()
    print(f"lookup: {lookup}")
    print("hi")
    # try:
    envelope = simplejson.loads(request.form["envelope"])
    print(f"envelope: {envelope}")
    print(f"request.form: {request.form}")
    print(f"ok really gonna try hard now")
    text = request.form.get("text", request.form.get("email"))
    print(f"text: {text}")
    lines = text.splitlines(True)
    for line in lines:
        print(f"line: {line}")
    to = email_to_phone(request.form["to"])
    print(f"to: {to}")
    sms = {
        "to": to,
        "from_": lookup.phone_for_email(envelope["from"]),
        "body": lines[0],
    }
    print(f"sms: {sms}")
    """
    except InvalidInput as e:
        print(e)
        return warn(str(e))
    """

    print(f"ALLES GUT HIER")

    # try:
    rv = twilio_api.messages.create(**sms)
    print(f"rv: {rv}")
    return rv.sid
    """
    except Exception as e:
        print("oh no")
        print(str(e))
        error_message = "Error sending message to Twilio"
        return warn(error_message), 444
    """


if __name__ == "__main__":
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get("PORT", 5000))
    if port == 5000 or True:
        app.debug = True
        print("in debug mode")
    app.run(host="0.0.0.0", port=port)
