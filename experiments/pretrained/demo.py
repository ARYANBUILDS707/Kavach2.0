"""Fictional demonstration SMS for the pretrained proof of concept.

Every message was written for this file. None is copied from a dataset, a real message or the
simulator scenarios. Brands are invented, links use the reserved `.example` domain (RFC 2606),
and there are no real phone numbers, names or account numbers.

`intent` is what the author wrote the message to look like. It is not an audited label. With
14 hand-written items, agreement with it is a smoke test of the pipeline, never an accuracy figure.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoMessage:
    id: str
    intent: str  # phishing | scam | spam | legitimate
    description: str
    text: str
    fictional: bool = True


DEMO_MESSAGES: tuple[DemoMessage, ...] = (
    DemoMessage("demo-01", "phishing", "bank account block with link",
                "FICTIONAL DEMO: Dear customer, your Examplebank account will be blocked today. "
                "Update your KYC now at http://examplebank-kyc.example/verify"),
    DemoMessage("demo-02", "phishing", "parcel customs fee with link",
                "FICTIONAL DEMO: Your FakeCourier parcel is on hold. Pay Rs 25 customs fee within "
                "24 hours: https://fakecourier-redelivery.example/pay"),
    DemoMessage("demo-03", "phishing", "one-time code theft",
                "FICTIONAL DEMO: This is Examplebank security. To stop a suspicious payment, reply "
                "with the 6-digit OTP we just sent you."),
    DemoMessage("demo-04", "phishing", "tax refund lure",
                "FICTIONAL DEMO: Income tax refund of Rs 14,500 approved. Submit your card details "
                "to receive it: http://refund-portal.example/claim"),
    DemoMessage("demo-05", "phishing", "electricity disconnection threat",
                "FICTIONAL DEMO: Your electricity will be disconnected tonight at 9.30 pm because "
                "the last bill was not updated. Call the officer immediately on the number in "
                "this message."),
    DemoMessage("demo-06", "scam", "family impersonation, new number",
                "FICTIONAL DEMO: Hi Mum, I dropped my phone, this is my new number. Can you send "
                "Rs 8,000 urgently? I will explain later."),
    DemoMessage("demo-07", "scam", "part-time job advance fee",
                "FICTIONAL DEMO: Earn Rs 5,000 daily from home liking videos. Pay a Rs 499 "
                "registration fee to start: http://easy-earn.example"),
    DemoMessage("demo-08", "phishing", "Hinglish account suspension",
                "FICTIONAL DEMO: Aapka Examplebank account band ho jayega. Turant link par click "
                "karke PAN update karein: http://pan-update.example"),
    DemoMessage("demo-09", "spam", "retail promotion",
                "FICTIONAL DEMO: Mega Sale at ShopFictional! Flat 50% off on all shoes this "
                "weekend only. Visit your nearest store. T&C apply."),
    DemoMessage("demo-10", "spam", "prize text",
                "FICTIONAL DEMO: Congratulations! You have won a free holiday voucher. Reply WIN "
                "to claim before midnight."),
    DemoMessage("demo-11", "legitimate", "genuine-looking one-time code",
                "FICTIONAL DEMO: 482913 is your Examplebank login code. It expires in 5 minutes. "
                "Never share this code with anyone, including bank staff."),
    DemoMessage("demo-12", "legitimate", "delivery update without payment",
                "FICTIONAL DEMO: Your FakeCourier order has been delivered to the front desk. "
                "Thank you for shopping with us."),
    DemoMessage("demo-13", "legitimate", "debit alert",
                "FICTIONAL DEMO: Rs 1,250 debited from your Examplebank account ending 0000 at "
                "a grocery store. Not you? Call the number on the back of your card."),
    DemoMessage("demo-14", "legitimate", "personal chat",
                "FICTIONAL DEMO: Running 10 minutes late, start dinner without me. See you soon!"),
)  # fmt: skip
