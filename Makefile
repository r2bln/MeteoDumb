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

.PHONY: install uninstall check-node-exporter check-tty check

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
		echo "ERROR: no read/write access to $(DEVICE). Run as root (sudo make install) or add the user to the dialout group."; \
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
