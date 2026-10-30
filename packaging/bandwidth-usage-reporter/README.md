# bandwidth-usage-reporter

`bandwidth-usage-reporter` generates a one-page bandwidth usage report from
vnStat daily and monthly traffic exports. It reads vnStat JSON or CSV files,
builds a normalized bandwidth usage JSON document, scores it with the packaged
model, renders a PostScript report, and can optionally submit the report to
`lpr`.

The input usually comes from a remote vnStat host, such as pfSense, which
uploads monthly and daily vnStat JSON files to the receiver host. The companion
`bandwidth-usage-systemd` package owns that receiver workflow.

## Requirements

The RPM includes an isolated Python runtime under `/opt/bandwidth-usage-reporter`
with the Python interpreter support files required by the reporter and these
frozen Python dependencies:

- `numpy==2.4.6`
- `scipy==1.17.1`

Printing requires CUPS `lpr`; disable printing when CUPS is not installed or
not configured.

## Installation

Install the reporter RPM:

```sh
dnf install bandwidth-usage-reporter
```

The supported executable is:

```text
/usr/bin/bandwidth-usage-report
```

The files under `/opt/bandwidth-usage-reporter` are package internals. The
wrapper sets up the packaged Python runtime before executing the report script.
Do not configure systemd units or operator procedures to run the internal script
there directly. In particular,
`python3 /opt/bandwidth-usage-reporter/bw_rpts_report.py` uses the system
interpreter and will not have the packaged NumPy/SciPy dependencies unless the
environment is recreated manually, which is not the intended runtime interface.

For receiver-side operation, install `bandwidth-usage-systemd` and let
`bandwidth-usage-run-report` invoke the reporter through the packaged wrapper.

## Basic Use

Generate JSON and PostScript output without printing:

```sh
bandwidth-usage-report \
    --input-dir /path/to/vnstat-files \
    --output-dir /tmp/bandwidth-usage-report
```

Generate a sample report from the packaged example data:

```sh
mkdir -p /tmp/bandwidth-usage-sample
bandwidth-usage-report \
    --input-dir /usr/share/doc/bandwidth-usage-reporter/bw_sample_data/raw \
    --output-dir /tmp/bandwidth-usage-sample \
    --date 2026-08-31
```

Use an explicit report date:

```sh
bandwidth-usage-report \
    --input-dir /path/to/vnstat-files \
    --output-dir /tmp/bandwidth-usage-report \
    --date 260525
```

Print only when `lpr` is installed and the printer is configured:

```sh
bandwidth-usage-report \
    --input-dir /path/to/vnstat-files \
    --output-dir /tmp/bandwidth-usage-report \
    --print \
    --lpr-option "-o fit-to-page=true"
```

## Input Files

The reporter looks for the newest matching files in the input directory.

Monthly input names:

```text
monthly.vnstat.*.json
monthly.vnstat.json
monthly.vnstat.*.csv
monthly.vnstat.csv
vnstat.monthly.csv
```

Daily input names:

```text
daily.vnstat.*.json
daily.vnstat.json
daily.vnstat.*.csv
daily.vnstat.csv
vnstat.daily.csv
```

## Documentation

- Command reference: `man bandwidth-usage-report`
- Sample raw vnStat data:
  `/usr/share/doc/bandwidth-usage-reporter/bw_sample_data/raw`
- Receiver integration: install `bandwidth-usage-systemd` and read its README
- Remote pfSense sender example: packaged as documentation by
  `bandwidth-usage-systemd`
