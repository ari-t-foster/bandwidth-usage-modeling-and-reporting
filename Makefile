SHELL := /bin/bash

PYTHON      ?= python3
PIPREQS     ?= pipreqs
RPMBUILD    ?= rpmbuild

ROOT        := $(CURDIR)
BUILD       := $(ROOT)/build
DIST        := $(ROOT)/dist

REPORTER    := $(ROOT)/reporter
ANALYSIS    := $(ROOT)/analysis
EXAMPLES    := $(ROOT)/examples

VENV        := $(BUILD)/reporter-env
RPMTOP      := $(BUILD)/rpmbuild
REPORTER_STAGE := $(BUILD)/reporter-stage
REPORTER_SOURCE := $(RPMTOP)/SOURCES/app_build.tar.gz
SYSTEMD_STAGE := $(BUILD)/systemd-stage
SYSTEMD_SOURCE := $(RPMTOP)/SOURCES/bandwidth-usage-systemd.tar.gz

REPORTER_SPEC := $(ROOT)/packaging/bandwidth-usage-reporter/bandwidth-usage-reporter.spec
REPORTER_PKG  := $(ROOT)/packaging/bandwidth-usage-reporter
REPORTER_BIN  := $(ROOT)/packaging/bandwidth-usage-reporter/bin/bandwidth-usage-report
REPORTER_SAMPLE_RAW := $(EXAMPLES)/bw_sample_data/raw
SYSTEMD_SPEC  := $(ROOT)/packaging/bandwidth-usage-systemd/bandwidth-usage-systemd.spec
SYSTEMD_SRC   := $(ROOT)/packaging/bandwidth-usage-systemd
PFSENSE_SRC   := $(ROOT)/deploy/pfsense

.PHONY: all deps lock model reporter \
        rpm-reporter rpm-systemd rpms check \
        smoke clean distclean

all: rpms

#
# Dependency maintenance
#

deps:
	rm -f $(REPORTER)/requirements.in
	$(PIPREQS) $(REPORTER) \
	    --force \
	    --savepath $(REPORTER)/requirements.in

lock: deps
	rm -rf $(BUILD)/lock-env
	$(PYTHON) -m venv $(BUILD)/lock-env
	$(BUILD)/lock-env/bin/pip install --upgrade pip
	$(BUILD)/lock-env/bin/pip install \
	    -r $(REPORTER)/requirements.in
	$(BUILD)/lock-env/bin/pip freeze \
	    > $(REPORTER)/requirements.lock
	rm -rf $(BUILD)/lock-env

#
# Optional model regeneration.
# Do NOT make normal RPM builds depend on this.
#

model:
	$(MAKE) -C $(ANALYSIS) model

#
# Reproduce the former app_build/ environment.
#

$(VENV)/.built: $(REPORTER)/requirements.lock
	rm -rf $(VENV)
	mkdir -p $(BUILD)
	$(PYTHON) -m venv --copies $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install \
	    -r $(REPORTER)/requirements.lock
	pyver="$$($(VENV)/bin/python -c 'import sys; print(f"python{sys.version_info[0]}.{sys.version_info[1]}")')" ; \
	stdlib="$$($(VENV)/bin/python -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')" ; \
	libdir="$$($(VENV)/bin/python -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")')" ; \
	mkdir -p "$(VENV)/lib64/$$pyver" ; \
	rsync -a --delete \
	    --exclude site-packages \
	    --exclude __pycache__ \
	    --exclude test \
	    --exclude tests \
	    "$$stdlib/" "$(VENV)/lib64/$$pyver/" ; \
	if [ -n "$$libdir" ]; then \
	    cp -a "$$libdir"/libpython*.so* "$(VENV)/lib64/" ; \
	fi
	touch $@

reporter: $(VENV)/.built

#
# RPM build tree
#

$(RPMTOP):
	mkdir -p $(RPMTOP)/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

$(REPORTER_SOURCE): $(VENV)/.built \
                    $(REPORTER)/bw_rpts_report.py \
                    $(REPORTER)/score_bandwidth_usage.py \
                    $(REPORTER)/requirements.lock \
                    $(REPORTER_PKG)/README.md \
                    $(REPORTER_PKG)/man/bandwidth-usage-report.1 \
                    $(shell find $(REPORTER_SAMPLE_RAW) -type f 2>/dev/null) \
                    $(REPORTER_BIN) | $(RPMTOP)
	rm -rf $(REPORTER_STAGE)
	mkdir -p $(REPORTER_STAGE)/app_build/man
	mkdir -p $(REPORTER_STAGE)/app_build/examples/bw_sample_data
	install -m 0755 $(REPORTER)/bw_rpts_report.py \
	    $(REPORTER_STAGE)/app_build/bw_rpts_report.py
	install -m 0755 $(REPORTER)/score_bandwidth_usage.py \
	    $(REPORTER_STAGE)/app_build/score_bandwidth_usage.py
	install -m 0644 $(REPORTER)/requirements.lock \
	    $(REPORTER_STAGE)/app_build/frozen_requirements.txt
	install -m 0755 $(REPORTER_BIN) \
	    $(REPORTER_STAGE)/app_build/bandwidth-usage-report
	install -m 0644 $(REPORTER_PKG)/README.md \
	    $(REPORTER_STAGE)/app_build/README.md
	install -m 0644 $(REPORTER_PKG)/man/bandwidth-usage-report.1 \
	    $(REPORTER_STAGE)/app_build/man/bandwidth-usage-report.1
	cp -a $(REPORTER_SAMPLE_RAW) \
	    $(REPORTER_STAGE)/app_build/examples/bw_sample_data/raw
	cp -a $(VENV) $(REPORTER_STAGE)/app_build/venv
	rm -f $(REPORTER_STAGE)/app_build/venv/.built \
	    $(REPORTER_STAGE)/app_build/venv/.gitignore \
	    $(REPORTER_STAGE)/app_build/venv/bin/f2py \
	    $(REPORTER_STAGE)/app_build/venv/bin/numpy-config \
	    $(REPORTER_STAGE)/app_build/venv/bin/pip \
	    $(REPORTER_STAGE)/app_build/venv/bin/pip3 \
	    $(REPORTER_STAGE)/app_build/venv/bin/pip3.*
	find $(REPORTER_STAGE)/app_build/venv/bin -type f \
	    -exec sed -i '1s|^#!$(VENV)/bin/python.*|#!/opt/bandwidth-usage-reporter/venv/bin/python3|' {} +
	tar -C $(REPORTER_STAGE) -czf $@ app_build

$(SYSTEMD_SOURCE): $(SYSTEMD_SPEC) \
                  $(SYSTEMD_SRC)/README.md \
                  $(shell find $(SYSTEMD_SRC)/config $(SYSTEMD_SRC)/libexec $(SYSTEMD_SRC)/man $(SYSTEMD_SRC)/sshd $(SYSTEMD_SRC)/sysusers $(SYSTEMD_SRC)/systemd $(SYSTEMD_SRC)/tmpfiles $(PFSENSE_SRC) -type f 2>/dev/null) | $(RPMTOP)
	rm -rf $(SYSTEMD_STAGE)
	mkdir -p $(SYSTEMD_STAGE)/bandwidth-usage-systemd
	cp -a $(SYSTEMD_SRC)/README.md \
	    $(SYSTEMD_SRC)/config \
	    $(SYSTEMD_SRC)/libexec \
	    $(SYSTEMD_SRC)/man \
	    $(SYSTEMD_SRC)/sshd \
	    $(SYSTEMD_SRC)/sysusers \
	    $(SYSTEMD_SRC)/systemd \
	    $(SYSTEMD_SRC)/tmpfiles \
	    $(SYSTEMD_STAGE)/bandwidth-usage-systemd/
	mkdir -p $(SYSTEMD_STAGE)/bandwidth-usage-systemd/examples
	cp -a $(PFSENSE_SRC) \
	    $(SYSTEMD_STAGE)/bandwidth-usage-systemd/examples/pfsense
	tar -C $(SYSTEMD_STAGE) -czf $@ bandwidth-usage-systemd

rpm-reporter: $(REPORTER_SOURCE)
	$(RPMBUILD) -bb $(REPORTER_SPEC) \
	    --define "_topdir $(RPMTOP)"
	mkdir -p $(DIST)
	find $(RPMTOP)/RPMS -type f -name '*.rpm' \
	    -exec cp -f {} $(DIST)/ \;

rpm-systemd: $(SYSTEMD_SOURCE)
	$(RPMBUILD) -bb $(SYSTEMD_SPEC) \
	    --define "_topdir $(RPMTOP)"
	mkdir -p $(DIST)
	find $(RPMTOP)/RPMS -type f -name '*.rpm' \
	    -exec cp -f {} $(DIST)/ \;

rpms: rpm-reporter rpm-systemd

check:
	$(PYTHON) -m py_compile $(REPORTER)/*.py
	bash -n $(SYSTEMD_SRC)/libexec/*
	bash -n $(REPORTER_BIN)

smoke: reporter
	$(VENV)/bin/python \
	    $(REPORTER)/bw_rpts_report.py \
	    --input-dir $(ROOT)/analysis/example_input \
	    --output-dir $(BUILD)/smoke-output

clean:
	rm -rf $(BUILD)

distclean: clean
	rm -rf $(DIST)
