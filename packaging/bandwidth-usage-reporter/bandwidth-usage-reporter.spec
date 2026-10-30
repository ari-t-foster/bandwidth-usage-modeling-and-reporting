%define __brp_check_rpaths %{nil}
%global debug_package %{nil}
%define __os_install_post %{nil}
%undefine _missing_build_ids_terminate_build
%global __requires_exclude_from ^/opt/bandwidth-usage-reporter/venv/.*$

Name:           bandwidth-usage-reporter
Version:        1.0.0
Release:        1%{?dist}
Summary:        Bandwidth Usage Modeling & Reporting application

License:        BSD-3-Clause
Source0:        app_build.tar.gz

BuildRequires:  python3
Requires:       python3

%description
Production scoring and report-generation application for Bandwidth Usage
Modeling & Reporting. The package includes the checked-in reporter scripts and
an isolated Python runtime with the frozen NumPy/SciPy dependencies.

%global _distroname %{name}
%global _script1 bw_rpts_report.py
%global _script2 score_bandwidth_usage.py
%global _entrypoint bandwidth-usage-report

%prep
%setup -q -n app_build

%build
# No build steps required for the scripts themselves

%install
rm -rf %{buildroot}

mkdir -p %{buildroot}/opt/%{_distroname}
install -m 0755 %{_script1} %{_script2} %{buildroot}/opt/%{_distroname}/
install -m 0644 frozen_requirements.txt %{buildroot}/opt/%{_distroname}/
cp -a venv %{buildroot}/opt/%{_distroname}/venv

mkdir -p %{buildroot}%{_bindir}
install -m 0755 %{_entrypoint} %{buildroot}%{_bindir}/%{_entrypoint}

install -D -m 0644 man/bandwidth-usage-report.1 \
    %{buildroot}%{_mandir}/man1/bandwidth-usage-report.1

# The venv is generated below build/ before rpmbuild. Keep installed helper
# shebangs and activation metadata pointed at the final RPM location.
find %{buildroot}/opt/%{_distroname}/venv/bin -type f \
    -exec sed -i \
        -e "1s|^#!.*reporter-env/bin/python.*|#!/opt/%{_distroname}/venv/bin/python3|" \
        -e "s|%{buildroot}||g" \
        {} +
sed -i \
    -e "s|%{buildroot}||g" \
    -e "s|build/reporter-env|opt/%{_distroname}/venv|g" \
    %{buildroot}/opt/%{_distroname}/venv/pyvenv.cfg

%files
%doc README.md
%doc examples/bw_sample_data
%{_bindir}/%{_entrypoint}
%{_mandir}/man1/bandwidth-usage-report.1*
%dir /opt/%{_distroname}
/opt/%{_distroname}/%{_script1}
/opt/%{_distroname}/%{_script2}
/opt/%{_distroname}/frozen_requirements.txt
/opt/%{_distroname}/venv/

%clean
rm -rf %{buildroot}

%changelog
* Wed Sep 30 2026 Ari Foster <packages@scienceopera.net> - 1.0.0-1
- Build from the repository-local generated reporter runtime.

* Wed May 27 2026 Ari Foster <packages@scienceopera.net> - 1.0
- Initial build.
