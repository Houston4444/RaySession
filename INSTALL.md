# Preparing the source tree

If you just cloned the git repository, make sure you also
cloned the submodules, which you can do using:

`$ git submodule update --init`

# Building

## Build dependencies

The required build dependencies are: (devel packages of these)

 - qtpy
 - PyQt5 or PyQt6
 - Qt5 dev tools or Qt6 dev tools
 - qtchooser

On Debian and Ubuntu, use these commands as root to install all build
dependencies:

- for Qt5 build:

`$ [sudo] apt-get install python3-qtpy python3-pyqt5 pyqt5-dev-tools qtchooser qttools5-dev-tools`

- for Qt6 build:

`$ [sudo] apt-get install python3-qtpy python3-pyqt6 pyqt6-dev-tools qtchooser`

To build RaySession, simply run as usual:

`$ make`

if you prefer to build it with Qt6:

`$ QT_VERSION=6 make`

Depending of the distribution you might need to use the LRELEASE variable
to build.  If you don't have 'lrelease' executable but 'lrelease-qt5' use:

`$ make LRELEASE=lrelease-qt5`

# Installing

To install RaySession, simply run as usual:

`$ [sudo] make install`

Packagers can make use of the 'PREFIX' and 'DESTDIR' variable during install,
like this:

`$ [sudo] make install PREFIX=/usr DESTDIR=./test-dir`

# Uninstalling

To uninstall RaySession, run:

`$ [sudo] make uninstall`

# Running

You can run RaySession without install, by using:

`$ ./src/bin/raysession`

To run it, you'll additionally need:

   - python3-liblo
   - python3-pyqt5.qtsvg or python3-pyqt6.qtsvg


IMPORTANT: since python 3.11, because pyliblo has been totally abandonned
by Dominic Sacre, for liblo you need to use the following fork:

    https://github.com/gesellkammer/pyliblo3

Simply install it with:

`$ python3 -m pip install pyliblo3`
