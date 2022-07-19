#!/usr/bin/make -f
# Makefile for houston_patchbay #
# ---------------------- #
# Created by houston4444
#

PYUIC := pyuic5
PYRCC := pyrcc5

LRELEASE := lrelease
ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt5
endif

ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt4
endif

# ---------------------

all: RES UI LOCALE

# ---------------------
# Resources

RES: patchbay/resources_rc.py

patchbay/resources_rc.py: resources/resources.qrc
	$(PYRCC) $< -o $@

# ---------------------
# UI code

UI: mkdir_ui patchbay 

mkdir_ui:
	@if ! [ -e patchbay/ui ];then mkdir -p patchbay/ui; fi

patchbay: patchbay/ui/canvas_options.py \
		patchbay/ui/canvas_port_info.py \
		patchbay/ui/filter_frame.py \
		patchbay/ui/patchbay_tools.py

patchbay/ui/%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
		
# ------------------------
# # Translations Files

LOCALE: locale

locale: locale/patchbay_en.qm  \
		locale/patchbay_fr.qm

locale/%.qm: locale/%.ts
	$(LRELEASE) $< -qm $@

locale/%.qm: locale/%.ts
	$(LRELEASE) $< -qm $@

# -------------------------

clean:
	rm -f *~ patchbay/resources_rc.py \
			 locale/*.qm
	rm -f -R patchbay/ui \
			 patchbay/__pycache__ \
			 patchbay/*/__pycache__ \
			 patchbay/*/*/__pycache__

# -------------------------

debug:
	$(MAKE) DEBUG=true

# -------------------------
