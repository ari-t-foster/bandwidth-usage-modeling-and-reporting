#
SHELL=/bin/sh
PATH=/etc:/bin:/sbin:/usr/bin:/usr/sbin

# See crontab(5) for field format.
0       3       *       *       *       root    /root/upload_bw_stats.sh || true
