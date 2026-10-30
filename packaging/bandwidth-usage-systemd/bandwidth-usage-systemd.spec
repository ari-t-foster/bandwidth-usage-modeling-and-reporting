Name:           bandwidth-usage-systemd
Version:        1.0.0
Release:        1%{?dist}
Summary:        Receiver systemd integration for Bandwidth Usage Modeling & Reporting

License:        BSD-3-Clause
BuildArch:      noarch
Source0:        %{name}.tar.gz

BuildRequires:  systemd-rpm-macros
Requires:       bandwidth-usage-reporter
Requires:       bash
Requires:       coreutils
Requires:       openssh-server
Requires(post): systemd
Requires(preun): systemd
Requires(postun): systemd

%description
Systemd units, SFTP receiver configuration, runtime account definitions,
tmpfiles rules, configuration, and helper scripts for Bandwidth Usage Modeling
& Reporting receiver hosts.

%prep
%setup -q -n %{name}

%build
# Static integration files only.

%install
rm -rf %{buildroot}

install -D -m 0644 systemd/bandwidth-usage-incoming.path \
    %{buildroot}%{_unitdir}/bandwidth-usage-incoming.path
install -D -m 0644 systemd/bandwidth-usage-incoming.service \
    %{buildroot}%{_unitdir}/bandwidth-usage-incoming.service
install -D -m 0644 systemd/bandwidth-usage-report.service \
    %{buildroot}%{_unitdir}/bandwidth-usage-report.service

install -D -m 0755 libexec/bandwidth-usage-move-incoming \
    %{buildroot}%{_libexecdir}/bandwidth-usage/bandwidth-usage-move-incoming
install -D -m 0755 libexec/bandwidth-usage-run-report \
    %{buildroot}%{_libexecdir}/bandwidth-usage/bandwidth-usage-run-report

install -D -m 0644 man/bandwidth-usage-run-report.8 \
    %{buildroot}%{_mandir}/man8/bandwidth-usage-run-report.8

install -D -m 0644 config/bandwidth-usage \
    %{buildroot}%{_sysconfdir}/sysconfig/bandwidth-usage
install -D -m 0644 sshd/50-bandwidth-usage-sftp.conf \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-bandwidth-usage-sftp.conf
install -D -m 0644 sysusers/bandwidth-usage.conf \
    %{buildroot}%{_sysusersdir}/bandwidth-usage.conf
install -D -m 0644 tmpfiles/bandwidth-usage.conf \
    %{buildroot}%{_tmpfilesdir}/bandwidth-usage.conf

%post
if command -v systemd-sysusers >/dev/null; then
    systemd-sysusers %{_sysusersdir}/bandwidth-usage.conf || :
fi
%tmpfiles_create %{_tmpfilesdir}/bandwidth-usage.conf
%systemd_post bandwidth-usage-incoming.path

%preun
%systemd_preun bandwidth-usage-incoming.path

%postun
%systemd_postun bandwidth-usage-incoming.path

%files
%doc README.md
%doc examples/pfsense
%{_unitdir}/bandwidth-usage-incoming.path
%{_unitdir}/bandwidth-usage-incoming.service
%{_unitdir}/bandwidth-usage-report.service
%dir %{_libexecdir}/bandwidth-usage
%{_libexecdir}/bandwidth-usage/bandwidth-usage-move-incoming
%{_libexecdir}/bandwidth-usage/bandwidth-usage-run-report
%{_mandir}/man8/bandwidth-usage-run-report.8*
%config(noreplace) %{_sysconfdir}/sysconfig/bandwidth-usage
%config(noreplace) %{_sysconfdir}/ssh/sshd_config.d/50-bandwidth-usage-sftp.conf
%{_sysusersdir}/bandwidth-usage.conf
%{_tmpfilesdir}/bandwidth-usage.conf

%changelog
* Wed Sep 30 2026 Ari Foster <packages@scienceopera.net> - 1.0.0-1
- Initial receiver integration package.
