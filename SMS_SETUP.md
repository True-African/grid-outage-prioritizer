# SMS Setup

The dashboard can send the same SMS digest that it displays on screen.

## Default: Dry Run

By default, no real SMS is sent.

When you click **Send SMS digest**, messages are written to:

```text
outputs/sms_outbox.jsonl
```

This lets judges verify the exact messages without needing paid SMS credentials.

## Configure Recipients

Option 1: environment variable

```powershell
$env:KTT_SMS_RECIPIENTS="+2507XXXXXXXX,+2507YYYYYYYY"
```

Option 2: local file

Copy:

```text
sms_recipients.example.json
```

to:

```text
sms_recipients.local.json
```

Then edit:

```json
{
  "recipients": ["+2507XXXXXXXX"]
}
```

`sms_recipients.local.json` is ignored by Git so real phone numbers are not published.

## Configure Real Twilio SMS

Set:

```powershell
$env:KTT_SMS_PROVIDER="twilio"
$env:TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWILIO_AUTH_TOKEN="your_auth_token"
$env:TWILIO_FROM_NUMBER="+1XXXXXXXXXX"
$env:KTT_SMS_RECIPIENTS="+2507XXXXXXXX"
python dashboard.py
```

Open:

```text
http://127.0.0.1:8000
```

Click:

```text
Send SMS digest
```

## Notes

- Keep every SMS under 160 characters.
- Do not commit API keys or phone numbers.
- For the hackathon demo, dry-run mode is enough to prove the workflow.
- For field deployment in Rwanda, the provider can be swapped for a local SMS aggregator by replacing `send_sms` in `sms_sender.py`.

