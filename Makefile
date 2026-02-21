#!/usr/bin/make -f
# Makefile for RaySession #
# ---------------------- #
# Created by houston4444
#
PREFIX ?= /usr/local
DESTDIR =
DEST_RAY := $(DESTDIR)$(PREFIX)/share/raysession

LINK = ln -s -f
LRELEASE ?= lrelease
RCC ?= rcc
QT_VERSION ?= 6

# if you set QT_VERSION environment variable to 5 at the make command
# it will choose the other commands QT_API, pyuic5, pylupdat56.

ifeq ($(QT_VERSION), 6)
	QT_API ?= PyQt6
	PYUIC ?= pyuic6
	PYLUPDATE ?= pylupdate6
	RCC_EXEC := $(shell which $(RCC))
	RCC_QT6_DEB := /usr/lib/qt6/libexec/rcc

	ifeq (, ${RCC_EXEC})
		RCC := ${RCC_QT6_DEB}
	else
		ifeq ($(shell readlink ${RCC_EXEC}), qtchooser)
			ifeq ($(shell test -x ${RCC_QT6_DEB} | echo $$?), 0)
				RCC := ${RCC_QT6_DEB}
			endif
		endif
	endif

	ifeq (, $(shell which $(LRELEASE)))
		LRELEASE := lrelease-qt6
	endif

else
	QT_API ?= PyQt5
	PYUIC ?= pyuic5
	PYLUPDATE ?= pylupdate5
	ifeq (, $(shell which $(LRELEASE)))
		LRELEASE := lrelease-qt5
	endif
endif

# neeeded for make install
BUILD_CFG_FILE := src/shared/qt_api.py
QT_API_INST := $(shell grep ^QT_API= $(BUILD_CFG_FILE) 2>/dev/null| cut -d'=' -f2| cut -d"'" -f2)
QT_API_INST ?= PyQt5

ICON_SIZES := 16 24 32 48 64 96 128 256

PYTHON := python3
ifeq (, $(shell which $(PYTHON)))
	PYTHON := python
endif

PATCHBAY_DIR=HoustonPatchbay

# ---------------------

all: PATCHBAY QT_PREPARE RES UI LOCALE

PATCHBAY:
	@(cd $(PATCHBAY_DIR) && $(MAKE))

QT_PREPARE:
	$(info compiling for Qt$(QT_VERSION) using $(QT_API))
	$(file > $(BUILD_CFG_FILE),QT_API='$(QT_API)')

    ifneq ($(QT_API), $(QT_API_INST))
		rm -f *~ src/*~ src/*.pyc src/frontend/ui/*.py \
		    resources/locale/*.qm src/resources_rc.py
    endif
	install -d src/gui/ui

# ---------------------
# Resources

RES: src/gui/resources_rc.py

src/gui/resources_rc.py: resources/resources.qrc
	${RCC} -g python $< |sed 's/ PySide. / qtpy /' > $@

# ---------------------
# UI code

UI: $(shell \
	ls resources/ui/*.ui| sed 's|\.ui$$|.py|'| sed 's|^resources/|src/gui/|')

src/gui/ui/%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
	
# ------------------------
# # Translations Files

LOCALE: locale

locale: locale/raysession_en.qm \
		locale/raysession_fr.qm \

locale/%.qm: locale/%.ts
	-$(LRELEASE) $< -qm $@

# -------------------------

clean:
	@(cd $(PATCHBAY_DIR) && $(MAKE) $@)
	rm -f *~ src/*~ src/*.pyc src/gui/resources_rc.py locale/*.qm
	rm -f -R src/gui/ui
	rm -f -R src/__pycache__ src/*/__pycache__ src/*/*/__pycache__ \
		  src/*/*/*/__pycache__
	rm -f src/shared/qt_api.py

# -------------------------

debug:
	$(MAKE) DEBUG=true

# -------------------------

install: uninstall pure_install

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/raysession
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-daemon
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-proxy
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-jack_checker_daemon
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-jack_config_script
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-pulse2jack
	rm -f $(DESTDIR)$(PREFIX)/bin/ray_control
	rm -f $(DESTDIR)$(PREFIX)/bin/ray_git
	
	rm -f $(DESTDIR)$(PREFIX)/share/applications/raysession.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/*/apps/raysession.png
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/raysession.svg
	rm -rf $(DESTDIR)/etc/xdg/raysession/client_templates/40_ray_nsm
	rm -rf $(DESTDIR)/etc/xdg/raysession/client_templates/60_ray_lash
	rm -f $(DESTDIR)/etc/bash_completion.d/ray_completion.sh
	rm -f $(DESTDIR)$(PREFIX)/share/bash-completion/completions/ray_control
	rm -rf $(DEST_RAY)

pure_install:
	# Create directories
	install -d $(DESTDIR)$(PREFIX)/bin/
	install -d $(DESTDIR)$(PREFIX)/share/applications/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/
	install -d $(DEST_RAY)/
	install -d $(DEST_RAY)/locale/
	install -d $(DEST_RAY)/$(_DIR)/
	install -d $(DEST_RAY)/$(PATCHBAY_DIR)/locale/
	install -d $(DESTDIR)/etc/xdg/raysession/client_templates/
	install -d $(DESTDIR)$(PREFIX)/share/bash-completion/completions/
	
	# Install icons
	for sz in $(ICON_SIZES);do \
		install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/$${sz}x$${sz}/apps/ ;\
		install -m 644 resources/main_icon/$${sz}x$${sz}/raysession.png \
			$(DESTDIR)$(PREFIX)/share/icons/hicolor/$${sz}x$${sz}/apps/ ;\
	done

	# Copy Templates Factory
	cp -r client_templates/40_ray_nsm  $(DESTDIR)/etc/xdg/raysession/client_templates/
	cp -r client_templates/60_ray_lash $(DESTDIR)/etc/xdg/raysession/client_templates/
	cp -r client_templates  $(DEST_RAY)/
	cp -r session_templates $(DEST_RAY)/
	cp -r session_scripts   $(DEST_RAY)/
	cp -r data              $(DEST_RAY)/

	# Copy completion script
	cp -r src/completion/ray_completion.sh $(DESTDIR)$(PREFIX)/share/bash-completion/completions/ray_control
	sed -i "s|XXX_PYCOMPLETION_XXX|$(DEST_RAY)/src/completion|" \
		$(DESTDIR)$(PREFIX)/share/bash-completion/completions/ray_control

	# Copy patchbay themes, manual and lib
	cp -r HoustonPatchbay/themes $(DEST_RAY)/$(PATCHBAY_DIR)/
	cp -r HoustonPatchbay/manual $(DEST_RAY)/$(PATCHBAY_DIR)/
	cp -r HoustonPatchbay/source $(DEST_RAY)/$(PATCHBAY_DIR)/

	# Copy Desktop Files
	install -m 644 data/share/applications/*.desktop \
		$(DESTDIR)$(PREFIX)/share/applications/

	# Install icons, scalable
	install -m 644 resources/main_icon/scalable/raysession.svg \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/

	# Install main code
	cp -r src $(DEST_RAY)/

	$(LINK) $(DEST_RAY)/src/bin/ray-jack_checker_daemon $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray-jack_config_script  $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray-pulse2jack          $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray_git                 $(DESTDIR)$(PREFIX)/bin/
	
	# compile python files
	$(PYTHON) -m compileall $(DEST_RAY)/HoustonPatchbay/source/
	$(PYTHON) -m compileall $(DEST_RAY)/src/
	
	# install local manual
	cp -r manual $(DEST_RAY)/
	
	# install utility-scripts
	cp -r utility-scripts $(DEST_RAY)/
	
	# install main bash scripts to bin
	install -m 755 data/bin/raysession  $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/bin/ray-daemon  $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/bin/ray_control $(DESTDIR)$(PREFIX)/bin/
	
	# Install Translations
	install -m 644 locale/*.qm $(DEST_RAY)/locale/
	install -m 644 $(PATCHBAY_DIR)/locale/*.qm $(DEST_RAY)/$(PATCHBAY_DIR)/locale


