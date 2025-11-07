# ![RaySession Logo](https://raw.githubusercontent.com/Houston4444/RaySession/master/resources/main_icon/128x128/raysession.png) RaySession

What is RaySession ?
---------------------

![Screenshot](https://raw.githubusercontent.com/Houston4444/RaySession/master/resources/screenshots/Screenshot_20211203_173011.png)

RaySession is a GNU/Linux session manager for audio programs such as Ardour, Carla, QTractor, Guitarix, Patroneo, Jack Mixer, etc...<br>
The principle is to load together audio programs, then be able to save or close all documents together.<br>
Its main purpose is to manage NSM compatible programs, but it also helps for other programs.<br>
<br>
it benefits from a nice patchbay, a [complete manual](https://raysession.tuxfamily.org/en/manual) and a [web site](https://raysession.tuxfamily.org) .<br>

An integrated client can save and restore JACK connections.<br>
Except this, RaySession doesn't deals with JACK, the recommended user behavior is to use it when JACK is already started.<br>

Features
---------------------

* Load many programs together and remember their documents and jack connections in an unified folder
* Nice patchbay with stereo connections, wrappable boxes and a search tool
* Snapshot at each save (optional), then you can go back to the snapshot (it uses `git`)
* Save client as template, and then restore it easily
* Save session as template
* Make almost all actions and get several informations with the CLI named `ray_control`
* Script sessions and clients actions with shell scripts
* Remember and recall JACK configuration with the jack_config session scripts
* Having sub-sessions working through the network with the "Network Session" template
* Remember the virtual desktop of the programs (requires `wmctrl`, doesn't works with Wayland)
* Bookmark the current session folder in your file manager and file pickers (gtk, kde, qt, fltk)
* Many others...


![Screenshot](https://raw.githubusercontent.com/Houston4444/RaySession/master/resources/screenshots/Screenshot_20211203_162333.png)


Install
---------------------

read [INSTALL.md](INSTALL.md)


Infos
---------------------

You can see documentation on NSM protocol at: https://new-session-manager.jackaudio.org/api/index.html

RaySession is being developed by Mathieu Picot (houston4444), using Python3 and qtpy.
