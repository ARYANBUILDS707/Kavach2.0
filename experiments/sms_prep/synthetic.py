"""Explicitly synthetic benign hard negatives (M4.2, owner decision 4).

Legitimate-looking OTP, transaction, account-notification, delivery, appointment and utility
messages that share surface cues with phishing (links, urgency, "if this was not you") but are
benign. Everything is fictional and safe:

- institutions, couriers, merchants, clinics and utilities are invented names;
- links use the reserved `.invalid` TLD, so they can never resolve;
- phone numbers use the reserved fictional 555-01xx range;
- no real brand, person, account number or code is used (codes are random digits).

The corpus is deterministic for a seed. It is not collected data: every record carries
`origin = "synthetic"`, is reported separately from real-world evaluation, and never joins the
real-world test set. Template families are the split groups, so evaluation on held-out
templates measures generalization to unseen wording rather than memorized templates.
"""

import hashlib
import random
import string
from dataclasses import dataclass

GENERATOR_VERSION = 1
DEFAULT_SEED = 20261105
DEFAULT_PER_TEMPLATE = 10

BANKS = [
    "Northvale Bank", "Corvane Credit Union", "Halbrook Savings", "Tessmoor Bank",
    "Brightwater Trust", "Oakfield Federal Credit", "Marlow & Pike Bank", "Quillon Bank",
    "Ashgrove Building Society", "Redfern Mutual",
]  # fmt: skip
COURIERS = [
    "Parcelwick", "Swiftcrate Delivery", "Dovetail Couriers", "Kestrel Freight",
    "Lanternpost Express", "Mapleway Logistics",
]  # fmt: skip
MERCHANTS = [
    "Fenwick Outfitters", "Larkspur Home", "Tidewell Books", "Orchardline Market",
    "Pinecrest Electronics", "Bramble & Co", "Saltmarsh Cafe", "Wrenfield Pharmacy",
]  # fmt: skip
CLINICS = ["Eastmere Clinic", "Brightwater Dental", "Willowfield Health", "Cinderford Surgery"]
UTILITIES = ["Calder Power", "Harrowgate Water", "Ninefold Broadband", "Alderbank Gas"]
PAYERS = ["Tamsin Holt", "Rory Venn", "Ilse Marden", "Pavel Okonkwo", "Dara Lindqvist"]
FIRST_NAMES = ["Alex", "Sam", "Priya", "Jordan", "Maria", "Chen", "Omar", "Lena", "Noor", "Tobias"]
CURRENCIES = ["$", "£", "€", "Rs. "]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
MONTHS = ["January", "March", "May", "July", "September", "November"]
PREFIXES = ["", "", "", "Hi {first}, ", "Hello {first}. ", "Dear customer, "]
SUFFIXES = [
    "", "", "", " Reply HELP for help or STOP to opt out.", " Thank you.", " Msg&data rates may apply.",
]  # fmt: skip

# category -> six template families. Slots: {inst} {courier} {merchant} {clinic} {utility}
# {payer} {amount} {balance} {last4} {code} {mins} {when} {time} {time2} {ref} {tracking}
# {month} {link} {phone}
TEMPLATES: dict[str, list[str]] = {
    "otp_login": [
        "{code} is your {inst} verification code. It expires in {mins} minutes. Do not share this code with anyone, including {inst} staff.",
        "Your {inst} one-time passcode is {code}. Enter it to finish signing in. If you did not try to sign in, ignore this message.",
        "Use code {code} to log in to {inst} online banking. Valid for {mins} min. We will never call to ask for it.",
        "{inst}: {code} is your security code for signing in on a new device. Never forward it. Not you? Open the {inst} app and choose Report.",
        "Login code: {code}. It works once and expires at {time}. {inst} will never ask you for this code by phone or text.",
        "Hi, {code} is the code to verify your {inst} account email change. It expires in {mins} minutes.",
    ],
    "otp_payment": [
        "Your {inst} OTP for the {amount} payment to {merchant} is {code}. Valid for {mins} minutes. Do not share it.",
        "Confirm card payment: enter {code} to approve {amount} at {merchant} on your card ending {last4}. Not you? Call {phone} straight away.",
        "{code} is your one-time password to add {merchant} as a payee. It expires in {mins} minutes. {inst}",
        "{inst}: authorise transfer of {amount} to account ending {last4} with code {code}. Never share this code.",
        "Purchase code {code} for {amount} at {merchant}. If you did not request it, do not enter it and contact {inst} using the number on your card.",
        "To complete your online purchase of {amount} from {merchant}, enter {code}. Valid for {mins} minutes.",
    ],
    "bank_debit": [
        "{inst}: {amount} was spent on your card ending {last4} at {merchant} on {when}. Balance {balance}.",
        "Debit alert: {amount} withdrawn from account ending {last4} at {time}. Available balance {balance}. Queries: use the {inst} app.",
        "{inst} alert: a payment of {amount} to {merchant} cleared on {when}. Ref {ref}. Reply STOP to opt out of alerts.",
        "Card ending {last4} was used for {amount} at {merchant}. If this was you, no action is needed. {inst}",
        "Standing order of {amount} to {merchant} was paid today from your account ending {last4}.",
        "{inst}: ATM withdrawal of {amount} at {time}. Card ending {last4}. Remaining balance {balance}.",
    ],
    "bank_credit": [
        "{inst}: {amount} has been credited to your account ending {last4} on {when}. Available balance {balance}.",
        "Credit alert: salary of {amount} received at {time}. Account ending {last4}.",
        "Your refund of {amount} from {merchant} has been added to your card ending {last4}. Ref {ref}.",
        "{inst}: deposit of {amount} cleared on {when}. Balance now {balance}. Thank you for banking with us.",
        "Transfer received: {amount} from {payer} to account ending {last4}. Ref {ref}.",
        "Interest of {amount} was paid into your savings account ending {last4} today. {inst}",
    ],
    "account_notice": [
        "Your {inst} statement for {month} is ready. View it in the {inst} app or at {link}.",
        "{inst}: your password was changed on {when} at {time}. If this was you, nothing more to do. If not, open the app and lock your account.",
        "We have updated our terms of service from {when}. Read the summary at {link}. No action is needed. {inst}",
        "{inst}: you added a new payee ({merchant}) at {time}. If you did not do this, call {phone}.",
        "Your {inst} online banking profile was updated: mobile number changed. If you did not make this change, contact us through the app.",
        "{inst}: scheduled maintenance on {when} from 01:00 to 03:00. Online banking may be unavailable. Sorry for any trouble.",
    ],
    "card_notice": [
        "{inst}: your new card ending {last4} has been dispatched and should arrive within 5 working days. Activate it in the app.",
        "Your card ending {last4} has been activated. You can now use it in shops and online. {inst}",
        "{inst}: your card ending {last4} expires next month. Your replacement is on its way; no action needed.",
        "Travel notice added for card ending {last4} from {when}. Manage it in the {inst} app.",
        "Your card ending {last4} limit was changed to {amount} as you requested at {time}. {inst}",
        "{inst}: contactless payments on card ending {last4} were switched off at your request.",
    ],
    "delivery_dispatch": [
        "{courier}: your parcel from {merchant} has been dispatched. Track it at {link}. Tracking {tracking}.",
        "Good news! Order {ref} from {merchant} has shipped with {courier}. Estimated delivery {when}.",
        "{courier}: we have collected your parcel ({tracking}). You will get another message on the day of delivery.",
        "{merchant}: your order is on its way. Expected {when} between {time} and {time2}. Track: {link}",
        "{courier} update: parcel {tracking} left our depot at {time}. No action required.",
        "Your {merchant} order {ref} has been packed and handed to {courier}.",
    ],
    "delivery_out": [
        "{courier}: your parcel {tracking} is out for delivery today. Driver ETA {time}. Track live at {link}.",
        "Out for delivery: {merchant} order {ref}. Please make sure someone is home to sign for it.",
        "{courier}: your delivery window is {time}-{time2} today. Reply 1 to leave it with a neighbour.",
        "Your parcel is 5 stops away. Follow your driver at {link}. {courier}",
        "{courier}: your parcel arrives today. A signature is needed; photo ID may be requested.",
        "Heads up from {merchant}: your order {ref} is out for delivery with {courier} and should arrive by {time}.",
    ],
    "delivery_delivered": [
        "{courier}: parcel {tracking} was delivered at {time} and left in your safe place. Proof of delivery: {link}",
        "Delivered: {merchant} order {ref}. We hope you enjoy it! Rate your delivery at {link}.",
        "{courier}: your parcel was handed to {payer} at {time}. Questions? Use the help page at {link}.",
        "Your {merchant} order {ref} has been delivered to your front door. Reply STOP to unsubscribe.",
        "{courier}: delivery completed for {tracking}. Thanks for choosing us.",
        "Delivered at {time} today: parcel {tracking}. If something is missing, report it within 48 hours at {link}.",
    ],
    "delivery_slot": [
        "{courier}: we missed you. A new delivery is booked for {when} between {time} and {time2}. To change the slot, use your tracking page at {link}.",
        "{courier}: your parcel {tracking} could not be delivered today. We will try again {when}. No payment is needed.",
        "Your {merchant} order {ref} is held at the {courier} pickup point on the high street. Collect within 7 days with your order number.",
        "{courier}: choose a delivery day for parcel {tracking} at {link}. This service is free.",
        "Delivery attempt failed for {tracking}. Rebook free of charge at {link} or reply 2 to collect from the depot.",
        "{courier}: your parcel was returned to {merchant} at their request. Contact {merchant} for a refund of {amount}.",
    ],
    "appointment": [
        "{clinic}: reminder of your appointment on {when} at {time}. Reply C to confirm or R to reschedule.",
        "Reminder: check-up with {clinic} {when} at {time}. Please arrive 10 minutes early.",
        "{clinic}: your test results are ready. Please book a call with the nurse at {link} or ring {phone}.",
        "{clinic}: we need to move your appointment from {when} to a new time. Pick another slot at {link}.",
        "Your prescription at {clinic} is ready for collection. Open Monday to Friday, 9 to 5.",
        "{clinic}: thanks for visiting today. Your next check-up is due in six months.",
    ],
    "utility_notice": [
        "{utility}: your bill of {amount} is ready. It will be collected by direct debit on {when}. View at {link}.",
        "{utility}: planned supply interruption on {when} from {time} to {time2} in your area. We apologise for the inconvenience.",
        "{utility}: thank you, we received your payment of {amount} on {when}. Account ending {last4}.",
        "Meter reading reminder from {utility}: please submit your reading at {link} before {when}.",
        "{utility}: your engineer visit is booked for {when} between {time} and {time2}.",
        "{utility}: your direct debit amount will change to {amount} from next month. Details at {link}. No action needed.",
    ],
}  # fmt: skip

INSTITUTION_SLOTS = {
    "otp_login": BANKS, "otp_payment": BANKS, "bank_debit": BANKS, "bank_credit": BANKS,
    "account_notice": BANKS, "card_notice": BANKS,
}  # fmt: skip


@dataclass(frozen=True)
class SyntheticMessage:
    template_id: str
    category: str
    text: str


def slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def digits(rng: random.Random, low: int, high: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(rng.randint(low, high)))


def fill_slots(rng: random.Random, category: str) -> dict[str, str]:
    currency = rng.choice(CURRENCIES)

    def money(low: int, high: int) -> str:
        return f"{currency}{rng.randint(low, high)}.{rng.randint(0, 99):02d}"

    institution = rng.choice(INSTITUTION_SLOTS.get(category, BANKS))
    courier = rng.choice(COURIERS)
    utility = rng.choice(UTILITIES)
    clinic = rng.choice(CLINICS)
    host = slug(
        courier if category.startswith("delivery")
        else clinic if category == "appointment"
        else utility if category == "utility_notice"
        else institution
    )  # fmt: skip
    hour = rng.randint(7, 17)
    return {
        "inst": institution,
        "courier": courier,
        "merchant": rng.choice(MERCHANTS),
        "clinic": clinic,
        "utility": utility,
        "payer": rng.choice(PAYERS),
        "first": rng.choice(FIRST_NAMES),
        "amount": money(2, 900),
        "balance": money(100, 9000),
        "last4": digits(rng, 4, 4),
        "code": digits(rng, 4, 8),
        "mins": str(rng.choice([3, 5, 10, 15, 30])),
        "when": rng.choice(["today", "tomorrow", *WEEKDAYS]),
        "time": f"{hour}:{rng.choice(['00', '15', '30', '45'])}",
        "time2": f"{hour + rng.randint(1, 3)}:{rng.choice(['00', '30'])}",
        "ref": "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(8)),
        "tracking": "".join(rng.choice(string.ascii_uppercase) for _ in range(2))
        + digits(rng, 9, 9),
        "month": rng.choice(MONTHS),
        "link": f"https://{host}.invalid/{rng.choice(['t', 'track', 'a', 'help', 'view'])}/{digits(rng, 6, 6)}",
        "phone": f"555-01{rng.randint(0, 99):02d}",
    }


def template_ids() -> list[str]:
    return [
        f"{category}-{i + 1}" for category, items in TEMPLATES.items() for i in range(len(items))
    ]


def generate(
    seed: int = DEFAULT_SEED, per_template: int = DEFAULT_PER_TEMPLATE
) -> list[SyntheticMessage]:
    """Deterministic corpus: `per_template` distinct messages for every template family."""
    messages = []
    for category, items in TEMPLATES.items():
        for index, template in enumerate(items):
            template_id = f"{category}-{index + 1}"
            rng = random.Random(f"{seed}|{template_id}")
            seen: set[str] = set()
            attempts = 0
            while len(seen) < per_template and attempts < per_template * 50:
                attempts += 1
                slots = fill_slots(rng, category)
                text = (rng.choice(PREFIXES) + template + rng.choice(SUFFIXES)).format(**slots)
                seen.add(text)
            if len(seen) < per_template:
                raise RuntimeError(f"{template_id}: could not produce {per_template} variants")
            messages.extend(SyntheticMessage(template_id, category, t) for t in sorted(seen))
    return messages


def corpus_sha256(messages: list[SyntheticMessage]) -> str:
    lines = sorted(f"{m.template_id}\t{m.category}\t{m.text}" for m in messages)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
