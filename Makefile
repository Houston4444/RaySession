#!/usr/bin/make -f
# Makefile for RaySession #
# ---------------------- #
# Created by houston4444
#
PREFIX ?= /usr/local
DESTDIR =
DEST_RAY := $(DESTDIR)$(PREFIX)/share/raysession

LINK = ln -s -f
PYUIC := pyuic5
PYRCC := pyrcc5

LRELEASE := lrelease
ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt5
endif

ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt4
endif

PYTHON := python3
ifeq (, $(shell which $(PYTHON)))
 PYTHON := python
endif

PATCHBAY_DIR=HoustonPatchbay

# ---------------------

all: PATCHBAY RES UI LOCALE

PATCHBAY:
	@(cd $(PATCHBAY_DIR) && $(MAKE))

# ---------------------
# Resources

RES: src/gui/resources_rc.py

src/gui/resources_rc.py: resources/resources.qrc
	$(PYRCC) $< -o $@

# ---------------------
# UI code

UI: mkdir_ui raysession ray_proxy

mkdir_ui:
	@if ! [ -e src/gui/ui ];then mkdir -p src/gui/ui; fi

raysession: src/gui/ui/abort_copy.py \
	    src/gui/ui/abort_session.py \
	    src/gui/ui/about_raysession.py \
	    src/gui/ui/add_application.py \
	    src/gui/ui/ardour_convert.py \
	    src/gui/ui/client_properties.py \
	    src/gui/ui/client_rename.py \
	    src/gui/ui/client_slot.py \
	    src/gui/ui/client_trash.py \
	    src/gui/ui/donations.py \
	    src/gui/ui/daemon_url.py \
	    src/gui/ui/error_dialog.py \
	    src/gui/ui/hydro_rh_nsm.py \
	    src/gui/ui/jack_config_info.py \
	    src/gui/ui/list_snapshots.py \
	    src/gui/ui/new_executable.py \
	    src/gui/ui/new_session.py \
	    src/gui/ui/nsm_properties.py \
	    src/gui/ui/ray_hack_copy.py \
	    src/gui/ui/nsm_open_info.py \
	    src/gui/ui/open_session.py \
	    src/gui/ui/preview_client_slot.py \
	    src/gui/ui/quit_app.py \
	    src/gui/ui/ray_hack_properties.py \
	    src/gui/ui/ray_net_properties.py \
	    src/gui/ui/ray_to_nsm.py \
	    src/gui/ui/raysession.py \
	    src/gui/ui/remove_template.py \
	    src/gui/ui/save_template_session.py \
	    src/gui/ui/session_scripts_info.py \
	    src/gui/ui/script_info.py \
	    src/gui/ui/script_user_action.py \
	    src/gui/ui/session_notes.py \
	    src/gui/ui/snapshot_name.py \
	    src/gui/ui/snapshots_info.py \
	    src/gui/ui/snapshot_progress.py \
	    src/gui/ui/startup_dialog.py \
	    src/gui/ui/systray_close.py \
	    src/gui/ui/systray_management.py \
	    src/gui/ui/stop_client.py \
	    src/gui/ui/stop_client_no_save.py \
	    src/gui/ui/template_slot.py \
	    src/gui/ui/waiting_close_user.py

src/gui/ui/%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@

ray_proxy: src/clients/proxy/ui_proxy_copy.py \
	   src/clients/proxy/ui_proxy_gui.py
	
src/clients/proxy/ui_%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
	
PY_CACHE:
	$(PYTHON) -m compileall src/
	
# ------------------------
# # Translations Files

LOCALE: locale

locale: locale/raysession_en.qm \
		locale/raysession_fr.qm \

locale/%.qm: locale/%.ts
	$(LRELEASE) $< -qm $@

# -------------------------

clean:
	@(cd $(PATCHBAY_DIR) && $(MAKE) $@)
	rm -f *~ src/*~ src/*.pyc  src/clients/proxy/ui_*.py \
	      src/gui/resources_rc.py  locale/*.qm
	rm -f -R src/gui/ui
	rm -f -R src/__pycache__ src/*/__pycache__ src/*/*/__pycache__ \
		  src/*/*/*/__pycache__

# -------------------------

debug:
	$(MAKE) DEBUG=true

# -------------------------

install:
	# Create directories
	install -d $(DESTDIR)$(PREFIX)/bin/
	install -d $(DESTDIR)$(PREFIX)/share/applications/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/16x16/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/24x24/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/32x32/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/64x64/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/96x96/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/256x256/apps/
	install -d $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/
	install -d $(DEST_RAY)/
	install -d $(DEST_RAY)/locale/
	install -d $(DEST_RAY)/$(PATCHBAY_DIR)/
	install -d $(DEST_RAY)/$(PATCHBAY_DIR)/locale/
	install -d $(DESTDIR)/etc/xdg/
	install -d $(DESTDIR)/etc/xdg/raysession/
	install -d $(DESTDIR)/etc/xdg/raysession/client_templates/
	
	# Copy Templates Factory
	cp -r client_templates/40_ray_nsm  $(DESTDIR)/etc/xdg/raysession/client_templates/
	cp -r client_templates/60_ray_lash $(DESTDIR)/etc/xdg/raysession/client_templates/
	cp -r client_templates  $(DEST_RAY)/
	cp -r session_templates $(DEST_RAY)/
	cp -r session_scripts   $(DEST_RAY)/
	cp -r data              $(DEST_RAY)/

	# Copy patchbay themes
	cp -r HoustonPatchbay/themes $(DEST_RAY)/$(PATCHBAY_DIR)/
	cp -r HoustonPatchbay/manual $(DEST_RAY)/$(PATCHBAY_DIR)/

	# Copy Desktop Files
	install -m 644 data/share/applications/*.desktop \
		$(DESTDIR)$(PREFIX)/share/applications/

	# Install icons
	install -m 644 resources/main_icon/16x16/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/16x16/apps/
	install -m 644 resources/main_icon/24x24/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/24x24/apps/
	install -m 644 resources/main_icon/32x32/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/32x32/apps/
	install -m 644 resources/main_icon/48x48/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -m 644 resources/main_icon/64x64/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/64x64/apps/
	install -m 644 resources/main_icon/96x96/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/96x96/apps/
	install -m 644 resources/main_icon/128x128/raysession.png \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/
	install -m 644 resources/main_icon/256x256/raysession.png \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/256x256/apps/

	# Install icons, scalable
	install -m 644 resources/main_icon/scalable/raysession.svg \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/

	# Install main code
	cp -r src $(DEST_RAY)/
	rm $(DEST_RAY)/src/gui/patchbay
	cp -r $(PATCHBAY_DIR)/patchbay $(DEST_RAY)/src/gui/
	
	$(LINK) $(DEST_RAY)/src/bin/ray-jack_checker_daemon $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray-jack_config_script  $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray-pulse2jack          $(DESTDIR)$(PREFIX)/bin/
	$(LINK) $(DEST_RAY)/src/bin/ray_git                 $(DESTDIR)$(PREFIX)/bin/
	
	# compile python files
	$(PYTHON) -m compileall $(DEST_RAY)/src/
	
	# install local manual
	cp -r manual $(DEST_RAY)/
	
	# install utility-scripts
	cp -r utility-scripts $(DEST_RAY)/
	
	# install main bash scripts to bin
	install -m 755 data/raysession  $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/ray-daemon  $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/ray_control $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/ray-proxy   $(DESTDIR)$(PREFIX)/bin/
	
	# modify PREFIX in main bash scripts
	sed -i "s?X-PREFIX-X?$(PREFIX)?" \
		$(DESTDIR)$(PREFIX)/bin/raysession \
		$(DESTDIR)$(PREFIX)/bin/ray-daemon \
		$(DESTDIR)$(PREFIX)/bin/ray_control \
		$(DESTDIR)$(PREFIX)/bin/ray-proxy
	
	# Install Translations
	install -m 644 locale/*.qm $(DEST_RAY)/locale/
	install -m 644 $(PATCHBAY_DIR)/locale/*.qm $(DEST_RAY)/$(PATCHBAY_DIR)/locale

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
	rm -rf $(DEST_RAY)
