# Bandwidth Usage Modeling and Reporting

## Description

This repository contains a bandwidth-capacity modeling analysis and a companion reporting workflow for vnStat traffic data. The analysis examines usage distributions and capacity-planning assumptions; the operational tooling converts daily and monthly vnStat exports into normalized JSON, scores them with the packaged model, and generates a one-page PostScript report.

The repository includes the Jupyter analysis and source workbook, reporting scripts, Fedora RPM packaging, pfSense sender and systemd receiver integration, and sample inputs and outputs. It is not necessary to configure pfSense, SFTP, or systemd to inspect the sample data or run the reporter manually.

## Project Case Study

The methodology, model comparisons, findings, and limitations are covered in the [project case study](https://scienceopera.net/projects/bandwidth-usage-modeling-and-reporting).

## Licensing and data

The original code in this repository is licensed under BSD-3-Clause; see [LICENSE](LICENSE).

The analysis workbook includes figures transcribed manually from published reports. These numerical observations are distinguished from the reports' own narrative, figures, and presentation. Consult the project case study for the data sources and methodological limitations.

## Repository layout

```
├── analysis
│   ├── allData.ods
│   └── Analysis.ipynb
├── deploy
│   └── pfsense
│       ├── README.md
│       ├── upload_bw_stats.etc.cron.d
│       └── upload_bw_stats.sh
├── dist
│   ├── bandwidth-usage-reporter-1.0.0-1.fc44.x86_64.rpm
│   └── bandwidth-usage-systemd-1.0.0-1.fc44.noarch.rpm
├── examples
│   └── bw_sample_data
│       ├── previously_generated
│       │   ├── bandwidth_usage.260831.json
│       │   └── bandwidth_usage.260831.ps
│       └── raw
│           ├── daily.vnstat.260831.json
│           └── monthly.vnstat.260831.json
├── LICENSE
├── Makefile
├── packaging
│   ├── bandwidth-usage-reporter
│   │   ├── bandwidth-usage-reporter.spec
│   │   ├── bin
│   │   │   └── bandwidth-usage-report
│   │   ├── man
│   │   │   └── bandwidth-usage-report.1
│   │   └── README.md
│   └── bandwidth-usage-systemd
│       ├── bandwidth-usage-systemd.spec
│       ├── config
│       │   └── bandwidth-usage
│       ├── libexec
│       │   ├── bandwidth-usage-move-incoming
│       │   └── bandwidth-usage-run-report
│       ├── man
│       │   └── bandwidth-usage-run-report.8
│       ├── README.md
│       ├── sshd
│       │   └── 50-bandwidth-usage-sftp.conf
│       ├── systemd
│       │   ├── bandwidth-usage-incoming.path
│       │   ├── bandwidth-usage-incoming.service
│       │   └── bandwidth-usage-report.service
│       ├── sysusers
│       │   └── bandwidth-usage.conf
│       └── tmpfiles
│           └── bandwidth-usage.conf
├── README.md
└── reporter
    ├── bw_rpts_report.py
    ├── requirements.in
    ├── requirements.lock
    └── score_bandwidth_usage.py
```

- **`analysis/`** — Jupyter notebook (`Analysis.ipynb`) and supporting spreadsheet (`allData.ods`) for the usage-distribution and capacity modeling work. The original analysis environment used Python 3.13.3.
- **`deploy/pfsense/`** — Example sender script and cron template for collecting vnStat data on pfSense and transferring exports to the receiver. See its [README](deploy/pfsense/README.md).
- **`dist/`** — Prebuilt Fedora 44 RPM artifacts for the reporter and systemd receiver integration. The corresponding RPM specs and packaging sources are under `packaging/`.
- **`examples/bw_sample_data/`** — Sample daily/monthly vnStat inputs and previously generated JSON/PostScript outputs, allowing an offline demonstration without deploying the sender or receiver.
- **`packaging/`** — RPM specifications, executable wrapper, service helpers, configuration templates, systemd units, SSH/SFTP configuration, account/directory definitions, and manual pages. See the [reporter package README](packaging/bandwidth-usage-reporter/README.md) and [receiver package README](packaging/bandwidth-usage-systemd/README.md).
- **`reporter/`** — Python report-generation and scoring implementation, plus Python dependency declarations and lockfile.
- **`Makefile`** — Project build entry point, including RPM packaging.

## Try the sample report

After installing the `bandwidth-usage-reporter` RPM on a compatible Fedora system, generate output from the supplied example inputs:

```sh
mkdir -p /tmp/bandwidth-usage-sample
bandwidth-usage-report \
    --input-dir /usr/share/doc/bandwidth-usage-reporter/bw_sample_data/raw \
    --output-dir /tmp/bandwidth-usage-sample \
    --date 2026-08-31
```

The packaged command generates JSON and PostScript files without printing unless `--print` is requested. For installation details, prerequisites, receiver configuration, and troubleshooting, refer to the component READMEs linked above.
