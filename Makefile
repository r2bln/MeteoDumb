PREFIX       ?= /usr/local
BINDIR       ?= $(PREFIX)/bin
UNITDIR      ?= /etc/systemd/system
TEXTFILE_DIR ?= /var/lib/prometheus/node-exporter

BIN_NAME     := meteo-exporter
SERVICE_NAME := meteo-exporter
SCRIPT       := meteo-exporter.sh
UNIT_FILE    := systemd/meteo-exporter.service
PROM_FILE    := $(TEXTFILE_DIR)/meteo.prom

NODE_EXPORTER_SERVICES := prometheus-node-exporter node_exporter node-exporter

.PHONY: install uninstall check-node-exporter

install: check-node-exporter
	install -d -m 0755 $(TEXTFILE_DIR)
	install -m 0755 $(SCRIPT) $(BINDIR)/$(BIN_NAME)
	install -m 0644 $(UNIT_FILE) $(UNITDIR)/$(SERVICE_NAME).service
	systemctl daemon-reload
	systemctl enable --now $(SERVICE_NAME).service
	@echo "Installed. Check status: systemctl status $(SERVICE_NAME)"

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

uninstall:
	-systemctl disable --now $(SERVICE_NAME).service
	rm -f $(UNITDIR)/$(SERVICE_NAME).service
	rm -f $(BINDIR)/$(BIN_NAME)
	systemctl daemon-reload
	rm -f $(PROM_FILE)
	@echo "Uninstalled."
