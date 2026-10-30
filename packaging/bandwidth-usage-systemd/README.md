# bandwidth-usage-systemd

`bandwidth-usage-systemd` installs the receiver-side systemd integration for
Bandwidth Usage Modeling & Reporting. It watches an SFTP upload directory,
moves uploaded vnStat files into the report spool, and starts report generation
through the packaged reporter.

Install the reporter package first:

```sh
dnf install bandwidth-usage-reporter
dnf install bandwidth-usage-systemd
```

## Installed Units

The package installs:

```text
/usr/lib/systemd/system/bandwidth-usage-incoming.path
/usr/lib/systemd/system/bandwidth-usage-incoming.service
/usr/lib/systemd/system/bandwidth-usage-report.service
```

`bandwidth-usage-incoming.path` watches:

```text
/var/sftp/bandwidth-usage
```

When that directory changes, systemd starts
`bandwidth-usage-incoming.service`. That service runs
`bandwidth-usage-move-incoming`, moves regular files to the spool directory,
sets ownership to `bandwidth-usage:bandwidth-usage`, and orders
`bandwidth-usage-report.service` after the move.

`bandwidth-usage-report.service` is a oneshot service. It runs as:

```text
bandwidth-usage:bandwidth-usage
```

The service invokes `bandwidth-usage-run-report` from
`/usr/libexec/bandwidth-usage`. That helper reads `/etc/sysconfig/bandwidth-usage`
and then calls `/usr/bin/bandwidth-usage-report`.

Do not point the unit directly at
`/opt/bandwidth-usage-reporter/bw_rpts_report.py`. The `/opt` tree is the
reporter package's internal runtime. Direct invocation with the system Python
interpreter bypasses the packaged virtual environment and can fail unless
NumPy/SciPy are installed separately. The intended service interface is
`bandwidth-usage-run-report`.

## Accounts And Directories

The package defines these accounts with sysusers:

```text
bandwidth-usage
bandwidth-usage-upload
```

The package defines these directories with tmpfiles:

```text
/var/lib/bandwidth-usage                 0750 bandwidth-usage:bandwidth-usage
/var/sftp                                0755 root:root
/var/sftp/bandwidth-usage                0700 bandwidth-usage-upload:bandwidth-usage-upload
/var/spool/bandwidth-usage               0775 bandwidth-usage:bandwidth-usage
/var/spool/bandwidth-usage/.cache        0775 bandwidth-usage:bandwidth-usage
```

## Configuration

The configuration file is:

```text
/etc/sysconfig/bandwidth-usage
```

Fields:

```text
BANDWIDTH_USAGE_INCOMING_DIR=/var/sftp/bandwidth-usage
BANDWIDTH_USAGE_SPOOL_DIR=/var/spool/bandwidth-usage
BANDWIDTH_USAGE_OUTPUT_DIR=/var/spool/bandwidth-usage/.cache
BANDWIDTH_USAGE_REPORT=/usr/bin/bandwidth-usage-report
BANDWIDTH_USAGE_PRINT=1
BANDWIDTH_USAGE_LPR_OPTIONS="-o fit-to-page=true"
BANDWIDTH_USAGE_REPORT_DATE=
```

`BANDWIDTH_USAGE_PRINT` accepts `1`, `yes`, `true`, or `on` to print, and `0`,
`no`, `false`, or `off` to skip printing. Printing requires CUPS `lpr`; set
`BANDWIDTH_USAGE_PRINT=0` when the report host should only generate files.

When `BANDWIDTH_USAGE_REPORT_DATE` is empty, the reporter infers the report
date from the newest daily vnStat row.

## SSH/SFTP Credentials

The package installs an SSH server fragment:

```text
/etc/ssh/sshd_config.d/50-bandwidth-usage-sftp.conf
```

It restricts `bandwidth-usage-upload` to internal SFTP with:

```text
ChrootDirectory /var/sftp
ForceCommand internal-sftp -d /
```

The package does not ship SSH keys. Provision one sender public key for the
upload account. With the packaged account home of `/var/sftp`, the default
OpenSSH authorized-keys location is:

```text
/var/sftp/.ssh/authorized_keys
```

Recommended receiver-side ownership and modes:

```sh
install -d -o bandwidth-usage-upload -g bandwidth-usage-upload -m 0700 /var/sftp/.ssh
install -o bandwidth-usage-upload -g bandwidth-usage-upload -m 0600 sender.pub /var/sftp/.ssh/authorized_keys
```

The `authorized_keys` file contains public key lines, for example an
`ssh-ed25519` public key. Do not place private keys in the package or in the
receiver spool.

The remote vnStat host owns the corresponding private key. Keep it readable
only by the account that runs the upload script. The included pfSense example
uses the default SSH identity unless local deployment adds an explicit `scp -i`
option.

After provisioning keys or changing the SSH fragment, validate SSH configuration
and reload sshd according to local policy:

```sh
sshd -t
systemctl reload sshd
```

## Activation

Configure the report host in this order:

```sh
dnf install bandwidth-usage-reporter bandwidth-usage-systemd
editor /etc/sysconfig/bandwidth-usage
```

Provision the sender public key for `bandwidth-usage-upload`, validate sshd,
and reload sshd. Then enable the path unit:

```sh
systemctl daemon-reload
systemctl enable --now bandwidth-usage-incoming.path
```

Check the watcher:

```sh
systemctl status bandwidth-usage-incoming.path
```

Run report generation once through the unit:

```sh
systemctl start bandwidth-usage-report.service
```

Review logs:

```sh
journalctl -u bandwidth-usage-incoming.service -u bandwidth-usage-report.service
```

## Manual Upload Test

From the remote vnStat host, run the sender with verbose SSH output. The pfSense
example uses:

```sh
WAN_INTERFACE=bge0 REMOTE_HOST=receiver.example.net /root/upload_bw_stats.sh -v
```

Expected report-host result:

- uploaded JSON files appear under `/var/sftp/bandwidth-usage`;
- the path unit starts the incoming service;
- files move to `/var/spool/bandwidth-usage`;
- the report service writes JSON and PostScript output under
  `/var/spool/bandwidth-usage/.cache`;
- if printing is enabled, the PostScript report is submitted to `lpr`.

## Remote vnStat Host

The remote host runs vnStat and uploads JSON files. On pfSense, use the examples
packaged as documentation:

```text
/usr/share/doc/bandwidth-usage-systemd/pfsense/upload_bw_stats.sh
/usr/share/doc/bandwidth-usage-systemd/pfsense/upload_bw_stats.etc.cron.d
/usr/share/doc/bandwidth-usage-systemd/pfsense/README.md
```

These examples run on the remote host, not on the report host. They are included
in this RPM as documentation only and are not installed as active cron or system
configuration.

## Disabling

Disable future automatic processing:

```sh
systemctl disable --now bandwidth-usage-incoming.path
```

Stopping the path unit does not delete uploaded files, generated reports, SSH
keys, or account definitions.

## Troubleshooting

- Missing uploads: confirm the remote host runs vnStat, `jq`, and `scp`, and
  that `REMOTE_HOST`, `REMOTE_USER`, `REMOTE_PATH`, and `WAN_INTERFACE` match
  the deployment.
- SSH/SFTP failures: check `sshd -t`, the `Match User bandwidth-usage-upload`
  fragment, the sender public key, and `/var/sftp` chroot ownership. The chroot
  directory itself must remain `root:root` and not be writable by the upload
  user.
- Permission failures: check tmpfiles-created ownership for
  `/var/sftp/bandwidth-usage`, `/var/spool/bandwidth-usage`, and
  `/var/spool/bandwidth-usage/.cache`.
- Report failures: run `systemctl start bandwidth-usage-report.service` and
  inspect `journalctl -u bandwidth-usage-report.service`.
- Printing failures: install and configure CUPS `lpr`, or set
  `BANDWIDTH_USAGE_PRINT=0` and rerun the report service.
- Empty or stale reports: verify that both monthly and daily vnStat files are
  present in `/var/spool/bandwidth-usage` and match the names accepted by
  `bandwidth-usage-report`.

## Documentation

- Report command reference: `man bandwidth-usage-report`
- Receiver helper reference: `man bandwidth-usage-run-report`
