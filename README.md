# ![RaySession Logo](https://raw.githubusercontent.com/Houston4444/RaySession/master/resources/128x128/raysession.png) RaySession

What is RaySession ?
---------------------

RaySession is a GNU/Linux session manager for audio programs such as Ardour, Carla, QTractor, Patroneo etc...<br>
The principle is to load together audio programs, then be able to save or close all documents together.<br>
It communicates with programs using the Non Session Manager API, so programs compatible with NSM are also compatible with RaySession.<br>
<br>
An integrated client can save and restore JACK connections.<br>
Except this, RaySession doesn't deals with JACK, the recommended user behavior is to use it when JACK is already started.<br>

Features
---------------------

* Factory templates for NSM and LASH compatible applications
* Possibility to save any client as template
* Save session as template
* Remember if client was started or not
* Make a snapshot at each session save and allow to go backward in time (requires git)
* Make almost all actions and get several informations with the CLI named ray_control
* Script sessions and clients actions with shell scripts
* Remember and recall JACK configuration with the jack_config session scripts
* Having sub-sessions working through the network with the "Network Session" template
* Bookmark the current session folder in your file manager and file pickers (gtk, kde, qt, fltk)
* Remember the virtual desktop of the programs (requires wmctrl)
* Abort session allmost anytime
* Possibility to KILL client if clean exit is too long
* Restore or remove definitely a client in the trash
* Open Session Folder button (open default file manager)

Screenshot
---------------------

![Screenshot](https://raw.githubusercontent.com/Houston4444/RaySession/master/resources/screenshots/Screenshot_20200625_142130.png)


You can see documentation on NSM at: http://non.tuxfamily.org/wiki/Non%20Session%20Manager

RaySession is being developed by houston4444, using Python3 and Qt5.
