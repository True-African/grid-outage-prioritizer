# Voice Note Setup

The dashboard includes a voice-note option for owners who prefer hearing the plan instead of reading a chart or SMS.

## What It Does

The same forecast and appliance plan used for the SMS digest are converted into a short spoken instruction:

```text
KTT Power voice note for Neighborhood salon. Highest outage risk is 19:00-20:00. Switch off Hair dryer and Hair straightener first. Keep LED lighting, Phone charging, Mobile money router, Hair clippers, and TV/radio on if backup allows. If internet is not available, use the cached plan for 6 hours. After that, use critical only mode.
```

The exact words update when the current forecast, business, or alert changes.

## Browser Playback

1. Start the dashboard:

```bash
python dashboard.py
```

2. Open:

```text
http://127.0.0.1:8000
```

3. Select a business.
4. Click **Play voice prompt**.

The browser reads the current instruction aloud using the built-in Web Speech feature. This does not require a backend audio service.

## Saved WAV Voice Note

Click **Save voice note** to create a local `.wav` file.

On Windows, the app uses the built-in SAPI text-to-speech engine through PowerShell. Generated audio is saved under:

```text
outputs/voice_notes/
```

That folder is ignored by Git because voice files are demo artifacts, not source code.

If audio generation is not available on the machine, the dashboard still shows the transcript. The transcript can be read aloud, played by browser speech, or recorded manually.

## Why This Matters

This is the concrete non-reader workflow:

- A salon owner clicks one button and hears the action.
- The message names appliances, not model scores.
- It includes the offline fallback: use cached plan for 6 hours, then critical-only mode.
- It can be translated to Kinyarwanda using the same template.
