# RaySession plans

Of course, the main objectives of RaySession are already achieved. There are still a lot of features ideas for the patchbay, see https://github.com/Houston4444/HoustonPatchbay/blob/main/plans.md. But few features can be added to RaySession itself too.


## Add some widgets to the tool bar

Since tool bar is customizable, we could add optional actions for _recents sessions_, _session scripts_, maybe others.

## Remove totally ray-proxy

RayHack does the job ray-proxy was doing. RayHack appeared in the v0.9.0 (Jul 2020). ray-proxy is still included to ensure compatibility with sessions created with older versions, but its code has not been maintained, and errors could appears because of a lib or python update. The solution could simply be to convert ray-proxy to RayHack at session open, this means it will not be possible to re-open this session with older RS version, but I didn't really care about this scenario from the start TBH, these kinds of considerations slow down development considerably.

This would be a good task for the 1.0.0 release.

## add dialog for icon selection

In client properties dialog, it would be nice to can select an icon directly, Unfortunately Qt does not provides an icon chooser, but KDE does with kdialog, it would be nice for KDE users to add a button to browse the icons with kdialog --geticon.

## improve donations dialog with tips

Give some user tips in donations dialog, make it prettier.


## Connections

Allow some automatic disconnections, sometimes some programs auto-connect some ports and it can be annoying. Of course user can set JACK settings to prevent that, but it can be boring for other softwares.

## Pipewire config script

Such as Jack Config Memory script, it would be useful to can switch pipewire configs between sessions. For the moment, I don't know enough Pipewire, and another one than me could do that.

## Rooms

As carla-patchbay, be able to load inside a session, a session starting a new JACK instance (or PW if possible), with audio and midi ports. I don't know if it is really doable without extra latency.

## Plugin launcher

First, there is a client to write for this, maybe starting from carla-single, starting with carla-database window if no config file is found. We could add a button directly in RaySession GUI (Add Plugin). What would be nice would be to can select the default plugin GUI or a generic one (it needs one more NSM capability I think).

It can be very long to implement, but it would be a big step forward.