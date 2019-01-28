#!/usr/bin/make -f
# Makefile for RaySession #
# ---------------------- #
# Created by houston4444
#
PREFIX  = /usr/local
DESTDIR =
DEST_RAY := $(DESTDIR)$(PREFIX)/share/raysession

LINK = ln -s
PYUIC := pyuic5
PYRCC := pyrcc5

LRELEASE := lrelease
ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt5
endif

ifeq (, $(shell which $(LRELEASE)))
 LRELEASE := lrelease-qt4
endif

# -----------------------------------------------------------------------------------------------------------------------------------------

all: RES UI LOCALE

# -----------------------------------------------------------------------------------------------------------------------------------------
# Resources

RES: src/gui/resources_rc.py

src/gui/resources_rc.py: resources/resources.qrc
	$(PYRCC) $< -o $@

# -----------------------------------------------------------------------------------------------------------------------------------------
# UI code

UI: raysession ray_proxy

raysession: src/gui/ui_abort_copy.py \
	    src/gui/ui_abort_session.py \
	    src/gui/ui_about_raysession.py \
	    src/gui/ui_add_application.py \
	    src/gui/ui_client_properties.py \
	    src/gui/ui_client_slot.py \
	    src/gui/ui_client_trash.py \
	    src/gui/ui_edit_executable.py \
	    src/gui/ui_daemon_url.py \
	    src/gui/ui_error_dialog.py \
	    src/gui/ui_list_snapshots.py \
	    src/gui/ui_new_executable.py \
	    src/gui/ui_new_session.py \
	    src/gui/ui_nsm_open_info.py \
	    src/gui/ui_open_session.py \
	    src/gui/ui_quit_app.py \
	    src/gui/ui_raysession.py \
	    src/gui/ui_save_template_session.py \
	    src/gui/ui_snapshot_name.py \
	    src/gui/ui_snapshot_progress.py \
	    src/gui/ui_stop_client.py

src/gui/ui_%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
	
ray_proxy: src/clients/proxy/ui_proxy_copy.py \
	   src/clients/proxy/ui_proxy_gui.py
	
src/clients/proxy/ui_%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
# -----------------------------------------------------------------------------------------------------------------------------------------
# # Translations Files

LOCALE: locale

locale: locale/raysession_fr_FR.qm locale/raysession_en_EN.qm

locale/%.qm: locale/%.ts
	$(LRELEASE) $< -qm $@
# -----------------------------------------------------------------------------------------------------------------------------------------

clean:
	rm -f *~ src/*~ src/*.pyc src/gui/ui_*.py src/clients/proxy/ui_*.py \
	      src/gui/resources_rc.py locale/*.qm
	rm -f -R src/__pycache__ src/*/__pycache__ src/*/*/__pycache__
# -----------------------------------------------------------------------------------------------------------------------------------------

debug:
	$(MAKE) DEBUG=true

# -----------------------------------------------------------------------------------------------------------------------------------------

install:
	#clean unwanted __pycache__ folders
	rm -f -R src/__pycache__ src/*/__pycache__ src/*/*/__pycache__
	
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
	
	# Copy Client Templates Factory
	cp -r client_templates  $(DEST_RAY)/
	cp -r session_templates $(DEST_RAY)/
	
	# Copy Desktop Files
	install -m 644 data/*.desktop $(DESTDIR)$(PREFIX)/share/applications/

	# Install icons
	install -m 644 resources/16x16/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/16x16/apps/
	install -m 644 resources/24x24/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/24x24/apps/
	install -m 644 resources/32x32/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/32x32/apps/
	install -m 644 resources/48x48/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -m 644 resources/48x48/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -m 644 resources/64x64/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/64x64/apps/
	install -m 644 resources/96x96/raysession.png   \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/96x96/apps/
	install -m 644 resources/128x128/raysession.png \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/
	install -m 644 resources/256x256/raysession.png \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/256x256/apps/

	# Install icons, scalable
	install -m 644 resources/scalable/raysession.svg \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/

	# Install main code
	cp -r src $(DEST_RAY)/
	
	# install main bash scripts to bin
	install -m 755 data/raysession $(DESTDIR)$(PREFIX)/bin/
	install -m 755 data/ray-daemon $(DESTDIR)$(PREFIX)/bin/
	
	# modify PREFIX in main bash scripts
	sed -i "s?X-PREFIX-X?$(PREFIX)?" \
		$(DESTDIR)$(PREFIX)/bin/raysession \
		$(DESTDIR)$(PREFIX)/bin/ray-daemon
	
	# Install Translations
	install -m 644 locale/*.qm $(DEST_RAY)/locale/
	-----------------------------------------------------------------------------------------------------------------------------------------

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/raysession
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-daemon
	rm -f $(DESTDIR)$(PREFIX)/share/applications/raysession.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/*/apps/raysession.png
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/raysession.svg
	rm -rf $(DEST_RAY)
