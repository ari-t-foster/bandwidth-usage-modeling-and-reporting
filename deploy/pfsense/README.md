# pfSense Sender Deployment

This directory contains the pfSense-side sender material for Bandwidth Usage
Modeling & Reporting. It is deployed manually. The receiver RPM may include
these files as documentation examples, but it does not install them as active
pfSense or report-host configuration.

## Prerequisites

- pfSense Traffic Totals, including `vnstat`
- `jq`
- SSH/SFTP access to the receiver
- The WAN interface name used by vnStat, for example `bge0`

## Configuration

Install `upload_bw_stats.sh` on the pfSense host, commonly as:

```sh
/root/upload_bw_stats.sh
```

The script defaults are generic and can be overridden in the environment:

```sh
WAN_INTERFACE=bge0
REMOTE_USER=bandwidth-usage-upload
REMOTE_HOST=receiver.example.net
REMOTE_PATH=bandwidth-usage/
LOCAL_FOLDER=/root/.upload_bw_stats
```

Create the local staging directory:

```sh
mkdir -p /root/.upload_bw_stats
chmod 700 /root/.upload_bw_stats
```

Generate or reuse a dedicated SSH key for the sender. Provision the public key
for the receiver-side upload account according to the receiver administrator's
policy. Do not store private keys in this repository.

## Receiver Path

The packaged receiver expects restricted SFTP uploads to land under:

```text
/var/sftp/bandwidth-usage
```

With the packaged SSH chroot, the sender uses the remote path:

```text
bandwidth-usage/
```

## Cron

Use `upload_bw_stats.etc.cron.d` as the cron.d template. Review the path to the
installed script, then install it on pfSense using the local administrative
process.

## Manual Test

Run the sender once with verbose SSH output:

```sh
WAN_INTERFACE=bge0 REMOTE_HOST=receiver.example.net /root/upload_bw_stats.sh -v
```

Expected receiver-side result:

- monthly and daily vnStat JSON files appear in the receiver incoming path;
- `bandwidth-usage-incoming.path`, when enabled on the receiver, moves them to
  `/var/spool/bandwidth-usage`;
- the report service generates output under
  `/var/spool/bandwidth-usage/.cache`.

## Rollback

Remove the cron entry and the deployed sender script. Remove the dedicated SSH
public key from the receiver account if this sender should no longer upload.
