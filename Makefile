PREFIX       ?= /usr/local
BINDIR       ?= $(PREFIX)/bin
UNITDIR      ?= /etc/systemd/system
TEXTFILE_DIR ?= /var/lib/prometheus/node-exporter
DEVICE       ?= /dev/ttyUSB0
BAUD         ?= 115200
STALE_SECS   ?= 15

BIN_NAME     := meteo-exporter
SERVICE_NAME := meteo-exporter
SCRIPT       := meteo-exporter.sh
UNIT_FILE    := systemd/meteo-exporter.service
PROM_FILE    := $(TEXTFILE_DIR)/meteo.prom
DEFAULTS_FILE := /etc/default/$(SERVICE_NAME)

NODE_EXPORTER_SERVICES := prometheus-node-exporter node_exporter node-exporter

APRS_BIN_NAME      := aprs-beacon
APRS_SERVICE_NAME  := aprs-beacon
APRS_SCRIPT        := aprs-beacon.py
APRS_SERVICE_UNIT  := systemd/aprs-beacon.service
APRS_TIMER_UNIT    := systemd/aprs-beacon.timer
APRS_DEFAULTS_FILE := /etc/default/aprs-beacon
APRS_STATE_DIR     := /var/lib/aprs-beacon
APRS_STATE_FILE    := $(APRS_STATE_DIR)/last-sent

APRS_CALLSIGN ?=
APRS_LAT      ?=
APRS_LON      ?=
APRS_PASSCODE ?=
APRS_SERVER   ?= rotate.aprs2.ru:14580
APRS_INTERVAL ?= 600
APRS_COMMENT  ?= github.com/r2bln/MeteoDumb

.PHONY: install uninstall check-node-exporter check-tty check \
        aprs-install aprs-activate aprs-deactivate aprs-uninstall aprs-check check-aprs-config

install: check-node-exporter check-tty
	install -d -m 0755 $(TEXTFILE_DIR)
	install -m 0755 $(SCRIPT) $(BINDIR)/$(BIN_NAME)
	install -m 0644 $(UNIT_FILE) $(UNITDIR)/$(SERVICE_NAME).service
	printf 'METEO_DEVICE=%s\nMETEO_BAUD=%s\nMETEO_TEXTFILE_DIR=%s\n' "$(DEVICE)" "$(BAUD)" "$(TEXTFILE_DIR)" > $(DEFAULTS_FILE)
	chmod 0644 $(DEFAULTS_FILE)
	systemctl daemon-reload
	systemctl enable --now $(SERVICE_NAME).service
	@echo "Installed. Check status: systemctl status $(SERVICE_NAME)"
	@echo "Verify sensor data is flowing with: make check"

check-node-exporter:
	@found=""; \
	for svc in $(NODE_EXPORTER_SERVICES); do \
		if systemctl is-active --quiet "$$svc" 2>/dev/null; then \
			echo "Found active node_exporter service: $$svc"; \
			found="$$svc"; \
			break; \
		fi; \
	done; \
	if [ -z "$$found" ]; then \
		echo "ERROR: no active node_exporter systemd service found (tried: $(NODE_EXPORTER_SERVICES))."; \
		echo "Install and start prometheus-node-exporter with the textfile collector enabled first, then re-run 'make install'."; \
		exit 1; \
	fi

check-tty:
	@if [ ! -e "$(DEVICE)" ]; then \
		echo "ERROR: serial device $(DEVICE) not found. Is the sensor plugged in?"; \
		exit 1; \
	fi
	@if [ ! -c "$(DEVICE)" ]; then \
		echo "ERROR: $(DEVICE) exists but is not a character (serial) device."; \
		exit 1; \
	fi
	@if [ ! -r "$(DEVICE)" ] || [ ! -w "$(DEVICE)" ]; then \
		user="$${SUDO_USER:-$$(id -un)}"; \
		echo "ERROR: no read/write access to $(DEVICE) for user '$$user'."; \
		echo "Add the user to the group that owns the device and re-login, e.g.:"; \
		echo "  sudo usermod -aG $$(stat -c '%G' $(DEVICE)) $$user"; \
		echo "(log out and back in, or run 'newgrp $$(stat -c '%G' $(DEVICE))', for the group change to take effect)"; \
		echo "Alternatively, run 'sudo make install' so the check and the service itself use root."; \
		exit 1; \
	fi
	@echo "Serial device $(DEVICE) is present and accessible."

check:
	@if [ ! -f "$(PROM_FILE)" ]; then \
		echo "ERROR: $(PROM_FILE) does not exist. Is meteo-exporter running? (systemctl status $(SERVICE_NAME))"; \
		exit 1; \
	fi
	@ts=$$(awk '/^meteo_last_reading_timestamp_seconds/ {print $$2}' "$(PROM_FILE)"); \
	if [ -z "$$ts" ]; then \
		echo "ERROR: no meteo_last_reading_timestamp_seconds metric in $(PROM_FILE) yet."; \
		exit 1; \
	fi; \
	now=$$(date +%s); \
	age=$$(( now - $${ts%.*} )); \
	if [ "$$age" -gt $(STALE_SECS) ]; then \
		echo "ERROR: last reading is $${age}s old (> $(STALE_SECS)s) - meteo-exporter is not receiving fresh data."; \
		exit 1; \
	fi; \
	echo "OK: last reading $${age}s ago, meteo-exporter is receiving sensor data."

uninstall:
	-systemctl disable --now $(SERVICE_NAME).service
	rm -f $(UNITDIR)/$(SERVICE_NAME).service
	rm -f $(BINDIR)/$(BIN_NAME)
	rm -f $(DEFAULTS_FILE)
	systemctl daemon-reload
	rm -f $(PROM_FILE)
	@echo "Uninstalled."

# --- aprs-beacon (METEO-2) -------------------------------------------------
#
# install/uninstall only stage files and config - they never touch APRS-IS.
# activate/deactivate is the separate, explicit switch that starts/stops
# actually broadcasting the configured position to the public APRS-IS network.

check-aprs-config:
	@if [ -z "$(APRS_CALLSIGN)" ] || [ -z "$(APRS_LAT)" ] || [ -z "$(APRS_LON)" ]; then \
		echo "ERROR: APRS_CALLSIGN, APRS_LAT and APRS_LON are required, e.g.:"; \
		echo "  sudo make aprs-install APRS_CALLSIGN=R2BLN-13 APRS_LAT=55.9328 APRS_LON=36.0184"; \
		exit 1; \
	fi
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found."; exit 1; }

aprs-install: check-aprs-config
	install -d -m 0755 $(APRS_STATE_DIR)
	install -m 0755 $(APRS_SCRIPT) $(BINDIR)/$(APRS_BIN_NAME)
	install -m 0644 $(APRS_SERVICE_UNIT) $(UNITDIR)/$(APRS_SERVICE_NAME).service
	sed 's/^OnUnitActiveSec=.*/OnUnitActiveSec=$(APRS_INTERVAL)/' $(APRS_TIMER_UNIT) > $(UNITDIR)/$(APRS_SERVICE_NAME).timer
	chmod 0644 $(UNITDIR)/$(APRS_SERVICE_NAME).timer
	{ \
		printf 'APRS_CALLSIGN=%s\n' "$(APRS_CALLSIGN)"; \
		printf 'APRS_LAT=%s\n' "$(APRS_LAT)"; \
		printf 'APRS_LON=%s\n' "$(APRS_LON)"; \
		printf 'APRS_SERVER=%s\n' "$(APRS_SERVER)"; \
		printf 'APRS_COMMENT=%s\n' "$(APRS_COMMENT)"; \
		printf 'METEO_TEXTFILE_DIR=%s\n' "$(TEXTFILE_DIR)"; \
		if [ -n "$(APRS_PASSCODE)" ]; then printf 'APRS_PASSCODE=%s\n' "$(APRS_PASSCODE)"; fi; \
	} > $(APRS_DEFAULTS_FILE)
	chmod 0644 $(APRS_DEFAULTS_FILE)
	systemctl daemon-reload
	@echo "Installed (not activated) - nothing has been sent to APRS-IS."
	@echo "Review $(APRS_DEFAULTS_FILE), then run: sudo make aprs-activate"

aprs-activate:
	systemctl enable --now $(APRS_SERVICE_NAME).timer
	@echo "Activated: $(APRS_SERVICE_NAME).timer will beacon every $(APRS_INTERVAL)s from now on."
	@echo "This publicly broadcasts the configured position on APRS-IS. Verify with: make aprs-check"

aprs-deactivate:
	-systemctl disable --now $(APRS_SERVICE_NAME).timer
	@echo "Deactivated - no more beacons will be sent. Config and files left in place."
	@echo "Re-enable any time with: sudo make aprs-activate"

aprs-uninstall: aprs-deactivate
	rm -f $(UNITDIR)/$(APRS_SERVICE_NAME).service
	rm -f $(UNITDIR)/$(APRS_SERVICE_NAME).timer
	rm -f $(BINDIR)/$(APRS_BIN_NAME)
	rm -f $(APRS_DEFAULTS_FILE)
	systemctl daemon-reload
	rm -rf $(APRS_STATE_DIR)
	@echo "Uninstalled."

aprs-check:
	@if [ ! -f "$(APRS_STATE_FILE)" ]; then \
		echo "ERROR: $(APRS_STATE_FILE) does not exist yet."; \
		echo "Has aprs-beacon.timer fired since activation? (systemctl list-timers $(APRS_SERVICE_NAME).timer)"; \
		exit 1; \
	fi
	@ts=$$(cat "$(APRS_STATE_FILE)"); \
	now=$$(date +%s); \
	age=$$(( now - ts )); \
	stale=$$(( $(APRS_INTERVAL) * 2 )); \
	if [ "$$age" -gt "$$stale" ]; then \
		echo "ERROR: last successful beacon was $${age}s ago (> $${stale}s)."; \
		echo "Check: journalctl -u $(APRS_SERVICE_NAME).service"; \
		exit 1; \
	fi; \
	echo "OK: last beacon sent $${age}s ago."
