"""Send one explicit SMTP smoke-test message to a controlled mailbox.

Run from apps/api after configuring the production secret manager:
  python scripts/send_test_email.py controlled-mailbox@example.com --send
No message is sent unless --send is supplied.
"""
import argparse
import asyncio
from datetime import datetime, timezone

from app.config import settings, validate_production_settings
from app.emailer import send_email


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipient", help="A mailbox you control for delivery verification")
    parser.add_argument("--send", action="store_true", help="Explicitly authorize sending one real test email")
    args = parser.parse_args()
    if not args.send:
        parser.error("No email sent. Re-run with --send after verifying the recipient.")
    validate_production_settings()
    await send_email(
        args.recipient,
        "EDITFLOW AI SMTP delivery test",
        "This is a one-time SMTP smoke test.\n"
        f"Sent at {datetime.now(timezone.utc).isoformat()}\n"
        "If this message arrived, SMTP transport accepted the message. "
        "Also verify inbox placement and SPF/DKIM/DMARC results in your mail provider.",
    )
    print(f"SMTP message accepted for delivery to {args.recipient}. Check inbox and spam folders.")


if __name__ == "__main__":
    asyncio.run(main())
