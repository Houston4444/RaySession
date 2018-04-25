#!/usr/bin/make -f
# Makefile for RaySession #
# ---------------------- #
# Created by houston4444
#

PREFIX  = /usr/local
DESTDIR =

LINK   = ln -s
PYUIC ?= pyuic5
PYRCC ?= pyrcc5
LRELEASE ?= lrelease-qt4
# -----------------------------------------------------------------------------------------------------------------------------------------

all: RES UI LOCALE

# -----------------------------------------------------------------------------------------------------------------------------------------
# Resources

RES: src/resources_rc.py

src/resources_rc.py: resources/resources.qrc
	$(PYRCC) $< -o $@

# -----------------------------------------------------------------------------------------------------------------------------------------
# UI code

UI: raysession

raysession: src/ui_raysession.py src/ui_about_raysession.py src/ui_client_slot.py src/ui_new_executable.py \
	src/ui_new_session.py src/ui_open_session.py src/ui_proxy_gui.py src/ui_quit_app.py src/ui_abort_session.py src/ui_error_dialog.py src/ui_proxy_copy.py src/ui_nsm_open_info.py src/ui_save_template_session.py src/ui_add_application.py src/ui_client_properties.py src/ui_stop_client.py src/ui_abort_copy.py src/ui_client_trash.py


src/ui_%.py: resources/ui/%.ui
	$(PYUIC) $< -o $@
# -----------------------------------------------------------------------------------------------------------------------------------------
# # Translations Files

LOCALE: locale

locale: locale/raysession_fr_FR.qm locale/raysession_en_EN.qm

locale/%.qm: locale/%.ts
	$(LRELEASE) $< -qm $@
# -----------------------------------------------------------------------------------------------------------------------------------------

clean:
	rm -f *~ src/*~ src/*.pyc src/ui_*.py src/resources_rc.py locale/*.qm
	rm -f -R src/__pycache__
# -----------------------------------------------------------------------------------------------------------------------------------------

debug:
	$(MAKE) DEBUG=true

# -----------------------------------------------------------------------------------------------------------------------------------------

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
	install -d $(DESTDIR)$(PREFIX)/share/raysession/
	install -d $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -d $(DESTDIR)$(PREFIX)/share/raysession/locale/
	
	# Copy Client Templates Factory
	cp -r client_templates  $(DESTDIR)$(PREFIX)/share/raysession/
	cp -r session_templates $(DESTDIR)$(PREFIX)/share/raysession/

# 	# Install script files and binaries
	install -m 755 data/raysession                    $(DESTDIR)$(PREFIX)/bin/ 
	install -m 755 data/ray-daemon                    $(DESTDIR)$(PREFIX)/bin/ 
# 	install -m 755 data/ray-proxy                     $(DESTDIR)$(PREFIX)/bin/
	
	install -m 644 data/*.desktop                     $(DESTDIR)$(PREFIX)/share/applications/

	# Install icons
	install -m 644 resources/16x16/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/16x16/apps/
	install -m 644 resources/24x24/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/24x24/apps/
	install -m 644 resources/32x32/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/32x32/apps/
	install -m 644 resources/48x48/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -m 644 resources/48x48/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/48x48/apps/
	install -m 644 resources/64x64/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/64x64/apps/
	install -m 644 resources/96x96/raysession.png     $(DESTDIR)$(PREFIX)/share/icons/hicolor/96x96/apps/
	install -m 644 resources/128x128/raysession.png   $(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/
	install -m 644 resources/256x256/raysession.png   $(DESTDIR)$(PREFIX)/share/icons/hicolor/256x256/apps/

	# Install icons, scalable
	install -m 644 resources/scalable/raysession.svg  $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/

	# Install main code
	install -m 755 src/raysession        $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -m 755 src/ray-daemon        $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -m 755 src/ray-proxy         $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -m 755 src/ray-jackpatch     $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -m 755 src/sooperlooper_lash $(DESTDIR)$(PREFIX)/share/raysession/src/
	install -m 644 src/*.py $(DESTDIR)$(PREFIX)/share/raysession/src/
	
	# Install Translations
	install -m 644 locale/*.qm $(DESTDIR)$(PREFIX)/share/raysession/locale/
	
	# Adjust PREFIX value in script file
	sed -i "s?X-PREFIX-X?$(PREFIX)?" $(DESTDIR)$(PREFIX)/bin/raysession
	sed -i "s?X-PREFIX-X?$(PREFIX)?" $(DESTDIR)$(PREFIX)/bin/ray-daemon
# 	sed -i "s?X-PREFIX-X?$(PREFIX)?" $(DESTDIR)$(PREFIX)/bin/ray-proxy
# -----------------------------------------------------------------------------------------------------------------------------------------

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/raysession
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-daemon
	rm -f $(DESTDIR)$(PREFIX)/bin/ray-proxy
	rm -f $(DESTDIR)$(PREFIX)/share/applications/raysession.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/*/apps/raysession.png
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/raysession.svg
	rm -rf $(DESTDIR)$(PREFIX)/share/raysession/
