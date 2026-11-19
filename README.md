# Using Apple Shortcuts to Monitor Financial Data

### Disclaimer
These scripts and their output are provided for informational and convenience purposes only, “as is,” without warranties of any kind. They are not financial, investment, tax, or legal advice, and should not be relied on as the basis for financial decisions. Market data and summaries may be delayed, incomplete, inaccurate, or unavailable; verify information independently before acting.

You are responsible for protecting your API keys, reviewing and running the scripts, and deciding whether to rely on or share their output. If you use Apple Shortcuts or other third-party services, your data may be processed under those providers’ terms and privacy practices. Review the output and confirm recipients before sending it.

KRSS.llc does not guarantee that the scripts or services will operate without errors or interruptions. To the fullest extent permitted by law, KRSS.llc disclaims responsibility for losses or damages arising from the scripts, their output, or related third-party services.

## Swing-entry screening

`sma_alert.py` checks the configured tickers for a 1% breakout, volume
confirmation, rising 50-day SMA, 20-day SMA momentum, ATR extension, the
and average daily dollar volume. It writes a readable latest-run summary to
`sma_alert.log` and stdout, including rejection reasons and proposed stop and
target levels for potential setups. It does not place orders.

The earnings-calendar and 10-session time-stop checks are omitted because
they require manual date tracking.

## Testing each script

1. These scripts and procedures are intended for [macOS 27.x.x and Apple Shortcuts App](https://support.apple.com/guide/shortcuts/welcome/ios)
2. Read the top of each script for any program language dependencies and ensure they are installed
3. Execute the script using the command line ```python3 script.py```

## Using Shortcuts (macOS)

1. Open the Apple Shortcuts App, create a new Shortcut
2. First shortcut block type: Run Shell Script
Shell: python3
Input: Input
Pass Input: to stdin
Copy and paste the script into the provided script block. Ensure you input your API key.
3. Second shortcut block type: Text
Text value: Shell Script Result
4. Third shortcut block type: Use Cloud model
Model value: Summarize this financial market news data and inlcude the urls in the output: Text
5. Fourth shortcut block type: Send
Send value: Replace recipients with the iMessage recipients
6. Using the Terminal App, input a [cron](https://simplecrontab.com/guides/macos-cron-setup/) for when you want the shortcut to execute ```0 7 * * 1-5 shortcuts run "The name of your shortcut"```

Recipients will receive an iMessage containing the script output when the cron job executes or on demand as you manually trigger the shortcut from the Apple shortcuts app.
